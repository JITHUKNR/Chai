import os
import logging
import threading
import re
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

# --- CONFIGURATION ---
TOKEN = os.environ.get("TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) 
PREMIUM_LIMIT = 50 

# --- DATABASE CONNECTION ---
if not MONGO_URL:
    print("⚠️ MONGO_URL is missing! Data will not be saved.")
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
def home(): return "Chai Bot V14 Running!"
def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# --- MEMORY ---
queues = {'any': [], 'Male': [], 'Female': []}
pairs = {} 

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

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
            'blocked_users': [],
            'last_mode': 'any',
            'referred_by': None
        })
    else:
        users_collection.update_one({'_id': user_id}, {'$set': {'name': first_name}})

def update_referral(referrer_id):
    if db is None: return
    users_collection.update_one({'_id': referrer_id}, {'$inc': {'referrals': 1}})

def set_user_gender(user_id, gender):
    if db is None: return
    users_collection.update_one({'_id': user_id}, {'$set': {'gender': gender}})

def update_search_mode(user_id, mode):
    if db is None: return
    users_collection.update_one({'_id': user_id}, {'$set': {'last_mode': mode}})

def block_user_in_db(user_id, target_id):
    if db is None: return
    users_collection.update_one({'_id': user_id}, {'$addToSet': {'blocked_users': target_id}})

def unblock_user_in_db(user_id, target_id):
    if db is None: return
    users_collection.update_one({'_id': user_id}, {'$pull': {'blocked_users': target_id}})

def unblock_all_in_db(user_id):
    if db is None: return
    users_collection.update_one({'_id': user_id}, {'$set': {'blocked_users': []}})

def has_link(text):
    if not text: return False
    regex = r"(http|https|www\.|t\.me|telegram\.me|\.com|\.net|\.org|\.in)"
    return re.search(regex, text, re.IGNORECASE) is not None

def mask_name(name):
    if not name: return "User"
    # എറർ ഒഴിവാക്കാൻ പേര് ക്ലീൻ ചെയ്യുന്നു (Remove special chars)
    clean_name = re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", "", name)
    if not clean_name: return "User"
    
    if len(clean_name) <= 2: return clean_name + "***"
    return clean_name[:2] + "***"

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    create_or_update_user(user_id, user.first_name)
    user_data = get_user(user_id)
    
    args = context.args
    if args and args[0].isdigit():
        referrer_id = int(args[0])
        if referrer_id != user_id and get_user(referrer_id) and user_data.get('referred_by') is None:
            users_collection.update_one({'_id': user_id}, {'$set': {'referred_by': referrer_id}})
            update_referral(referrer_id)
            try:
                await context.bot.send_message(referrer_id, "🎉 **New Referral!**\nSomeone joined using your link.")
            except: pass
            
    user_data = get_user(user_id)

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
    set_user_gender(user_id, gender)
    
    await update.message.reply_text(f"✅ Gender set to **{gender}**!")
    await show_main_menu(update)

async def show_main_menu(update: Update):
    buttons = [
        [KeyboardButton("🔀 RANDOM (FREE)")],
        [KeyboardButton("💜 GIRLS ONLY"), KeyboardButton("💙 BOYS ONLY")],
        [KeyboardButton("REFER AND EARN PREMIUM 🤑"), KeyboardButton("🌟 Donate Stars")],
        [KeyboardButton("❌ Stop Chat")]
    ]
    await update.message.reply_text(
        "**Main Menu** 🏠\nPlease select an option 👇",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
        parse_mode='Markdown'
    )

