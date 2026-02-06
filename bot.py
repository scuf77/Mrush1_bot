import logging
import re
import os
import threading
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InputMediaPhoto
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from flask import Flask
from dotenv import load_dotenv

# ---------- Flask (healthcheck РґР»СЏ Railway) ----------
app = Flask(__name__)

@app.route("/")
def health_check():
    return "Mrush1 Bot is running", 200

def run_flask():
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        debug=False,
        use_reloader=False
    )

# ---------- Р›РѕРіРёСЂРѕРІР°РЅРёРµ ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- РљРѕРЅС„РёРіСѓСЂР°С†РёСЏ ----------
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN РЅРµ РЅР°Р№РґРµРЅ РІ РїРµСЂРµРјРµРЅРЅС‹С… РѕРєСЂСѓР¶РµРЅРёСЏ!")

# РљР°РЅР°Р» (РѕР±СЏР·Р°С‚РµР»СЊРЅР°СЏ РїРѕРґРїРёСЃРєР°)
CHANNEL_ID = os.getenv("CHANNEL_ID", "@shop_mrush1")
# Р‘РµСЃРµРґР° (РѕР±СЏР·Р°С‚РµР»СЊРЅРѕРµ СѓС‡Р°СЃС‚РёРµ)
CHAT_ID = "@chat_mrush1"  # РџСѓР±Р»РёС‡РЅР°СЏ СЃСѓРїРµСЂРіСЂСѓРїРїР° (СЃРј. https://t.me/chat_mrush1)

START_HOUR = 8
END_HOUR = 23

FORBIDDEN_WORDS = {"СЃСѓРєР°", "Р±Р»СЏС‚СЊ", "РїРёР·РґРµС†", "С…СѓР№", "РµР±Р°С‚СЊ"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}

# РҐСЂР°РЅРµРЅРёРµ РёРЅС„РѕСЂРјР°С†РёРё Рѕ РїРѕСЃС‚Р°С… РІ РѕРїРµСЂР°С‚РёРІРЅРѕР№ РїР°РјСЏС‚Рё
user_posts = {}

# РџСЂРѕСЃС‚РѕРµ РјРµРЅСЋ Р±РѕС‚Р°
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("📤 Разместить объявление")],
        [KeyboardButton("❓ Помощь"), KeyboardButton("❌ Отмена размещения")],
    ],
    resize_keyboard=True,
)

# Inline-РєРЅРѕРїРєРё РґР»СЏ Р±С‹СЃС‚СЂРѕРіРѕ РїРµСЂРµС…РѕРґР° Рё РїСЂРѕРІРµСЂРєРё
SUBSCRIBE_CHECK_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("РљР°РЅР°Р» @shop_mrush1", url="https://t.me/shop_mrush1")
    ],
    [
        InlineKeyboardButton("Р‘РµСЃРµРґР° @chat_mrush1", url="https://t.me/chat_mrush1")
    ],
    [
        InlineKeyboardButton("РџСЂРѕРІРµСЂРёС‚СЊ РїРѕРґРїРёСЃРєСѓ", callback_data="check_subscription")
    ]
])

def is_within_working_hours() -> bool:
    now = datetime.now()
    current_time = now.hour + now.minute / 60
    return START_HOUR <= current_time < END_HOUR

