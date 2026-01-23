import os
import logging
import threading
from flask import Flask
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.environ.get("TOKEN")
PREMIUM_LIMIT = 50 

# --- WEB SERVER ---
app_web = Flask(__name__)
@app_web.route('/')
def home(): return "Chai Bot Running!"
def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# --- DATA STORAGE ---
users = {}  
queues = {'any': [], 'Male': [], 'Female': []}
pairs = {}

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # Register User
    if user_id not in users:
        users[user_id] = {'gender': None, 'referrals': 0}

    # If gender is NOT set, ask for it
    if users[user_id]['gender'] is None:
        buttons = [[KeyboardButton("👦 I am Male"), KeyboardButton("👧 I am Female")]]
        await update.message.reply_text(
            f"👋 **Hi {user.first_name}!**\n\n"
            "Welcome to **Chai**! ☕️\n"
            "**Before we start, please select your gender:** 👇",
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
            parse_mode='Markdown'
        )
    else:
        # If gender IS set, show main menu directly
        await show_main_menu(update)

async def set_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in users: return await start(update, context)

    # Gender Lock Check
    if users[user_id]['gender'] is not None:
        await update.message.reply_text("⚠️ **Gender is already set!**\nYou cannot change it.")
        await show_main_menu(update)
        return

    if text == "👦 I am Male":
        users[user_id]['gender'] = "Male"
    elif text == "👧 I am Female":
        users[user_id]['gender'] = "Female"
    
    await update.message.reply_text(f"✅ Gender set to **{users[user_id]['gender']}**!")
    await show_main_menu(update)

async def show_main_menu(update: Update):
    # ബട്ടണുകൾ കൃത്യമായി ഇവിടെ സെറ്റ് ചെയ്യുന്നു
    buttons = [
        [KeyboardButton("☕️ Find Partner (Any)")],
        [KeyboardButton("👧 Search Girls (Premium)"), KeyboardButton("👦 Search Boys (Premium)")],
        [KeyboardButton("💎 My Profile"), KeyboardButton("❌ Stop Chat")]
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

    # Gender check
    if user_id not in users or users[user_id]['gender'] is None:
        await start(update, context)
        return

    target_gender = "any"
    
    # Premium Check
    if "Girls" in text:
        if users[user_id]['referrals'] < PREMIUM_LIMIT:
            await update.message.reply_text("🔒 **Premium Feature!**\nYou need 50 referrals.")
            return
        target_gender = "Female"
    elif "Boys" in text:
        if users[user_id]['referrals'] < PREMIUM_LIMIT:
            await update.message.reply_text("🔒 **Premium Feature!**\nYou need 50 referrals.")
            return
        target_gender = "Male"

    # Queue Logic
    user_gender = users[user_id]['gender']
    
    # Add to queue if not already there
    if user_id not in queues['any']:
        queues['any'].append(user_id)
        if user_gender == "Male": queues['Male'].append(user_id)
        elif user_gender == "Female": queues['Female'].append(user_id)

    await update.message.reply_text(f"🔍 **Searching...**\nWaiting for a partner... ☕️")
    
    # Try to Match
    available_list = queues[target_gender] if target_gender != 'any' else queues['any']
    
    if len(available_list) > 1:
        for potential_partner in available_list:
            if potential_partner != user_id:
                # Match Found!
                
                # 1. Remove both from ALL queues
                for q in queues.values():
                    if user_id in q: q.remove(user_id)
                    if potential_partner in q: q.remove(potential_partner)
                
                # 2. Save Pair
                pairs[user_id] = potential_partner
                pairs[potential_partner] = user_id
                
                # 3. Send Success Message
                await context.bot.send_message(user_id, "✅ **Partner Found!**\nSay Hi! 👋")
                await context.bot.send_message(potential_partner, "✅ **Partner Found!**\nSay Hi! 👋")
                return

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in pairs:
        partner = pairs[user_id]
        del pairs[user_id]
        del pairs[partner]
        await context.bot.send_message(partner, "❌ **Partner left.**\nType /start to find new.")
        await update.message.reply_text("❌ **You left.**\nUse Main Menu to search again.")
        await show_main_menu(update)
        
    elif user_id in queues['any']:
        for q in queues.values():
            if user_id in q: q.remove(user_id)
        await update.message.reply_text("🛑 **Search Stopped.**")
        await show_main_menu(update)
    
    else:
        await update.message.reply_text("⚠️ You are not in a chat.")
        await show_main_menu(update)

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users: return
    
    ref_count = users[user_id]['referrals']
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={user_id}"
    
    await update.message.reply_text(
        f"👤 **Your Profile**\n\n"
        f"Referrals: {ref_count}/{PREMIUM_LIMIT}\n"
        f"Link: `{link}`",
        parse_mode='Markdown'
    )

# --- MESSAGE HANDLER ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # 1. Handle Menu Buttons
    if text == "👦 I am Male" or text == "👧 I am Female":
        await set_gender(update, context)
    elif text == "☕️ Find Partner (Any)":  # കൃത്യം അക്ഷരങ്ങൾ
        await find_partner(update, context)
    elif "Search Girls" in text:
        await find_partner(update, context)
    elif "Search Boys" in text:
        await find_partner(update, context)
    elif "My Profile" in text:
        await my_profile(update, context)
    elif "Stop Chat" in text:
        await stop_chat(update, context)
        
    # 2. Handle Chatting (User to User)
    elif user_id in pairs:
        try:
            await update.message.copy(chat_id=pairs[user_id])
        except:
            await stop_chat(update, context)
            
    # 3. Handle Unknown Text
    else:
        # യൂസർ എന്തെങ്കിലും ടൈപ്പ് ചെയ്താൽ മെനു കാണിക്കുന്നു
        await update.message.reply_text("👇 Please use the buttons below.")
        await show_main_menu(update)

# --- RUN ---
def main():
    if not TOKEN: return
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    
    print("Chai Bot Final Started...")
    app.run_polling()

if __name__ == "__main__":
    main()
