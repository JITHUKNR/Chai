import os
import logging
import threading
from flask import Flask
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.environ.get("TOKEN")
PREMIUM_LIMIT = 50  # Referrals needed for premium

# --- WEB SERVER (Render) ---
app_web = Flask(__name__)
@app_web.route('/')
def home(): return "Chai International is Running!"
def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# --- DATA STORAGE (Memory) ---
users = {}  
queues = {'any': [], 'Male': [], 'Female': []}
pairs = {}

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    args = context.args

    # Check for referral
    if user_id not in users:
        referrer_id = None
        if args and args[0].isdigit():
            referrer_id = int(args[0])
            if referrer_id != user_id and referrer_id in users:
                users[referrer_id]['referrals'] += 1
                try:
                    await context.bot.send_message(referrer_id, "🎉 **New Referral!**\nSomeone joined using your link.")
                except:
                    pass

        users[user_id] = {'gender': None, 'referrals': 0, 'premium': False, 'referred_by': referrer_id}

    # Ask for Gender if not set
    if users[user_id]['gender'] is None:
        buttons = [[KeyboardButton("👦 I am Male"), KeyboardButton("👧 I am Female")]]
        await update.message.reply_text(
            f"👋 **Hi {user.first_name}!**\n\n"
            "Welcome to **Chai**! ☕️\n"
            "Here you can chat anonymously with strangers.\n\n"
            "**Before we start, please select your gender:** 👇",
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
            parse_mode='Markdown'
        )
    else:
        await show_main_menu(update)

async def set_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in users: return await start(update, context)

    if text == "👦 I am Male":
        users[user_id]['gender'] = "Male"
    elif text == "👧 I am Female":
        users[user_id]['gender'] = "Female"
    else:
        return

    await update.message.reply_text(f"✅ Gender set to **{users[user_id]['gender']}**!")
    await show_main_menu(update)

async def show_main_menu(update: Update):
    buttons = [
        [KeyboardButton("🔀 RANDOM (FREE)")],
        [KeyboardButton("👧 Search Girls (Premium)"), KeyboardButton("👦 Search Boys (Premium)")],
        [KeyboardButton("💎 My Profile & Link"), KeyboardButton("❌ Stop Chat")]
    ]
    await update.message.reply_text(
        "**Main Menu** 🏠\nPlease select an option 👇",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
        parse_mode='Markdown'
    )

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    if user_id not in users: return await start(update, context)

    ref_count = users[user_id]['referrals']
    is_premium = ref_count >= PREMIUM_LIMIT
    status = "💎 PREMIUM" if is_premium else "🆓 FREE"
    
    bot_username = context.bot.username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"

    text = (
        f"👤 **User Profile**\n"
        f"Name: {user.first_name}\n"
        f"Status: **{status}**\n"
        f"Referrals: {ref_count}/{PREMIUM_LIMIT}\n\n"
        f"🔗 **Your Referral Link:**\n`{ref_link}`\n\n"
        f"💡 _Share this link! Get {PREMIUM_LIMIT} referrals to unlock Gender Filter!_"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id in pairs:
        await update.message.reply_text("⚠️ You are already in a chat! Click **Stop Chat** first.")
        return

    target_gender = "any"
    
    # Premium Check
    if text == "👧 Search Girls (Premium)":
        if users[user_id]['referrals'] < PREMIUM_LIMIT:
            await update.message.reply_text("🔒 **Premium Feature!**\nYou need 50 referrals to use this feature. Check 'My Profile'.")
            return
        target_gender = "Female"
        
    elif text == "👦 Search Boys (Premium)":
        if users[user_id]['referrals'] < PREMIUM_LIMIT:
            await update.message.reply_text("🔒 **Premium Feature!**\nYou need 50 referrals to use this feature. Check 'My Profile'.")
            return
        target_gender = "Male"

    # Queue Logic
    user_gender = users[user_id]['gender']
    
    if user_id not in queues['any']:
        queues['any'].append(user_id)
        if user_gender == "Male": queues['Male'].append(user_id)
        elif user_gender == "Female": queues['Female'].append(user_id)

    await update.message.reply_text(f"🔍 **Searching for partner...**\nPlease wait! 💜")
    
    # Check for Match
    match_found = False
    
    # Helper to connect
    async def connect(u1, u2):
        for q in queues.values():
            if u1 in q: q.remove(u1)
            if u2 in q: q.remove(u2)
        pairs[u1] = u2
        pairs[u2] = u1
        await context.bot.send_message(u1, "✅ **Partner Found!** Say Hi! 👋")
        await context.bot.send_message(u2, "✅ **Partner Found!** Say Hi! 👋")

    # Matching Logic
    available_list = queues[target_gender] if target_gender != 'any' else queues['any']
    
    if len(available_list) > 1:
        for potential_partner in available_list:
            if potential_partner != user_id:
                # Basic check to avoid self-match logic errors
                await connect(user_id, potential_partner)
                match_found = True
                break

# --- MAIN HANDLER ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if text in ["👦 I am Male", "👧 I am Female"]:
        await set_gender(update, context)
    elif text == "💎 My Profile & Link":
        await my_profile(update, context)
    elif "Find Partner" in text or "Search" in text:
        await find_partner(update, context)
    elif text == "❌ Stop Chat":
        if user_id in pairs:
            partner = pairs[user_id]
            del pairs[user_id]
            del pairs[partner]
            await context.bot.send_message(partner, "❌ **Partner left.**\nType /start to find a new one.")
            await update.message.reply_text("❌ **You left.**\nSelect **Find Partner** to search again.")
        elif user_id in queues['any']:
            for q in queues.values():
                if user_id in q: q.remove(user_id)
            await update.message.reply_text("🛑 **Search Stopped.**")
        else:
            await update.message.reply_text("⚠️ You are not in a chat.")
            
    elif user_id in pairs:
        try: await update.message.copy(chat_id=pairs[user_id])
        except: pass
        
    else:
        if text not in ["👦 I am Male", "👧 I am Female"]: 
            await update.message.reply_text("👇 Please use the menu buttons.")

# --- RUN ---
def main():
    if not TOKEN: return
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    
    print("Chai International Started...")
    app.run_polling()

if __name__ == "__main__":
    main()