async def check_subscriptions(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> tuple[bool, str]:
    """
    РџСЂРѕРІРµСЂСЏРµС‚, СЃРѕСЃС‚РѕРёС‚ Р»Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РІ РѕР±СЏР·Р°С‚РµР»СЊРЅРѕРј РєР°РЅР°Р»Рµ Рё Р±РµСЃРµРґРµ.
    Р’РѕР·РІСЂР°С‰Р°РµС‚ (True, '') РїСЂРё СѓСЃРїРµС…Рµ Р»РёР±Рѕ (False, С‚РµРєСЃС‚_РѕС€РёР±РєРё).
    """
    # РЎРЅР°С‡Р°Р»Р° РїСЂРѕРІРµСЂСЏРµРј РєР°РЅР°Р» (СЂРѕСЃС‚РµСЂ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ public: @shop_mrush1)
    try:
        member_channel = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member_channel.status == "kicked":
            return False, "вќЊ Р’С‹ Р±С‹Р»Рё Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅС‹ РІ РєР°РЅР°Р»Рµ Рё РЅРµ РјРѕР¶РµС‚Рµ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ Р±РѕС‚Р°."
        if member_channel.status not in ["member", "administrator", "creator"]:
            return False, "вќЊ Р’С‹ РЅРµ РїРѕРґРїРёСЃР°РЅС‹ РЅР° РѕСЃРЅРѕРІРЅРѕР№ РєР°РЅР°Р»."
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РїСЂРѕРІРµСЂРєРё РїРѕРґРїРёСЃРєРё РЅР° РєР°РЅР°Р» {CHANNEL_ID}: {e}")
        return False, "вќЊ РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё РїСЂРѕРІРµСЂРєРµ РїРѕРґРїРёСЃРєРё РЅР° РєР°РЅР°Р»."

    # Р—Р°С‚РµРј РїСЂРѕРІРµСЂСЏРµРј Р±РµСЃРµРґСѓ (РґРѕР»Р¶РЅР° Р±С‹С‚СЊ РїСѓР±Р»РёС‡РЅРѕР№ СЃСѓРїРµСЂРіСЂСѓРїРїРѕР№: @chat_mrush1)
    try:
        member_chat = await context.bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
        if member_chat.status == "kicked":
            return False, "вќЊ Р’С‹ Р±С‹Р»Рё Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅС‹ РІ Р±РµСЃРµРґРµ Рё РЅРµ РјРѕР¶РµС‚Рµ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ Р±РѕС‚Р°."
        if member_chat.status not in ["member", "administrator", "creator"]:
            return False, "вќЊ Р’С‹ РЅРµ СЃРѕСЃС‚РѕРёС‚Рµ РІ РѕР±СЏР·Р°С‚РµР»СЊРЅРѕР№ Р±РµСЃРµРґРµ."
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РїСЂРѕРІРµСЂРєРё СѓС‡Р°СЃС‚РёСЏ РІ Р±РµСЃРµРґРµ {CHAT_ID}: {e}")
        return False, "вќЊ РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё РїСЂРѕРІРµСЂРєРµ РІР°С€РµРіРѕ СЃС‚Р°С‚СѓСЃР° РІ Р±РµСЃРµРґРµ."

    return True, ""

def check_post_limit_and_duplicates(user_id: int, text: str) -> tuple[bool, str]:
    now = datetime.now()
    if user_id not in user_posts:
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}
        return True, ""

    user_data = user_posts[user_id]
    # РЎР±СЂР°СЃС‹РІР°РµРј СЃС‡С‘С‚С‡РёРє, РµСЃР»Рё РЅР°СЃС‚СѓРїРёР» РЅРѕРІС‹Р№ РґРµРЅСЊ
    if now.date() != user_data["date"].date():
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}

    if user_posts[user_id]["count"] >= 3:
        return False, "вќЊ Р’С‹ РїСЂРµРІС‹СЃРёР»Рё Р»РёРјРёС‚ РІ 3 РїРѕСЃС‚Р° Р·Р° СЃСѓС‚РєРё. РџРѕРїСЂРѕР±СѓР№С‚Рµ Р·Р°РІС‚СЂР°."

    # РџСЂРѕРІРµСЂРєР° РЅР° РґСѓР±Р»РёРєР°С‚С‹ (90%+ СЃС…РѕР¶РµСЃС‚Рё)
    for post, post_time in user_data["posts"]:
        similarity = calculate_similarity(text.strip(), post.strip())
        if similarity >= 0.9:
            time_diff = now - post_time
            if time_diff < timedelta(days=1):
                hours_left = 24 - time_diff.total_seconds() // 3600
                return False, f"вќЊ РџРѕС…РѕР¶РёР№ РїРѕСЃС‚ СѓР¶Рµ РїСѓР±Р»РёРєРѕРІР°Р»СЃСЏ. РџРѕРІС‚РѕСЂРЅР°СЏ РїСѓР±Р»РёРєР°С†РёСЏ РІРѕР·РјРѕР¶РЅР° С‡РµСЂРµР· {int(hours_left)} С‡."

    return True, ""

