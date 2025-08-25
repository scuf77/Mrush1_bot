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
    KeyboardButton
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

# ---------- Flask (healthcheck для Railway) ----------
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

# ---------- Логирование ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- Конфигурация ----------
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения!")

# Канал (обязательная подписка)
CHANNEL_ID = os.getenv("CHANNEL_ID", "@shop_mrush1")
# Беседа (обязательное участие)
CHAT_ID = "@chat_mrush1"  # Публичная супергруппа (см. https://t.me/chat_mrush1)

START_HOUR = 5
END_HOUR = 20

FORBIDDEN_WORDS = {"сука", "блять", "пиздец", "хуй", "ебать"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}

# Хранение информации о постах в оперативной памяти
user_posts = {}

# Главное меню бота
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🆘 Помощь")],
        [KeyboardButton("👨‍💻 Написать администратору")],
        [KeyboardButton("📤 Разместить объявление")],
    ],
    resize_keyboard=True,
)

# Клавиатура «назад»
BACK_BUTTON = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton("🔙 Назад в меню")]],
    resize_keyboard=True,
)

# Inline-кнопки для быстрого перехода и проверки
SUBSCRIBE_CHECK_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("Канал @shop_mrush1", url="https://t.me/shop_mrush1")
    ],
    [
        InlineKeyboardButton("Беседа @chat_mrush1", url="https://t.me/chat_mrush1")
    ],
    [
        InlineKeyboardButton("Проверить подписку", callback_data="check_subscription")
    ]
])

def is_within_working_hours() -> bool:
    now = datetime.now()
    current_time = now.hour + now.minute / 60
    return START_HOUR <= current_time < END_HOUR

async def check_subscriptions(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> tuple[bool, str]:
    """
    Проверяет, состоит ли пользователь в обязательном канале и беседе.
    Возвращает (True, '') при успехе либо (False, текст_ошибки).
    """
    # Сначала проверяем канал (ростер должен быть public: @shop_mrush1)
    try:
        member_channel = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member_channel.status == "kicked":
            return False, "❌ Вы были заблокированы в канале и не можете использовать бота."
        if member_channel.status not in ["member", "administrator", "creator"]:
            return False, "❌ Вы не подписаны на основной канал."
    except Exception as e:
        logger.error(f"Ошибка проверки подписки на канал {CHANNEL_ID}: {e}")
        return False, "❌ Произошла ошибка при проверке подписки на канал."

    # Затем проверяем беседу (должна быть публичной супергруппой: @chat_mrush1)
    try:
        member_chat = await context.bot.get_chat_member(chat_id=CHAT_ID, user_id=user_id)
        if member_chat.status == "kicked":
            return False, "❌ Вы были заблокированы в беседе и не можете использовать бота."
        if member_chat.status not in ["member", "administrator", "creator"]:
            return False, "❌ Вы не состоите в обязательной беседе."
    except Exception as e:
        logger.error(f"Ошибка проверки участия в беседе {CHAT_ID}: {e}")
        return False, "❌ Произошла ошибка при проверке вашего статуса в беседе."

    return True, ""

def check_post_limit_and_duplicates(user_id: int, text: str) -> tuple[bool, str]:
    now = datetime.now()
    if user_id not in user_posts:
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}
        return True, ""

    user_data = user_posts[user_id]
    # Сбрасываем счётчик, если наступил новый день
    if now.date() != user_data["date"].date():
        user_posts[user_id] = {"posts": [], "count": 0, "date": now}

    if user_posts[user_id]["count"] >= 3:
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
    user_username = (user_username or "").lower()

    # Есть ли #офтоп
    is_offtopic = any(hashtag in text_lower for hashtag in ["#офтоп", "#оффтоп"])
    # Проверка на наличие @username (связь с продавцом/покупателем)
    usernames = re.findall(r"@([a-zA-Z0-9_]{5,})", text)
    if not usernames:
        return False, "❌ В сообщении отсутствует контактная информация (@username)."

    if not is_offtopic:
        actions = ["продам", "обмен", "куплю", "продаю", "обменяю", "покупка", "продажа"]
        if not any(action in text_lower for action in actions):
            return False, "❌ Укажите действие: 'продам', 'обмен' или 'куплю'."

        mail_keywords = [
            "почта", "почту", "почты", "указ", "утер", "утерь", "утеря",
            "оки", "ок ру", "ок.ру", "одноклассники", "спакес", "однокласники",
            "одноклассника", "однокласника", "одноклассников", "однокласников",
            "спейсис", "спакес", "spaces",
        ]
        if not any(keyword in text_lower for keyword in mail_keywords):
            return False, "❌ Укажите информацию о привязках."

    # Лимит капса
    if len(text) > 10 and (sum(c.isupper() for c in text) / len(text) > 0.7):
        return False, "❌ Слишком много текста в верхнем регистре (капс)."

    # Мат
    if any(word in text_lower for word in FORBIDDEN_WORDS):
        return False, "❌ Обнаружен мат. Уберите его."

    # Запрещённые ссылки (кроме t.me/shop_mrush1)
    if re.search(r"(https?://|www\.|\.com|\.ru|\.org|t\.me/[a-zA-Z0-9_]+)", text) and not re.search(r"t\.me/shop_mrush1", text):
        return False, "❌ Ссылки запрещены (кроме t.me/shop_mrush1)."

    # Упоминания ботов
    if re.search(r"@[a-zA-Z0-9_]*bot\b", text_lower):
        return False, "❌ Упоминания ботов запрещены."

    # Лишние упоминания чужих @username
    for username in usernames:
        username_lower = username.lower()
        if username_lower.endswith("bot"):
            continue
        if username_lower not in [user_username, "vardges_grigoryan"]:
            return False, f"❌ Упоминание @{username} запрещено. Укажите свой контакт (@ваш_ник)."

    return True, "✅ Сообщение соответствует требованиям."

