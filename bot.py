import os
import logging
import threading
import re
from flask import Flask
import pymongo # ഡാറ്റാബേസ് പാക്കേജ്
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, 
    InlineKeyboardMarkup, LabeledPrice
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    PreCheckoutQueryHandler, filters, ContextTypes
)

# --- CONFIGURATION ---
TOKEN = os.environ.get("TOKEN")
MONGO_URL = os.environ.get("MONGO_URL") # റെൻഡറിൽ കൊടുത്ത ലിങ്ക് എടുക്കുന്നു
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
PREMIUM_LIMIT = 50 

# --- DATABASE CONNECTION (MongoDB) ---
if not MONGO_URL:
    print("⚠️ MONGO_URL is missing! Data will not be saved.")
    db = None
else:
    try:
        client = pymongo.MongoClient(MONGO_URL)
        db = client['ChaiBot'] # ഡാറ്റാബേസ് പേര്
        users_collection = db['users'] # യൂസർമാരുടെ വിവരങ്ങൾ
        print("✅ Connected to MongoDB!")
    except Exception as e:
        print(f"❌ Database Error: {e}")
        db = None

# --- WEB SERVER ---
app_web = Flask(__name__)
@app_web.route('/')
def home(): return "Chai Bot with Database Running!"
def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# --- MEMORY (Temporary) ---
# Queue and Pairs are temporary (active chats break on restart anyway)
queues = {'any': [], 'Male': [], 'Female': []}
pairs = {} 

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- HELPER FUNCTIONS (DB) ---

def get_user(user_id):
    if db is None: return {}
    return users_collection.find_one({'_id': user_id})

def create_user(user_id, first_name):
    if db is None: return
    if not users_collection.find_one({'_id': user_id}):
        users_collection.insert_one({
            '_id': user_id,
            'name': first_name,
            'gender': None,
            'referrals': 0,
            'blocked_users': [],
            'referred_by': None
        })

def update_referral(referrer_id):
    if db is None: return
    users_collection.update_one(
        {'_id': referrer_id},
        {'$inc': {'referrals': 1}} # കൗണ്ട് 1 കൂട്ടുന്നു
    )

def set_user_gender(user_id, gender):
    if db is None: return
    users_collection.update_one(
        {'_id': user_id},
        {'$set': {'gender': gender}}
    )

def block_user_in_db(user_id, target_id):
    if db is None: return
    users_collection.update_one(
        {'_id': user_id},
        {'$addToSet': {'blocked_users': target_id}} # ഡ്യൂപ്ലിക്കേറ്റ് വരാതെ ചേർക്കുന്നു
    )

def unblock_all_in_db(user_id):
    if db is None: return
    users_collection.update_one(
        {'_id': user_id},
        {'$set': {'blocked_users': []}}
    )

def has_link(text):
    if not text: return False
    regex = r"(http|https|www\.|t\.me|telegram\.me|\.com|\.net|\.org|\.in)"
    return re.search(regex, text, re.IGNORECASE) is not None

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # Check User in DB
    user_data = get_user(user_id)
    
    if not user_data:
        # Create New User
        create_user(user_id, user.first_name)
        
        # Check Referral
        args = context.args
        if args and args[0].isdigit():
            referrer_id = int(args[0])
            # സ്വന്തം ലിങ്ക് അല്ല, റെഫറർ നിലവിലുണ്ട് എന്ന് ഉറപ്പാക്കുന്നു
            if referrer_id != user_id and get_user(referrer_id):
                update_referral(referrer_id) # DB Update
                try:
                    await context.bot.send_message(referrer_id, "🎉 **New Referral!**\nSomeone joined using your link.")
                except: pass
        
        # Refresh Data
        user_data = get_user(user_id)

    # If gender is NOT set
    if user_data.get('gender') is None:
        buttons = [[KeyboardButton("👦 I am Male"), KeyboardButton("👧 I am Female")]]
        await update.message.reply_text(
            f"👋 **Hi {user.first_name}!**\n\n"
            "Welcome to **Chai**! ☕️\n"
            "**Before we start, please select your gender:** 👇",
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
            parse_mode='Markdown'
        )
    else:
        await show_main_menu(update)