def calculate_similarity(text1: str, text2: str) -> float:
    """Р’С‹С‡РёСЃР»СЏРµС‚ СЃС…РѕР¶РµСЃС‚СЊ РґРІСѓС… С‚РµРєСЃС‚РѕРІ (0.0 - 1.0)"""
    if not text1 or not text2:
        return 0.0
    
    # РџСЂРёРІРѕРґРёРј Рє РЅРёР¶РЅРµРјСѓ СЂРµРіРёСЃС‚СЂСѓ Рё СѓР±РёСЂР°РµРј Р»РёС€РЅРёРµ РїСЂРѕР±РµР»С‹
    text1 = text1.lower().strip()
    text2 = text2.lower().strip()
    
    if text1 == text2:
        return 1.0
    
    # РџСЂРѕСЃС‚РѕР№ Р°Р»РіРѕСЂРёС‚Рј СЃС…РѕР¶РµСЃС‚Рё РЅР° РѕСЃРЅРѕРІРµ РѕР±С‰РёС… СЃР»РѕРІ
    words1 = set(text1.split())
    words2 = set(text2.split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    return len(intersection) / len(union) if union else 0.0

def add_successful_post(user_id: int, text: str):
    now = datetime.now()
    user_data = user_posts[user_id]
    user_data["posts"].append([text, now])
    user_data["count"] += 1
    user_data["date"] = now

def check_message(text: str, user_username: str) -> tuple[bool, str]:
    text_lower = text.lower()
    user_username = (user_username or "").lower()

    # РџСЂРѕРІРµСЂРєР° РЅР° РЅР°Р»РёС‡РёРµ @username (СЃРІСЏР·СЊ СЃ РїСЂРѕРґР°РІС†РѕРј/РїРѕРєСѓРїР°С‚РµР»РµРј)
    usernames = re.findall(r"@([a-zA-Z0-9_]{5,})", text)
    if not usernames:
        return False, "вќЊ Р’ СЃРѕРѕР±С‰РµРЅРёРё РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚ РєРѕРЅС‚Р°РєС‚РЅР°СЏ РёРЅС„РѕСЂРјР°С†РёСЏ (@username)."

    # РџСЂРѕРІРµСЂРєР° РґРµР№СЃС‚РІРёСЏ (РїСЂРѕРґР°Рј/РєСѓРїР»СЋ/РѕР±РјРµРЅ)
    actions = ["РїСЂРѕРґР°Рј", "РѕР±РјРµРЅ", "РєСѓРїР»СЋ", "РїСЂРѕРґР°СЋ", "РѕР±РјРµРЅСЏСЋ", "РїРѕРєСѓРїРєР°", "РїСЂРѕРґР°Р¶Р°", "#РѕС„С‚РѕРї", "#РѕС„С„С‚РѕРї"]
    if not any(action in text_lower for action in actions):
        return False, "вќЊ РЈРєР°Р¶РёС‚Рµ РґРµР№СЃС‚РІРёРµ: РїСЂРѕРґР°Рј/РєСѓРїР»СЋ/РѕР±РјРµРЅ"

    # РњР°С‚
    if any(word in text_lower for word in FORBIDDEN_WORDS):
        return False, "вќЊ РћР±РЅР°СЂСѓР¶РµРЅ РјР°С‚. РЈР±РµСЂРёС‚Рµ РµРіРѕ."

    # РЎР»РёС€РєРѕРј РјРЅРѕРіРѕ РєР°РїСЃР°
    if len(text) > 10 and (sum(c.isupper() for c in text) / len(text) > 0.7):
        return False, "вќЊ РЎР»РёС€РєРѕРј РјРЅРѕРіРѕ С‚РµРєСЃС‚Р° РІ РІРµСЂС…РЅРµРј СЂРµРіРёСЃС‚СЂРµ (РєР°РїСЃ)."

    # РЈРїРѕРјРёРЅР°РЅРёСЏ Р±РѕС‚РѕРІ
    if re.search(r"@[a-zA-Z0-9_]*bot\b", text_lower):
        return False, "вќЊ РЈРїРѕРјРёРЅР°РЅРёСЏ Р±РѕС‚РѕРІ Р·Р°РїСЂРµС‰РµРЅС‹."

    # Р›РёС€РЅРёРµ СѓРїРѕРјРёРЅР°РЅРёСЏ С‡СѓР¶РёС… @username
    for username in usernames:
        username_lower = username.lower()
        if username_lower.endswith("bot"):
            continue
        if username_lower not in [user_username, "vardges_grigoryan"]:
            return False, f"вќЊ РЈРїРѕРјРёРЅР°РЅРёРµ @{username} Р·Р°РїСЂРµС‰РµРЅРѕ. РЈРєР°Р¶РёС‚Рµ СЃРІРѕР№ РєРѕРЅС‚Р°РєС‚ (@РІР°С€_РЅРёРє)."

    return True, "вњ… РЎРѕРѕР±С‰РµРЅРёРµ СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚ С‚СЂРµР±РѕРІР°РЅРёСЏРј."

def check_file_extension(file_name: str) -> bool:
    if not file_name:
        return False
    return any(file_name.lower().endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS)

# ---------- РџСЂРёРІРµС‚СЃС‚РІРµРЅРЅРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ ----------
async def send_welcome_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    greeting = (
        "<b>рџ¤– РџСЂРёРІРµС‚! РЇ Р±РѕС‚ РґР»СЏ СЂР°Р·РјРµС‰РµРЅРёСЏ РѕР±СЉСЏРІР»РµРЅРёР№ Рѕ РїРѕРєСѓРїРєРµ/РїСЂРѕРґР°Р¶Рµ С†РёС„СЂРѕРІС‹С… С†РµРЅРЅРѕСЃС‚РµР№.</b>\n\n"
        "рџ“ќ <b>РљР°Рє СЂР°Р·РјРµСЃС‚РёС‚СЊ РѕР±СЉСЏРІР»РµРЅРёРµ:</b>\n"
        "1. РќР°Р¶РјРёС‚Рµ В«рџ“¤ Р Р°Р·РјРµСЃС‚РёС‚СЊ РѕР±СЉСЏРІР»РµРЅРёРµВ»\n"
        "2. РћС‚РїСЂР°РІСЊС‚Рµ РґРѕ 5 С„РѕС‚РѕРіСЂР°С„РёР№ (РµСЃР»Рё РЅСѓР¶РЅРѕ)\n"
        "3. РћС‚РїСЂР°РІСЊС‚Рµ С‚РµРєСЃС‚ РѕР±СЉСЏРІР»РµРЅРёСЏ\n"
        "4. Р“РѕС‚РѕРІРѕ!\n\n"
        "рџ“Њ <b>РћСЃРЅРѕРІРЅС‹Рµ РїСЂР°РІРёР»Р°:</b>\n"
        "вЂў РЈРєР°Р¶РёС‚Рµ РґРµР№СЃС‚РІРёРµ: РїСЂРѕРґР°Рј/РєСѓРїР»СЋ/РѕР±РјРµРЅ\n"
        "вЂў РЈРєР°Р¶РёС‚Рµ С†РµРЅСѓ РёР»Рё Р±СЋРґР¶РµС‚\n"
        "вЂў РћСЃС‚Р°РІСЊС‚Рµ СЃРІРѕР№ @username РґР»СЏ СЃРІСЏР·Рё\n"
        "вЂў РќРµ РёСЃРїРѕР»СЊР·СѓР№С‚Рµ РјР°С‚ Рё РєР°РїСЃ\n"
        "вЂў РњРѕР¶РЅРѕ РїСЂРёРєСЂРµРїРёС‚СЊ РґРѕ 5 С„РѕС‚РѕРіСЂР°С„РёР№ Рє РѕРґРЅРѕРјСѓ РѕР±СЉСЏРІР»РµРЅРёСЋ\n\n"
        "РџРѕР»РЅС‹Рµ РїСЂР°РІРёР»Р°: <a href='https://t.me/shop_mrush1/13'>t.me/shop_mrush1/13</a>"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=greeting,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=MAIN_MENU,
    )

    # РџСЂРёРјРµСЂ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ
    try:
        with open("primerbot.jpg", "rb") as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=(
                    "РџСЂРёРјРµСЂ РѕР±СЉСЏРІР»РµРЅРёСЏ:\n"
                    "В«РџСЂРѕРґР°Рј Р·Р° 100в‚Ѕ РёР»Рё РѕР±РјРµРЅСЏСЋ РЅР° Р°РєРє РїРѕСЃРёР»СЊРЅРµРµ СЃ РјРѕРµР№ РґРѕРїР»Р°С‚РѕР№. "
                    "РќР° Р°РєРєР°СѓРЅС‚Рµ РµСЃС‚СЊ РІРѕР·РјРѕР¶РЅРѕСЃС‚СЊ СѓРєР°Р·Р°С‚СЊ СЃРІРѕСЋ РїРѕС‡С‚Сѓ. "
                    "РљРѕРЅС‚Р°РєС‚С‹ РґР»СЏ СЃРІСЏР·Рё: @vardges_grigoryanВ»"
                ),
            )
    except FileNotFoundError:
        await context.bot.send_message(chat_id=chat_id, text="вљ пёЏ РќРµ СѓРґР°Р»РѕСЃСЊ РЅР°Р№С‚Рё РїСЂРёРјРµСЂ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ.", disable_web_page_preview=True)

