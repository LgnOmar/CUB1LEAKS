"""
Anonymous Dormitory Report Bot
==============================
A Telegram bot for students to anonymously report dormitory issues
(poor food, hygiene, broken equipment, disorganization, etc.).

How it works:
  Students DM the bot with a photo/video/text.  The bot copies the
  content to a public channel with no sender attribution — Telegram's
  copy_message() never reveals the original chat or username.

Setup:
  1. Bot       → talk to @BotFather, /newbot, paste token
  2. Channel   → create channel, add bot as admin (Post Messages)
  3. Config    → export BOT_TOKEN and CHANNEL_ID
  4. Run       → python bot.py

  BOT_TOKEN   = the token from @BotFather
  CHANNEL_ID  = @channel_username  OR  -100xxxxxxxxxx (numeric)
"""

import asyncio
import html
import logging
import os
import time

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

# ── Configuration ─────────────────────────────────────────────────────────────

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not BOT_TOKEN:
    raise SystemExit("❌ Set BOT_TOKEN env var (from @BotFather)")
if not CHANNEL_ID:
    raise SystemExit("❌ Set CHANNEL_ID env var (channel username or numeric id)")

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("anon_dorm_bot")

# ── Constants ─────────────────────────────────────────────────────────────────

HEADER = "📋 <b>Anonymous Report</b>\n────────────────\n"
RATE_LIMIT = 30          # seconds between submissions per user
SKIP_KEYWORD = "/skip"

WELCOME = f"""
📸 <b>Anonymous Dormitory Report Bot</b>

See a problem? Send a photo, video, or text describing it and your
report will be posted <b>anonymously</b> to our dorm channel.

<b>What to report:</b>
• Poor food quality
• Hygiene issues
• Broken equipment
• Disorganization
• Anything else needing attention

Just send your media — you can add a caption with details (what happened,
where, when).
"""

HELP = """
<b>How to use this bot:</b>

1. Send a photo, video, document, or text message describing an issue
2. If your media has a caption, it is posted as-is (anonymously)
3. If it has no caption, you'll be asked for an optional description
4. Your report appears on the channel with no name attached

<b>Commands:</b>
/start — show welcome message
/help  — show this help
/skip  — post without a description (when prompted)

One report per 30 seconds to prevent spam.
"""


# ── Rate limiting (in-memory, per-user) ──────────────────────────────────────

_last_seen: dict[int, float] = {}


def _rate_limited(uid: int) -> int | None:
    """Return seconds-remaining if user is throttled, else None."""
    now = time.time()
    last = _last_seen.get(uid, 0)
    remaining = RATE_LIMIT - (now - last)
    if remaining > 0:
        return int(remaining + 1)
    _last_seen[uid] = now
    return None


# ── States ────────────────────────────────────────────────────────────────────

class Form(StatesGroup):
    description = State()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _copy_to_channel(
    src_chat: int,
    src_msg: int,
    caption: str,
) -> None:
    """Copy a media message to the channel with a new anonymous caption."""
    await bot.copy_message(
        chat_id=CHANNEL_ID,
        from_chat_id=src_chat,
        message_id=src_msg,
        caption=caption,
        parse_mode="HTML",
    )


# ── Bot & Dispatcher ──────────────────────────────────────────────────────────

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ── Command handlers ─────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(WELCOME, parse_mode="HTML")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP, parse_mode="HTML")


# ── Media handlers (photo / video / document) ─────────────────────────────────

@dp.message(F.photo | F.video | F.document)
async def handle_media(message: Message, state: FSMContext):
    """Receive a media item — post immediately if it has a caption, otherwise
    ask for an optional description."""

    # Throttle
    rl = _rate_limited(message.from_user.id)
    if rl:
        await message.answer(f"⚠️ Please wait {rl}s before submitting another report.")
        return

    # Reject albums
    if message.media_group_id:
        await message.answer("🚫 Please send items one at a time — albums are not supported yet.")
        return

    # Media with existing caption → post directly
    if message.caption:
        caption = f"{HEADER}{html.escape(message.caption)}"
        await _copy_to_channel(message.chat.id, message.message_id, caption)
        await message.answer(
            "✅ Your report was posted anonymously. Thank you for helping improve our dorm!"
        )
        return

    # No caption → ask for optional description
    await state.update_data(
        src_chat=message.chat.id,
        src_msg=message.message_id,
    )
    await state.set_state(Form.description)
    await message.answer(
        "📝 Add a brief description (what happened? where?)\n"
        f"Or type {SKIP_KEYWORD} to post without a description."
    )


# ── Description state handlers ────────────────────────────────────────────────

@dp.message(Form.description, Command("skip"))
async def desc_skip(message: Message, state: FSMContext):
    """User chose to skip the description — post media only."""
    data = await state.get_data()
    await _copy_to_channel(data["src_chat"], data["src_msg"], HEADER.strip())
    await message.answer("✅ Your report was posted anonymously. Thank you!")
    await state.clear()


@dp.message(Form.description, F.text)
async def desc_received(message: Message, state: FSMContext):
    """User typed a description — attach it to the media and post."""
    data = await state.get_data()
    caption = f"{HEADER}{html.escape(message.text)}"
    await _copy_to_channel(data["src_chat"], data["src_msg"], caption)
    await message.answer("✅ Your report was posted anonymously. Thank you!")
    await state.clear()


# ── Plain-text handler (no media) ─────────────────────────────────────────────

@dp.message(StateFilter(None), F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    """A standalone text message is treated as a report."""
    rl = _rate_limited(message.from_user.id)
    if rl:
        await message.answer(f"⚠️ Please wait {rl}s before submitting another report.")
        return

    text = f"{HEADER}{html.escape(message.text)}"
    await bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML")
    await message.answer(
        "✅ Your report was posted anonymously. Thank you for helping improve our dorm!"
    )


# ── Fallback ──────────────────────────────────────────────────────────────────

@dp.message()
async def handle_else(message: Message):
    await message.answer(
        "I can handle photos, videos, documents, and text.\n"
        "Send a picture of the issue or describe it in text."
    )


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    log.info("Starting Anonymous Dorm Report Bot …")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
