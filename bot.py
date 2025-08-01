import logging
import re
import asyncio
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from dotenv import load_dotenv

# Инициализация Flask для Railway
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Mrush1 Bot is running", 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8000)), debug=False, use_reloader=False)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN") or os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")

GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "644710593")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@shop_mrush1")

START_HOUR = 8
END_HOUR = 23
FORBIDDEN_WORDS = {'сука', 'блять', 'пиздец', 'хуй', 'ебать'}
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif'}
user_posts = {}

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

def is_within_working_hours() -> bool:
    now = datetime.now().hour
    return START_HOUR <= now < END_HOUR

async def check_subscription_and_block(context: ContextTypes, user_id: int) -> tuple[bool, str]:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status == 'kicked':
            return False, "❌ Вы были заблокированы в канале и не можете использовать бота."
        return member.status in ['member', 'administrator', 'creator'], ""
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False, "❌ Ошибка проверки статуса. Попробуйте позже."

def check_post_limit_and_duplicates(user_id: int, text: str) -> tuple[bool, str]:
    now = datetime.now()
    if user_id not in user_posts:
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}
        return True, ""

    user_data = user_posts[user_id]
    if now.date() != user_data["date"].date():
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}

    if user_data["count"] >= 3:
        return False, "❌ Лимит 3 поста в сутки!"

    for post, post_time in user_data["posts"]:
        if post.strip() == text.strip() and (now - post_time) < timedelta(days=1):
            hours_left = 24 - (now - post_time).total_seconds() // 3600
            return False, f"❌ Пост уже публиковался. Повторите через {int(hours_left)} ч."

    return True, ""

def add_successful_post(user_id: int, text: str):
    now = datetime.now()
    user_data = user_posts[user_id]
    user_data["posts"].append([text, now])
    user_data["count"] += 1
    user_data["date"] = now

def check_message(text: str, user_username: str) -> tuple[bool, str]:
    text_lower = text.lower()
    user_username = user_username.lower() if user_username else ""
    is_offtopic = any(hashtag in text_lower for hashtag in ['#офтоп', '#оффтоп'])
    usernames = re.findall(r'@([a-zA-Z0-9_]{5,})', text)

    if not usernames:
        return False, "❌ Укажите @username для связи"
    
    if not is_offtopic:
        actions = ['продам', 'обмен', 'куплю', 'продаю', 'обменяю']
        if not any(action in text_lower for action in actions):
            return False, "❌ Укажите: 'продам', 'обмен' или 'куплю'"

        mail_keywords = ['почта', 'утеря', 'оки', 'ок.ру', 'одноклассники']
        if not any(keyword in text_lower for keyword in mail_keywords):
            return False, "❌ Укажите информацию о привязках"

    if sum(c.isupper() for c in text) / len(text) > 0.7:
        return False, "❌ Слишком много капса"

    if any(word in text_lower for word in FORBIDDEN_WORDS):
        return False, "❌ Обнаружен мат"

    if re.search(r'(https?://|www\.|\.com|\.ru|t\.me/[a-zA-Z0-9_]+)', text) and not re.search(r't\.me/shop_mrush1', text):
        return False, "❌ Ссылки запрещены (кроме t.me/shop_mrush1)"

    if re.search(r'@[a-zA-Z0-9_]*bot\b', text_lower):
        return False, "❌ Упоминания ботов запрещены"

    for username in usernames:
        if not username.lower().endswith("bot") and username.lower() not in [user_username, 'vardges_grigoryan']:
            return False, f"❌ Укажите свой контакт (@ваш_ник)"

    return True, "✅ Сообщение соответствует требованиям"

def check_file_extension(file_name: str) -> bool:
    return file_name and any(file_name.lower().endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS)

async def start(update: Update, context: ContextTypes):
    if not is_within_working_hours():
        await update.message.reply_text("⏰ Бот работает с 8:00 до 23:00. Пожалуйста, напишите позже.")
        return
    
    greeting = (
        "🤖 *Привет, я Mrush1* — бот для размещения объявлений!\n\n"
        "📌 Правила:\n"
        "🔗 [Правила группы](https://t.me/shop_mrush1/11)\n"
        "🔗 [Как подать заявку](https://t.me/shop_mrush1/13)\n\n"
        "📸 *Пример поста:*"
    )

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=greeting,
        parse_mode="Markdown",
        reply_markup=MAIN_MENU
    )
    
    try:
        with open("primerbot.jpg", "rb") as photo:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo,
                caption="Продам за 100₽\nКонтакты: @vardges_grigoryan"
            )
    except FileNotFoundError:
        await update.message.reply_text("⚠️ Не удалось отправить пример")

