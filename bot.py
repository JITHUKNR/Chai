import os
import logging
import threading
from flask import Flask
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. CONFIGURATION ---
TOKEN = os.environ.get("TOKEN")

# --- 2. WEB SERVER (Render-ൽ ഓഫ് ആകാതിരിക്കാൻ) ---
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Chai Bot is Running! ☕️"

def run_web_server():
    port = int(os.environ.get('PORT', 8080))
    app_web.run(host='0.0.0.0', port=port)

# --- 3. VARIABLES (ഇവിടെയാണ് ലിസ്റ്റ് സൂക്ഷിക്കുന്നത്) ---
queue = []      # വരിയിൽ നിൽക്കുന്നവർ
pairs = {}      # ജോടിയായവർ (User A -> User B)

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- 4. BOT COMMANDS ---

# Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    buttons = [[KeyboardButton("☕️ Find Partner")], [KeyboardButton("❌ Stop Chat")]]
    
    await update.message.reply_text(
        f"👋 **Namaskaram {user.first_name}!**\n\n"
        "സ്വാഗതം **Chai**-ലേക്ക്! ☕️\n"
        "ഇവിടെ നിങ്ങൾക്ക് പേര് വെളിപ്പെടുത്താതെ അപരിചിതരുമായി സംസാരിക്കാം.\n\n"
        "സംസാരിച്ചു തുടങ്ങാൻ **Find Partner** ക്ലിക്ക് ചെയ്യൂ! 👇",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True),
        parse_mode='Markdown'
    )

# Find Partner (സെർച്ച് ചെയ്യുമ്പോൾ)
async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 1. ഇതിനകം ചാറ്റ് ചെയ്യുന്നുണ്ടോ?
    if user_id in pairs:
        await update.message.reply_text("⚠️ നിങ്ങൾ ഇപ്പോൾ ചാറ്റിലാണ്! നിർത്താൻ **Stop Chat** ക്ലിക്ക് ചെയ്യൂ.")
        return

    # 2. ഇതിനകം വരിയിൽ (Queue) ഉണ്ടോ?
    if user_id in queue:
        await update.message.reply_text("⏳ പങ്കാളിയെ തിരയുന്നു... കുറച്ചു സമയം കാത്തിരിക്കൂ! ☕️")
        return

    # 3. വരിയിൽ ആരെങ്കിലും ഉണ്ടോ എന്ന് നോക്കുന്നു
    if len(queue) > 0:
        # വരിയിൽ ഉള്ള ആളെ എടുക്കുന്നു (Partner)
        partner_id = queue.pop(0)
        
        # രണ്ടുപേരെയും ജോടിയാക്കുന്നു
        pairs[user_id] = partner_id
        pairs[partner_id] = user_id
        
        # രണ്ടുപേർക്കും മെസ്സേജ് അയക്കുന്നു
        await context.bot.send_message(chat_id=user_id, text="✅ **കൂട്ടുക്കാരനെ കിട്ടി!** (Partner Found)\nഹായ് പറയൂ! 👋")
        await context.bot.send_message(chat_id=partner_id, text="✅ **കൂട്ടുക്കാരനെ കിട്ടി!** (Partner Found)\nഹായ് പറയൂ! 👋")
    
    else:
        # ആരുമില്ലെങ്കിൽ വരിയിൽ നിൽക്കുന്നു
        queue.append(user_id)
        await update.message.reply_text("⏳ **തിരയുന്നു...**\nആരെങ്കിലും വരുന്നത് വരെ കാത്തിരിക്കൂ.")

# Stop Chat
async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in pairs:
        partner_id = pairs[user_id]
        
        # ജോഡിയിൽ നിന്ന് മാറ്റുന്നു
        del pairs[user_id]
        del pairs[partner_id]
        
        await context.bot.send_message(chat_id=partner_id, text="❌ **പാർട്ട്നർ പോയി!**\nപുതിയ ആളെ കിട്ടാൻ /start അടിക്കുക.")
        await update.message.reply_text("❌ **നിങ്ങൾ ചാറ്റ് അവസാനിപ്പിച്ചു.**\nവീണ്ടും തുടങ്ങാൻ **Find Partner** ക്ലിക്ക് ചെയ്യൂ.")
    
    elif user_id in queue:
        queue.remove(user_id)
        await update.message.reply_text("🛑 **സെർച്ചിങ് നിർത്തി.**")
    
    else:
        await update.message.reply_text("⚠️ നിങ്ങൾ ഇപ്പോൾ ചാറ്റിൽ അല്ല.")

# Message Handler (മെസ്സേജ് കൈമാറുന്നത്)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # ബട്ടൺ ക്ലിക്ക് ചെയ്താൽ
    if text == "☕️ Find Partner":
        await find_partner(update, context)
        return
    elif text == "❌ Stop Chat":
        await stop_chat(update, context)
        return
        
    # ചാറ്റിംഗ് (User A -> User B)
    if user_id in pairs:
        partner_id = pairs[user_id]
        # കോപ്പി മെസ്സേജ് (Text, Photo, Sticker എല്ലാം പോകും)
        try:
            await update.message.copy(chat_id=partner_id)
        except:
            # ബ്ലോക്ക് ചെയ്താലോ മറ്റോ
            await stop_chat(update, context)
    else:
        # ആരുമായും കണക്ട് അല്ലെങ്കിൽ
        if text not in ["☕️ Find Partner", "❌ Stop Chat"]:
            await update.message.reply_text("⚠️ ആരുമായും കണക്ട് ആയിട്ടില്ല!\n**Find Partner** ക്ലിക്ക് ചെയ്യൂ. 👇")

# --- MAIN ---
def main():
    if not TOKEN:
        print("Error: TOKEN not found!")
        return

    # വെബ് സെർവർ ബാക്ക്ഗ്രൗണ്ടിൽ റൺ ചെയ്യുന്നു (Render-ന് വേണ്ടി)
    threading.Thread(target=run_web_server, daemon=True).start()
    
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", find_partner))
    app.add_handler(CommandHandler("stop", stop_chat))
    
    # ടെക്സ്റ്റ്, ഫോട്ടോ, വീഡിയോ എല്ലാം കൈകാര്യം ചെയ്യാൻ
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    print("Chai Bot Started... ☕️")
    app.run_polling()

if __name__ == "__main__":
    main()
