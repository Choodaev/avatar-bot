import os
import tempfile
import asyncio
import threading
from dotenv import load_dotenv
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ContentType, URLInputFile
from aiogram.filters import Command
import replicate

# Загружаем переменные окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REPLICATE_TOKEN = os.getenv("REPLICATE_API_TOKEN")

# Проверка токенов
if not TELEGRAM_TOKEN:
    raise ValueError("❌ Не задан TELEGRAM_BOT_TOKEN в .env")
if not REPLICATE_TOKEN:
    raise ValueError("❌ Не задан REPLICATE_API_TOKEN в .env")

# Инициализация бота
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()
os.environ["REPLICATE_API_TOKEN"] = REPLICATE_TOKEN

# ===============================
# 🔌 Веб-сервер для Render (чтобы бот не спал)
# ===============================
async def ping_handler(request):
    """Отвечает на запросы Render (health check)"""
    return web.Response(text="✅ Bot is alive!")

def run_web_server():
    """Запускает HTTP-сервер в отдельном потоке"""
    port = int(os.environ.get("PORT", 10000))  # Render передаёт PORT
    app = web.Application()
    app.router.add_get("/", ping_handler)
    app.router.add_get("/health", ping_handler)
    web.run_app(app, host="0.0.0.0", port=port, access_log=None)

# Запускаем веб-сервер в фоне
threading.Thread(target=run_web_server, daemon=True).start()
print(f"🌐 Веб-сервер запущен на порту {os.environ.get('PORT', 10000)}")

# ===============================
# 🤖 Telegram-бот
# ===============================
STYLES = {
    "anime": "anime style, big sparkling eyes, soft pastel background, fantasy, 8k, masterpiece",
    "cyberpunk": "cyberpunk style, neon lighting, futuristic city background, glowing eyes, sci-fi, cinematic",
    "premium": "professional portrait photography, soft golden hour lighting, shallow depth of field, elegant, high detail skin",
    "christmas": "festive christmas style, warm golden lights, soft bokeh, elegant holiday dress, cozy atmosphere"
}

@router.message(Command("start"))
async def send_welcome(message: Message):
    await message.answer(
        "📸 Привет! Отправь мне своё фото — и я создам уникальную аватарку с помощью FaceID!\n\n"
        "Доступные стили: аниме, киберпанк, премиум, рождественский.\n"
        "Полная версия (4K) доступна после генерации."
    )

@router.message(F.content_type == ContentType.PHOTO)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    await message.reply("🔄 Обрабатываю твоё фото с FaceID... (~15 секунд)")

    # Скачиваем фото
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        await bot.download_file(file_info.file_path, tmp.name)
        image_path = tmp.name

    try:
        # Генерация через Replicate (IP-Adapter FaceID)
        output = replicate.run(
            "tencentarc/ip-adapter-faceid-sdxl:ef4d7631a8a27a7e1b83a7a04d3f6a9a5d4b2b1a0c3a8a7a04d3f6a9a5d4b2b1",
            input={
                "image": open(image_path, "rb"),
                "prompt": STYLES["anime"],
                "negative_prompt": "blurry, distorted face, extra fingers, bad anatomy, low quality, text, watermark",
                "num_outputs": 1,
                "guidance_scale": 7.5,
                "num_inference_steps": 30,
                "scheduler": "K_EULER"
            }
        )

        if output and isinstance(output, list):
            await message.answer_photo(
                photo=URLInputFile(output[0]),
                caption="✨ Твой FaceID-аватар готов!\n\n⚠️ Это preview. Полная 4K-версия без водяного знака доступна после оплаты."
            )
        else:
            await message.reply("❌ Не удалось сгенерировать. Попробуй чёткое фото анфас.")

    except Exception as e:
        print(f"Ошибка генерации: {e}")
        await message.reply("⚠️ Ошибка сервера. Попробуй позже.")

    finally:
        # Удаляем фото (важно для конфиденциальности!)
        if os.path.exists(image_path):
            os.remove(image_path)

# Подключаем обработчики
dp.include_router(router)

# Запуск Telegram-бота
async def main():
    print("🤖 Telegram-бот запущен и готов принимать фото!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
