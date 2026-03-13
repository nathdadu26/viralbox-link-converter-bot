import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

load_dotenv()

BOT_TOKEN        = os.getenv("BOT_TOKEN")
MONGO_URI        = os.getenv("MONGO_URI")
SHORTENER_DOMAIN = os.getenv("SHORTENER_DOMAIN")
JOIN_BUTTON_LINK = os.getenv("JOIN_BUTTON_LINK")

# MongoDB setup
client = MongoClient(MONGO_URI)
db = client["viralbox_db"]

links_col = db["links"]
api_col = db["user_apis"]


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def get_user(user_id: int) -> dict | None:
    return api_col.find_one({"userId": user_id})


def extract_domain_links(text: str) -> list[str]:
    """Return all SHORTENER_DOMAIN links found in text."""
    pattern = rf'https?://{re.escape(SHORTENER_DOMAIN)}/[^\s]+'
    return re.findall(pattern, text)


def convert_single_link(api_key: str, short_url: str) -> str | None:
    """
    Look up longURL from DB for the given shortURL,
    then re-shorten it with the user's API key.
    Returns new short URL on success, None on failure.
    """
    data = links_col.find_one({"shortURL": short_url})
    if not data:
        return None

    long_url = data["longURL"]
    api_url = f"https://{SHORTENER_DOMAIN}/api?api={api_key}&url={long_url}"

    try:
        r = requests.get(api_url, timeout=10).json()
    except Exception:
        return None

    if r.get("status") != "success":
        return None

    new_short = r["shortenedUrl"].replace("\\/", "/")

    links_col.insert_one({
        "longURL": long_url,
        "shortURL": new_short,
        "created_at": datetime.utcnow()
    })

    return new_short


def build_reply_caption(
    original_text: str,
    api_key: str,
    header: str | None,
    footer: str | None,
    keep_text: bool
) -> str | None:
    """
    Build the final caption/text to send back.

    keep_text=True  → replace each domain link in original text in-place
    keep_text=False → extract links, convert them, send only those links
    Returns None if no domain links were found.
    """
    links = extract_domain_links(original_text)
    if not links:
        return None

    # Build link map: original → converted
    link_map: dict[str, str] = {}
    for link in links:
        converted = convert_single_link(api_key, link)
        if converted:
            link_map[link] = converted

    if not link_map:
        return None

    if keep_text:
        # Replace every domain link in the original text
        result = original_text
        for old, new in link_map.items():
            result = result.replace(old, new)
    else:
        # Only the converted links, one per line
        result = "\n".join(link_map.values())

    # Attach header / footer
    parts = []
    if header:
        parts.append(header)
    parts.append(result)
    if footer:
        parts.append(footer)

    return "\n".join(parts)


# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    name = user.first_name or "User"

    doc = get_user(user_id)

    if doc and doc.get("apiKey"):
        api_key  = doc["apiKey"]
        mode     = "Keep Text 📝" if doc.get("keepText", False) else "Delete Text 🗑️"
        header   = doc.get("header") or "Not set"
        footer   = doc.get("footer") or "Not set"

        text = (
            f"👋 Welcome back, *{name}*!\n\n"
            f"✅ *API Key:* `{api_key}`\n"
            f"📌 *Mode:* `{mode}`\n"
            f"🔝 *Header:* {header}\n"
            f"🔚 *Footer:* {footer}\n\n"
            f"Send {SHORTENER_DOMAIN} link to convert it to your link."
        )
    else:
        text = (
            f"👋 Welcome, *{name}*!\n\n"
            "To get started, please set your API key:\n"
            "`/setapi YOUR_API_KEY`"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("♻️ Join Update Channel", url=JOIN_BUTTON_LINK)]
    ])

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ─────────────────────────────────────────────
#  /setapi
# ─────────────────────────────────────────────

async def set_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if len(context.args) != 1:
        await update.message.reply_text("Usage:\n`/setapi YOUR_API_KEY`", parse_mode="Markdown")
        return

    api_key = context.args[0]

    api_col.update_one(
        {"userId": user_id},
        {"$set": {"apiKey": api_key}},
        upsert=True
    )

    await update.message.reply_text("✅ API Key saved successfully!")


# ─────────────────────────────────────────────
#  /add_header  /delete_header
# ─────────────────────────────────────────────

