# ==============================
#  TAEKOOK TELEGRAM BOT
#  PART 1 / 3
# ==============================

import os
import logging
import asyncio
import random
import requests
import pytz
import urllib.parse
from groq import Groq
from telegram import Update, BotCommand, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.error import Forbidden, BadRequest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime, timedelta, timezone, time

# ***********************************
# WARNING: YOU MUST INSTALL pymongo AND pytz
# ***********************************
try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure, OperationFailure
except ImportError:
    class MockClient:
        def __init__(self, *args, **kwargs): pass
        def admin(self): return self
        def command(self, *args, **kwargs): raise ConnectionFailure("pymongo not imported.")
    MongoClient = MockClient
    ConnectionFailure = Exception
    OperationFailure = Exception

# -------------------- CONFIG --------------------
COOLDOWN_TIME_SECONDS = 180
MEDIA_LIFETIME_HOURS = 1

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('TOKEN')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
PORT = int(os.environ.get('PORT', 8443))
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
MONGO_URI = os.environ.get('MONGO_URI')

ADMIN_TELEGRAM_ID = 7567364364
ADMIN_CHANNEL_ID = os.environ.get('ADMIN_CHANNEL_ID', '-1002992093797')

DB_NAME = "Taekook_bot"

# -------------------- TRUTH OR DARE --------------------
TRUTH_QUESTIONS = [
    "What is the first thing you noticed about me? 🙈",
    "Have you ever dreamt about us? 💭",
    "What's your favorite song of mine? 🎶",
    "If we went on a date right now, where would you take me? 🍷",
    "What is a secret you've never told anyone? 🤫",
    "Do you get jealous when I look at others? 😏",
    "What's the craziest thing you've done for love? ❤️"
]

DARE_CHALLENGES = [
    "Send a voice note saying 'I Love You'! 🎤",
    "Send the 3rd photo from your gallery (no cheating)! 📸",
    "Close your eyes and type 'You are my universe' without mistakes! ✨",
    "Send a selfie doing a finger heart! 🫰",
    "Send 10 purple hearts 💜 right now!",
    "Change your WhatsApp status to my photo for 1 hour! 🤪"
]

# -------------------- SCENARIOS --------------------
SCENARIOS = {
    "Romantic": "Sweet late-night balcony date. Rainy, cozy.",
    "Jealous": "User talked to someone else. You are jealous.",
    "Enemy": "College enemies with hidden tension.",
    "Mafia": "Mafia boss & innocent assistant.",
    "Comfort": "User is crying. You comfort gently."
}

# -------------------- PERSONAS --------------------
COMMON_RULES = (
    "Roleplay as a BTS boyfriend. "
    "Be human, flirty, emotional."
)

BTS_PERSONAS = {
    "RM": COMMON_RULES + " You are Namjoon. Dominant, intellectual.",
    "Jin": COMMON_RULES + " You are Jin. Funny, dramatic.",
    "Suga": COMMON_RULES + " You are Suga. Cold, savage.",
    "J-Hope": COMMON_RULES + " You are J-Hope. Sunshine.",
    "Jimin": COMMON_RULES + " You are Jimin. Soft, clingy.",
    "V": COMMON_RULES + " You are V. Mysterious.",
    "Jungkook": COMMON_RULES + " You are Jungkook. Teasing.",
    "TaeKook": COMMON_RULES + " You are TaeKook. Possessive."
}

# -------------------- DB SETUP --------------------
db_client = None
db_collection_users = None
db_collection_media = None
db_collection_sent = None
db_collection_cooldown = None

# -------------------- GROQ --------------------
groq_client = Groq(api_key=GROQ_API_KEY)
chat_history = {}
last_user_message = {}
current_scenario = {}

def add_emojis_balanced(text):
    if len(text.split()) < 4:
        return text
    return text + " 💜"

def establish_db_connection():
    global db_client, db_collection_users, db_collection_media, db_collection_sent, db_collection_cooldown
    if db_client:
        try:
            db_client.admin.command('ping')
            return True
        except:
            db_client = None
    try:
        db_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db_client.admin.command('ping')
        db = db_client[DB_NAME]
        db_collection_users = db['users']
        db_collection_media = db['channel_media']
        db_collection_sent = db['sent_media']
        db_collection_cooldown = db['cooldown']
        return True
    except Exception as e:
        logger.error(e)
        return False
# ==============================
#  PART 2 / 3
# ==============================

