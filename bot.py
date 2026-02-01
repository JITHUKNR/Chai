# ==============================
#  TELEGRAM BTS ROLEPLAY BOT
#  UPDATED: SINGLE /broadcast
# ==============================

import os
import logging
import asyncio
import random
import pytz
import urllib.parse
from datetime import datetime, timedelta, timezone, time

from groq import Groq
from pymongo import MongoClient
from telegram import (
    Update, BotCommand,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# ---------------- CONFIG ----------------
TOKEN = os.environ.get("TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8443))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MONGO_URI = os.environ.get("MONGO_URI")

ADMIN_TELEGRAM_ID = 7567364364
ADMIN_CHANNEL_ID = "-1002992093797"

COOLDOWN_TIME_SECONDS = 180
MEDIA_LIFETIME_HOURS = 1
DB_NAME = "Taekook_bot"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- DB ----------------
db_client = MongoClient(MONGO_URI)
db = db_client[DB_NAME]
users_col = db["users"]
media_col = db["channel_media"]
sent_col = db["sent_media"]
cooldown_col = db["cooldown"]

# ---------------- GROQ ----------------
groq = Groq(api_key=GROQ_API_KEY)
chat_history = {}
last_user_message = {}
current_scenario = {}

# ---------------- PERSONAS ----------------
COMMON_RULES = (
    "Roleplay as a BTS boyfriend. "
    "Be natural, flirty, emotional, human."
)

BTS_PERSONAS = {
    "RM": COMMON_RULES + " You are Namjoon. Dominant, intellectual.",
    "Jin": COMMON_RULES + " You are Jin. Funny, dramatic.",
    "Suga": COMMON_RULES + " You are Suga. Cold, savage.",
    "J-Hope": COMMON_RULES + " You are J-Hope. Loud sunshine.",
    "Jimin": COMMON_RULES + " You are Jimin. Soft, clingy.",
    "V": COMMON_RULES + " You are V. Mysterious, deep.",
    "Jungkook": COMMON_RULES + " You are Jungkook. Teasing.",
    "TaeKook": COMMON_RULES + " You are TaeKook. Toxic, possessive."
}

# ---------------- UTIL ----------------
def add_emojis_balanced(text):
    if len(text.split()) < 4:
        return text
    return text + " 💜"

# ---------------- START ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name
    users_col.update_one(
        {"user_id": uid},
        {"$setOnInsert": {
            "first_name": name,
            "character": "TaeKook",
            "joined_at": datetime.now(timezone.utc),
            "allow_media": True
        }},
        upsert=True
    )
    await update.message.reply_text(f"Annyeong {name} 💜")

# ---------------- BROADCAST (FINAL) ----------------
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    reply = update.message.reply_to_message
    args_text = " ".join(context.args)

    caption = args_text or ""
    reply_markup = None

    # BUTTON PARSE
    if "|" in args_text:
        parts = args_text.split("|")
        caption = parts[0].strip()
        buttons = []
        for part in parts[1:]:
            if "-" in part:
                txt, url = part.split("-", 1)
                buttons.append([InlineKeyboardButton(txt.strip(), url=url.strip())])
        if buttons:
            reply_markup = InlineKeyboardMarkup(buttons)

    users = [u["user_id"] for u in users_col.find({}, {"user_id": 1})]
    sent = 0

    await update.message.reply_text("📣 Broadcasting...")

    for uid in users:
        try:
            if reply and reply.photo:
                await context.bot.send_photo(
                    uid,
                    reply.photo[-1].file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    protect_content=True
                )
            elif reply and reply.video:
                await context.bot.send_video(
                    uid,
                    reply.video.file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    protect_content=True
                )
            else:
                await context.bot.send_message(
                    uid,
                    caption,
                    reply_markup=reply_markup
                )
            sent += 1
        except:
            pass

    await update.message.reply_text(f"✅ Sent to {sent} users")

# ---------------- AI CHAT ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    user = users_col.find_one({"user_id": uid}) or {}
    char = user.get("character", "TaeKook")
    system_prompt = BTS_PERSONAS.get(char, BTS_PERSONAS["TaeKook"])

    if uid not in chat_history:
        chat_history[uid] = [{"role": "system", "content": system_prompt}]

    chat_history[uid].append({"role": "user", "content": text})

    completion = groq.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=chat_history[uid]
    )

    reply = add_emojis_balanced(completion.choices[0].message.content)
    chat_history[uid].append({"role": "assistant", "content": reply})

    await update.message.reply_text(reply)

# ---------------- INIT ----------------
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Start bot"),
        BotCommand("broadcast", "Admin broadcast")
    ])

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
