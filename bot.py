import logging
import re
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
import os
from dotenv import load_dotenv

# === ЛОГИ ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === ЗАГРУЗКА ENV ===
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ Переменная окружения BOT_TOKEN не установлена")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "644710593")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@shop_mrush1")

# === НАСТРОЙКИ ===
START_HOUR = 8
END_HOUR = 23
FORBIDDEN_WORDS = {'сука', 'блять', 'пиздец', 'хуй', 'ебать'}
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif'}
user_posts = {}

# === КНОПКИ ===
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🆘 Помощь")],
        [KeyboardButton("👨‍💻 Написать администратору")],
        [KeyboardButton("📤 Разместить объявление")]
    ],
    resize_keyboard=True
)
BACK_BUTTON = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton("🔙 Назад в меню")]],
    resize_keyboard=True
)

# === ХЕЛПЕРЫ ===
def is_within_working_hours() -> bool:
    now = datetime.now(ZoneInfo("Europe/Moscow")).hour
    return START_HOUR <= now < END_HOUR

async def check_subscription_and_block(context: ContextTypes, user_id: int) -> tuple[bool, str]:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status == 'kicked':
            return False, "❌ Вы были заблокированы в канале и не можете использовать бота."
        return member.status in ['member', 'administrator', 'creator'], ""
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки: {e}")
        return False, "❌ Не удалось проверить подписку. Повторите позже."

def check_post_limit_and_duplicates(user_id: int, text: str) -> tuple[bool, str]:
    now = datetime.now()
    if user_id not in user_posts:
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}
        return True, ""

    data = user_posts[user_id]
    if now.date() != data["date"].date():
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}

    if data["count"] >= 3:
        return False, "❌ Лимит в 3 поста за сутки. Попробуйте завтра."

    for post, t in data["posts"]:
        if post.strip() == text.strip():
            diff = now - t
            if diff < timedelta(days=1):
                left = 24 - diff.total_seconds() // 3600
                return False, f"❌ Такой пост уже публиковался. Повтор через {int(left)} ч."

    return True, ""

def add_successful_post(user_id: int, text: str):
    now = datetime.now()
    data = user_posts[user_id]
    data["posts"].append([text, now])
    data["count"] += 1
    data["date"] = now

def check_message(text: str, user_username: str) -> tuple[bool, str]:
    text_lower = text.lower()
    user_username = user_username.lower() if user_username else ""
    is_offtopic = any(tag in text_lower for tag in ['#офтоп', '#оффтоп'])

    usernames = re.findall(r'@([a-zA-Z0-9_]{5,})', text)
    if not usernames:
        return False, "❌ Укажите контактный Telegram @username."

    if not is_offtopic:
        actions = ['продам', 'обмен', 'куплю', 'продаю', 'обменяю']
        if not any(act in text_lower for act in actions):
            return False, "❌ Укажите цель: 'продам', 'куплю' или 'обмен'."
        keywords = ['почта', 'утер', 'можно указать']
        if not any(word in text_lower for word in keywords):
            return False, "❌ Укажите информацию о почте (есть/утеряна/можно указать)."

    if len(text) > 10 and sum(c.isupper() for c in text) / len(text) > 0.7:
        return False, "❌ Слишком много КАПСА."

    if any(word in text_lower for word in FORBIDDEN_WORDS):
        return False, "❌ Уберите ненормативную лексику."

    if re.search(r'(https?://|\.com|\.ru|\.org)', text) and 't.me/shop_mrush1' not in text:
        return False, "❌ Ссылки запрещены (кроме t.me/shop_mrush1)."

    for username in usernames:
        uname = username.lower()
        if uname.endswith("bot"):
            continue
        if uname not in [user_username, 'vardges_grigoryan']:
            return False, f"❌ Укажите свой Telegram (@ваш_ник), а не @{username}."

    return True, "✅ Сообщение корректно."

def check_file_extension(filename: str) -> bool:
    return filename and any(filename.lower().endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS)

# === ОБРАБОТЧИКИ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_within_working_hours():
        await update.message.reply_text("⏰ Бот работает с 8:00 до 23:00.")
        return
    await send_welcome_message(context, update.effective_chat.id)

