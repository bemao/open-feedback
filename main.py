import os
import json
import asyncio
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
import uvicorn
import requests
from pydantic import BaseModel

from dotenv import load_dotenv

import prompts as p

load_dotenv()

# ── args ──────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--call", metavar="NUMBER")
parser.add_argument("--port", type=int, default=5001)
parser.add_argument(
    "--type",
    default="interview",
    choices=["interview", "application", "site_visit", "first_date"],
)
parser.add_argument(
    "--voice",
    default="ash",
    choices=[
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "sage",
        "shimmer",
        "verse",
        "marin",
        "cedar",
    ],
)
args, _ = parser.parse_known_args()

# ── config ────────────────────────────────────────────────────────────────────
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
BASE_URL = os.environ.get("BASE_URL", f"http://localhost:{args.port}")
REALTIME_MODEL = "gpt-realtime-mini-2025-12-15"

# default values for voice and system prompt
VOICE = "ash"
SYSTEM_PROMPT = p.SYSTEM_PROMPT_INTERVIEW

AUDIO_CACHE_DIR = Path("audio_cache")
AUDIO_CACHE_DIR.mkdir(exist_ok=True)

FINAL_RESPONSE_WAIT = 12  # number of seconds to wait for the agent to deliver goodby message before hanging up

with open("tools.json", "r") as f:
    TOOLS = json.load(f)


def get_system_prompt(prompt_type):
    match prompt_type.lower():
        case "interview":
            return p.SYSTEM_PROMPT_INTERVIEW
        case "application":
            return p.SYSTEM_PROMPT_APPLICATION
        case "site_visit":
            return p.SYSTEM_PROMPT_SITE_VISIT
        case "first_date":
            return p.SYSTEM_PROMPT_DATE
        case _:
            raise ValueError(f"Prompt type '{prompt_type}' not recognized")


# ── conversation log store (call_sid → list of turn dicts) ────────────────────
conversation_logs: dict[str, list[dict]] = {}


def log_turn(call_sid: str, role: str, content: str):
    if call_sid not in conversation_logs:
        conversation_logs[call_sid] = []
    conversation_logs[call_sid].append({"role": role, "content": content})
    print(f"[{call_sid}] {role}: {content}")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI()


class CallConfig(BaseModel):
    prompt_type: str
    voice: str


@app.post("/update-call-config")
async def update_call_config(cfg: CallConfig):
    global SYSTEM_PROMPT, VOICE_NAME
    SYSTEM_PROMPT = get_system_prompt(cfg.prompt_type)
    VOICE_NAME = cfg.voice
    print(f"Updated call config: prompt_type={cfg.prompt_type}, voice={cfg.voice}")
    return {"ok": True}


@app.post("/incoming-call")
async def incoming_call():
    print(BASE_URL)
    """
    Twilio hits this when the call connects.
    We return TwiML that opens a media stream to /media-stream.
    """
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://{BASE_URL.replace("https://", "").replace("http://", "")}/media-stream"/>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="text/xml")


