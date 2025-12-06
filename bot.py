import os
import tempfile
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, ContentType, URLInputFile,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import replicate

# Загрузка переменных окружения
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

# Состояния FSM
class UserFlow(StatesGroup):
    awaiting_consent = State()
    awaiting_photo = State()
    awaiting_style = State()

# Стили генерации
STYLES = {
    "new_year": "festive new year style, golden sparkles, soft glowing lights, elegant holiday outfit, cozy winter atmosphere, cinematic, 8k",
    "ornament": "Ultra-realistic Christmas tree ornament: take the face from the uploaded photo and transform it into a small, handcrafted holiday figurine. Preserve exact facial likeness to the uploaded image—even if the source is just a portrait. The figurine is full-body, dressed in cozy, festive knitted attire and matching footwear, styled for the holidays. The miniature is seamlessly scaled up to a lifelike full-size representation while maintaining structural and textural integrity. Highly detailed fabric folds, fine stitching, tiny accessories, and a mix of glossy polymer surfaces with hand-painted matte textures. Include subtle imperfections for authenticity, realistic skin rendering, accurate proportions, and zero distortion. The full-body ornament hangs from a delicate golden thread, suspended among natural green pine branches, with a warm, golden holiday bokeh in the background. Atmosphere: cozy, festive, and intimate. Lighting: soft, warm, diffused, with gentle reflections. Style: premium handcrafted aesthetic, cinematic shallow depth of field.",
    "premium": "professional portrait photography, soft golden hour lighting, shallow depth of field, elegant, high detail skin, 85mm lens",
    "photo_studio": "clean photo studio portrait, neutral seamless background, professional lighting, natural skin tones, sharp focus, modern headshot style",
    "cyberpunk": "cyberpunk style, neon city lights, futuristic outfit, glowing eyes, rain-soaked streets, sci-fi cinematic, detailed"
}

# Подписи для кнопок
STYLE_TITLES = {
    "new_year": "✨ Новогодний",
    "ornament": "🎄 Елочная игрушка",
    "premium": "💎 Премиум",
    "photo_studio": "📸 Фотостудия",
    "cyberpunk": "🕶️ Киберпанк"
}

# Команда /start
@router.message(Command("start"))
async def send_welcome(message: Message, state: FSMContext):
    await state.set_state(UserFlow.awaiting_consent)
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

# Обработка согласия
@router.message(UserFlow.awaiting_consent, F.text == "Принимаю")
async def consent_accepted(message: Message, state: FSMContext):
    await state.set_state(UserFlow.awaiting_photo)
    await message.answer(
        "✅ Спасибо за доверие!\n\n"
        "Теперь отправь мне своё фото — и я создам стильную аватарку."
    )

@router.message(UserFlow.awaiting_consent)
async def consent_not_given(message: Message):
    await message.answer("Пожалуйста, нажми «Принимаю», чтобы продолжить.")

# Обработка фото
@router.message(UserFlow.awaiting_photo, F.content_type == ContentType.PHOTO)
async def handle_photo(message: Message, state: FSMContext):
    # Сохраняем фото временно
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        await bot.download_file(file_info.file_path, tmp.name)
        image_path = tmp.name

    # Сохраняем путь в состоянии
    await state.update_data(image_path=image_path)
    await state.set_state(UserFlow.awaiting_style)

    # Кнопки выбора стиля
    buttons = [
        [KeyboardButton(text=STYLE_TITLES["new_year"])],
        [KeyboardButton(text=STYLE_TITLES["ornament"])],
        [KeyboardButton(text=STYLE_TITLES["premium"])],
        [KeyboardButton(text=STYLE_TITLES["photo_studio"])],
        [KeyboardButton(text=STYLE_TITLES["cyberpunk"])]
    ]
    await message.answer(
        "Выбери стиль аватарки:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=buttons,
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

@router.message(UserFlow.awaiting_photo)
async def not_a_photo(message: Message):
    await message.answer("Пожалуйста, отправь именно фото (не файл, не текст).")

# Обработка выбора стиля
@router.message(UserFlow.awaiting_style)
async def handle_style_choice(message: Message, state: FSMContext):
    text = message.text
    style_key = None

    # Определяем ключ стиля по тексту кнопки
    for key, title in STYLE_TITLES.items():
        if title == text:
            style_key = key
            break

    if not style_key:
        await message.answer("Пожалуйста, выбери стиль из списка.")
        return

    # Получаем путь к фото
    user_data = await state.get_data()
    image_path = user_data.get("image_path")

    if not image_path or not os.path.exists(image_path):
        await message.answer("Фото утеряно. Пожалуйста, отправь его заново.")
        await state.set_state(UserFlow.awaiting_photo)
        return

    await message.reply("🔄 Генерирую аватарку... (~15 секунд)")

    try:
        output = replicate.run(
            "tencentarc/ip-adapter-faceid-sdxl:ef4d7631a8a27a7e1b83a7a04d3f6a9a5d4b2b1a0c3a8a7a04d3f6a9a5d4b2b1",
            input={
                "image": open(image_path, "rb"),
                "prompt": STYLES[style_key],
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
            await message.reply("❌ Не удалось сгенерировать. Попробуй другое фото.")

    except Exception as e:
        print(f"Ошибка генерации: {e}")
        await message.reply("⚠️ Ошибка сервера. Попробуй позже.")

    finally:
        # Удаляем фото
        if os.path.exists(image_path):
            os.remove(image_path)
        # Сбрасываем состояние — можно начать заново
        await state.clear()
        await message.answer("Хочешь создать ещё одну аватарку? Просто отправь новое фото!")

# Обработка остальных сообщений (если пользователь вне потока)
@router.message()
async def fallback(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Начни с команды /start")
    elif "awaiting_photo" in current_state:
        await message.answer("Пожалуйста, отправь фото.")
    elif "awaiting_style" in current_state:
        await message.answer("Пожалуйста, выбери стиль из списка.")

# Запуск бота
dp.include_router(router)

async def main():
    print("🤖 Telegram-бот запущен и готов принимать фото!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