# -------------------- START COMMAND --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    if establish_db_connection():
        db_collection_users.update_one(
            {'user_id': user_id},
            {
                '$set': {
                    'first_name': user_name,
                    'last_seen': datetime.now(timezone.utc),
                    'notified_24h': False
                },
                '$setOnInsert': {
                    'joined_at': datetime.now(timezone.utc),
                    'allow_media': True,
                    'character': 'TaeKook'
                }
            },
            upsert=True
        )

    if user_id in chat_history:
        del chat_history[user_id]

    await update.message.reply_text(
        f"Annyeong, **{user_name}**! 👋💜\nWho do you want to chat with today?",
        parse_mode="Markdown"
    )
    await switch_character(update, context)

# -------------------- CHARACTER SWITCH --------------------
async def switch_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐨 RM", callback_data="set_RM"),
         InlineKeyboardButton("🐹 Jin", callback_data="set_Jin")],
        [InlineKeyboardButton("🐱 Suga", callback_data="set_Suga"),
         InlineKeyboardButton("🐿️ J-Hope", callback_data="set_J-Hope")],
        [InlineKeyboardButton("🐥 Jimin", callback_data="set_Jimin"),
         InlineKeyboardButton("🐯 V", callback_data="set_V")],
        [InlineKeyboardButton("🐰 Jungkook", callback_data="set_Jungkook")]
    ])
    await update.message.reply_text("Pick your favorite! 👇", reply_markup=keyboard)

async def set_character_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    selected_char = query.data.split("_")[1]

    if establish_db_connection():
        db_collection_users.update_one(
            {'user_id': user_id},
            {'$set': {'character': selected_char}}
        )

    await query.answer(f"Selected {selected_char}! 💜")

    keyboard = [
        [InlineKeyboardButton("🥰 Soft Romance", callback_data='plot_Romantic'),
         InlineKeyboardButton("😡 Jealousy", callback_data='plot_Jealous')],
        [InlineKeyboardButton("⚔️ Enemy/Hate", callback_data='plot_Enemy'),
         InlineKeyboardButton("🕶️ Mafia Boss", callback_data='plot_Mafia')],
        [InlineKeyboardButton("🤗 Comfort Me", callback_data='plot_Comfort')]
    ]

    await query.message.edit_text(
        f"**{selected_char}** is ready.\nChoose the vibe 😏",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# -------------------- SCENARIO SET --------------------
async def set_plot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    plot_key = query.data.split("_")[1]

    current_scenario[user_id] = SCENARIOS.get(plot_key, "Just chatting.")

    if user_id in chat_history:
        del chat_history[user_id]

    selected_char = "TaeKook"
    if establish_db_connection():
        user_doc = db_collection_users.find_one({'user_id': user_id})
        if user_doc:
            selected_char = user_doc.get('character', 'TaeKook')

    system_prompt = BTS_PERSONAS.get(selected_char, BTS_PERSONAS["TaeKook"])
    system_prompt += f" SCENARIO: {current_scenario[user_id]}"

    start_prompt = f"Start the roleplay based on scenario: {current_scenario[user_id]}"

    completion = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": start_prompt}
        ],
        model="llama-3.1-8b-instant"
    )

    msg = add_emojis_balanced(completion.choices[0].message.content)

    chat_history[user_id] = [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": msg}
    ]

    await query.message.edit_text(msg, parse_mode="Markdown")

# -------------------- TRUTH OR DARE --------------------
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤔 Truth", callback_data='game_truth'),
         InlineKeyboardButton("🔥 Dare", callback_data='game_dare')]
    ])
    await update.message.reply_text(
        "**Truth or Dare?** 😏",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == 'game_truth':
        await query.edit_message_text(
            f"**TRUTH:** {random.choice(TRUTH_QUESTIONS)}",
            parse_mode="Markdown"
        )
    elif query.data == 'game_dare':
        await query.edit_message_text(
            f"**DARE:** {random.choice(DARE_CHALLENGES)}",
            parse_mode="Markdown"
        )

# -------------------- AI CHAT HANDLER --------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    last_user_message[user_id] = text

    if establish_db_connection():
        db_collection_users.update_one(
            {'user_id': user_id},
            {'$set': {'last_seen': datetime.now(timezone.utc), 'notified_24h': False}},
            upsert=True
        )

    selected_char = "TaeKook"
    if establish_db_connection():
        user_doc = db_collection_users.find_one({'user_id': user_id})
        if user_doc:
            selected_char = user_doc.get('character', 'TaeKook')

    system_prompt = BTS_PERSONAS.get(selected_char, BTS_PERSONAS["TaeKook"])
    if user_id in current_scenario:
        system_prompt += f" CURRENT SCENARIO: {current_scenario[user_id]}"

    if user_id not in chat_history:
        chat_history[user_id] = [{"role": "system", "content": system_prompt}]
    else:
        chat_history[user_id][0]['content'] = system_prompt

    chat_history[user_id].append({"role": "user", "content": text})

    completion = groq_client.chat.completions.create(
        messages=chat_history[user_id],
        model="llama-3.1-8b-instant"
    )

    reply = add_emojis_balanced(completion.choices[0].message.content)
    chat_history[user_id].append({"role": "assistant", "content": reply})

    regen_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Change Reply", callback_data="regen_msg")]]
    )

    await update.message.reply_text(reply, reply_markup=regen_markup, parse_mode="Markdown")