# ---------- РћР±СЂР°Р±РѕС‚РєР° РїРѕСЃС‚Р° ----------
async def handle_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    user_id = user.id
    user_username = user.username or ""
    
    # РџРѕР»СѓС‡Р°РµРј С‚РµРєСЃС‚ РёР· С‚РµРєСѓС‰РµРіРѕ СЃРѕРѕР±С‰РµРЅРёСЏ РёР»Рё РёР· СЃРѕС…СЂР°РЅС‘РЅРЅС‹С… РґР°РЅРЅС‹С…
    text = (msg.text or msg.caption or context.user_data.get("post_text") or "").strip()
    
    # РџРѕР»СѓС‡Р°РµРј С„РѕС‚РѕРіСЂР°С„РёРё РёР· СЃРѕС…СЂР°РЅС‘РЅРЅС‹С… РґР°РЅРЅС‹С… РёР»Рё РёР· С‚РµРєСѓС‰РµРіРѕ СЃРѕРѕР±С‰РµРЅРёСЏ
    saved_photos = context.user_data.get("post_photos", [])
    current_photos = msg.photo or []
    document = msg.document

    if not is_within_working_hours():
        current_time = datetime.now().strftime("%H:%M")
        await msg.reply_text(
            f"вЏ° Р‘РѕС‚ СЂР°Р±РѕС‚Р°РµС‚ СЃ 8:00 РґРѕ 23:00 РїРѕ РњРЎРљ. РЎРµР№С‡Р°СЃ {current_time}. РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РЅР°РїРёС€РёС‚Рµ Р·Р°РІС‚СЂР° СЃ 8:00.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True
        )
        return

    # РџРµСЂРµРґ РїСѓР±Р»РёРєР°С†РёРµР№ РµС‰С‘ СЂР°Р· СѓР±РµР¶РґР°РµРјСЃСЏ, С‡С‚Рѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РїРѕРґРїРёСЃР°РЅ
    subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
    if not subscriptions_ok:
        await msg.reply_text(
            f"{subscriptions_msg}\n"
            "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РїРѕРґРїРёС€РёС‚РµСЃСЊ РЅР° РєР°РЅР°Р» Рё Р±РµСЃРµРґСѓ Рё РЅР°Р¶РјРёС‚Рµ В«РџСЂРѕРІРµСЂРёС‚СЊ РїРѕРґРїРёСЃРєСѓВ»:",
            reply_markup=SUBSCRIBE_CHECK_KEYBOARD,
            disable_web_page_preview=True
        )
        return

    if not text:
        await msg.reply_text("вќЊ Р”РѕР±Р°РІСЊС‚Рµ С‚РµРєСЃС‚ РѕР±СЉСЏРІР»РµРЅРёСЏ (РјРѕР¶РЅРѕ РєР°Рє РїРѕРґРїРёСЃСЊ Рє С„РѕС‚Рѕ).", reply_markup=MAIN_MENU, disable_web_page_preview=True)
        return

    # Р›РёРјРёС‚ Рё РґСѓР±Р»РёРєР°С‚С‹
    limit_ok, limit_msg = check_post_limit_and_duplicates(user_id, text)
    if not limit_ok:
        await msg.reply_text(limit_msg, reply_markup=MAIN_MENU, disable_web_page_preview=True)
        return

    # РџСЂРѕРІРµСЂРєР° РєРѕРЅС‚РµРЅС‚Р°
    content_ok, content_msg = check_message(text, user_username)
    if not content_ok:
        await msg.reply_text(content_msg, reply_markup=MAIN_MENU, disable_web_page_preview=True)
        return

    # РџСЂРѕРІРµСЂРєР° РґРѕРєСѓРјРµРЅС‚Р°, РµСЃР»Рё РѕРЅ РµСЃС‚СЊ
    if document and not check_file_extension(document.file_name):
        await msg.reply_text(
            "вќЊ РќРµРґРѕРїСѓСЃС‚РёРјС‹Рµ С„Р°Р№Р»С‹. Р Р°Р·СЂРµС€РµРЅС‹ С‚РѕР»СЊРєРѕ JPG, JPEG, PNG, GIF.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True
        )
        return

    try:
        # Р•СЃР»Рё РµСЃС‚СЊ СЃРѕС…СЂР°РЅС‘РЅРЅС‹Рµ С„РѕС‚РѕРіСЂР°С„РёРё (СЂРµР¶РёРј СЃРѕР·РґР°РЅРёСЏ РїРѕСЃС‚Р° СЃ РЅРµСЃРєРѕР»СЊРєРёРјРё С„РѕС‚Рѕ)
        if saved_photos:
            if len(saved_photos) == 1:
                # РћРґРЅР° С„РѕС‚РѕРіСЂР°С„РёСЏ - РёСЃРїРѕР»СЊР·СѓРµРј send_photo
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=saved_photos[0],
                    caption=text
                )
            else:
                # РќРµСЃРєРѕР»СЊРєРѕ С„РѕС‚РѕРіСЂР°С„РёР№ - РёСЃРїРѕР»СЊР·СѓРµРј send_media_group
                media_group = []
                for i, photo_id in enumerate(saved_photos):
                    # РџРѕРґРїРёСЃСЊ С‚РѕР»СЊРєРѕ Рє РїРµСЂРІРѕР№ С„РѕС‚РѕРіСЂР°С„РёРё
                    if i == 0:
                        media_group.append(InputMediaPhoto(media=photo_id, caption=text))
                    else:
                        media_group.append(InputMediaPhoto(media=photo_id))
                
                await context.bot.send_media_group(
                    chat_id=CHANNEL_ID,
                    media=media_group
                )
        # Р•СЃР»Рё С„РѕС‚РѕРіСЂР°С„РёСЏ РІ С‚РµРєСѓС‰РµРј СЃРѕРѕР±С‰РµРЅРёРё (СЃС‚Р°СЂС‹Р№ СЃРїРѕСЃРѕР± - РґР»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё)
        elif current_photos:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=current_photos[-1].file_id,
                caption=text
            )
        # Р•СЃР»Рё РґРѕРєСѓРјРµРЅС‚ РІ С‚РµРєСѓС‰РµРј СЃРѕРѕР±С‰РµРЅРёРё
        elif document:
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=document.file_id,
                caption=text
            )
        # РўРѕР»СЊРєРѕ С‚РµРєСЃС‚
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text, disable_web_page_preview=True)

        add_successful_post(user_id, text)
        await msg.reply_text("вњ… Р’Р°С€Рµ РѕР±СЉСЏРІР»РµРЅРёРµ СѓСЃРїРµС€РЅРѕ РѕРїСѓР±Р»РёРєРѕРІР°РЅРѕ!", reply_markup=MAIN_MENU, disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"РћС€РёР±РєР° РїСЂРё РїСѓР±Р»РёРєР°С†РёРё РѕР±СЉСЏРІР»РµРЅРёСЏ: {e}")
        await msg.reply_text(
            "вќЊ РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё РїСѓР±Р»РёРєР°С†РёРё РѕР±СЉСЏРІР»РµРЅРёСЏ. РџРѕРїСЂРѕР±СѓР№С‚Рµ С‡СѓС‚СЊ РїРѕР·Р¶Рµ.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True
        )