async def set_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    user_data = get_user(user_id)

    if not user_data: return await start(update, context)

    if user_data.get('gender') is not None:
        await update.message.reply_text("⚠️ **Gender is already set!**\nYou cannot change it.")
        await show_main_menu(update)
        return

    gender = "Male" if text == "👦 I am Male" else "Female"
    set_user_gender(user_id, gender) # DB Save
    
    await update.message.reply_text(f"✅ Gender set to **{gender}**!")
    await show_main_menu(update)

async def show_main_menu(update: Update):
    buttons = [
        [KeyboardButton("🔀 RANDOM (FREE)")],
        [KeyboardButton("👧 Search Girls (Premium)"), KeyboardButton("👦 Search Boys (Premium)")],
        [KeyboardButton("💎 My Profile"), KeyboardButton("🌟 Donate Stars")],
        [KeyboardButton("❌ Stop Chat")]
    ]
    await update.message.reply_text(
        "**Main Menu** 🏠\nPlease select an option 👇",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
        parse_mode='Markdown'
    )

async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id in pairs:
        await update.message.reply_text("⚠️ You are already in a chat! Click **Stop Chat** first.")
        return

    user_data = get_user(user_id)
    if not user_data or user_data.get('gender') is None:
        await start(update, context)
        return

    target_gender = "any"
    referrals = user_data.get('referrals', 0)
    
    if "Girls" in text:
        if referrals < PREMIUM_LIMIT:
            await update.message.reply_text(f"🔒 **Premium Feature!**\nYou need {PREMIUM_LIMIT} referrals.")
            return
        target_gender = "Female"
    elif "Boys" in text:
        if referrals < PREMIUM_LIMIT:
            await update.message.reply_text(f"🔒 **Premium Feature!**\nYou need {PREMIUM_LIMIT} referrals.")
            return
        target_gender = "Male"

    user_gender = user_data['gender']
    
    if user_id not in queues['any']:
        queues['any'].append(user_id)
        if user_gender == "Male": queues['Male'].append(user_id)
        elif user_gender == "Female": queues['Female'].append(user_id)

    await update.message.reply_text(f"🔍 **Searching...**\nWaiting for a partner... ☕️")
    
    available_list = queues[target_gender] if target_gender != 'any' else queues['any']
    blocked_list = user_data.get('blocked_users', [])
    
    if len(available_list) > 1:
        for potential_partner in available_list:
            # Check Partner's Block List from DB
            partner_data = get_user(potential_partner)
            partner_blocked = partner_data.get('blocked_users', [])
            
            if (potential_partner != user_id and 
                potential_partner not in blocked_list and 
                user_id not in partner_blocked):
                
                for q in queues.values():
                    if user_id in q: q.remove(user_id)
                    if potential_partner in q: q.remove(potential_partner)
                
                pairs[user_id] = potential_partner
                pairs[potential_partner] = user_id
                
                chat_buttons = [[KeyboardButton("❌ Stop Chat"), KeyboardButton("⚠️ Report & Block")]]
                markup = ReplyKeyboardMarkup(chat_buttons, resize_keyboard=True)
                
                await context.bot.send_message(user_id, "✅ **Partner Found!**\nSay Hi! 👋", reply_markup=markup)
                await context.bot.send_message(potential_partner, "✅ **Partner Found!**\nSay Hi! 👋", reply_markup=markup)
                return

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in pairs:
        partner = pairs[user_id]
        del pairs[user_id]
        del pairs[partner]
        
        await context.bot.send_message(partner, "❌ **Partner left.**\nType /start to find new.")
        await show_main_menu(update)
        
    elif user_id in queues['any']:
        for q in queues.values():
            if user_id in q: q.remove(user_id)
        await update.message.reply_text("🛑 **Search Stopped.**")
        await show_main_menu(update)
    
    else:
        await update.message.reply_text("⚠️ You are not in a chat.")
        await show_main_menu(update)

