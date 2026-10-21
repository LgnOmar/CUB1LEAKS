# Anonymous Dormitory Report Bot

A Telegram bot that lets students anonymously report dormitory problems
(poor food, hygiene, broken equipment, etc.) directly to a channel.

## How it works

1. Students open DM with the bot
2. They send a photo, video, or text describing the issue
3. The bot posts the content to a public channel with **no sender attribution**
4. Everyone in the channel sees the report anonymously

Telegram's `copy_message()` is used instead of `forward` — this creates a
clean copy that never reveals who sent it.

## Quick start

### 1. Create the bot

Talk to [@BotFather](https://t.me/BotFather) on Telegram:

```
/newbot
```

Give it a name like "Dorm Anonymous Reports" and a username like
`DormAnonReportBot`. BotFather will give you a token like
`123456789:AA...save_it_safe...`.

### 2. Create the channel

Create a **public channel** on Telegram (or use an existing one):

```
/thenewchannel  →  Dorm Reports  →  Public  →  @dorm_reports
```

Go to **Channel → Administrators → Add** → select your bot → grant
the **Post Messages** permission.

### 3. Configure

Create a `.env` file (or export environment variables):

```bash
export BOT_TOKEN="123456789:AA...your_token..."
export CHANNEL_ID="@dorm_reports"
# OR if you prefer the numeric ID:
# export CHANNEL_ID="-1001234567890"
```

### 4. Install & run

```bash
pip install -r requirements.txt
python bot.py
```

## Usage for students

```
/start     →  see welcome message
/help      →  see help

Send any photo, video, document, or text describing a dorm issue.
If your media has no caption, the bot asks for an optional description.
Type /skip to post without one.
```

## Deployment

The bot runs 24/7 as long as the process is alive. For continuous
operation, deploy to a server:

| Option          | Monthly cost | Notes                                   |
|-----------------|-------------|-----------------------------------------|
| VPS (DigitalOcean, Vultr) | $4–6  | `nohup python bot.py &`                 |
| Raspberry Pi    | one-time $35 | Leave running at the dorm               |
| pythonAnywhere  | Free / $5   | Web-based, limited networking           |
| Render / Railway| Free tier   | May need a paid plan for always-on       |

On a Linux server:

```bash
git clone <this-repo>
cd dorm-anon-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="..."
export CHANNEL_ID="..."
nohup python bot.py &
```

## Features

- **True anonymity** — sender info is never exposed to channel readers
- **Automatic Media Blurring** — photos and every frame of videos are strongly blurred before publishing to protect privacy
- **Fail-safe privacy** — original unblurred media is NEVER published; if processing fails, publication is aborted
- **Rate limiting** — 30 s cooldown per user to prevent spam
- **Multi-format** — photos, videos, documents, and plain text
- **Optional descriptions** — `/skip` to post media only
- **HTML-escaped captions** — prevents formatting injection

## Video Processing Requirements

Video frame blurring requires **FFmpeg**. The bot automatically discovers FFmpeg via:
1. System PATH (`ffmpeg`), or
2. `imageio-ffmpeg` package (included in `requirements.txt`).

On Windows, you can install FFmpeg system-wide via:
```powershell
winget install Gyan.FFmpeg.Essentials
```

## Privacy notes

- No database is used; the bot stores only an in-memory rate-limit cache
- User IDs are never logged to disk
- Original photos and videos are processed in temporary storage and deleted immediately after processing/publishing
- Unblurred media is never forwarded, copied, or published to the channel
- The bot operator (whoever runs it) can see sender info in Telegram logs,
  but **channel readers** see only the anonymous post

## License

MIT