# ---------- РљРѕРјР°РЅРґС‹ / РєРѕР»Р±СЌРєРё / СЃРѕРѕР±С‰РµРЅРёСЏ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    РЎСЂР°Р±Р°С‚С‹РІР°РµС‚, РєРѕРіРґР° РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РїРёС€РµС‚ /start.
    РџСЂРѕРІРµСЂСЏРµРј, РїРѕРґРїРёСЃР°РЅ Р»Рё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅР° РєР°РЅР°Р» @shop_mrush1 Рё Р±РµСЃРµРґСѓ @chat_mrush1.
    Р•СЃР»Рё РЅРµС‚ вЂ” РІС‹РІРѕРґРёРј СЃРѕРѕР±С‰РµРЅРёРµ Рё Inline-РєР»Р°РІРёР°С‚СѓСЂСѓ.
    Р•СЃР»Рё РґР°, РїРѕРєР°Р·С‹РІР°РµРј РїСЂРёРІРµС‚СЃС‚РІРµРЅРЅРѕРµ РјРµРЅСЋ.
    """
    user_id = update.effective_user.id

    if not is_within_working_hours():
        current_time = datetime.now().strftime("%H:%M")
        await update.message.reply_text(
            f"вЏ° Р‘РѕС‚ СЂР°Р±РѕС‚Р°РµС‚ СЃ 8:00 РґРѕ 23:00 РїРѕ РњРЎРљ. РЎРµР№С‡Р°СЃ {current_time}. РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РЅР°РїРёС€РёС‚Рµ РїРѕР·Р¶Рµ.",
            disable_web_page_preview=True
        )
        return

    subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
    if not subscriptions_ok:
        await update.message.reply_text(
            f"{subscriptions_msg}\n"
            "РџРѕСЃР»Рµ РїРѕРґРїРёСЃРєРё РЅР°Р¶РјРёС‚Рµ В«РџСЂРѕРІРµСЂРёС‚СЊ РїРѕРґРїРёСЃРєСѓВ».",
            reply_markup=SUBSCRIBE_CHECK_KEYBOARD,
            disable_web_page_preview=True
        )
        return

    await send_welcome_message(context, update.effective_chat.id)

async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "рџ‘ЁвЂЌрџ’» Р•СЃР»Рё Сѓ РІР°СЃ РІРѕР·РЅРёРєР»Рё РІРѕРїСЂРѕСЃС‹ вЂ” РїРёС€РёС‚Рµ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ: @vardges_grigoryan",
        reply_markup=MAIN_MENU,
        disable_web_page_preview=True
    )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "рџ“Њ <b>РљР°Рє СЂР°Р·РјРµСЃС‚РёС‚СЊ РѕР±СЉСЏРІР»РµРЅРёРµ:</b>\n"
        "1. РќР°Р¶РјРёС‚Рµ В«рџ“¤ Р Р°Р·РјРµСЃС‚РёС‚СЊ РѕР±СЉСЏРІР»РµРЅРёРµВ»\n"
        "2. РћС‚РїСЂР°РІСЊС‚Рµ РґРѕ 5 С„РѕС‚РѕРіСЂР°С„РёР№ (РµСЃР»Рё РЅСѓР¶РЅРѕ)\n"
        "3. РћС‚РїСЂР°РІСЊС‚Рµ С‚РµРєСЃС‚ РѕР±СЉСЏРІР»РµРЅРёСЏ\n"
        "4. Р“РѕС‚РѕРІРѕ!\n\n"
        "рџ“Њ <b>РћСЃРЅРѕРІРЅС‹Рµ РїСЂР°РІРёР»Р°:</b>\n"
        "вЂў РЈРєР°Р¶РёС‚Рµ РґРµР№СЃС‚РІРёРµ: РїСЂРѕРґР°Рј/РєСѓРїР»СЋ/РѕР±РјРµРЅ\n"
        "вЂў РЈРєР°Р¶РёС‚Рµ С†РµРЅСѓ РёР»Рё Р±СЋРґР¶РµС‚\n"
        "вЂў РћСЃС‚Р°РІСЊС‚Рµ СЃРІРѕР№ @username РґР»СЏ СЃРІСЏР·Рё\n"
        "вЂў РќРµ РёСЃРїРѕР»СЊР·СѓР№С‚Рµ РјР°С‚ Рё РєР°РїСЃ\n"
        "вЂў РњРѕР¶РЅРѕ РїСЂРёРєСЂРµРїРёС‚СЊ РґРѕ 5 С„РѕС‚РѕРіСЂР°С„РёР№ Рє РѕРґРЅРѕРјСѓ РѕР±СЉСЏРІР»РµРЅРёСЋ\n\n"
        "РџРѕР»РЅС‹Рµ РїСЂР°РІРёР»Р°: <a href='https://t.me/shop_mrush1/13'>t.me/shop_mrush1/13</a>"
    )
    await update.message.reply_text(
        help_text,
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
        disable_web_page_preview=True
    )


def clear_post_draft(user_data: dict):
    job = user_data.pop("media_group_job", None)
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass

    user_data["awaiting_post"] = False
    user_data.pop("post_photos", None)
    user_data.pop("post_text", None)
    user_data.pop("post_username", None)
    user_data.pop("pending_media_group_id", None)


async def publish_draft_post(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    user_username: str,
    chat_id: int,
    user_data: dict,
) -> bool:
    text = (user_data.get("post_text") or "").strip()
    photos = user_data.get("post_photos", [])

    if not text:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Добавьте текст объявления (можно подписью к фото).",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True,
        )
        return False

    subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
    if not subscriptions_ok:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"{subscriptions_msg}\n"
                "Пожалуйста, подпишитесь на канал и беседу и нажмите «Проверить подписку»:"
            ),
            reply_markup=SUBSCRIBE_CHECK_KEYBOARD,
            disable_web_page_preview=True,
        )
        return False

    limit_ok, limit_msg = check_post_limit_and_duplicates(user_id, text)
    if not limit_ok:
        await context.bot.send_message(chat_id=chat_id, text=limit_msg, reply_markup=MAIN_MENU, disable_web_page_preview=True)
        return False

    content_ok, content_msg = check_message(text, user_username)
    if not content_ok:
        await context.bot.send_message(chat_id=chat_id, text=content_msg, reply_markup=MAIN_MENU, disable_web_page_preview=True)
        return False

    try:
        if photos:
            if len(photos) == 1:
                await context.bot.send_photo(chat_id=CHANNEL_ID, photo=photos[0], caption=text)
            else:
                media = []
                for i, photo_id in enumerate(photos):
                    if i == 0:
                        media.append(InputMediaPhoto(media=photo_id, caption=text))
                    else:
                        media.append(InputMediaPhoto(media=photo_id))
                await context.bot.send_media_group(chat_id=CHANNEL_ID, media=media)
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text, disable_web_page_preview=True)

        add_successful_post(user_id, text)
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Ваше объявление успешно опубликовано!",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True,
        )
        clear_post_draft(user_data)
        return True
    except Exception as e:
        logger.exception(f"Ошибка при публикации объявления из черновика: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Произошла ошибка при публикации объявления. Попробуйте чуть позже.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True,
        )
        return False


async def publish_pending_media_group(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data or {}
    user_id = data.get("user_id")
    chat_id = data.get("chat_id")
    media_group_id = data.get("media_group_id")

    if not user_id or not chat_id:
        return

    user_data = context.application.user_data.get(user_id, {})
    if not user_data.get("awaiting_post"):
        return
    if user_data.get("pending_media_group_id") != media_group_id:
        return

    # Публикуем только если уже есть подпись/текст к альбому
    if not (user_data.get("post_text") or "").strip():
        return

    await publish_draft_post(
        context=context,
        user_id=user_id,
        user_username=user_data.get("post_username", ""),
        chat_id=chat_id,
        user_data=user_data,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text

    if text == "❓ Помощь":
        await show_help(update, context)
        return

    if text in {"❌ Отмена размещения", "/cancel", "отмена"}:
        if context.user_data.get("awaiting_post"):
            clear_post_draft(context.user_data)
            await msg.reply_text("❌ Размещение отменено.", reply_markup=MAIN_MENU, disable_web_page_preview=True)
        else:
            await msg.reply_text("Сейчас нет активного размещения.", reply_markup=MAIN_MENU, disable_web_page_preview=True)
        return

    if text == "📤 Разместить объявление":
        context.user_data["awaiting_post"] = True
        context.user_data["post_photos"] = []
        context.user_data["post_text"] = None
        context.user_data["post_username"] = msg.from_user.username or ""
        context.user_data["pending_media_group_id"] = None
        context.user_data.pop("media_group_job", None)

        await msg.reply_text(
            "📝 Отправьте до 5 фото с подписью (или просто текст).\n"
            "Если отправите альбом с подписью, бот опубликует его сразу автоматически.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True,
        )
        return

    if context.user_data.get("awaiting_post", False):
        context.user_data["post_username"] = msg.from_user.username or ""

        if msg.photo:
            photos = context.user_data.get("post_photos", [])
            if len(photos) >= 5:
                await msg.reply_text(
                    "❌ Уже добавлено 5 фото. Отправьте текст объявления или нажмите отмену.",
                    reply_markup=MAIN_MENU,
                    disable_web_page_preview=True,
                )
                return

            photos.append(msg.photo[-1].file_id)
            context.user_data["post_photos"] = photos

            if msg.caption:
                context.user_data["post_text"] = msg.caption.strip()

            if msg.media_group_id:
                context.user_data["pending_media_group_id"] = msg.media_group_id
                job = context.user_data.get("media_group_job")
                if job:
                    try:
                        job.schedule_removal()
                    except Exception:
                        pass

                if context.job_queue and context.user_data.get("post_text"):
                    context.user_data["media_group_job"] = context.job_queue.run_once(
                        publish_pending_media_group,
                        when=1.2,
                        data={
                            "user_id": msg.from_user.id,
                            "chat_id": msg.chat_id,
                            "media_group_id": msg.media_group_id,
                        },
                        name=f"publish_media_group_{msg.from_user.id}",
                    )
                return

            if context.user_data.get("post_text"):
                await publish_draft_post(
                    context=context,
                    user_id=msg.from_user.id,
                    user_username=context.user_data.get("post_username", ""),
                    chat_id=msg.chat_id,
                    user_data=context.user_data,
                )
                return

            remaining = 5 - len(photos)
            await msg.reply_text(
                f"✅ Фото добавлено ({len(photos)}/5). Можно добавить ещё {remaining} или отправить текст.",
                reply_markup=MAIN_MENU,
                disable_web_page_preview=True,
            )
            return

        if msg.document:
            if not check_file_extension(msg.document.file_name):
                await msg.reply_text(
                    "❌ Недопустимый формат. Разрешены только JPG, JPEG, PNG, GIF.",
                    reply_markup=MAIN_MENU,
                    disable_web_page_preview=True,
                )
                return

            photos = context.user_data.get("post_photos", [])
            if len(photos) >= 5:
                await msg.reply_text(
                    "❌ Уже добавлено 5 фото. Отправьте текст объявления или нажмите отмену.",
                    reply_markup=MAIN_MENU,
                    disable_web_page_preview=True,
                )
                return

            photos.append(msg.document.file_id)
            context.user_data["post_photos"] = photos

            if msg.caption:
                context.user_data["post_text"] = msg.caption.strip()
                await publish_draft_post(
                    context=context,
                    user_id=msg.from_user.id,
                    user_username=context.user_data.get("post_username", ""),
                    chat_id=msg.chat_id,
                    user_data=context.user_data,
                )
                return

            remaining = 5 - len(photos)
            await msg.reply_text(
                f"✅ Изображение добавлено ({len(photos)}/5). Можно добавить ещё {remaining} или отправить текст.",
                reply_markup=MAIN_MENU,
                disable_web_page_preview=True,
            )
            return

        if text:
            if not context.user_data.get("post_text"):
                context.user_data["post_text"] = text.strip()

            await publish_draft_post(
                context=context,
                user_id=msg.from_user.id,
                user_username=context.user_data.get("post_username", ""),
                chat_id=msg.chat_id,
                user_data=context.user_data,
            )
            return

    if msg.photo or msg.document:
        await handle_post(update, context)
        return

    await msg.reply_text("🔄 Выберите действие 👇", reply_markup=MAIN_MENU, disable_web_page_preview=True)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_subscription":
        user_id = query.from_user.id
        subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
        if subscriptions_ok:
            await query.edit_message_text("вњ… Р’СЃС‘ РѕС‚Р»РёС‡РЅРѕ! Р’С‹ РїРѕРґРїРёСЃР°РЅС‹ РЅР° РѕР±Р° С‡Р°С‚Р°.", disable_web_page_preview=True)
            # РћС‚РїСЂР°РІР»СЏРµРј РїСЂРёРІРµС‚
            await send_welcome_message(context, query.message.chat.id)
        else:
            await query.edit_message_text(
                text=(
                    f"{subscriptions_msg}\n\n"
                    "РЈР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ РїРѕРґРїРёСЃР°Р»РёСЃСЊ Рё РЅР°Р¶РјРёС‚Рµ В«РџСЂРѕРІРµСЂРёС‚СЊ РїРѕРґРїРёСЃРєСѓВ» СЃРЅРѕРІР°."
                ),
                reply_markup=SUBSCRIBE_CHECK_KEYBOARD,
                disable_web_page_preview=True
            )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception(f"РћС€РёР±РєР°: {context.error}")

# ---------- main ----------
def main():
    # Р—Р°РїСѓСЃРє Flask РІ РѕС‚РґРµР»СЊРЅРѕРј РїРѕС‚РѕРєРµ
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # РџСЂРёР»РѕР¶РµРЅРёРµ PTB
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(
        MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.IMAGE, handle_message)
    )
    application.add_error_handler(error_handler)

    logger.info("Р—Р°РїСѓСЃРє polling (СЃРёРЅС…СЂРѕРЅРЅС‹Р№)...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
