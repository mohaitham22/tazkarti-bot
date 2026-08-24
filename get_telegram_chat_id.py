"""
Get your Telegram chat ID
----------------------------
Before running this: open your bot's chat in the Telegram app (search
its username) and send it any message, like "hi". Telegram only shows
a chat in getUpdates after you've messaged the bot at least once.

Then run this script -- it reads TELEGRAM_BOT_TOKEN from your .env
file and prints your real chat ID.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

resp = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=10)
data = resp.json()

if not data.get("ok"):
    print("Telegram API error:", data)
elif not data.get("result"):
    print("No messages found yet.")
    print("Open your bot's chat in Telegram, send it a message (like 'hi'), then run this again.")
else:
    seen = set()
    for update in data["result"]:
        msg = update.get("message") or update.get("channel_post")
        if not msg:
            continue
        chat = msg["chat"]
        if chat["id"] in seen:
            continue
        seen.add(chat["id"])
        name = chat.get("username") or chat.get("first_name") or "(unknown)"
        print(f"Chat ID: {chat['id']}   (from: {name}, type: {chat['type']})")

    if not seen:
        print("No usable chat found. Make sure you messaged the bot directly, not a group.")
    else:
        print("\nCopy the Chat ID above (the number) into TELEGRAM_CHAT_ID in your .env file.")
