import os
import logging
import threading
from flask import Flask
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.environ.get("TOKEN")
PREMIUM_LIMIT = 50  # പ്രീമിയം കിട്ടാൻ വേണ്ട റെഫറലുകൾ

# --- WEB SERVER (Render) ---
app_web = Flask(__name__)
@app_web.route('/')
def home(): return "Chai Premium is Running!"
def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# --- DATA STORAGE (Memory) ---
# ശ്രദ്ധിക്കുക: Render റീസ്റ്റാർട്ട് ആയാൽ ഈ ഡാറ്റ പോകും. 
# ഡാറ്റ സേവ് ചെയ്യാൻ പിന്നീട് Database ഉപയോഗിക്കണം.
users = {}  # {user_id: {'gender': 'M', 'referrals': 0, 'premium': False, 'referred_by': None}}
queues = {'any': [], 'Male': [], 'Female': []}
pairs = {}

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    args = context.args  # റെഫറൽ ലിങ്ക് വഴി വന്നോ എന്ന് നോക്കുന്നു

    # പുതിയ യൂസർ ആണെങ്കിൽ
    if user_id not in users:
        referrer_id = None
        if args and args[0].isdigit():
            referrer_id = int(args[0])
            # സ്വന്തം ലിങ്ക് ക്ലിക്ക് ചെയ്താലോ എന്ന് നോക്കുന്നു
            if referrer_id != user_id and referrer_id in users:
                users[referrer_id]['referrals'] += 1
                try:
                    await context.bot.send_message(referrer_id, "🎉 **New Referral!**\nനിങ്ങളുടെ ലിങ്ക് വഴി ഒരാൾ ജോയിൻ ചെയ്തു.")
                except:
                    pass

        users[user_id] = {'gender': None, 'referrals': 0, 'premium': False, 'referred_by': referrer_id}

    # ആദ്യം ജെൻഡർ ചോദിക്കുന്നു
    if users[user_id]['gender'] is None:
        buttons = [[KeyboardButton("👦 I am Male"), KeyboardButton("👧 I am Female")]]
        await update.message.reply_text(
            f"👋 **Hi {user.first_name}!**\n\nBefore we start, please select your gender:",
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
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
        [KeyboardButton("☕️ Find Partner (Any)")],
        [KeyboardButton("👧 Search Girls (Premium)"), KeyboardButton("👦 Search Boys (Premium)")],
        [KeyboardButton("💎 My Profile & Link"), KeyboardButton("❌ Stop Chat")]
    ]
    await update.message.reply_text(
        "**Main Menu** 🏠\nതിരഞ്ഞെടുക്കൂ 👇",
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
    
    # റെഫറൽ ലിങ്ക് ഉണ്ടാക്കുന്നു
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
        await update.message.reply_text("⚠️ You are already in a chat!")
        return

    target_gender = "any"
    
    # Premium Check
    if text == "👧 Search Girls (Premium)":
        if users[user_id]['referrals'] < PREMIUM_LIMIT:
            await update.message.reply_text("🔒 **Premium Feature!**\nനിങ്ങൾക്ക് 50 റെഫറലുകൾ ഇല്ല. 'My Profile' നോക്കുക.")
            return
        target_gender = "Female"
        
    elif text == "👦 Search Boys (Premium)":
        if users[user_id]['referrals'] < PREMIUM_LIMIT:
            await update.message.reply_text("🔒 **Premium Feature!**\nനിങ്ങൾക്ക് 50 റെഫറലുകൾ ഇല്ല. 'My Profile' നോക്കുക.")
            return
        target_gender = "Male"

    # Queue Logic
    user_gender = users[user_id]['gender']
    
    # 1. Add to searching list
    if user_id not in queues['any']:
        queues['any'].append(user_id)
        if user_gender == "Male": queues['Male'].append(user_id)
        elif user_gender == "Female": queues['Female'].append(user_id)

    # 2. Searching...
    await update.message.reply_text(f"🔍 **Searching for {target_gender}...**\nPlease wait.")
    
    # 3. Match Logic (Simple version)
    # Note: In a real app, this logic is more complex to avoid matching with self or incorrect gender
    match_found = False
    
    # If searching for ANY
    if target_gender == "any":
        if len(queues['any']) > 1:
            for potential_partner in queues['any']:
                if potential_partner != user_id:
                    connect_users(user_id, potential_partner, context)
                    match_found = True
                    break
    
    # If searching for Specific Gender (Premium)
    else:
        if len(queues[target_gender]) > 0:
            for potential_partner in queues[target_gender]:
                if potential_partner != user_id:
                    connect_users(user_id, potential_partner, context)
                    match_found = True
                    break

def connect_users(user1, user2, context):
    # Remove from all queues
    for q in queues.values():
        if user1 in q: q.remove(user1)
        if user2 in q: q.remove(user2)
    
    pairs[user1] = user2
    pairs[user2] = user1
    
    # Notify users (Background task requires async handling, simplified here)
    # In this simple sync logic within async function calls, we might face issues if not handled carefully.
    # But since we call this from find_partner which is async, we can't await directly inside this helper easily without passing context.
    # So we let the loop handle the connection or use a trick.
    pass # Actual connection message sent in the loop below

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
        # Check for match immediately after adding to queue
        # (Simplified Matching Logic for this code block)
        if user_id in queues['any']: # Still in queue
            # Try to find match
            target_q = 'any'
            if "Girls" in text: target_q = 'Female'
            elif "Boys" in text: target_q = 'Male'
            
            # Look for partner
            partner = None
            available_list = queues[target_q] if target_q != 'any' else queues['any']
            
            for p in available_list:
                if p != user_id and p not in pairs:
                    partner = p
                    break
            
            if partner:
                # Remove both from queues
                for q in queues.values():
                    if user_id in q: q.remove(user_id)
                    if partner in q: q.remove(partner)
                
                pairs[user_id] = partner
                pairs[partner] = user_id
                
                await context.bot.send_message(user_id, "✅ **Connected!** Say Hi 👋")
                await context.bot.send_message(partner, "✅ **Connected!** Say Hi 👋")

    elif text == "❌ Stop Chat":
        if user_id in pairs:
            partner = pairs[user_id]
            del pairs[user_id]
            del pairs[partner]
            await context.bot.send_message(partner, "❌ **Partner left.**")
            await update.message.reply_text("❌ **You left.**")
        elif user_id in queues['any']:
            for q in queues.values():
                if user_id in q: q.remove(user_id)
            await update.message.reply_text("🛑 **Search Stopped.**")
            
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
    
    print("Chai Premium Started...")
    app.run_polling()

if __name__ == "__main__":
    main()
