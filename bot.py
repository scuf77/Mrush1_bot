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

# Простое меню бота
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("📤 Разместить объявление")],
        [KeyboardButton("❓ Помощь")],
    ],
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

    # Проверка на дубликаты (90%+ схожести)
    for post, post_time in user_data["posts"]:
        similarity = calculate_similarity(text.strip(), post.strip())
        if similarity >= 0.9:
            time_diff = now - post_time
            if time_diff < timedelta(days=1):
                hours_left = 24 - time_diff.total_seconds() // 3600
                return False, f"❌ Похожий пост уже публиковался. Повторная публикация возможна через {int(hours_left)} ч."

    return True, ""

def calculate_similarity(text1: str, text2: str) -> float:
    """Вычисляет схожесть двух текстов (0.0 - 1.0)"""
    if not text1 or not text2:
        return 0.0
    
    # Приводим к нижнему регистру и убираем лишние пробелы
    text1 = text1.lower().strip()
    text2 = text2.lower().strip()
    
    if text1 == text2:
        return 1.0
    
    # Простой алгоритм схожести на основе общих слов
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

    # Проверка на наличие @username (связь с продавцом/покупателем)
    usernames = re.findall(r"@([a-zA-Z0-9_]{5,})", text)
    if not usernames:
        return False, "❌ В сообщении отсутствует контактная информация (@username)."

    # Проверка действия (продам/куплю/обмен)
    actions = ["продам", "обмен", "куплю", "продаю", "обменяю", "покупка", "продажа", "#офтоп", "#оффтоп"]
    if not any(action in text_lower for action in actions):
        return False, "❌ Укажите действие: продам/куплю/обмен"

    # Мат
    if any(word in text_lower for word in FORBIDDEN_WORDS):
        return False, "❌ Обнаружен мат. Уберите его."

    # Слишком много капса
    if len(text) > 10 and (sum(c.isupper() for c in text) / len(text) > 0.7):
        return False, "❌ Слишком много текста в верхнем регистре (капс)."

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
    greeting = (
        "<b>🤖 Привет! Я бот для размещения объявлений о покупке/продаже цифровых ценностей.</b>\n\n"
        "📝 <b>Как разместить объявление:</b>\n"
        "1. Нажмите «📤 Разместить объявление»\n"
        "2. Отправьте фото с текстом объявления в одном сообщении (подписью к фото)\n"
        "3. Или отправьте до 5 фото отдельно, а затем текст\n"
        "4. Готово!\n\n"
        "📌 <b>Основные правила:</b>\n"
        "• Укажите действие: продам/куплю/обмен\n"
        "• Укажите цену или бюджет\n"
        "• Оставьте свой @username для связи\n"
        "• Не используйте мат и капс\n"
        "• Можно прикрепить до 5 фотографий к одному объявлению\n\n"
        "Полные правила: <a href='https://t.me/shop_mrush1/13'>t.me/shop_mrush1/13</a>"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=greeting,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=MAIN_MENU,
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
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Не удалось найти пример изображения.", disable_web_page_preview=True)

# ---------- Отложенная публикация медиагруппы ----------
async def publish_media_group_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Вызывается по таймеру (~2 сек) после получения последнего фото из медиагруппы.
    К этому моменту все фото уже накоплены в user_data.
    """
    job_data = context.job.data
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]
    user_username = job_data.get("user_username", "")
    photos = job_data.get("photos", [])
    text = job_data.get("text", "").strip()

    if not text:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Фотографий добавлено: {len(photos)}/5.\n"
                 f"Теперь отправьте текст объявления для публикации.",
            disable_web_page_preview=True
        )
        return

    # --- Все проверки (подписка, лимит, контент) ---

    subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
    if not subscriptions_ok:
        await context.bot.send_message(chat_id=chat_id, text=subscriptions_msg, disable_web_page_preview=True)
        return

    limit_ok, limit_msg = check_post_limit_and_duplicates(user_id, text)
    if not limit_ok:
        await context.bot.send_message(chat_id=chat_id, text=limit_msg, disable_web_page_preview=True)
        return

    content_ok, content_msg = check_message(text, user_username)
    if not content_ok:
        await context.bot.send_message(chat_id=chat_id, text=content_msg, disable_web_page_preview=True)
        return

    if not is_within_working_hours():
        current_time = datetime.now().strftime("%H:%M")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏰ Бот работает с 8:00 до 23:00 по МСК. Сейчас {current_time}.",
            disable_web_page_preview=True
        )
        return

    try:
        if len(photos) == 1:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photos[0],
                caption=text
            )
        else:
            media_group = []
            for i, photo_id in enumerate(photos):
                if i == 0:
                    media_group.append(InputMediaPhoto(media=photo_id, caption=text))
                else:
                    media_group.append(InputMediaPhoto(media=photo_id))
            await context.bot.send_media_group(
                chat_id=CHANNEL_ID,
                media=media_group
            )

        add_successful_post(user_id, text)
        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Ваше объявление успешно опубликовано!",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.exception(f"Ошибка при публикации медиагруппы: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Произошла ошибка при публикации объявления. Попробуйте чуть позже.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True
        )

# ---------- Обработка поста ----------
async def handle_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user
    user_id = user.id
    user_username = user.username or ""
    
    # Получаем текст из текущего сообщения или из сохранённых данных
    text = (msg.text or msg.caption or context.user_data.get("post_text") or "").strip()
    
    # Получаем фотографии из сохранённых данных или из текущего сообщения
    saved_photos = context.user_data.get("post_photos", [])
    current_photos = msg.photo or []
    document = msg.document

    if not is_within_working_hours():
        current_time = datetime.now().strftime("%H:%M")
        await msg.reply_text(
            f"⏰ Бот работает с 8:00 до 23:00 по МСК. Сейчас {current_time}. Пожалуйста, напишите завтра с 8:00.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True
        )
        return

    # Перед публикацией ещё раз убеждаемся, что пользователь подписан
    subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
    if not subscriptions_ok:
        await msg.reply_text(
            f"{subscriptions_msg}\n"
            "Пожалуйста, подпишитесь на канал и беседу и нажмите «Проверить подписку»:",
            reply_markup=SUBSCRIBE_CHECK_KEYBOARD,
            disable_web_page_preview=True
        )
        return

    if not text:
        await msg.reply_text("❌ Добавьте текст объявления (можно как подпись к фото).", reply_markup=MAIN_MENU, disable_web_page_preview=True)
        return

    # Лимит и дубликаты
    limit_ok, limit_msg = check_post_limit_and_duplicates(user_id, text)
    if not limit_ok:
        await msg.reply_text(limit_msg, reply_markup=MAIN_MENU, disable_web_page_preview=True)
        return

    # Проверка контента
    content_ok, content_msg = check_message(text, user_username)
    if not content_ok:
        await msg.reply_text(content_msg, reply_markup=MAIN_MENU, disable_web_page_preview=True)
        return

    # Проверка документа, если он есть
    if document and not check_file_extension(document.file_name):
        await msg.reply_text(
            "❌ Недопустимые файлы. Разрешены только JPG, JPEG, PNG, GIF.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True
        )
        return

    try:
        # Если есть сохранённые фотографии (режим создания поста с несколькими фото)
        if saved_photos:
            if len(saved_photos) == 1:
                # Одна фотография - используем send_photo
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=saved_photos[0],
                    caption=text
                )
            else:
                # Несколько фотографий - используем send_media_group
                media_group = []
                for i, photo_id in enumerate(saved_photos):
                    # Подпись только к первой фотографии
                    if i == 0:
                        media_group.append(InputMediaPhoto(media=photo_id, caption=text))
                    else:
                        media_group.append(InputMediaPhoto(media=photo_id))
                
                await context.bot.send_media_group(
                    chat_id=CHANNEL_ID,
                    media=media_group
                )
        # Если фотография в текущем сообщении (старый способ - для обратной совместимости)
        elif current_photos:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=current_photos[-1].file_id,
                caption=text
            )
        # Если документ в текущем сообщении
        elif document:
            await context.bot.send_document(
                chat_id=CHANNEL_ID,
                document=document.file_id,
                caption=text
            )
        # Только текст
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text, disable_web_page_preview=True)

        add_successful_post(user_id, text)
        await msg.reply_text("✅ Ваше объявление успешно опубликовано!", reply_markup=MAIN_MENU, disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"Ошибка при публикации объявления: {e}")
        await msg.reply_text(
            "❌ Произошла ошибка при публикации объявления. Попробуйте чуть позже.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True
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
            f"⏰ Бот работает с 8:00 до 23:00 по МСК. Сейчас {current_time}. Пожалуйста, напишите позже.",
            disable_web_page_preview=True
        )
        return

    subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
    if not subscriptions_ok:
        await update.message.reply_text(
            f"{subscriptions_msg}\n"
            "После подписки нажмите «Проверить подписку».",
            reply_markup=SUBSCRIBE_CHECK_KEYBOARD,
            disable_web_page_preview=True
        )
        return

    await send_welcome_message(context, update.effective_chat.id)

async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👨‍💻 Если у вас возникли вопросы — пишите администратору: @vardges_grigoryan",
        reply_markup=MAIN_MENU,
        disable_web_page_preview=True
    )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📌 <b>Как разместить объявление:</b>\n"
        "1. Нажмите «📤 Разместить объявление»\n"
        "2. Отправьте до 5 фотографий (если нужно)\n"
        "3. Отправьте текст объявления\n"
        "4. Готово!\n\n"
        "📌 <b>Основные правила:</b>\n"
        "• Укажите действие: продам/куплю/обмен\n"
        "• Укажите цену или бюджет\n"
        "• Оставьте свой @username для связи\n"
        "• Не используйте мат и капс\n"
        "• Можно прикрепить до 5 фотографий к одному объявлению\n\n"
        "Полные правила: <a href='https://t.me/shop_mrush1/13'>t.me/shop_mrush1/13</a>"
    )
    await update.message.reply_text(
        help_text,
        parse_mode="HTML",
        reply_markup=MAIN_MENU,
        disable_web_page_preview=True
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text

    if text == "❓ Помощь":
        await show_help(update, context)
        return
    if text == "📤 Разместить объявление":
        await msg.reply_text(
            "📝 Отправьте фото с текстом в одном сообщении (подписью к фото).\n\n"
            "Или отправьте до 5 фотографий подряд, а затем текст объявления отдельным сообщением.",
            reply_markup=MAIN_MENU,
            disable_web_page_preview=True
        )
        context.user_data["awaiting_post"] = True
        context.user_data["post_photos"] = []  # Список file_id фотографий
        context.user_data["post_text"] = None  # Текст объявления
        return

    # Если пользователь уже выбрал «Разместить объявление»
    if context.user_data.get("awaiting_post", False):
        # Если это фотография
        if msg.photo:
            photos = context.user_data.get("post_photos", [])
            if len(photos) >= 5:
                await msg.reply_text(
                    "❌ Вы уже добавили максимальное количество фотографий (5). "
                    "Отправьте текст объявления для публикации.",
                    reply_markup=MAIN_MENU,
                    disable_web_page_preview=True
                )
                return
            
            # Сохраняем file_id самой большой версии фотографии
            photos.append(msg.photo[-1].file_id)
            context.user_data["post_photos"] = photos
            
            # Если есть подпись к фото, сохраняем
            if msg.caption:
                context.user_data["post_text"] = msg.caption.strip()
            
            # Проверяем, является ли это частью медиагруппы (несколько фото в одном сообщении)
            if msg.media_group_id:
                # Отменяем предыдущий таймер для этой медиагруппы (если был)
                job_name = f"media_group_{msg.from_user.id}_{msg.media_group_id}"
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
                
                # Ставим новый таймер на 2 сек — когда все фото из группы придут
                context.job_queue.run_once(
                    publish_media_group_job,
                    when=2,
                    name=job_name,
                    data={
                        "user_id": msg.from_user.id,
                        "chat_id": msg.chat.id,
                        "user_username": msg.from_user.username or "",
                        "photos": photos,
                        "text": context.user_data.get("post_text", ""),
                    }
                )
                # Очищаем состояние ожидания, т.к. публикацию возьмёт на себя job
                context.user_data["awaiting_post"] = False
                context.user_data.pop("post_photos", None)
                context.user_data.pop("post_text", None)
                return
            
            # Одно фото (без media_group_id) с подписью — сразу публикуем
            if context.user_data.get("post_text"):
                await handle_post(update, context)
                context.user_data["awaiting_post"] = False
                context.user_data.pop("post_photos", None)
                context.user_data.pop("post_text", None)
                return
            
            # Подписи нет — ждём текст отдельным сообщением
            remaining = 5 - len(photos)
            await msg.reply_text(
                f"✅ Фотография добавлена ({len(photos)}/5).\n"
                f"Можно добавить ещё {remaining} фотографий или отправить текст объявления для публикации.",
                reply_markup=MAIN_MENU,
                disable_web_page_preview=True
            )
            return
        
        # Если это документ (изображение)
        if msg.document:
            if not check_file_extension(msg.document.file_name):
                await msg.reply_text(
                    "❌ Недопустимые файлы. Разрешены только JPG, JPEG, PNG, GIF.",
                    reply_markup=MAIN_MENU,
                    disable_web_page_preview=True
                )
                return
            
            photos = context.user_data.get("post_photos", [])
            if len(photos) >= 5:
                await msg.reply_text(
                    "❌ Вы уже добавили максимальное количество фотографий (5). "
                    "Отправьте текст объявления для публикации.",
                    reply_markup=MAIN_MENU,
                    disable_web_page_preview=True
                )
                return
            
            # Для документов-изображений сохраняем file_id
            photos.append(msg.document.file_id)
            context.user_data["post_photos"] = photos
            
            # Если есть подпись к документу, сохраняем
            if msg.caption:
                context.user_data["post_text"] = msg.caption.strip()
            
            # Проверяем, является ли это частью медиагруппы
            if msg.media_group_id:
                job_name = f"media_group_{msg.from_user.id}_{msg.media_group_id}"
                current_jobs = context.job_queue.get_jobs_by_name(job_name)
                for job in current_jobs:
                    job.schedule_removal()
                
                context.job_queue.run_once(
                    publish_media_group_job,
                    when=2,
                    name=job_name,
                    data={
                        "user_id": msg.from_user.id,
                        "chat_id": msg.chat.id,
                        "user_username": msg.from_user.username or "",
                        "photos": photos,
                        "text": context.user_data.get("post_text", ""),
                    }
                )
                context.user_data["awaiting_post"] = False
                context.user_data.pop("post_photos", None)
                context.user_data.pop("post_text", None)
                return
            
            # Одиночный документ с подписью — сразу публикуем
            if context.user_data.get("post_text"):
                await handle_post(update, context)
                context.user_data["awaiting_post"] = False
                context.user_data.pop("post_photos", None)
                context.user_data.pop("post_text", None)
                return
            
            # Подписи нет — ждём текст отдельным сообщением
            remaining = 5 - len(photos)
            await msg.reply_text(
                f"✅ Изображение добавлено ({len(photos)}/5).\n"
                f"Можно добавить ещё {remaining} фотографий или отправить текст объявления для публикации.",
                reply_markup=MAIN_MENU,
                disable_web_page_preview=True
            )
            return
        
        # Если это текст (и пользователь уже в режиме создания поста)
        if text:
            # Сохраняем текст, если его ещё нет
            if not context.user_data.get("post_text"):
                context.user_data["post_text"] = text.strip()
            
            # Публикуем объявление
            await handle_post(update, context)
            # Очищаем данные
            context.user_data["awaiting_post"] = False
            context.user_data.pop("post_photos", None)
            context.user_data.pop("post_text", None)
            return

    # Если пользователь прислал фото или документ без режима создания поста — обрабатываем как пост
    if msg.photo or msg.document:
        await handle_post(update, context)
        return

    # Иначе просим выбрать действие
    await msg.reply_text("🔄 Выберите действие 👇", reply_markup=MAIN_MENU, disable_web_page_preview=True)

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_subscription":
        user_id = query.from_user.id
        subscriptions_ok, subscriptions_msg = await check_subscriptions(context, user_id)
        if subscriptions_ok:
            await query.edit_message_text("✅ Всё отлично! Вы подписаны на оба чата.", disable_web_page_preview=True)
            # Отправляем привет
            await send_welcome_message(context, query.message.chat.id)
        else:
            await query.edit_message_text(
                text=(
                    f"{subscriptions_msg}\n\n"
                    "Убедитесь, что подписались и нажмите «Проверить подписку» снова."
                ),
                reply_markup=SUBSCRIBE_CHECK_KEYBOARD,
                disable_web_page_preview=True
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