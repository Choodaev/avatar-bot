import os
import tempfile
import asyncio
import threading
from dotenv import load_dotenv
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ContentType, URLInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import replicate

# Загружаем переменные окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REPLICATE_TOKEN = os.getenv("REPLICATE_API_TOKEN")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ Не задан TELEGRAM_BOT_TOKEN в .env")
if not REPLICATE_TOKEN:
    raise ValueError("❌ Не задан REPLICATE_API_TOKEN в .env")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()
os.environ["REPLICATE_API_TOKEN"] = REPLICATE_TOKEN

# Состояние согласия
class UserDataAgreement(StatesGroup):
    awaiting_consent = State()

# ===============================
# 🔌 Веб-сервер для Render (health check)
# ===============================
async def ping_handler(request):
    return web.Response(text="✅ Bot is alive!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app = web.Application()
    app.router.add_get("/", ping_handler)
    app.router.add_get("/health", ping_handler)
    web.run_app(app, host="0.0.0.0", port=port, access_log=None)

threading.Thread(target=run_web_server, daemon=True).start()
print(f"🌐 Веб-сервер запущен на порту {os.environ.get('PORT', 10000)}")

# ===============================
# 🎨 Стили аватарок
# ===============================
STYLES = {
    "new_year": "festive new year style, golden sparkles, soft glowing lights, elegant holiday outfit, cozy winter atmosphere, cinematic, 8k",
    "premium": "professional portrait photography, soft golden hour lighting, shallow depth of field, elegant, high detail skin, 85mm lens",
    "photo_studio": "clean photo studio portrait, neutral seamless background, professional lighting, natural skin tones, sharp focus, modern headshot style",
    "cyberpunk": "cyberpunk style, neon city lights, futuristic outfit, glowing eyes, rain-soaked streets, sci-fi cinematic, detailed"
}

# ===============================
# 🤖 Обработчики Telegram
# ===============================
@router.message(Command("start"))
async def send_welcome(message: Message, state: FSMContext):
    await state.set_state(UserDataAgreement.awaiting_consent)
    await message.answer(
        "📸 Привет! Чтобы создать аватарку, мне нужно обработать твоё фото.\n\n"
        "⚠️ *Важно*:\n"
        "— Я использую твоё фото только для генерации аватарки\n"
        "— Фото удаляется сразу после обработки\n"
        "— Изображение временно передаётся в нейросеть (Replicate) для обработки\n"
        "— Сгенерированный аватар предназначен для личного использования\n\n"
        "Нажми «Принимаю» ниже, чтобы продолжить (а также согласен с "
        "[Согласием на обработку персональных данных и Политикой конфиденциальности]"
        "(https://telegra.ph/Politika-konfidencialnosti-12-06-68)):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Принимаю")]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

@router.message(UserDataAgreement.awaiting_consent, F.text == "Принимаю")
async def consent_accepted(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "✅ Спасибо за доверие!\n\n"
        "Теперь отправь мне своё фото — и я создам стильную аватарку.\n\n"
        "Доступные стили:\n✨ Новогодний\n💎 Премиум\n📸 Фотостудия\n🕶️ Киберпанк"
    )

@router.message(UserDataAgreement.awaiting_consent)
async def consent_not_given(message: Message):
    await message.answer(
        "Пожалуйста, нажми «Принимаю», чтобы я мог обработать твоё фото."
    )

@router.message(F.content_type == ContentType.PHOTO)
async def handle_photo(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == UserDataAgreement.awaiting_consent.state:
        await message.reply("Сначала нажми «Принимаю» в меню!")
        return

    user_id = message.from_user.id
    await message.reply("🔄 Обрабатываю твоё фото с FaceID... (~15 секунд)")

    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        await bot.download_file(file_info.file_path, tmp.name)
        image_path = tmp.name

    try:
        output = replicate.run(
            "tencentarc/ip-adapter-faceid-sdxl:ef4d7631a8a27a7e1b83a7a04d3f6a9a5d4b2b1a0c3a8a7a04d3f6a9a5d4b2b1",
            input={
                "image": open(image_path, "rb"),
                "prompt": STYLES["new_year"],
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
                caption="✨ Твой аватар готов!\n\n⚠️ Это preview. Полная 4K-версия без водяного знака доступна после оплаты."
            )
        else:
            await message.reply("❌ Не удалось сгенерировать. Попробуй чёткое фото анфас.")

    except Exception as e:
        print(f"Ошибка генерации: {e}")
        await message.reply("⚠️ Ошибка сервера. Попробуй позже.")

    finally:
        if os.path.exists(image_path):
            os.remove(image_path)

dp.include_router(router)

async def main():
    print("🤖 Telegram-бот запущен и готов принимать фото!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