# -------------------- CALLBACK HANDLER --------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data.startswith("set_"):
        await set_character_handler(update, context)
        return
    if query.data.startswith("plot_"):
        await set_plot_handler(update, context)
        return
    if query.data.startswith("game_"):
        await game_handler(update, context)
        return

    await query.answer() 
# ==============================
#  PART 3 / 3
# ==============================

# -------------------- ADMIN HELPERS --------------------
async def user_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return
    if establish_db_connection():
        count = db_collection_users.count_documents({})
        await update.message.reply_text(f"Total users: {count}")

# -------------------- UPDATED BROADCAST --------------------
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    reply = update.message.reply_to_message
    args_text = " ".join(context.args)

    caption = args_text or ""
    reply_markup = None

    # Button format: Caption | Text-URL
    if "|" in args_text:
        parts = args_text.split("|")
        caption = parts[0].strip()
        buttons = []
        for part in parts[1:]:
            if "-" in part:
                try:
                    txt, url = part.split("-", 1)
                    buttons.append(
                        [InlineKeyboardButton(txt.strip(), url=url.strip())]
                    )
                except:
                    pass
        if buttons:
            reply_markup = InlineKeyboardMarkup(buttons)

    if not establish_db_connection():
        await update.message.reply_text("DB Error")
        return

    users = [u['user_id'] for u in db_collection_users.find({}, {'user_id': 1})]
    sent = 0

    await update.message.reply_text("📣 Broadcasting...")

    for uid in users:
        try:
            # PHOTO
            if reply and reply.photo:
                await context.bot.send_photo(
                    uid,
                    reply.photo[-1].file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    protect_content=True
                )
            # VIDEO
            elif reply and reply.video:
                await context.bot.send_video(
                    uid,
                    reply.video.file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    protect_content=True
                )
            # TEXT
            else:
                await context.bot.send_message(
                    uid,
                    f"📢 {caption}",
                    reply_markup=reply_markup
                )
            sent += 1
        except:
            pass

    await update.message.reply_text(f"✅ Broadcast sent to {sent} users.")

# -------------------- MEDIA SEND --------------------
async def send_new_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_obj = update.message

    if not establish_db_connection():
        await message_obj.reply_text("DB Error.")
        return

    await message_obj.reply_text("Searching... 😉")

    try:
        media = db_collection_media.aggregate([{'$sample': {'size': 1}}])
        result = next(media, None)
        if not result:
            await message_obj.reply_text("No media found.")
            return

        if result['file_type'] == 'photo':
            await message_obj.reply_photo(result['file_id'], caption="Just for you 💜")
        else:
            await message_obj.reply_video(result['file_id'], caption="Just for you 💜")
    except Exception:
        await message_obj.reply_text("Error sending media.")

# -------------------- JOBS --------------------
async def check_inactivity(context: ContextTypes.DEFAULT_TYPE):
    if not establish_db_connection():
        return
    threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    users = db_collection_users.find(
        {'last_seen': {'$lt': threshold}, 'notified_24h': {'$ne': True}}
    )
    for user in users:
        try:
            await context.bot.send_message(
                user['user_id'],
                "Hey… I miss you 💜"
            )
            db_collection_users.update_one(
                {'_id': user['_id']},
                {'$set': {'notified_24h': True}}
            )
        except:
            pass

# -------------------- POST INIT --------------------
async def post_init(application: Application):
    commands = [
        BotCommand("start", "Restart Bot"),
        BotCommand("character", "Change Character"),
        BotCommand("game", "Truth or Dare"),
        BotCommand("broadcast", "Admin Broadcast")
    ]
    await application.bot.set_my_commands(commands)

    if application.job_queue:
        application.job_queue.run_repeating(check_inactivity, interval=3600, first=60)

# -------------------- MAIN --------------------
def main():
    if not all([TOKEN, WEBHOOK_URL, GROQ_API_KEY]):
        logger.error("Missing environment variables.")
        return

    application = Application.builder().token(TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("users", user_count))
    application.add_handler(CommandHandler("broadcast", broadcast_message))
    application.add_handler(CommandHandler("game", start_game))
    application.add_handler(CommandHandler("character", switch_character))

    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_message))

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
