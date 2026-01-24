import os
import logging
import threading
import time
import asyncio
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
def home(): return "Chai Bot V41 (Animation) Running!"
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

def create_or_update_user(user_id, first_name, username):
    if db is None: return
    safe_username = username if username else "None"
    if not users_collection.find_one({'_id': user_id}):
        users_collection.insert_one({
            '_id': user_id,
            'name': first_name,
            'username': safe_username,
            'gender': None,
            'referrals': 0,
            'good_karma': 0,
            'bad_karma': 0,
            'blocked_users': [],
            'last_mode': 'any',
            'referred_by': None
        })
    else:
        users_collection.update_one({'_id': user_id}, {'$set': {'name': first_name, 'username': safe_username}})

def update_referral(referrer_id):
    if db is None: return
    users_collection.update_one({'_id': referrer_id}, {'$inc': {'referrals': 1}})

def update_karma(user_id, is_good=True):
    if db is None: return
    field = 'good_karma' if is_good else 'bad_karma'
    users_collection.update_one({'_id': user_id}, {'$inc': {field: 1}})

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
    
    try:
        if update.message:
            await update.message.reply_text(text, reply_markup=markup, parse_mode='HTML')
        elif update.callback_query:
            await context.bot.send_message(chat_id=update.callback_query.message.chat.id, text=text, reply_markup=markup, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Menu error: {e}")

# --- BACKGROUND TASK ---
def check_inactivity_loop(application):
    while True:
        time.sleep(30)
        current_time = time.time()
        active_pairs = list(pairs.items())
        
        for user_id, partner_id in active_pairs:
            last_time = last_activity.get(user_id, current_time)
            if current_time - last_time > INACTIVITY_LIMIT:
                try:
                    async_send(application, user_id, "⚠️ <b>Chat ended due to inactivity.</b>")
                    async_send(application, partner_id, "⚠️ <b>Chat ended due to inactivity.</b>")
                    if user_id in pairs: del pairs[user_id]
                    if partner_id in pairs: del pairs[partner_id]
                    if user_id in last_activity: del last_activity[user_id]
                    if partner_id in last_activity: del last_activity[partner_id]
                except: pass

def async_send(app, chat_id, text):
    app.create_task(app.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML'))

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    create_or_update_user(user_id, user.first_name, user.username)
    
    args = context.args
    if args and args[0].isdigit():
        referrer_id = int(args[0])
        user_data = get_user(user_id)
        if referrer_id != user_id and get_user(referrer_id) and user_data.get('referred_by') is None:
            users_collection.update_one({'_id': user_id}, {'$set': {'referred_by': referrer_id}})
            update_referral(referrer_id)
            try:
                await context.bot.send_message(referrer_id, "🎉 <b>New Referral!</b>\nSomeone joined using your link.", parse_mode='HTML')
            except: pass
            
    user_data = get_user(user_id)
    if user_data.get('gender') is None:
        buttons = [[KeyboardButton("👦 I am Male"), KeyboardButton("👧 I am Female")]]
        await update.message.reply_text(
            f"👋 <b>Hi {html.escape(user.first_name)}!</b>\n\nWelcome to <b>Chai</b>! ☕️\n<b>Select your gender:</b> 👇",
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True), parse_mode='HTML'
        )
    else:
        await show_main_menu(update, context)

async def set_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if get_user(user_id).get('gender'):
        await update.message.reply_text("⚠️ <b>Gender already set!</b>", parse_mode='HTML')
        await show_main_menu(update, context)
        return
    set_user_gender(user_id, "Male" if text == "👦 I am Male" else "Female")
    await update.message.reply_text(f"✅ Set to <b>{text}</b>!", parse_mode='HTML')
    await show_main_menu(update, context)

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = ' '.join(context.args)
    if not msg:
        await update.message.reply_text("⚠️ <b>Usage:</b> /feedback [message]", parse_mode='HTML')
        return
    if ADMIN_ID != 0:
        try:
            await context.bot.send_message(ADMIN_ID, f"📩 <b>Feedback:</b>\n{html.escape(msg)}\nFrom: {user_id}", parse_mode='HTML')
            await update.message.reply_text("✅ Sent!")
        except: await update.message.reply_text("❌ Error.")

async def send_rating_prompt(context, chat_id, partner_id):
    try:
        keyboard = [[InlineKeyboardButton("👍 Good", callback_data=f"rate_good_{partner_id}"), InlineKeyboardButton("👎 Bad", callback_data=f"rate_bad_{partner_id}")]]
        await context.bot.send_message(chat_id, "📝 <b>How was your partner?</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    except: pass

async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data.startswith('rate_'):
        parts = data.split('_')
        rating = parts[1]; pid = int(parts[2])
        update_karma(pid, is_good=(rating == 'good'))
        await query.answer("Thanks!")
        await query.edit_message_text(f"✅ <b>Rated: {rating.capitalize()}</b>", parse_mode='HTML')

# --- CHAT & FIND PARTNER ---

async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    create_or_update_user(user_id, update.effective_user.first_name, update.effective_user.username)
    
    if user_id in pairs:
        await update.message.reply_text("⚠️ Use <b>Skip</b> or <b>Stop</b>.", parse_mode='HTML')
        return

    user_data = get_user(user_id)
    if not user_data or not user_data.get('gender'): await start(update, context); return

    target_gender = user_data.get('last_mode', 'any')
    if text == "💜 GIRLS ONLY": target_gender = "Female"; update_search_mode(user_id, "Female")
    elif text == "💙 BOYS ONLY": target_gender = "Male"; update_search_mode(user_id, "Male")
    elif text == "🔀 RANDOM (FREE)": target_gender = "any"; update_search_mode(user_id, "any")
    
    if target_gender in ["Female", "Male"] and user_data.get('referrals', 0) < PREMIUM_LIMIT:
        await update.message.reply_text(f"🔒 <b>Premium!</b> Need {PREMIUM_LIMIT} referrals.", parse_mode='HTML')
        return

    user_gender = user_data['gender']
    
    if user_id not in queues['any']:
        queues['any'].append(user_id)
        if user_gender == "Male": queues['Male'].append(user_id)
        elif user_gender == "Female": queues['Female'].append(user_id)

    mode_text = "Girl" if target_gender == "Female" else "Boy" if target_gender == "Male" else "Partner"
    
    # --- ANIMATION START ---
    msg = await update.message.reply_text(f"🔍 <b>Searching for {mode_text}.</b> ☕️", parse_mode='HTML')
    try:
        await asyncio.sleep(0.5)
        await msg.edit_text(f"🔍 <b>Searching for {mode_text}..</b> ☕️", parse_mode='HTML')
        await asyncio.sleep(0.5)
        await msg.edit_text(f"🔍 <b>Searching for {mode_text}...</b> ☕️", parse_mode='HTML')
    except: pass
    # --- ANIMATION END ---
    
    available = queues[target_gender] if target_gender != 'any' else queues['any']
    blocked = user_data.get('blocked_users', [])
    
    if len(available) > 1:
        for partner in available:
            p_data = get_user(partner)
            if partner != user_id and partner not in blocked and user_id not in p_data.get('blocked_users', []):
                for q in queues.values():
                    if user_id in q: q.remove(user_id)
                    if partner in q: q.remove(partner)
                
                pairs[user_id] = partner
                pairs[partner] = user_id
                
                last_activity[user_id] = time.time()
                last_activity[partner] = time.time()
                
                my_masked = mask_name(user_data.get('name', 'User'), user_data.get('good_karma', 0))
                p_masked = mask_name(p_data.get('name', 'User'), p_data.get('good_karma', 0))

                markup = ReplyKeyboardMarkup([[KeyboardButton("⏭ Skip"), KeyboardButton("❌ Stop Chat")], [KeyboardButton("⚠️ Report & Block")]], resize_keyboard=True)
                
                await context.bot.send_message(user_id, f"💜 <b>Connected!</b>\nName: {p_masked}", reply_markup=markup, parse_mode='HTML')
                await context.bot.send_message(partner, f"💜 <b>Connected!</b>\nName: {my_masked}", reply_markup=markup, parse_mode='HTML')
                return 

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in pairs:
        partner = pairs[user_id]
        del pairs[user_id]; del pairs[partner]
        if user_id in last_activity: del last_activity[user_id]
        if partner in last_activity: del last_activity[partner]
        await context.bot.send_message(partner, "❌ <b>Partner left.</b>", parse_mode='HTML')
        await send_rating_prompt(context, user_id, partner)
        await send_rating_prompt(context, partner, user_id)
        await show_main_menu(update, context)
    elif user_id in queues['any']:
        for q in queues.values(): 
            if user_id in q: q.remove(user_id)
        await update.message.reply_text("🛑 <b>Stopped.</b>", parse_mode='HTML')
        await show_main_menu(update, context)
    else: await show_main_menu(update, context)

async def skip_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in pairs:
        partner = pairs[user_id]
        del pairs[user_id]; del pairs[partner]
        if user_id in last_activity: del last_activity[user_id]
        if partner in last_activity: del last_activity[partner]
        await context.bot.send_message(partner, "❌ <b>Skipped.</b>", parse_mode='HTML')
        await send_rating_prompt(context, user_id, partner)
        await send_rating_prompt(context, partner, user_id)
        await find_partner(update, context)
    else: await show_main_menu(update, context)

# --- OTHER HANDLERS ---
async def show_referral_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; data = get_user(uid)
    link = f"https://t.me/{context.bot.username}?start={uid}"
    text = f"💎 <b>REFER & EARN PREMIUM</b> 💎\n\nInvite friends to unlock <b>Media Sharing</b> & <b>Gender Search</b>!\n\n📊 <b>Refs:</b> {data.get('referrals', 0)}/{PREMIUM_LIMIT}\n🔗 <b>Link:</b>\n<code>{link}</code>"
    await update.message.reply_text(text, parse_mode='HTML')

async def show_account_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; data = get_user(uid)
    status = "✅ Premium" if data.get('referrals', 0) >= PREMIUM_LIMIT else "❌ Free"
    safe_user = data.get('username', 'None')
    text = (f"👤 <b>MY ACCOUNT</b>\n\n📛 <b>Name:</b> {html.escape(data.get('name', 'User'))}\n"
            f"🔗 <b>User:</b> @{safe_user}\n"
            f"🆔 <b>ID:</b> <code>{uid}</code>\n🎖 <b>Status:</b> {status}\n"
            f"👍 <b>Good Karma:</b> {data.get('good_karma', 0)}\n"
            f"🚫 <b>Blocked:</b> {len(data.get('blocked_users', []))}")
    kb = [[InlineKeyboardButton("🚫 Manage Blocked", callback_data='show_blocked')]]
    if update.message: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
    else: await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in pairs: return await update.message.reply_text("⚠️ Not in chat.")
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Bad Words", callback_data='rep_abuse'), InlineKeyboardButton("18+", callback_data='rep_adult')], [InlineKeyboardButton("Cancel", callback_data='rep_cancel')]])
    await update.message.reply_text("⚠️ <b>Report:</b>", reply_markup=markup, parse_mode='HTML')

async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    uid = query.from_user.id
    if query.data == 'rep_cancel': return await query.edit_message_text("Cancelled.")
    if uid in pairs:
        pid = pairs[uid]; reason = "Adult" if query.data == 'rep_adult' else "Abuse"
        block_user_in_db(uid, pid); del pairs[uid]; del pairs[pid]
        if ADMIN_ID: 
            try: await context.bot.send_message(ADMIN_ID, f"🚨 <b>Report:</b> {uid} reported {pid} for {reason}", parse_mode='HTML')
            except: pass
        await context.bot.send_message(pid, f"🚫 <b>Reported for {reason}.</b>", parse_mode='HTML')
        await query.edit_message_text("✅ <b>Reported!</b>", parse_mode='HTML')
        await show_main_menu(update, context) 

async def manage_blocked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; uid = query.from_user.id
    if query.data == 'show_blocked':
        blocked = get_user(uid).get('blocked_users', [])[-10:]
        btns = [[InlineKeyboardButton(f"🔓 {bid}", callback_data=f"unblock_{bid}")] for bid in blocked] + [[InlineKeyboardButton("🔙 Back", callback_data='profile_back')]]
        await query.edit_message_text(f"🚫 <b>Blocked ({len(blocked)})</b>", reply_markup=InlineKeyboardMarkup(btns), parse_mode='HTML')
    elif query.data.startswith('unblock_'):
        unblock_user_in_db(uid, int(query.data.split('_')[1]))
        await query.answer("Unblocked!"); await manage_blocked(update, context)
    elif query.data == 'profile_back': await show_account_page(update, context)

# --- ADMIN PANEL ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = [[InlineKeyboardButton("📊 Stats", callback_data='admin_stats')], [InlineKeyboardButton("📢 Broadcast", callback_data='admin_broadcast')], [InlineKeyboardButton("❌ Close", callback_data='admin_close')]]
    await update.message.reply_text("🔒 <b>Admin</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return
    data = query.data
    if data == 'admin_close': await query.message.delete()
    elif data == 'admin_stats':
        total = users_collection.count_documents({})
        active = len(pairs) + len(queues['any']) + len(queues['Male']) + len(queues['Female'])
        await query.edit_message_text(f"📊 <b>Stats</b>\nUsers: {total}\nActive: {active}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data='admin_back')]]), parse_mode='HTML')
    elif data == 'admin_broadcast':
        await query.edit_message_text("📢 Reply /cast to a message.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data='admin_back')]]), parse_mode='HTML')
    elif data == 'admin_back': await admin_panel(query, context)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or not update.message.reply_to_message: return
    users = users_collection.find({}, {'_id': 1}); success = 0
    msg = await update.message.reply_text("📢 Sending...")
    for u in users:
        try: await update.message.reply_to_message.copy(u['_id']); success += 1
        except: pass
    await msg.edit_text(f"✅ Sent to {success} users.")

async def donate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("⭐️ 10", callback_data='pay_10'), InlineKeyboardButton("⭐️ 50", callback_data='pay_50')], [InlineKeyboardButton("🔙 Cancel", callback_data='pay_cancel')]]
    await update.message.reply_text("🌟 <b>Donate:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def handle_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == 'pay_cancel': return await query.edit_message_text("Cancelled.")
    amt = int(query.data.split('_')[1])
    await context.bot.send_invoice(query.from_user.id, "Support Chai", f"Donate {amt} Stars", f"chai_{amt}", "XTR", [LabeledPrice("Donation", amt)], "")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.pre_checkout_query.answer(ok=True)
async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("🌟 <b>Thanks!</b>", parse_mode='HTML')

# --- MAIN MESSAGE HANDLER ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message: return 
    text = update.message.text
    
    # Save Username Here
    create_or_update_user(user.id, user.first_name, user.username)

    if text in ["👦 I am Male", "👧 I am Female"]: await set_gender(update, context)
    elif text == "🔀 RANDOM (FREE)" or text == "💜 GIRLS ONLY" or text == "💙 BOYS ONLY": await find_partner(update, context)
    elif text == "REFER AND EARN PREMIUM 🤑": await show_referral_page(update, context)
    elif text == "👤 MY ACCOUNT": await show_account_page(update, context)
    elif text == "🌟 Donate Stars": await donate_menu(update, context)
    elif text == "📞 Feedback": await update.message.reply_text("✉️ <b>Send Feedback</b>\nType <code>/feedback your_message</code>", parse_mode='HTML')
    elif text == "❌ Stop Chat": await stop_chat(update, context)
    elif text == "⏭ Skip": await skip_chat(update, context)
    elif text == "⚠️ Report & Block": await handle_report(update, context)
    
    elif user.id in pairs:
        last_activity[user.id] = time.time()
        partner_id = pairs[user.id]
        
        # --- VIP MEDIA CHECK ---
        if not text:
            user_data = get_user(user.id)
            if user_data.get('referrals', 0) < PREMIUM_LIMIT:
                await update.message.reply_text("🔒 <b>Premium Feature!</b>\nPhotos/Videos/Voice are for Premium users only.\n\n<i>Refer friends to unlock!</i>", parse_mode='HTML')
                return

        # --- SEND TO REAL PARTNER ---
        try: 
            await context.bot.send_chat_action(partner_id, constants.ChatAction.TYPING)
            await update.message.copy(partner_id)
            last_activity[partner_id] = time.time()
            
            # --- SUPER CLEAN ADMIN LOGS (V41) ---
            if ADMIN_ID:
                p_data = get_user(partner_id)
                p_name = html.escape(p_data.get('name', 'Unknown'))
                
                s_name = html.escape(user.first_name)
                s_user = f"@{user.username}" if user.username else "NoUser"
                
                log_text = (
                    f"🔁 <b>Chat Relay</b>\n"
                    f"🗣 <b>{s_name}</b> ({s_user}) ➡️ <b>{p_name}</b>\n"
                    f"📄 <i>{html.escape(text) if text else 'Media File 📁'}</i>"
                )
                try: await context.bot.send_message(ADMIN_ID, log_text, parse_mode='HTML')
                except: pass

        except Exception as e:
            logger.error(f"Error sending message: {e}")
            await stop_chat(update, context)
    else: await show_main_menu(update, context)

# --- ERROR HANDLER ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

def main():
    if not TOKEN: return
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    
    app.add_error_handler(error_handler)
    
    threading.Thread(target=check_inactivity_loop, args=(app,), daemon=True).start()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("cast", broadcast_command))
    app.add_handler(CommandHandler("feedback", feedback_command))
    
    app.add_handler(CallbackQueryHandler(admin_callback, pattern='^admin_'))
    app.add_handler(CallbackQueryHandler(report_callback, pattern='^rep_'))
    app.add_handler(CallbackQueryHandler(handle_rating, pattern='^rate_'))
    app.add_handler(CallbackQueryHandler(manage_blocked, pattern='^(show_blocked|unblock_|profile_back)'))
    app.add_handler(CallbackQueryHandler(handle_payment_callback, pattern='^pay_'))
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    
    print("Chai Bot V41 (Animation & Logs) Started...")
    app.run_polling()

if __name__ == "__main__":
    main()
