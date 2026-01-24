import os
import logging
import threading
import time
from flask import Flask
import pymongo
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, 
    InlineKeyboardMarkup, LabeledPrice, constants
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    PreCheckoutQueryHandler, filters, ContextTypes
)
import html

# --- CONFIGURATION ---
TOKEN = os.environ.get("TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) 
PREMIUM_LIMIT = 50 
STAR_BADGE_LIMIT = 10 
INACTIVITY_LIMIT = 180 

# --- DATABASE CONNECTION ---
if not MONGO_URL:
    db = None
else:
    try:
        client = pymongo.MongoClient(MONGO_URL)
        db = client['ChaiBot']
        users_collection = db['users']
        print("✅ Connected to MongoDB!")
    except Exception as e:
        print(f"❌ Database Error: {e}")
        db = None

# --- WEB SERVER ---
app_web = Flask(__name__)
@app_web.route('/')
def home(): return "Chai Bot V39 (Perfect Logs) Running!"
def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# --- MEMORY ---
queues = {'any': [], 'Male': [], 'Female': []}
pairs = {} 
last_activity = {} 

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- HELPER FUNCTIONS ---
def get_user(user_id):
    if db is None: return {}
    data = users_collection.find_one({'_id': user_id})
    return data if data else {}

def create_or_update_user(user_id, first_name):
    if db is None: return
    if not users_collection.find_one({'_id': user_id}):
        users_collection.insert_one({
            '_id': user_id,
            'name': first_name,
            'gender': None,
            'referrals': 0,
            'good_karma': 0,
            'bad_karma': 0,
            'blocked_users': [],
            'last_mode': 'any',
            'referred_by': None
        })
    else:
        users_collection.update_one({'_id': user_id}, {'$set': {'name': first_name}})

def mask_name(name, good_karma=0):
    if not name: return "User"
    safe_name = html.escape(name)
    masked = safe_name[:2] + "***" if len(safe_name) > 2 else safe_name + "***"
    return f"⭐️ {masked}" if good_karma >= STAR_BADGE_LIMIT else masked

# --- UI HELPERS ---
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [KeyboardButton("🔀 RANDOM (FREE)")],
        [KeyboardButton("💜 GIRLS ONLY"), KeyboardButton("💙 BOYS ONLY")],
        [KeyboardButton("REFER AND EARN PREMIUM 🤑"), KeyboardButton("👤 MY ACCOUNT")],
        [KeyboardButton("🌟 Donate Stars"), KeyboardButton("📞 Feedback")]
    ]
    markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    text = "<b>Main Menu</b> 🏠\nPlease select an option 👇"
    if update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='HTML')
    elif update.callback_query:
        await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text=text, reply_markup=markup, parse_mode='HTML')

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.first_name)
    user_data = get_user(user.id)
    if user_data.get('gender') is None:
        buttons = [[KeyboardButton("👦 I am Male"), KeyboardButton("👧 I am Female")]]
        await update.message.reply_text(f"👋 <b>Hi {html.escape(user.first_name)}!</b>\nSelect gender:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True), parse_mode='HTML')
    else: await show_main_menu(update, context)

async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in pairs: return await update.message.reply_text("⚠️ Already in chat.")
    user_data = get_user(user_id)
    mode = user_data.get('last_mode', 'any')
    
    if user_id not in queues['any']:
        queues['any'].append(user_id)
        queues[user_data['gender']].append(user_id)

    await update.message.reply_text("🔍 <b>Searching for Real Users...</b>", parse_mode='HTML')
    
    target = queues[mode] if mode != 'any' else queues['any']
    if len(target) > 1:
        for p in target:
            if p != user_id:
                for q in queues.values():
                    if user_id in q: q.remove(user_id)
                    if p in q: q.remove(p)
                pairs[user_id] = p; pairs[p] = user_id
                last_activity[user_id] = last_activity[p] = time.time()
                markup = ReplyKeyboardMarkup([[KeyboardButton("⏭ Skip"), KeyboardButton("❌ Stop Chat")]], resize_keyboard=True)
                await context.bot.send_message(user_id, "💜 <b>Connected!</b>", reply_markup=markup, parse_mode='HTML')
                await context.bot.send_message(p, "💜 <b>Connected!</b>", reply_markup=markup, parse_mode='HTML')
                return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    
    if text in ["👦 I am Male", "👧 I am Female"]:
        users_collection.update_one({'_id': user.id}, {'$set': {'gender': "Male" if "Male" in text else "Female"}})
        await show_main_menu(update, context)
    elif text == "🔀 RANDOM (FREE)": await find_partner(update, context)
    elif text == "❌ Stop Chat":
        if user.id in pairs:
            p = pairs[user.id]; del pairs[user.id]; del pairs[p]
            await context.bot.send_message(p, "❌ <b>Partner left.</b>", parse_mode='HTML')
        await show_main_menu(update, context)
    elif user.id in pairs:
        p = pairs[user.id]
        await update.message.copy(p)
        # --- മനോഹരമായ അഡ്മിൻ ലോഗുകൾ ---
        if ADMIN_ID:
            log_msg = (
                f"💬 <b>ചാറ്റ് ലോഗ്</b>\n"
                f"👤 <b>അയച്ചയാൾ:</b> {html.escape(user.first_name)} (<code>{user.id}</code>)\n"
                f"➡️ <b>സ്വീകർത്താവ്:</b> (<code>{p}</code>)\n"
                f"------------------------\n"
                f"📝 <b>മെസ്സേജ്:</b>\n{html.escape(text) if text else '🖼 <i>മീഡിയ ഫയൽ</i>'}"
            )
            await context.bot.send_message(ADMIN_ID, log_msg, parse_mode='HTML')
            if not text: await update.message.forward(ADMIN_ID)
    else: await show_main_menu(update, context)

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.pre_checkout_query.answer(ok=True)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    threading.Thread(target=run_web_server, daemon=True).start()
    print("V39 Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
