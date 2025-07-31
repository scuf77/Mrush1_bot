import logging
import re
import asyncio
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram import Bot
from flask import Flask
import os
from dotenv import load_dotenv

# ===== 1. Flask сервер для Render =====
app = Flask(__name__)
PORT = 10000  # Рабочий порт для Render

@app.route('/')
def health_check():
    return "Mrush1 Bot is running", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ===== 2. Ваш оригинальный код без изменений =====
# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables")

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
    now = datetime.now(ZoneInfo("Europe/Moscow")).hour
    logger.info(f"Current server time: {datetime.now(ZoneInfo('Europe/Moscow'))}, Hour: {now}")
    return START_HOUR <= now < END_HOUR

async def check_subscription_and_block(context: ContextTypes, user_id: int) -> tuple[bool, str]:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status == 'kicked':
            return False, "❌ Вы были заблокированы в канале и не можете использовать бота."
        return member.status in ['member', 'administrator', 'creator'], ""
    except Exception as e:
        logger.error(f"Ошибка проверки подписки или статуса: {e}")
        return False, "❌ Произошла ошибка проверки статуса. Попробуйте позже."

def check_post_limit_and_duplicates(user_id: int, text: str) -> tuple[bool, str]:
    now = datetime.now()
    if user_id not in user_posts:
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}
        return True, ""

    user_data = user_posts[user_id]
    if now.date() != user_data["date"].date():
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}

    if user_data["count"] >= 3:
        return False, "❌ Вы превысили лимит в 3 поста за сутки. Попробуйте завтра."

    for post, post_time in user_data["posts"]:
        if post.strip() == text.strip():
            time_diff = now - post_time
            if time_diff < timedelta(days=1):
                hours_left = 24 - time_diff.total_seconds() // 3600
                return False, f"❌ Этот пост уже публиковался. Повторная публикация возможна через {int(hours_left)} ч."

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

    is_offtopic = any(hashtag in text_lower for hashtag in ['#офтоп', '#оффтоп', '#офтоп', '#оффтоп'])

    usernames = re.findall(r'@([a-zA-Z0-9_]{5,})', text)
    if not usernames:
        return False, "❌ В сообщении отсутствует контактная информация (@username)."

    if not is_offtopic:
        actions = ['продам', 'обмен', 'куплю', 'продаю', 'обменяю', 'покупка', 'продажа']
        if not any(action in text_lower for action in actions):
            return False, "❌ Укажите действие: 'продам', 'обмен' или 'куплю'."

        mail_keywords = ['почта', 'почту', 'указ', 'утер', 'утерь', 'утеря', 'оки', 'ок ру', 'ок.ру', 'одноклассники', 'спакес', 'однокласники', 'одноклассника', 'однокласника', 'одноклассников', 'однокласников']
        if not any(keyword in text_lower for keyword in mail_keywords):
            return False, "❌ Укажите информацию о привязках."

    if sum(c.isupper() for c in text) / len(text) > 0.7 and len(text) > 10:
        return False, "❌ Слишком много текста в верхнем регистре (капс)."

    if any(word in text_lower for word in FORBIDDEN_WORDS):
        return False, "❌ Обнаружен мат. Уберите его."

    if re.search(r'(https?://|www\.|\.com|\.ru|\.org|t\.me/[a-zA-Z0-9_]+)', text) and not re.search(
            r't\.me/shop_mrush1', text):
        return False, "❌ Ссылки запрещены (кроме t.me/shop_mrush1)."

    if re.search(r'@[a-zA-Z0-9_]*bot\b', text_lower):
        return False, "❌ Упоминания ботов запрещены."

    for username in usernames:
        username_lower = username.lower()
        if username_lower.endswith("bot"):
            continue
        if username_lower not in [user_username, 'vardges_grigoryan']:
            return False, f"❌ Упоминание @{username} запрещено. Укажите свой контакт (@ваш_ник)."

    return True, "✅ Сообщение соответствует требованиям."

def check_file_extension(file_name: str) -> bool:
    if not file_name:
        return False
    return any(file_name.lower().endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS)

async def start(update: Update, context: ContextTypes):
    logger.info(f"Received /start command from user {update.effective_user.id}")
    if not is_within_working_hours():
        await update.message.reply_text("⏰ Бот работает с 8:00 до 23:00. Пожалуйста, напишите позже.")
        return
    await send_welcome_message(context, update.effective_chat.id)

async def send_welcome_message(context: ContextTypes, chat_id: int):
    greeting = (
        "🤖 *Привет, я Mrush1* — бот для размещения объявлений о *покупке, продаже и обмене игровых аккаунтов*!\n\n"
        "📌 Ознакомься с правилами:\n"
        "🔗 [Правила группы](https://t.me/shop_mrush1/11)\n"
        "🔗 [Как правильно подать заявку](https://t.me/shop_mrush1/13)\n\n"
        "📸 *Вот пример поста:*"
    )

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=greeting,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=MAIN_MENU
        )

        # Попытка отправки изображения
        with open("primerbot.jpg", "rb") as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=(
                    "Продам за 100₽ или обменяю на акк посильнее с моей доплатой\n"
                    "На аккаунте есть возможность указать свою почту\n\n"
                    "Контакты для связи: @vardges_grigoryan"
                )
            )
    except FileNotFoundError:
        logger.warning("Файл primerbot.jpg не найден, пропускаем отправку изображения")
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Не удалось найти пример изображения.")
    except Exception as e:
        logger.error(f"Ошибка при отправке приветственного сообщения или изображения: {e}")
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Произошла ошибка при отправке сообщения.")