def check_file_extension(file_name: str) -> bool:
    if not file_name:
        return False
    return any(file_name.lower().endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS)

# ---------- Приветственное сообщение ----------
async def send_welcome_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    # Разделяем длинный текст на два блока
    greeting_part1 = (
        "🤖 *Привет, я Mrush1* — бот для размещения объявлений о *покупке, продаже и обмене игровых аккаунтов*!\n\n"
        "Перед тем как продолжить, убедитесь, что вы подписаны на:\n"
        f"• Основной канал: {CHANNEL_ID}\n"
        f"• Беседу: {CHAT_ID}\n"
        "И только затем можно пользоваться ботом.\n\n"
        "📝 Как подать объявление:\n"
        "1) Сначала нажмите «📤 Разместить объявление».\n"
        "2) Отправьте текст объявления (+ фото, если нужно).\n"
        "3) Бот проверит пост на соответствие правилам.\n"
        "4) Бот опубликует в канале, если всё ОК.\n"
    )

    greeting_part2 = (
    "📌 <b>Основные требования к объявлениям</b>:\n"
    "• Укажите действие (продам, обмен, куплю) или #оффтоп.\n"
    "• Укажите краткую информацию о цене / бюджете.\n"
    "• Укажите, что с почтой (есть/утеряна/можно указать свою).\n"
    "• Не используйте капс и нецензурные выражения.\n"
    "• Запрещены ссылки (кроме t.me/shop_mrush1) и упоминания чужих @username.\n"
    "• Обязательно оставьте свой @контакт.\n\n"
    "Полный перечень правил смотрите в самом канале:\n"
    '🔗 <a href="https://t.me/shop_mrush1/11">Правила площадки</a>\n'
    '🔗 <a href="https://t.me/shop_mrush1/13">Как правильно подать заявку</a>\n'
)

    await context.bot.send_message(
        chat_id=chat_id,
        text=greeting_part1,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=MAIN_MENU,
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=greeting_part2,
        parse_mode="HTML",
        disable_web_page_preview=True
    )

    # Пример изображения
    try:
        with open("primerbot.jpg", "rb") as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=(
                    "Пример объявления:\n"
                    "«Продам за 100₽ или обменяю на акк посильнее с моей доплатой. "
                    "На аккаунте есть возможность указать свою почту. "
                    "Контакты для связи: @vardges_grigoryan»"
                ),
            )
    except FileNotFoundError:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Не удалось найти пример изображения.")

# ---------- Обработка поста ----------
async def handle_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    user_id = user.id
    user_username = user.username or ""
    text = (msg.text or msg.caption or "").strip()

    if not is_within_working_hours():
        current_time = datetime.now().strftime("%H:%M")
        await msg.reply_text(
            f"⏰ Бот работает с {START_HOUR}:00 до {END_HOUR}:00. Сейчас {current_time}. Пожалуйста, напишите завтра с {START_HOUR}:00.",
            reply_markup=MAIN_MENU,
        )
        return

    # Перед публикацией ещё раз убеждаемся, что пользователь подписан
    subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
    if not subscriptions_ok:
        await msg.reply_text(
            f"{subscriptions_msg}\n"
            "Пожалуйста, подпишитесь на канал и беседу и нажмите «Проверить подписку»:",
            reply_markup=SUBSCRIBE_CHECK_KEYBOARD,
        )
        return

    if not text:
        await msg.reply_text("❌ Добавьте текст объявления (можно как подпись к фото).", reply_markup=MAIN_MENU)
        return

    # Лимит и дубли
    limit_ok, limit_msg = check_post_limit_and_duplicates(user_id, text)
    if not limit_ok:
        await msg.reply_text(limit_msg, reply_markup=MAIN_MENU)
        return

    # Проверка контента
    content_ok, content_msg = check_message(text, user_username)
    if not content_ok:
        await msg.reply_text(content_msg, reply_markup=MAIN_MENU)
        return

    photos = msg.photo or []
    document = msg.document

    if document and not check_file_extension(document.file_name):
        await msg.reply_text(
            "❌ Недопустимые файлы. Разрешены только JPG, JPEG, PNG, GIF.",
            reply_markup=MAIN_MENU,
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
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text)

        add_successful_post(user_id, text)
        await msg.reply_text("✅ Ваше объявление успешно опубликовано!", reply_markup=MAIN_MENU)
    except Exception as e:
        logger.exception(f"Ошибка при публикации объявления: {e}")
        await msg.reply_text(
            "❌ Произошла ошибка при публикации объявления. Попробуйте чуть позже.",
            reply_markup=MAIN_MENU
        )

