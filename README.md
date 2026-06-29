```
██████╗ ██████╗ ███████╗ ███╗   ██╗  
██╔═══██╗██╔══██╗██╔════╝████╗  ██║  
██║   ██║██████╔╝█████╗  ██╔██╗ ██║  
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║  
╚██████╔╝██║     ███████╗██║ ╚████║   
╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝ 
███████╗███████╗███████╗██████╗ ██████╗  █████╗  ██████╗██╗  ██╗ 
██╔════╝██╔════╝██╔════╝██╔══██╗██╔══██╗██╔══██╗██╔════╝██║ ██╔╝ 
█████╗  █████╗  █████╗  ██║  ██║██████╔╝███████║██║     █████╔╝ 
██╔══╝  ██╔══╝  ██╔══╝  ██║  ██║██╔══██╗██╔══██║██║     ██╔═██╗ 
██║     ███████╗███████╗██████╔╝██████╔╝██║  ██║╚██████╗██║  ██╗ 
╚═╝     ╚══════╝╚══════╝╚═════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝
```
The world's first (?) open source agent for delivering thoughtful and considerate rejections.

## Our Story
We recently interviewed for a job at a FAANG company and, for reasons that we can only attribute to blatent descrimination, were not hired.
However, the news that we were not going to be offered a job was delivered in such a courteous and thoughtful manner, that we couldn't help
but be touched. 

Rather than delivering a simple, "thanks, but no thanks" email, the recruiter reached out to schedule a phone call for the next day. We arranged our schedule, blocked our calendar and set to wondering about the contents of the call. What would the recruiter say? Did the interview go better than we though? Were there specific feedback given or related openings we might consider? We had a great time imagining all of the possibilites. 

When the hour of the phone call arrived, the recruiter courteously informed us that, although the interviewers enjoyed speaking with us, 
we weren't quite up the the level they normally look for. No additional information could be provided. They then thanked us
for the time we took going through the process and ended the call. How could we not be touched by such a courteous and not-at-all-time-wasting phone call?

Then the idea occurred to us: why should this courtesy be limited to those who are not-quite-up-to-the-level that FAANG companies typically
look for? Everyone deserves to be rejected in an equally courteous manner. Hence, `open_feedback` was born. 

You can now reject anyone, anywhere, for anything in a kind and empathetic way! No more wasting people's time with sterile emails, you can
waste their time talking to a bot!

## Quickstart
`open_feedback` relies on three services: 
- Twilio for making phone call
- Openai realtime api for powering the chat agent
- `ngrok` for exposing the API

**Steps**
1. Setup Twilio and ngrok accounts -- as of June 2026, these two both offer free versions.
2. Put some money into openai API pay-go and get an API key
3. Update the `.env` file with the credentials and ngrok redirect URL
4. Start ngrok
   ```
   ngrok http <port>
   ```
5. (In another terminal) Start service
   ```
   uv run python main.py
   ```
6. (In another terminal) Reject!
   ```
   uv run python main.py --call <number to call> --type <type of rejection to deliver> --voice <name of voice>
   ```

**Have fun!**



