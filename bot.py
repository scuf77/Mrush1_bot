import logging
import re
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from dotenv import load_dotenv

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка токена
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "644710593")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@shop_mrush1")

if not TOKEN:
    raise ValueError("Не задана переменная окружения BOT_TOKEN")

# Основные настройки
START_HOUR = 8
END_HOUR = 23
FORBIDDEN_WORDS = {'сука', 'блять', 'пиздец', 'хуй', 'ебать'}
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif'}
user_posts = {}

# Меню
MAIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("🆘 Помощь"),
      KeyboardButton("👨‍💻 Написать администратору"),
      KeyboardButton("📤 Разместить объявление")]],
    resize_keyboard=True
)

BACK_BUTTON = ReplyKeyboardMarkup([[KeyboardButton("🔙 Назад в меню")]], resize_keyboard=True)

def is_within_hours() -> bool:
    return START_HOUR <= datetime.now(ZoneInfo("Europe/Moscow")).hour < END_HOUR

def contains_forbidden_words(text: str) -> bool:
    return any(bad_word in text.lower() for bad_word in FORBIDDEN_WORDS)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Добро пожаловать! Этот бот создан для размещения объявлений в нашем канале.\n\n"
        "Выберите нужную команду:",
        reply_markup=MAIN_MENU
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text if update.message.text else ""
    photo = update.message.photo
    document = update.message.document

    if text == "🆘 Помощь":
        await update.message.reply_text(
            "ℹ️ <b>Помощь</b>\n\n"
            "📤 Чтобы разместить объявление — нажмите на кнопку '📤 Разместить объявление'.\n"
            "👨‍💻 Для связи с администратором — нажмите соответствующую кнопку.\n\n"
            "❗ Не публикуйте спам, мат или запрещённый контент. Объявления проходят модерацию.",
            parse_mode='HTML',
            reply_markup=BACK_BUTTON
        )
        return

    if text == "👨‍💻 Написать администратору":
        await update.message.reply_text(
            "📨 <b>Связь с админом:</b> @scuf77",
            parse_mode='HTML',
            reply_markup=BACK_BUTTON
        )
        return

    if text == "📤 Разместить объявление":
        user_posts[user_id] = {"text": "", "photo": None}
        await update.message.reply_text(
            "📝 Отправьте текст объявления или прикрепите фото.\n\n"
            "Когда вы всё отправите, я покажу вам предварительный просмотр для подтверждения.",
            reply_markup=BACK_BUTTON
        )
        return

    if text == "🔙 Назад в меню":
        await update.message.reply_text("Вы вернулись в главное меню.", reply_markup=MAIN_MENU)
        return

    # Сбор текста объявления
    if user_id in user_posts:
        if contains_forbidden_words(text):
            await update.message.reply_text("🚫 Обнаружена ненормативная лексика. Пожалуйста, уберите её.")
            return

        if photo:
            user_posts[user_id]["photo"] = photo[-1].file_id
        elif document and any(document.file_name.lower().endswith(ext) for ext in ALLOWED_IMAGE_EXTENSIONS):
            user_posts[user_id]["photo"] = document.file_id

        if text:
            user_posts[user_id]["text"] += f"{text}\n"

        preview_text = user_posts[user_id]["text"].strip()
        buttons = [
            [InlineKeyboardButton("✅ Опубликовать", callback_data="confirm")],
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        if user_posts[user_id]["photo"]:
            await update.message.reply_photo(user_posts[user_id]["photo"], caption=preview_text or "📸 Фото", reply_markup=reply_markup)
        else:
            await update.message.reply_text(preview_text or "📤 Пустое объявление", reply_markup=reply_markup)
        return

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if query.data == "confirm":
        if user_id not in user_posts:
            await query.answer("Объявление не найдено.")
            return

        post = user_posts.pop(user_id)
        try:
            if post["photo"]:
                await context.bot.send_photo(CHANNEL_ID, post["photo"], caption=post["text"])
            else:
                await context.bot.send_message(CHANNEL_ID, post["text"])
            await query.message.edit_text("✅ Объявление отправлено на модерацию.")
        except Exception as e:
            logger.error(f"Ошибка при отправке: {e}")
            await query.message.edit_text("❌ Ошибка при отправке. Попробуйте позже.")

    elif query.data == "cancel":
        user_posts.pop(user_id, None)
        await query.message.edit_text("❌ Объявление отменено.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.warning(f"Ошибка: {context.error}")

# 🚀 Запуск приложения
async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.IMAGE, handle_message))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_error_handler(error_handler)
    logger.info("✅ Бот запущен")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
