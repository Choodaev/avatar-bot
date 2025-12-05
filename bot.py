import os
import tempfile
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ContentType, URLInputFile
from aiogram.filters import Command
import replicate

# Загружаем переменные окружения из .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REPLICATE_TOKEN = os.getenv("REPLICATE_API_TOKEN")

# Проверка наличия токенов
if not TELEGRAM_TOKEN:
    raise ValueError("❌ Не задан TELEGRAM_BOT_TOKEN в файле .env")
if not REPLICATE_TOKEN:
    raise ValueError("❌ Не задан REPLICATE_API_TOKEN в файле .env")

# Инициализация бота и диспетчера
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()

# Устанавливаем токен для Replicate
os.environ["REPLICATE_API_TOKEN"] = REPLICATE_TOKEN

# Стили для генерации (можно расширять)
STYLES = {
    "anime": "anime style, big sparkling eyes, soft pastel background, fantasy, 8k, masterpiece, best quality",
    "cyberpunk": "cyberpunk style, neon lighting, futuristic city background, glowing eyes, sci-fi, cinematic, detailed",
    "premium": "professional portrait photography, soft golden hour lighting, shallow depth of field, elegant, high detail skin, 85mm lens",
    "christmas": "festive christmas style, warm golden lights, soft bokeh, elegant holiday dress, cozy atmosphere, cinematic, premium"
}

@router.message(Command("start"))
async def send_welcome(message: Message):
    await message.answer(
        "📸 Привет! Отправь мне своё фото — и я создам уникальную аватарку с помощью нейросети!\n\n"
        "Я использую технологию FaceID, чтобы сохранить твои черты даже в аниме или киберпанке.\n\n"
        "После генерации ты увидишь preview. Полная версия (4K, без водяного знака) доступна за символическую плату."
    )

@router.message(F.content_type == ContentType.PHOTO)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    await message.reply("🔄 Обрабатываю твоё фото с FaceID... (~15 секунд)")

    # Получаем самую большую версию фото
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    file_path = file_info.file_path

    # Сохраняем во временный файл
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_file:
        await bot.download_file(file_path, tmp_file.name)
        image_path = tmp_file.name

    try:
        # Запускаем IP-Adapter FaceID + SDXL
        output = replicate.run(
            "tencentarc/ip-adapter-faceid-sdxl:ef4d7631a8a27a7e1b83a7a04d3f6a9a5d4b2b1a0c3a8a7a04d3f6a9a5d4b2b1",
            input={
                "image": open(image_path, "rb"),
                "prompt": STYLES["anime"],  # Можно менять на другой стиль
                "negative_prompt": "blurry, distorted face, extra fingers, bad anatomy, low quality, text, watermark, ugly",
                "num_outputs": 1,
                "guidance_scale": 7.5,
                "num_inference_steps": 30,
                "scheduler": "K_EULER"
            }
        )

        # Отправляем результат
        if output and isinstance(output, list):
            image_url = output[0]
            await message.answer_photo(
                photo=URLInputFile(image_url),
                caption="✨ Твой FaceID-аватар готов!\n\n⚠️ Это preview. Чтобы получить 4K без водяного знака — оплати 49 ₽ (скоро добавим кнопку 💳)."
            )
        else:
            await message.reply("❌ Не удалось сгенерировать изображение. Попробуй чёткое фото анфас.")

    except Exception as e:
        print(f"Ошибка при генерации: {e}")
        await message.reply("⚠️ Серверная ошибка. Попробуй позже или отправь другое фото.")

    finally:
        # Удаляем фото сразу после обработки (важно для конфиденциальности!)
        if os.path.exists(image_path):
            os.remove(image_path)

# Подключаем роутер
dp.include_router(router)

# Запуск бота
async def main():
    print("✅ FaceID-бот запущен и готов принимать фото!")
    print("Нажмите Ctrl+C для остановки.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