async def add_header(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "Usage:\n`/add_header Your Header Text`",
            parse_mode="Markdown"
        )
        return

    header_text = " ".join(context.args)

    api_col.update_one(
        {"userId": user_id},
        {"$set": {"header": header_text}},
        upsert=True
    )

    await update.message.reply_text(
        f"✅ Header saved:\n\n{header_text}"
    )


async def delete_header(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    api_col.update_one(
        {"userId": user_id},
        {"$unset": {"header": ""}}
    )

    await update.message.reply_text("✅ Header deleted.")


# ─────────────────────────────────────────────
#  /add_footer  /delete_footer
# ─────────────────────────────────────────────

async def add_footer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "Usage:\n`/add_footer Your Footer Text`",
            parse_mode="Markdown"
        )
        return

    footer_text = " ".join(context.args)

    api_col.update_one(
        {"userId": user_id},
        {"$set": {"footer": footer_text}},
        upsert=True
    )

    await update.message.reply_text(
        f"✅ Footer saved:\n\n{footer_text}"
    )


async def delete_footer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    api_col.update_one(
        {"userId": user_id},
        {"$unset": {"footer": ""}}
    )

    await update.message.reply_text("✅ Footer deleted.")


# ─────────────────────────────────────────────
#  /keep_text  /delete_text
# ─────────────────────────────────────────────

async def keep_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    api_col.update_one(
        {"userId": user_id},
        {"$set": {"keepText": True}},
        upsert=True
    )

    await update.message.reply_text(
        "✅ *Keep Text* mode enabled.\n\n"
        "Original caption will be kept as-is — only links will be converted in place.",
        parse_mode="Markdown"
    )


async def delete_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    api_col.update_one(
        {"userId": user_id},
        {"$set": {"keepText": False}},
        upsert=True
    )

    await update.message.reply_text(
        "✅ *Delete Text* mode enabled.\n\n"
        "Only converted links will be sent (original caption text removed).",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────
#  MAIN MESSAGE / MEDIA HANDLER
# ─────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    doc = get_user(user_id)

    if not doc or not doc.get("apiKey"):
        await message.reply_text(
            "⚠️ Please set your API key first:\n`/setapi YOUR_API_KEY`",
            parse_mode="Markdown"
        )
        return

    api_key   = doc["apiKey"]
    header    = doc.get("header")
    footer    = doc.get("footer")
    keep_text_mode = doc.get("keepText", False)

    # Determine the text / caption to process
    original_text = message.text or message.caption or ""

    if not original_text:
        return

    # Build the new caption
    new_caption = build_reply_caption(
        original_text, api_key, header, footer, keep_text_mode
    )

    if new_caption is None:
        # No domain links found — silently ignore
        return

    # ── Reply with media (if any) ──────────────────────────────────────
    if message.photo:
        await message.reply_photo(
            photo=message.photo[-1].file_id,
            caption=new_caption
        )
    elif message.video:
        await message.reply_video(
            video=message.video.file_id,
            caption=new_caption
        )
    elif message.document:
        await message.reply_document(
            document=message.document.file_id,
            caption=new_caption
        )
    elif message.audio:
        await message.reply_audio(
            audio=message.audio.file_id,
            caption=new_caption
        )
    elif message.animation:
        await message.reply_animation(
            animation=message.animation.file_id,
            caption=new_caption
        )
    elif message.voice:
        await message.reply_voice(
            voice=message.voice.file_id,
            caption=new_caption
        )
    elif message.video_note:
        # video notes don't support captions; send separately
        await message.reply_video_note(video_note=message.video_note.file_id)
        await message.reply_text(new_caption)
    else:
        # Plain text message
        await message.reply_text(new_caption)


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    from health_check import start_health_server
    start_health_server()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",         start))
    app.add_handler(CommandHandler("setapi",        set_api))
    app.add_handler(CommandHandler("add_header",    add_header))
    app.add_handler(CommandHandler("delete_header", delete_header))
    app.add_handler(CommandHandler("add_footer",    add_footer))
    app.add_handler(CommandHandler("delete_footer", delete_footer))
    app.add_handler(CommandHandler("keep_text",     keep_text))
    app.add_handler(CommandHandler("delete_text",   delete_text))

    # All message types (text + every media type with possible caption)
    app.add_handler(
        MessageHandler(
            filters.TEXT
            | filters.PHOTO
            | filters.VIDEO
            | filters.Document.ALL
            | filters.AUDIO
            | filters.ANIMATION
            | filters.VOICE
            | filters.VIDEO_NOTE,
            handle_message
        )
    )

    print("✅ Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