async def contact_admin(update: Update, context: ContextTypes):
    await update.message.reply_text(
        "👨‍💻 Вопросы к администратору: @vardges_grigoryan",
        reply_markup=BACK_BUTTON
    )

async def show_help(update: Update, context: ContextTypes):
    help_text = (
        "📌 Как подать объявление:\n"
        "1. Подпишись на @shop_mrush1\n"
        "2. Нажми /start\n"
        "3. Отправь текст и фото (если нужно)\n\n"
        "⚠ Требования:\n"
        "- Укажите действие (продам/куплю/обмен)\n"
        "- Цена/бюджет\n"
        "- Инфо о привязках\n"
        "- Ваш @username\n"
        "- Без мата/капса/ссылок"
    )
    await update.message.reply_text(help_text, reply_markup=BACK_BUTTON)

async def handle_post(update: Update, context: ContextTypes):
    user_id = update.message.from_user.id
    text = update.message.text or update.message.caption or ""
    user_username = update.message.from_user.username

    subscription_ok, sub_msg = await check_subscription_and_block(context, user_id)
    if not subscription_ok:
        await update.message.reply_text(
            f"{sub_msg or f'❌ Подпишитесь на {CHANNEL_ID}!'}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Проверить подписку", callback_data="check_subscription")]
            ])
        )
        return

    limit_ok, limit_msg = check_post_limit_and_duplicates(user_id, text)
    if not limit_ok:
        await update.message.reply_text(limit_msg, reply_markup=MAIN_MENU)
        return

    content_ok, content_msg = check_message(text, user_username)
    if not content_ok:
        await update.message.reply_text(content_msg, reply_markup=MAIN_MENU)
        return

    try:
        if update.message.photo:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=update.message.photo[-1].file_id,
                caption=text
            )
        elif update.message.document and check_file_extension(update.message.document.file_name):
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=update.message.document.file_id,
                caption=text
            )
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

        add_successful_post(user_id, text)
        await update.message.reply_text("✅ Объявление опубликовано!", reply_markup=MAIN_MENU)
    except Exception as e:
        logger.error(f"Ошибка публикации: {e}")
        await update.message.reply_text("❌ Ошибка публикации", reply_markup=MAIN_MENU)

async def handle_message(update: Update, context: ContextTypes):
    text = update.message.text
    if text == "👨‍💻 Написать администратору":
        await contact_admin(update, context)
    elif text == "🆘 Помощь":
        await show_help(update, context)
    elif text == "🔙 Назад в меню":
        await update.message.reply_text("🏠 Главное меню:", reply_markup=MAIN_MENU)
    elif text == "📤 Разместить объявление":
        await update.message.reply_text("📝 Отправьте текст объявления:", reply_markup=BACK_BUTTON)
        context.user_data['awaiting_post'] = True
    elif context.user_data.get('awaiting_post', False):
        await handle_post(update, context)
        context.user_data['awaiting_post'] = False
    else:
        await update.message.reply_text("🔄 Выберите действие 👇", reply_markup=MAIN_MENU)

async def callback_query_handler(update: Update, context: ContextTypes):
    query = update.callback_query
    await query.answer()
    if query.data == "check_subscription":
        user_id = query.from_user.id
        subscription_ok, sub_msg = await check_subscription_and_block(context, user_id)
        if subscription_ok:
            await query.edit_message_text("✅ Вы подписаны!")
        else:
            await query.edit_message_text(
                f"❌ Вы не подписаны на @shop_mrush1\n{sub_msg or ''}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Проверить снова", callback_data="check_subscription")]
                ])
            )

async def error_handler(update: Update, context: ContextTypes):
    logger.error(f"Ошибка: {context.error}")

async def run_bot():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.IMAGE, handle_message))
    application.add_error_handler(error_handler)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    logger.info("Бот запущен")
    while True:
        await asyncio.sleep(3600)

def main():
    # Запуск Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Запуск бота
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_bot())
    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        loop.close()

if __name__ == '__main__':
    import threading
    main()