@app.websocket("/media-stream")
async def media_stream(twilio_ws: WebSocket):
    """
    Persistent WebSocket bridge between Twilio and OpenAI Realtime API.

    Two concurrent tasks run for the lifetime of the call:
      receive_from_twilio — forwards G.711 audio chunks to OpenAI
      send_to_twilio      — forwards OpenAI TTS audio deltas back to Twilio

    Tool calls are handled inside send_to_twilio when OpenAI emits them.
    """
    await twilio_ws.accept()

    call_sid = None
    stream_sid = None  # Twilio stream ID, needed to send audio back
    shutdown = asyncio.Event()

    # Connect to OpenAI Realtime
    openai_ws = await websockets.connect(
        f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}",
        additional_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
    )

    # Configure the session
    await openai_ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": SYSTEM_PROMPT,
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcmu"},
                            "turn_detection": {
                                "type": "server_vad",
                                "silence_duration_ms": 600,
                                "threshold": 0.5,
                                "create_response": True,
                                "interrupt_response": True,
                            },
                        },
                        "output": {
                            "voice": VOICE_NAME,
                            "format": {"type": "audio/pcmu"},
                        },
                    },
                    "tools": TOOLS,
                    "tool_choice": "auto",
                    "output_modalities": ["audio"],
                },
            }
        )
    )

    await openai_ws.send(json.dumps({"type": "response.create"}))

    # ── task 1: Twilio → OpenAI ───────────────────────────────────────────────
    async def receive_from_twilio():
        nonlocal call_sid, stream_sid  # exposes call_sid and stream_sid to this function
        msg_count = 0
        try:
            async for raw in twilio_ws.iter_text():
                if shutdown.is_set():
                    break
                event = json.loads(raw)

                if event["event"] == "start":
                    stream_sid = event["start"]["streamSid"]
                    call_sid = event["start"]["callSid"]
                    print(f"[{call_sid}] Stream started.")

                elif event["event"] == "media":
                    # Forward raw G.711 audio to OpenAI — already base64 encoded
                    await openai_ws.send(
                        json.dumps(
                            {
                                "type": "input_audio_buffer.append",
                                "audio": event["media"]["payload"],
                            }
                        )
                    )

                elif event["event"] == "stop":
                    print(f"[{call_sid}] Stream stopped.")
                    break

        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await openai_ws.close()

    # ── task 2: OpenAI → Twilio ───────────────────────────────────────────────
    async def send_to_twilio():
        """
        Handle all events from OpenAI Realtime:
          response.audio.delta      → stream TTS audio to Twilio immediately
          response.audio_transcript → log what the assistant said
          conversation.item.input_audio_transcription → log what the candidate said
          response.function_call    → handle tool calls
        """
        # Accumulate function call args across deltas
        fn_call_buffer: dict = {}
        pending_hangup = False
        current_response_item_id: str | None = None
        audio_ms_sent: int = 0
        assistant_speaking = False

        try:
            async for raw in openai_ws:
                event = json.loads(raw)
                etype = event.get("type", "")

                # ── stream TTS audio to caller ────────────────────────────────
                if etype == "response.output_audio.delta" and stream_sid:
                    await twilio_ws.send_json(
                        {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": event["delta"]},
                        }
                    )
                    import base64

                    chunk_bytes = len(base64.b64decode(event["delta"]))
                    audio_ms_sent += chunk_bytes // 8

                elif etype == "response.output_item.added":
                    current_response_item_id = event.get("item", {}).get("id")
                    audio_ms_sent = 0
                    assistant_speaking = True

                # ── log assistant transcript ──────────────────────────────────
                elif etype == "response.output_audio_transcript.done":
                    if call_sid:
                        log_turn(call_sid, "assistant", event.get("transcript", ""))

                # ── log candidate transcript ──────────────────────────────────
                elif etype == "conversation.item.input_audio_transcription.completed":
                    if call_sid:
                        log_turn(call_sid, "candidate", event.get("transcript", ""))

                # ── accumulate function call ──────────────────────────────────
                elif etype == "response.function_call_arguments.delta":
                    fn_call_buffer.setdefault("name", event.get("name", ""))
                    fn_call_buffer.setdefault("args", "")
                    fn_call_buffer["call_id"] = event.get("call_id", "")
                    fn_call_buffer["args"] += event.get("delta", "")

                # -- interruption ---
                elif (
                    etype == "input_audio_buffer.speech_started" and assistant_speaking
                ):
                    print(
                        f"[{call_sid}] User interrupted — clearing Twilio audio buffer"
                    )
                    if stream_sid:
                        await twilio_ws.send_json(
                            {
                                "event": "clear",
                                "streamSid": stream_sid,
                            }
                        )
                        if current_response_item_id:
                            await openai_ws.send(
                                json.dumps(
                                    {
                                        "type": "conversation.item.truncate",
                                        "item_id": current_response_item_id,
                                        "content_index": 0,
                                        "audio_end_ms": audio_ms_sent,
                                    }
                                )
                            )
                        try:
                            await openai_ws.send(
                                json.dumps(
                                    {
                                        "type": "response.cancel",
                                    }
                                )
                            )
                        except:
                            pass

                # -- errors -- this is due to caching the playback
                elif etype == "error":
                    if (
                        event.get("error", {}).get("code")
                        == "response_cancel_not_active"
                    ):
                        pass
                    else:
                        print(f"[OpenAI error] {event}")

                # ── execute function call ─────────────────────────────────────
                elif etype == "response.function_call_arguments.done":
                    fn_name = fn_call_buffer.get("name") or event.get("name", "")
                    call_id = fn_call_buffer.get("call_id") or event.get("call_id", "")
                    fn_call_buffer = {}

                    print(f"[{call_sid}] Tool call: {fn_name}")

                    if fn_name == "end_call":
                        pending_hangup = True
                        # return tool result so OpenAI can say goodbye naturally
                        await openai_ws.send(
                            json.dumps(
                                {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": json.dumps({"status": "ok"}),
                                    },
                                }
                            )
                        )
                        await openai_ws.send(json.dumps({"type": "response.create"}))

                elif etype == "error":
                    print(f"[OpenAI error] {event}")

                # --- hangup ---
                elif etype == "response.done":
                    assistant_speaking = False
                    if pending_hangup:
                        print(f"[{call_sid}] Response done, hanging up.")
                        await asyncio.sleep(
                            FINAL_RESPONSE_WAIT
                        )  # small buffer for audio to finish playing
                        shutdown.set()  # signal receive_from_twilio to stop
                        await twilio_ws.close()
                        return

        except Exception as e:
            print(f"[send_to_twilio error] {e}")

    # ── run both tasks concurrently for the life of the call ─────────────────
    await asyncio.gather(
        receive_from_twilio(),
        send_to_twilio(),
    )


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if args.call:
        requests.post(
            f"{BASE_URL}/update-call-config",
            json={
                "prompt_type": args.type,
                "voice": args.voice,
            },
            timeout=5,
        )

        from twilio.rest import Client as TwilioClient

        client = TwilioClient(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"],
        )
        call = client.calls.create(
            to=args.call,
            from_=os.environ["TWILIO_PHONE_NUMBER"],
            url=f"{BASE_URL}/incoming-call",
        )
        print(f"Outbound call placed. SID: {call.sid}")
    else:
        print(f"Starting server → {BASE_URL}/incoming-call")
        uvicorn.run(app, host="0.0.0.0", port=args.port)
