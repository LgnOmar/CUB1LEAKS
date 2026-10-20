import json
import os
import time
import urllib.request

token = os.environ.get("BOT_TOKEN")

if not token:
    print("BOT_TOKEN is not set in this terminal.")
    raise SystemExit(1)

url = f"https://api.telegram.org/bot{token}/getUpdates"
offset = None

print("Waiting for a new channel post...")
print("Now send a NEW text message in your private test channel.")

deadline = time.time() + 120

while time.time() < deadline:
    params = {"timeout": 10}
    if offset is not None:
        params["offset"] = offset

    request = urllib.request.Request(
        url,
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode())

        if not data.get("ok"):
            print("Telegram API returned an error.")
            break

        for update in data.get("result", []):
            offset = update["update_id"] + 1
            post = update.get("channel_post")

            if post:
                chat = post["chat"]
                print("\nChannel title:", chat.get("title", "(unknown)"))
                print("Channel ID:", chat["id"])
                raise SystemExit(0)

    except Exception as error:
        print("Request failed:", type(error).__name__)
        break

print("No channel post received. Check the bot permissions and try again.")