async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = update.message.text
    
    create_or_update_user(user_id, user.first_name)
    
    if user_id in pairs:
        await update.message.reply_text("⚠️ You are already in a chat! Use **Skip** or **Stop**.")
        return

    user_data = get_user(user_id)
    if not user_data or user_data.get('gender') is None:
        await start(update, context)
        return

    last_mode = user_data.get('last_mode', 'any')
    target_gender = last_mode
    
    if text == "💜 GIRLS ONLY":
        target_gender = "Female"
        update_search_mode(user_id, "Female")
    elif text == "💙 BOYS ONLY":
        target_gender = "Male"
        update_search_mode(user_id, "Male")
    elif text == "🔀 RANDOM (FREE)":
        target_gender = "any"
        update_search_mode(user_id, "any")
    
    referrals = user_data.get('referrals', 0)
    
    if target_gender == "Female" and referrals < PREMIUM_LIMIT:
        await update.message.reply_text(f"🔒 **Premium Feature!**\nYou need {PREMIUM_LIMIT} referrals to search Girls.")
        return
    
    if target_gender == "Male" and referrals < PREMIUM_LIMIT:
        await update.message.reply_text(f"🔒 **Premium Feature!**\nYou need {PREMIUM_LIMIT} referrals to search Boys.")
        return

    user_gender = user_data['gender']
    
    if user_id not in queues['any']:
        queues['any'].append(user_id)
        if user_gender == "Male": queues['Male'].append(user_id)
        elif user_gender == "Female": queues['Female'].append(user_id)

    mode_text = "Partner"
    if target_gender == "Female": mode_text = "Girl"
    elif target_gender == "Male": mode_text = "Boy"
    
    await update.message.reply_text(f"🔍 **Searching for {mode_text}...**\nWaiting... ☕️")
    
    available_list = queues[target_gender] if target_gender != 'any' else queues['any']
    blocked_list = user_data.get('blocked_users', [])
    
    if len(available_list) > 1:
        for potential_partner in available_list:
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
                
                # Names Cleaned
                my_name = user_data.get('name', 'User')
                partner_name = partner_data.get('name', 'User')
                
                msg_to_me = f"💜 **Connected with new!**\nName : {mask_name(partner_name)}"
                msg_to_partner = f"💜 **Connected with new!**\nName : {mask_name(my_name)}"
                
                chat_buttons = [
                    [KeyboardButton("⏭ Skip"), KeyboardButton("❌ Stop Chat")],
                    [KeyboardButton("⚠️ Report & Block")]
                ]
                markup = ReplyKeyboardMarkup(chat_buttons, resize_keyboard=True)
                
                await context.bot.send_message(user_id, msg_to_me, reply_markup=markup, parse_mode='Markdown')
                await context.bot.send_message(potential_partner, msg_to_partner, reply_markup=markup, parse_mode='Markdown')
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

async def skip_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in pairs:
        partner = pairs[user_id]
        del pairs[user_id]
        del pairs[partner]
        
        await context.bot.send_message(partner, "❌ **Partner skipped you.**\nType /start to find new.")
        await update.message.reply_text("⏭ **Skipped! Searching new...** ⏳")
        
        await find_partner(update, context)
    else:
        await update.message.reply_text("⚠️ You are not in a chat.")
        await show_main_menu(update)

# --- REPORT & BLOCK ---