# ---------- Команды / колбэки / сообщения ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Срабатывает, когда пользователь пишет /start.
    Проверяем, подписан ли пользователь на канал @shop_mrush1 и беседу @chat_mrush1.
    Если нет — выводим сообщение и Inline-клавиатуру.
    Если да, показываем приветственное меню.
    """
    user_id = update.effective_user.id

    if not is_within_working_hours():
        current_time = datetime.now().strftime("%H:%M")
        await update.message.reply_text(
            f"⏰ Бот работает с {START_HOUR}:00 до {END_HOUR}:00. Сейчас {current_time}. Пожалуйста, напишите позже."
        )
        return

    subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
    if not subscriptions_ok:
        await update.message.reply_text(
            f"{subscriptions_msg}\n"
            "После подписки нажмите «Проверить подписку».",
            reply_markup=SUBSCRIBE_CHECK_KEYBOARD
        )
        return

    await send_welcome_message(context, update.effective_chat.id)

async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_within_working_hours():
        await update.message.reply_text(
            f"⏰ Бот работает только с {START_HOUR}:00 до {END_HOUR}:00. Попробуйте позже."
        )
        return
    await update.message.reply_text(
        "👨‍💻 Если у вас возникли вопросы — пишите администратору: @vardges_grigoryan",
        reply_markup=BACK_BUTTON,
    )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_within_working_hours():
        await update.message.reply_text(
            f"⏰ Бот работает только с {START_HOUR}:00 до {END_HOUR}:00. Попробуйте позже."
        )
        return

    # Укороченный help-текст, чтобы не перегружать
    help_text = (
    "📌 <b>Как подать объявление:</b>\n"
    f"1. Подпишитесь на канал и зайдите в беседу:\n   • {CHANNEL_ID}\n   • {CHAT_ID}\n"
    "2. Нажмите /start, чтобы бот удостоверился, что вы подписаны.\n"
    "3. Нажмите «📤 Разместить объявление».\n"
    "4. Отправьте ваш текст и фото (опционально) боту.\n"
    "5. Готово — объявление отправится в канал, если все проверки пройдены.\n\n"
    "📌 <b>Основные правила:</b>\n"
    "- Указывать действие (продам/куплю/обмен) или #оффтоп.\n"
    "- Указать, что с почтой (если по игре).\n"
    "- Запрещён мат, капс, ссылки (кроме t.me/shop_mrush1).\n"
    "- Обязательно: ваш @username.\n\n"
    "Полный перечень правил смотрите в самом канале:\n"
    '🔗 <a href="https://t.me/shop_mrush1/11">Правила площадки</a>\n'
    '🔗 <a href="https://t.me/shop_mrush1/13">Как правильно подать заявку</a>\n'
)
    await update.message.reply_text(help_text, parse_mode="HTML", reply_markup=BACK_BUTTON)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text

    if text == "👨‍💻 Написать администратору":
        await contact_admin(update, context)
        return
    if text == "🆘 Помощь":
        await show_help(update, context)
        return
    if text == "🔙 Назад в меню":
        await msg.reply_text("🏠 Главное меню:", reply_markup=MAIN_MENU)
        context.user_data["awaiting_post"] = False
        return
    if text == "📤 Разместить объявление":
        await msg.reply_text(
            "📝 Отправьте текст вашего объявления и, при желании, прикрепите фото аккаунта.",
            reply_markup=BACK_BUTTON,
        )
        context.user_data["awaiting_post"] = True
        return

    # Если пользователь уже выбрал «Разместить объявление»
    if context.user_data.get("awaiting_post", False):
        await handle_post(update, context)
        context.user_data["awaiting_post"] = False
        return

    # Если пользователь прислал фото или документ — обрабатываем как пост
    if msg.photo or msg.document:
        await handle_post(update, context)
        return

    # Иначе просим выбрать действие
    await msg.reply_text("🔄 Пожалуйста, выберите действие 👇", reply_markup=MAIN_MENU)

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_subscription":
        user_id = query.from_user.id
        subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
        if subscriptions_ok:
            await query.edit_message_text("✅ Всё отлично! Вы подписаны на оба чата.")
            # Отправляем привет
            await send_welcome_message(context, query.message.chat.id)
        else:
            await query.edit_message_text(
                text=(
                    f"{subscriptions_msg}\n\n"
                    "Убедитесь, что подписались и нажмите «Проверить подписку» снова."
                ),
                reply_markup=SUBSCRIBE_CHECK_KEYBOARD
            )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception(f"Ошибка: {context.error}")

# ---------- main ----------
def main():
    # Запуск Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Приложение PTB
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(
        MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.IMAGE, handle_message)
    )
    application.add_error_handler(error_handler)

    logger.info("Запуск polling (синхронный)...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