async def contact_admin(update: Update, context: ContextTypes):
    if not is_within_working_hours():
        await update.message.reply_text("⏰ Бот работает с 8:00 до 23:00. Пожалуйста, напишите позже.")
        return

    await update.message.reply_text(
        "👨‍💻 Если у вас возникли вопросы — пишите администратору: @vardges_grigoryan",
        reply_markup=BACK_BUTTON
    )

async def show_help(update: Update, context: ContextTypes):
    if not is_within_working_hours():
        await update.message.reply_text("⏰ Бот работает с 8:00 до 23:00. Пожалуйста, напишите позже.")
        return

    help_text = (
        "📌 Как правильно подать объявление? Просто выполни несколько простых пунктов! ✅\n\n"
        "1. Подпишись на канал: @shop_mrush1\n"
        "2. Нажми /start\n"
        "3. Отправь объявление боту (текст и, при желании, фото в формате JPG, JPEG, PNG или GIF)\n\n"
        "⚠ Требования к постам:\n"
        "- Цель (продам/куплю/обмен) или укажите #оффтоп (если тема не связана с игрой Разрушители)\n"
        "- Цена или бюджет (Продаю за 1000₽/Куплю до 500₽/Меняю + доплата 300₽)\n"
        "- Почта (есть/утеряна/можно указать свою). Не требуется для #оффтоп\n"
        "- Фото (по желанию, только JPG, JPEG, PNG, GIF)\n"
        "- Без мата, капса, ссылок и ботов\n"
        "- Ваш контакт в Telegram (@ваш_ник)\n\n"
        "💬 Остались вопросы? Нажмите «👨‍💻 Написать администратору»"
    )

    await update.message.reply_text(help_text, reply_markup=BACK_BUTTON)

async def handle_post(update: Update, context: ContextTypes):
    user_id = update.message.from_user.id
    text = update.message.text or update.message.caption or ""
    user_username = update.message.from_user.username

    if not is_within_working_hours():
        await update.message.reply_text("⏰ Бот работает с 8:00 до 23:00. Пожалуйста, напишите позже.")
        return

    subscription_ok, subscription_msg = await check_subscription_and_block(context, user_id)
    if not subscription_ok:
        await update.message.reply_text(
            f"{subscription_msg if subscription_msg else f'❌ Чтобы опубликовать объявление, подпишитесь на канал {CHANNEL_ID}!'}\n"
            "Нажмите кнопку ниже, чтобы проверить подписку:",
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

    photos = update.message.photo
    document = update.message.document
    if document and not check_file_extension(document.file_name):
        await update.message.reply_text(
            "❌ Прикреплены недопустимые файлы. Разрешены только изображения (JPG, JPEG, PNG, GIF).",
            reply_markup=MAIN_MENU
        )
        return

    try:
        if photos:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photos[-1].file_id,
                caption=text
            )
        elif document:
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=document.file_id,
                caption=text
            )
        else:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=text
            )

        add_successful_post(user_id, text)
        await update.message.reply_text(
            "✅ Ваше объявление успешно опубликовано!",
            reply_markup=MAIN_MENU
        )
    except Exception as e:
        logger.error(f"Ошибка при публикации объявления: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при публикации объявления. Попробуйте позже.",
            reply_markup=MAIN_MENU
        )

async def handle_message(update: Update, context: ContextTypes):
    text = update.message.text
    if text == "👨‍💻 Написать администратору":
        await contact_admin(update, context)
    elif text == "🆘 Помощь":
        await show_help(update, context)
    elif text == "🔙 Назад в меню":
        await update.message.reply_text("🏠 Главное меню:", reply_markup=MAIN_MENU)
    elif text == "📤 Разместить объявление":
        await update.message.reply_text(
            "📝 Отправьте текст вашего объявления и, при желании, прикрепите фото Вашего аккаунта.",
            reply_markup=BACK_BUTTON
        )
        context.user_data['awaiting_post'] = True
    elif context.user_data.get('awaiting_post', False):
        await handle_post(update, context)
        context.user_data['awaiting_post'] = False
    else:
        await update.message.reply_text("🔄 Пожалуйста, выберите действие 👇", reply_markup=MAIN_MENU)

async def callback_query_handler(update: Update, context: ContextTypes):
    query = update.callback_query
    await query.answer()
    if query.data == "check_subscription":
        user_id = query.from_user.id
        subscription_ok, subscription_msg = await check_subscription_and_block(context, user_id)
        if subscription_ok:
            await query.edit_message_text("✅ Вы успешно подписались на канал!")
            await send_welcome_message(context, query.message.chat_id)
        else:
            await query.edit_message_text(
                f"❌ Вы не подписаны на канал (@shop_mrush1). Подпишитесь и попробуйте ещё раз.\n{subscription_msg if subscription_msg else ''}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Проверить подписку", callback_data="check_subscription")]
                ])
            )

async def error_handler(update: Update, context: ContextTypes):
    logger.error(f"Update {update} caused error {context.error}")
    if str(context.error).startswith("Conflict"):
        logger.error("Conflict detected! Ensure only one bot instance is running. Check for local instances, multiple Render services, or other deployments using the same token.")

async def bot_main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.IMAGE, handle_message))
    application.add_error_handler(error_handler)

    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Mrush1 Bot started polling...")
    await application.run_polling()

def run_async_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot_main())
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        loop.close()

# ===== 3. Запуск приложения =====
if __name__ == '__main__':
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Запускаем бота
    run_async_bot()