async def report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in pairs:
        await update.message.reply_text("⚠️ You are not in a chat.")
        return

    keyboard = [
        [InlineKeyboardButton("🤬 Bad Words", callback_data='rep_abuse'), InlineKeyboardButton("🔞 18+", callback_data='rep_adult')],
        [InlineKeyboardButton("🤖 Spam", callback_data='rep_spam'), InlineKeyboardButton("🔙 Cancel", callback_data='rep_cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("⚠️ **Report & Block:**", reply_markup=reply_markup)

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

        block_user_in_db(user_id, partner_id)
        del pairs[user_id]
        del pairs[partner_id]
        
        if ADMIN_ID != 0:
            try:
                reporter = await context.bot.get_chat(user_id)
                target = await context.bot.get_chat(partner_id)
                r_user = f"@{reporter.username}" if reporter.username else "No Username"
                t_user = f"@{target.username}" if target.username else "No Username"
                await context.bot.send_message(
                    chat_id=ADMIN_ID, 
                    text=f"🚨 **REPORT**\nBy: {r_user} ({user_id})\nTo: {t_user} ({partner_id})\nReason: {reason}"
                )
            except: pass

        await context.bot.send_message(partner_id, f"🚫 **Reported for {reason}.**\nChat ended.")
        await query.edit_message_text(f"✅ **Reported & Blocked!**")
        await show_main_menu_callback(query, context)
    else:
        await query.edit_message_text("⚠️ Chat ended.")

async def show_blocked_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_data = get_user(user_id)
    if not user_data: return
    
    blocked_list = user_data.get('blocked_users', [])
    if not blocked_list:
        await query.answer("No blocked users.")
        await query.edit_message_text("✅ **You haven't blocked anyone.**")
        return

    keyboard = []
    for b_user_id in blocked_list[-10:]:
        keyboard.append([InlineKeyboardButton(f"🔓 Unblock ID: {b_user_id}", callback_data=f"unblock_{b_user_id}")])
    
    keyboard.append([InlineKeyboardButton("🔓 Unblock All", callback_data='unblock_all')])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='profile_back')])
    await query.edit_message_text("🚫 **Blocked Users List:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_unblock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == 'profile_back':
        await my_profile_callback(update, context)
        return

    if data == 'unblock_all':
        unblock_all_in_db(user_id)
        await query.answer("All unblocked!")
        await query.edit_message_text("✅ **All blocked users have been unblocked.**")
        return

    if data.startswith('unblock_'):
        target_id = int(data.split('_')[1])
        unblock_user_in_db(user_id, target_id)
        await query.answer("User unblocked!")
        await show_blocked_users(update, context)

# --- STARS & PROFILE ---

async def donate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⭐️ 10", callback_data='pay_10'), InlineKeyboardButton("⭐️ 20", callback_data='pay_20'), InlineKeyboardButton("⭐️ 50", callback_data='pay_50')],
        [InlineKeyboardButton("⭐️ 100", callback_data='pay_100'), InlineKeyboardButton("⭐️ 500", callback_data='pay_500')],
        [InlineKeyboardButton("🔙 Cancel", callback_data='pay_cancel')]
    ]
    await update.message.reply_text("🌟 **Donate Stars:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'pay_cancel': return await query.edit_message_text("❌ Cancelled.")
    
    amount = int(query.data.split('_')[1])
    await context.bot.send_invoice(
        chat_id=query.from_user.id,
        title="Support Chai Bot",
        description=f"Donate {amount} Stars",
        payload=f"chai_{amount}",
        currency="XTR",
        prices=[LabeledPrice("Donation", amount)],
        provider_token=""
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌟 **Thanks for the donation!**")

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data: return
    
    ref_count = user_data.get('referrals', 0)
    blocked_count = len(user_data.get('blocked_users', []))
    
    keyboard = [[InlineKeyboardButton(f"🚫 Manage Blocked Users ({blocked_count})", callback_data='show_blocked')]]
    
    await update.message.reply_text(
        f"👤 **Your Profile**\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"👥 Referrals: {ref_count}/{PREMIUM_LIMIT}\n"
        f"🚫 Blocked: {blocked_count}\n\n"
        f"🔗 Link: `https://t.me/{context.bot.username}?start={user_id}`\n\n"
        f"💡 _Share link to earn premium!_",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )

async def my_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    user_data = get_user(user_id)
    ref_count = user_data.get('referrals', 0)
    blocked_count = len(user_data.get('blocked_users', []))
    
    keyboard = [[InlineKeyboardButton(f"🚫 Manage Blocked Users ({blocked_count})", callback_data='show_blocked')]]
    
    await query.edit_message_text(
        f"👤 **Your Profile**\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"👥 Referrals: {ref_count}/{PREMIUM_LIMIT}\n"
        f"🚫 Blocked: {blocked_count}\n\n"
        f"🔗 Link: `https://t.me/{context.bot.username}?start={user_id}`",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )

async def show_main_menu_callback(query, context):
    buttons = [
        [KeyboardButton("🔀 RANDOM (FREE)")],
        [KeyboardButton("💜 GIRLS ONLY"), KeyboardButton("💙 BOYS ONLY")],
        [KeyboardButton("REFER AND EARN PREMIUM 🤑"), KeyboardButton("🌟 Donate Stars")],
        [KeyboardButton("❌ Stop Chat")]
    ]
    await context.bot.send_message(chat_id=query.from_user.id, text="**Main Menu** 🏠", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True), parse_mode='Markdown')

# --- MESSAGE HANDLER ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text 

    if text == "👦 I am Male" or text == "👧 I am Female":
        await set_gender(update, context)
    elif text == "🔀 RANDOM (FREE)":
        await find_partner(update, context)
    
    elif text and "GIRLS ONLY" in text:
        await find_partner(update, context)
    elif text and "BOYS ONLY" in text:
        await find_partner(update, context)
        
    elif text == "REFER AND EARN PREMIUM 🤑":
        await my_profile(update, context)
    elif text == "💎 My Profile":
        await my_profile(update, context)
        
    elif text == "🌟 Donate Stars":
        await donate_menu(update, context)
    elif text == "❌ Stop Chat":
        await stop_chat(update, context)
    elif text == "⏭ Skip":
        await skip_chat(update, context)
    elif text == "⚠️ Report & Block":
        await report_menu(update, context)
        
    elif user_id in pairs:
        if text and has_link(text):
            await update.message.reply_text("🚫 **Links are not allowed!**")
            return
        try:
            partner_id = pairs[user_id]
            # Typing Indicator
            await context.bot.send_chat_action(chat_id=partner_id, action=constants.ChatAction.TYPING)
            # Copy (Supports Voice, Video, Text)
            await update.message.copy(chat_id=partner_id)
            if ADMIN_ID != 0:
                user = update.effective_user
                uname = f"@{user.username}" if user.username else "No User"
                caption = f"👤 {user.first_name} ({uname})"
                try:
                    if text: await context.bot.send_message(chat_id=ADMIN_ID, text=f"{caption}: {text}")
                    else:
                        await update.message.forward(chat_id=ADMIN_ID)
                        await context.bot.send_message(chat_id=ADMIN_ID, text=f"👆 Media from {caption}")
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
    app.add_handler(CallbackQueryHandler(show_blocked_users, pattern='^show_blocked$'))
    app.add_handler(CallbackQueryHandler(handle_unblock_callback, pattern='^unblock_'))
    app.add_handler(CallbackQueryHandler(handle_unblock_callback, pattern='^profile_back$'))
    app.add_handler(CallbackQueryHandler(handle_payment_callback, pattern='^pay_'))
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    
    print("Chai Bot V14 (Fixes Applied) Started...")
    app.run_polling()

if __name__ == "__main__":
    main()