async def report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in pairs:
        await update.message.reply_text("⚠️ You are not in a chat.")
        return

    keyboard = [
        [InlineKeyboardButton("🤬 Bad Words / Abuse", callback_data='rep_abuse')],
        [InlineKeyboardButton("🔞 18+ / Adult Content", callback_data='rep_adult')],
        [InlineKeyboardButton("🤖 Spam / Scam", callback_data='rep_spam')],
        [InlineKeyboardButton("🔙 Cancel", callback_data='rep_cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("⚠️ **Select a reason to Report & Block:**", reply_markup=reply_markup)

async def handle_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id

    if data == 'rep_cancel':
        await query.edit_message_text("✅ Report cancelled.")
        return

    if user_id in pairs:
        partner_id = pairs[user_id]
        reason = "Abuse"
        if data == 'rep_adult': reason = "Adult Content"
        elif data == 'rep_spam': reason = "Spam"

        # Block in DB
        block_user_in_db(user_id, partner_id)

        del pairs[user_id]
        del pairs[partner_id]
        
        if ADMIN_ID != 0:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID, 
                    text=f"🚨 **REPORT ALERT**\nReporter: {user_id}\nTarget: {partner_id}\nReason: {reason}"
                )
            except: pass

        await context.bot.send_message(partner_id, f"🚫 **You have been reported for {reason}.**\nChat ended.")
        await query.edit_message_text(f"✅ **Reported & Blocked!**\nYou won't match with them again.")
        await show_main_menu_callback(query, context)
    else:
        await query.edit_message_text("⚠️ Chat already ended.")

async def show_main_menu_callback(query, context):
    buttons = [
        [KeyboardButton("🔀 RANDOM (FREE)")],
        [KeyboardButton("👧 Search Girls (Premium)"), KeyboardButton("👦 Search Boys (Premium)")],
        [KeyboardButton("💎 My Profile"), KeyboardButton("🌟 Donate Stars")],
        [KeyboardButton("❌ Stop Chat")]
    ]
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="**Main Menu** 🏠\nPlease select an option 👇",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
        parse_mode='Markdown'
    )

async def handle_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == 'unblock_all':
        user_id = query.from_user.id
        unblock_all_in_db(user_id) # DB Clear
        await query.answer("All users unblocked!")
        await query.edit_message_text("✅ **All blocked users have been cleared.**")

async def donate_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_invoice(
        chat_id=update.message.chat_id,
        title="Support Chai Bot ☕️",
        description="Donate 50 Stars to help us keep the server running!",
        payload="chai_donation",
        currency="XTR",
        prices=[LabeledPrice("Donation", 50)],
        provider_token=""
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload != 'chai_donation':
        await query.answer(ok=False, error_message="Something went wrong.")
    else:
        await query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌟 **Thank you for your donation!** 🌟")

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data: return
    
    ref_count = user_data.get('referrals', 0)
    blocked_count = len(user_data.get('blocked_users', []))
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={user_id}"
    
    keyboard = [[InlineKeyboardButton("🔓 Unblock All Users", callback_data='unblock_all')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"👤 **Your Profile**\n\n"
        f"Referrals: {ref_count}/{PREMIUM_LIMIT}\n"
        f"Blocked Users: {blocked_count}\n"
        f"Link: `{link}`",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if text == "👦 I am Male" or text == "👧 I am Female":
        await set_gender(update, context)
    elif text == "🔀 RANDOM (FREE)":
        await find_partner(update, context)
    elif "Search Girls" in text:
        await find_partner(update, context)
    elif "Search Boys" in text:
        await find_partner(update, context)
    elif "My Profile" in text:
        await my_profile(update, context)
    elif "Donate Stars" in text:
        await donate_stars(update, context)
    elif text == "❌ Stop Chat":
        await stop_chat(update, context)
    elif text == "⚠️ Report & Block":
        await report_menu(update, context)
        
    elif user_id in pairs:
        if text and has_link(text):
            await update.message.reply_text("🚫 **Links are not allowed!**")
            return

        try:
            await update.message.copy(chat_id=pairs[user_id])
            if ADMIN_ID != 0:
                try: await update.message.forward(chat_id=ADMIN_ID)
                except: pass
        except:
            await stop_chat(update, context)
    else:
        await show_main_menu(update)

def main():
    if not TOKEN: return
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_report_callback, pattern='^rep_'))
    app.add_handler(CallbackQueryHandler(handle_profile_callback, pattern='^unblock_all'))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    
    print("Chai Bot Database Version Started...")
    app.run_polling()

if __name__ == "__main__":
    main()