async def send_welcome_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    greeting = (
        "🤖 *Привет, я Mrush1* — бот для размещения объявлений о *продаже/покупке/обмене* игровых аккаунтов!\n\n"
        "📌 Правила:\n"
        "🔗 [Правила](https://t.me/shop_mrush1/11)\n"
        "🔗 [Пример заявки](https://t.me/shop_mrush1/13)\n\n"
        "📸 Пример поста:"
    )
    await context.bot.send_message(chat_id=chat_id, text=greeting, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=MAIN_MENU)
    try:
        with open("primerbot.jpg", "rb") as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption="Продам за 100₽ или обменяю. Почта можно указать свою. Контакт: @vardges_grigoryan"
            )
    except FileNotFoundError:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Пример изображения не найден.")

async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👨‍💻 Пишите администратору: @vardges_grigoryan", reply_markup=BACK_BUTTON)

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📌 Как подать объявление:\n"
        "- Подпишитесь на @shop_mrush1\n"
        "- Нажмите /start\n"
        "- Отправьте объявление (текст + при желании фото)\n\n"
        "⚠ Требования:\n"
        "- Укажите цель (продам/куплю/обмен) или #оффтоп\n"
        "- Цена или бюджет\n"
        "- Инфо о почте\n"
        "- Без мата, капса, ссылок и ботов\n"
        "- Укажите ваш @username"
    )
    await update.message.reply_text(help_text, reply_markup=BACK_BUTTON)

async def handle_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_username = update.message.from_user.username
    text = update.message.caption or update.message.text or ""
    photos = update.message.photo
    doc = update.message.document

    if not is_within_working_hours():
        await update.message.reply_text("⏰ Бот работает с 8:00 до 23:00.")
        return

    sub_ok, sub_msg = await check_subscription_and_block(context, user_id)
    if not sub_ok:
        await update.message.reply_text(
            f"{sub_msg}\nНажмите для проверки:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Проверить подписку", callback_data="check_subscription")]])
        )
        return

    ok, msg = check_post_limit_and_duplicates(user_id, text)
    if not ok:
        await update.message.reply_text(msg, reply_markup=MAIN_MENU)
        return

    valid, reason = check_message(text, user_username)
    if not valid:
        await update.message.reply_text(reason, reply_markup=MAIN_MENU)
        return

    try:
        if photos:
            await context.bot.send_photo(chat_id=CHANNEL_ID, photo=photos[-1].file_id, caption=text)
        elif doc and check_file_extension(doc.file_name):
            await context.bot.send_document(chat_id=CHANNEL_ID, document=doc.file_id, caption=text)
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text)
        add_successful_post(user_id, text)
        await update.message.reply_text("✅ Опубликовано!", reply_markup=MAIN_MENU)
    except Exception as e:
        logger.error(f"Ошибка при публикации: {e}")
        await update.message.reply_text("❌ Ошибка при публикации. Попробуйте позже.", reply_markup=MAIN_MENU)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    if msg == "👨‍💻 Написать администратору":
        await contact_admin(update, context)
    elif msg == "🆘 Помощь":
        await show_help(update, context)
    elif msg == "🔙 Назад в меню":
        await update.message.reply_text("🏠 Главное меню:", reply_markup=MAIN_MENU)
    elif msg == "📤 Разместить объявление":
        await update.message.reply_text("📝 Отправьте текст объявления + фото (опционально)", reply_markup=BACK_BUTTON)
        context.user_data["awaiting_post"] = True
    elif context.user_data.get("awaiting_post"):
        await handle_post(update, context)
        context.user_data["awaiting_post"] = False
    else:
        await update.message.reply_text("🔄 Выберите действие ниже:", reply_markup=MAIN_MENU)

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "check_subscription":
        user_id = query.from_user.id
        sub_ok, sub_msg = await check_subscription_and_block(context, user_id)
        if sub_ok:
            await query.edit_message_text("✅ Подписка подтверждена!")
        else:
            await query.edit_message_text(
                f"❌ Подписка не найдена.\n{sub_msg}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Проверить снова", callback_data="check_subscription")]])
            )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")

# === ГЛАВНАЯ ТОЧКА ВХОДА ===
async def run_bot():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.IMAGE, handle_message))
    application.add_error_handler(error_handler)
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("✅ Бот запущен")
    await application.run_polling()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Бот остановлен вручную.")
