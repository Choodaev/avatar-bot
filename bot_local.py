import compat_patch
import os
import tempfile
import asyncio
import json
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, ContentType, URLInputFile, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, CallbackQuery
)
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types.pre_checkout_query import PreCheckoutQuery
from PIL import Image, ImageDraw, ImageFont
import torch
from diffusers import StableDiffusionXLPipeline

# === КОНФИГУРАЦИЯ ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ Не задан TELEGRAM_BOT_TOKEN в .env")

# Пакеты
PACKETS = {
    "base": {"label": "Базовый (5 генераций)", "price": 4900, "generations": 5},
    "standard": {"label": "Стандарт (20 генераций)", "price": 19900, "generations": 20},
    "premium": {"label": "Премиум (50 генераций)", "price": 29900, "generations": 50}
}

# Файлы
ANALYTICS_FILE = "analytics.json"
BALANCE_FILE = "user_balances.json"

# === ИНИЦИАЛИЗАЦИЯ ===
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()
pipe = None

# === АНАЛИТИКА ===
def log_generation(style: str, substyle: str, success: bool = True):
    try:
        try:
            with open(ANALYTICS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"total": 0, "styles": {}}

        data["total"] += 1
        if style not in data["styles"]:
            data["styles"][style] = {"total": 0, "substyles": {}}
        data["styles"][style]["total"] += 1
        if substyle not in data["styles"][style]["substyles"]:
            data["styles"][style]["substyles"][substyle] = 0
        data["styles"][style]["substyles"][substyle] += 1

        with open(ANALYTICS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"📊 Аналитика: {style} / {substyle} → {'✓' if success else '✗'}")
    except Exception as e:
        print(f"⚠️ Ошибка аналитики: {e}")

# === БАЛАНС ===
async def get_user_balance(user_id: int) -> int:
    try:
        with open(BALANCE_FILE, "r") as f:
            balances = json.load(f)
        return balances.get(str(user_id), 0)
    except:
        return 0

async def update_user_balance(user_id: int, delta: int):
    try:
        with open(BALANCE_FILE, "r") as f:
            balances = json.load(f)
    except:
        balances = {}
    balances[str(user_id)] = balances.get(str(user_id), 0) + delta
    with open(BALANCE_FILE, "w") as f:
        json.dump(balances, f)

# === ВОДЯНОЙ ЗНАК ===
def add_watermark(image_path: str) -> str:
    image = Image.open(image_path).convert("RGB")
    image.thumbnail((1280, 720), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
    except:
        font = ImageFont.load_default()
    text = "PREVIEW @lumifyaibot"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = image.width - text_width - 20
    y = image.height - text_height - 20
    draw.rectangle([x-5, y-5, x+text_width+5, y+text_height+5], fill=(0, 0, 0, 128))
    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    preview_path = tempfile.mktemp(suffix=".jpg")
    image.save(preview_path, "JPEG", quality=85)
    return preview_path

# === МОДЕЛЬ ===
async def load_model():
    global pipe
    if pipe is not None:
        return
    print("🔄 Загружаем модель SDXL + IP-Adapter...")
    try:
        pipe = StableDiffusionXLPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0",
            torch_dtype=torch.float32,
            use_safetensors=True
        ).to("cpu")
        pipe.load_ip_adapter(
            "h94/IP-Adapter",
            subfolder="sdxl",
            weight_name="ip-adapter_sdxl.bin"
        )
        pipe.set_ip_adapter_scale(0.7)
        print("✅ Модель загружена!")
    except Exception as e:
        print(f"❌ Ошибка загрузки модели: {e}")
        raise

# === FSM ===
class UserFlow(StatesGroup):
    awaiting_consent = State()
    awaiting_photo = State()
    awaiting_main_style = State()
    awaiting_substyle = State()

# === СТИЛИ ===
MAIN_STYLES = {
    "new_year": "✨ Новогодний",
    "ornament": "🎄 Елочная игрушка",
    "premium": "💎 Премиум",
    "photo_studio": "📸 Фотостудия",
    "cyberpunk": "🕶️ Киберпанк",
    "female_portrait": "👩‍🦰 Женский портрет",
    "male_portrait": "👨‍🦰 Мужской портрет",
    "studio": "📸 Студийное"
}

SUBSTYLES = {
    "new_year": {
        "snow": "winter snowy background, soft falling snowflakes, warm scarf, cozy atmosphere, festive lights, cinematic",
        "tree": "standing next to a decorated christmas tree, golden ornaments, warm bokeh, joyful expression, holiday sweater",
        "fireplace": "relaxing by a cozy fireplace, warm golden light, christmas stockings, soft shadows, intimate mood",
        "outdoor_snow": "Hyper-realistic 8K editorial frame. Nikon D5600, crisp winter color grading with cold blue-grays, high clarity, sharp textures. The model’s facial features must remain 100% identical to the uploaded photo. The model stands among frosted pine branches in a thick brown shearling jacket, red gloves catching snow. Emotion: calm, slightly curious expression. Atmosphere: dense frosty forest, heavy snow on branches. Light: overcast diffused daylight, realistic cold shadows. Medium shot, cinematic depth, visible cold air particles.",
        "sparkler": "Hyper-realistic 8K editorial frame. Shot on Nikon D5600 with the same warm festive reference color palette: glowing golden lights, soft cinematic contrast, cozy winter ambiance. The subject (do not alter any facial features, preserve 100%) stands in front of a Christmas-decorated entrance, holding a sparkler while gazing upward with a sense of wonder, dreamy expression, slight smile, soft relaxed eyebrows. Medium shot from slightly below eye level for cinematic uplift. Lighting: warm reflections from fairy lights illuminating cheeks, cool ambient shadows on sides, true-to-life skin texture with fine pores and subtle winter-redness. Outfit: fluffy cream sherpa jacket, knit beanie; detailed fabric realism. Snow-like sparkles of light reflecting on clothing. Background: Christmas tree branches, red bows, ornaments, dense bokeh. Atmosphere: magical, story-like holiday moment.",
        "sparkler_tree": "Hyper-realistic 8K editorial frame. Shot on Nikon D5600 with identical soft-warm Christmas grading. The subject (maintain all real facial features exactly) stands in semi-profile, head turned slightly toward the camera, soft smile, thoughtful festive mood. Holding a sparkler near the chest. Side lighting from warm fairy lights creates dramatic warm highlights along the cheekbone and hairline. Outfit: sherpa coat with visible detailed wool fibers, beanie with knitted texture. Skin: natural pores, realistic winter glow. Background: dense Christmas garland with red ornaments, warm twinkling lights creating cinematic rim light around the subject. Atmosphere: romantic winter holiday moment, slight snow fall effect optional.",
        "winter_portrait": "Hyper-realistic 8K editorial frame, Nikon D5600, do not change facial features even 1%, use the exact face from the uploaded photo; medium portrait of a man in a winter studio setup with falling snow; outfit: white knit sweater, red winter pants, white winter boots; emotion: confident calm gaze into the distance; lighting: soft cinematic key light + cold rim-light; textures: hyper-detailed knit fabric, realistic snow particles, soft fur fibers.",
        "snowflake_portrait": "Hyper-realistic 8K editorial frame, Nikon D5600, do not change facial close-up portrait, winter studio fashion aesthetic, soft falling snow; structured winter knit, minimalist high-fashion silhouette; emotion: confident masculine gaze; lighting: sharp fashion light with cold textures: clean knit weave, realistic skin texture, cold sparkle in features even outfit: white calm luxury, edges; snow.",
        "christmas_market": "Stylize the uploaded selfie into a cinematic night film still. The shot is framed slightly wider — I’m walking through a snowy Christmas market street, visible in full motion, as if caught in a spontaneous moment. The camera captures me in profile, mid-step, with a direct, fleeting glance into the camera — like I just noticed being photographed. I hold a Christmas Starbucks cup in the hand closest to the camera, the other arm moving naturally. I wear a long beige wool coat that reaches below the knees, a thick knitted scarf, and no headwear — my hair moves slightly in the cold air. A dense snowfall fills the air with large visible flakes, creating motion and depth, while the background — kiosks, lights, and people — appears softly blurred. Reflections shimmer on the wet pavement; cool blue night tones mix with warm amber light for strong contrast. Shot with a cinematic film tone — handheld motion blur, soft haze diffusion, film grain, and warm/cool color palette evoking the 90s night-movie aesthetic. The atmosphere is moody, vivid, and alive — a moment frozen between motion and emotion. Keep my original face, proportions, hairstyle, and expression exactly as in the selfie — no alteration or beautification.",
        "ny_90s_style1": "Use uploaded photo as strict facial reference, do not alter face even by 1%. A 1990s Soviet apartment, warm tungsten lighting, shadows from tinsel on the walls, vintage patterned carpet behind. Person sits at the New Year dinner table, oversized fluffy cream sweater, Soviet faux-fur hat and Soviet gold tinsel around the neck. Rests head on one hand, holding a slice of bread with red caviar in the other, with a bored, iconic 90s melancholy expression. Real spruce tree with glass ornaments and foil rain behind. Realistic fabric textures, cinematic contrast. Shot as a 1997 point-and-shoot camera, soft retro lens, Kodak 400 film look, gentle grain, subtle vignette, built-in flash glare. Keep original face from uploaded photo unchanged.",
        "ny_900s_style2": "Use uploaded photo as strict facial reference, do not alter face even by 1%. A 1990s Soviet apartment, warm tungsten lighting, shadows from tinsel on the walls. Person at a Soviet New Year table, leaning forward playfully, holding a champagne glass with a cheeky smile. Tinsel garlands drape over the lamp, authentic Soviet food: mandarins in mesh bag, 'Сухарики', herring salad. Warm tungsten mood, deep 90s shadows. Outfit: oversized fluffy cream sweater, Soviet faux-fur hat. Realistic fabric weave texture. Shot as 1997 compact camera, direct flash, washed-out whites, soft retro lens. Keep original face from uploaded photo unchanged."
    },
    "ornament": {
        "classic": "classic red and gold christmas ornament, intricate hand-painted details, hanging on pine branches",
        "angel": "angel-themed ornament, delicate wings, soft glow, iridescent finish, suspended by golden thread",
        "snowman": "festive snowman ornament, carrot nose, scarf, top hat, glossy polymer texture, holiday cheer"
    },
    "premium": {
        "golden_hour": "golden hour lighting, soft bokeh, warm tones, elegant pose, shallow depth of field",
        "monochrome": "black and white portrait, high contrast, dramatic lighting, timeless elegance, film grain",
        "urban": "city rooftop background, modern outfit, wind-blown hair, dynamic composition, golden sunset",
        "cinematic_neon": "Use the user's appearance 1:1 — face, skin, hair, and body without any changes. Realistic portrait in Wong Kar-wai style, depicting the subject sitting in an old car, wearing a black button-up shirt. The subject’s head is slightly turned, gazing through a rain-streaked window. The camera is positioned inside the car, shooting the subject through the front passenger window. Outside, neon red and green street lights streak and blur, casting reflections and deep shadows across the subject’s face, causing skin tones to shift with the lighting. Emphasize the sharp jawline and neck contour. The image features high-contrast red-green color grading, heavy film grain, strong motion blur on external lights, and glowing halation around light sources. Atmosphere: urban solitude, loneliness, and unanswered questions in a vast city. Do not change the user's face — preserve exact facial features, expression, and proportions from the uploaded photo."
    },
    "photo_studio": {
        "white": "pure white seamless background, professional lighting, natural expression, corporate headshot",
        "grey": "neutral grey background, soft shadows, modern business look, crisp focus",
        "gradient": "subtle blue-to-white gradient background, clean aesthetic, professional portrait"
    },
    "cyberpunk": {
        "neon_rain": "neon-lit rainy street, reflective puddles, glowing tattoos, futuristic jacket, cybernetic eyes",
        "hologram": "holographic interface overlay, data streams, digital glitches, high-tech visor, night city",
        "samurai": "cyberpunk samurai, neon katana, traditional-meets-futuristic armor, cherry blossoms in rain"
    },
    "female_portrait": {
        "warm_sweater": "Hyper realistic warm portrait with simulated golden-hour sunlight. Outfit: oversized beige knit sweater with realistic wool texture. Hair: loose waves. Makeup: soft brown shadows + glossy lips. Expression: dreamy, slightly wistful. Atmosphere: nostalgia, warm evening mood. Lighting: warm directional sunlight with long shadows. Background: warm neutral studio matte. Keep original facial features from uploaded photo.",
        "sensual_portrait": "High-resolution fashion beauty. Outfit: black simple turtleneck (matte texture). Hair: sleek straight hair behind ears. Makeup: neutral matte with defined brows. Expression: serious focus. Lighting: strong side key + blue-tinted fill for cinematic drama. Atmosphere: cool-toned night mood. Keep original face from uploaded photo.",
        "tender_portrait": "Hyper-realistic portrait with gentle wind effect. Outfit: silk blouse with soft folds. Hair: loose natural waves moving with wind. Makeup: minimalist nude. Expression: strong emotional intensity. Lighting: bright fashion lighting with soft fill. Atmosphere: high-energy editorial. Keep original face from uploaded photo.",
        "denim_portrait": "Fashion portrait 3/4 turn. Outfit: light denim jacket off one shoulder. Hair: loose half-up style. Makeup: soft glam. Expression: flirty, mysterious slight smile. Lighting: diffused beauty light + rim glow. Atmosphere: soft feminine elegance. Keep original face from the uploaded photo.",
        "rock_portrait": "Ultra-realistic avant-garde portrait. Skin: crispy detail, realistic micro-shadows. Clothing: asymmetrical structured shirt with stiff folds (designer piece). Hair: slick side-parted. Expression: detached high-fashion emotionlessness. Lighting: dramatic directional light, geometric shadow shapes. Atmosphere: modern architectural studio mood. POV: close shoulder-up, slightly low angle. Use the original face from the uploaded photo.",
        "cityscape_portrait": "A woman with the face from the uploaded photo unchanged is standing on a rooftop or high terrace at night. Behind her, a large city skyline is visible; tall buildings are lit up, with windows glowing like tiny dots. The sky is overcast and cloudy, but the city lights softly illuminate both the environment and the woman’s face. She is standing sideways, looking directly at the camera. Her hair is soft, wavy, slightly blown by the wind, with only a few fine strands naturally resting on her face, while the rest of her hair stays naturally around her head. She has a subtle, sweet, and confident smile. Her eyes are half-open, looking directly at the camera, giving the photo a warm, engaging energy. The corners of her lips show a faint smile. She is wearing a thick dark red hooded hoodie. The hoodie is loose and comfortable. On the back, there is a large pattern or lettering, which stands out in white tones against the black-and-white fabric. The hood sits behind her, giving volume around her shoulders. The buildings in the background are modern and tall; the lights add a sense of nightlife, vibrancy, and movement. On the left side of the photo is a more rounded skyscraper, while on the right there are more angular, layered structures. The building lights appear slightly blurred. Her posture is slightly turned to the side, with her shoulder closer to the camera. Use the face from the photo I provided.",
        "black_panther": "Extreme close-up beauty portrait, half-face composition of a young woman with the face from the uploaded photo unchanged. Camera positioned straight-on with a slight upward bias, capturing only one eye fully visible. Model’s head slightly turned, gaze directly to the camera, intense confident look. Mouth slightly parted, relaxed but sensual expression. Smooth hairstyle with soft strands sweeping across the forehead; clean and controlled. Bold graphic winged eyeliner; dramatic eyeshadow with deep gradient; high-fashion matte contours; glossy natural-toned lips. Sharp detailing around the eye, maximum precision. Dense black fur partially covering the left side of the face and foreground, adding depth and mystery. High neckline in matte black fabric visible on the right side. Clean beauty lighting with sharp highlights on cheekbones and lips. Balanced shadows for sculpted facial structure; minimal fall-off. Perfect skin texture, soft gleam on the surface. Minimal gradient background transitioning from medium grey to darker tones, seamless and unobtrusive. Mysterious luxury, seductive elegance, editorial beauty shot. Focus on the eyes and skin perfection. Ultra-realistic glamor photography with flawless skin rendering, crisp makeup detail, and rich fur texture in the foreground.",
        "winter_car_portrait": "Use the face of a beautiful young woman from the uploaded photo unchanged. She has long, dark, wavy hair cascading over her shoulders and down her back. A cozy, intimate moment inside a modern, luxurious car with a panoramic glass roof, capturing a stunning snow-covered winter forest visible through the windows. The woman is seated in the passenger seat, turned slightly to the right, leaning back with her right elbow resting on the center console. Her right hand is now resting gently on her lap or casually by her side, not touching her head. Her expression is serene and pensive, looking out the window with softly parted lips. She is wearing an all-white, chunky cable-knit sweater and matching loose-fitting, high-waisted pants, creating a monochrome, soft texture contrast against the light grey leather car interior and a blanket covering the armrest. She is holding a light-colored, insulated travel mug in her left hand, bringing it up towards her chin. The natural light is soft, diffuse daylight, predominantly coming from the large side window and the sunroof, casting very gentle, high-key illumination with minimal shadows. The overall palette is a striking, clean monochrome of whites, light greys, and deep greens/blacks from the forest. The atmosphere is quiet, luxurious, and warmly contrasted with the cold winter outside.",
        "ski_resort": "Use the uploaded subject’s face with 100% accuracy. Do NOT change facial structure, proportions, expression, smile shape, eyes, nose, lips, jawline, or skin texture. Recreate the face exactly as in the reference — same person, same features, same harmony. No beautification or stylization of the face. Hair characteristics stay the same (texture, flow, styling), but do not alter length or color. A bright, sunny alpine ski resort at high altitude. Clear deep-blue sky with scattered thin clouds. Sharp, crisp sunlight illuminates the snow and creates clean reflections on the goggles and jacket. Surrounding mountains in the background are covered with pure white snow and subtle shadows from the peaks. The subject stands in the center of the frame, facing the camera with a confident, joyful smile. Pose: both hands slightly raised, holding the sides of the ski goggles above the eyes. Body is upright, shoulders relaxed, natural posture. Outfit: a stylish glossy white ski jumpsuit with a front zipper, fitted silhouette, and precise stitching. A fluffy dark red hood frames the head. A black belt bag with gold hardware (GG logo) sits securely around the waist. Black ski poles with straps are held in each hand. Lighting: strong direct daylight from above, casting soft natural shadows. High contrast, crisp alpine brightness. Surface snow highly detailed — visible crystals, texture, light sparkle. Color palette: clean whites, deep blues, natural skin tones, subtle warm highlights from sunlight. Mood: luxurious winter vacation, high-fashion ski aesthetic, hyper-realistic 4K clarity. Face must remain fully identical to the reference photo.",
        "ice_fairy_tale": "Кадр построен по диагонали: девушка с загруженной фотографии, лицо не изменять, стоит в полный рост среди ледяных торосов, корпус развернут в три четверти, лицо повернуто к камере через плечо. Длинный серебристый шлейф платья красиво стелется по снегу. Освещение естественное, мягкое дневное, подчёркивает блеск ткани. На женщине роскошное полупрозрачное платье бордового цвета, расшитое пайетками, кристаллами и бисером. Фактура напоминает ледяную корку: рукава длинные, облегающие, часть плеч и спины открыта. Платье идеально садится по фигуре, множество сверкающих деталей. Серьги — крупные, серебристые, инкрустированы камнями, гармонируют с общим образом. Волосы гладко зачёсаны назад, собраны в низкий пучок или хвост. Пара тонких прядей у лица добавляет естественности и подчёркивает утончённость. Ландшафт арктический: массивные ледяные глыбы и снежное покрытие создают атмосферу ледяного царства. Фон выполнен в сине-голубой гамме, подчёркивает чистоту и холод композиции. Мягкое голубое небо, лёгкие облака. Use the original face from the uploaded photo unchanged.",
        "winter_cozy": "Waist-up dynamic portrait. Use the face of the woman from the uploaded photo unchanged. Scene: cozy Nordic winter cabin, photoreal lifestyle fashion. Outfit: oversized grey chunky sweater with red bow appliqués. Composition: one arm extended toward the camera, sweater sleeve filling the foreground in close-up; the other hand holds a mug at chest level. Expression: playful, gaze directed at or slightly below the lens. Background: snowy forest visible through black window frames. Lighting: soft daylight key light from the left, reflected off a white blanket, plus soft fill light from fairy lights. Textures: highly detailed knit structure, fluffy yarn texture on the sweater, satin sheen on the bows. Camera: 50mm lens, cinematic portrait, shallow depth of field, f/2.8, ISO 200, 1/320s, 3:4 aspect ratio. Keep the original face, expression, and proportions exactly as in the uploaded photo.",
        "sunlight_glow": "Use the user's appearance 1:1 — face, skin, hair, and body without any changes. A stunning beauty portrait of a woman, captured during golden hour. Camera positioned for a head and shoulders shot, slightly low angle, showing her in profile with her head gently tilted back and eyes looking upwards. Voluminous, wavy hair with intense golden backlight creating a radiant halo effect around her head. Her skin has a luminous, healthy glow with subtle highlights on cheekbones, natural makeup with glossy lips. She is wearing a simple, elegant draped garment in soft golden satin or silk, strapless. The scene is bathed in strong, warm backlight, creating dramatic rim lighting on her hair, face outline, and shoulders, complemented by soft, warm fill light on her front features. The background is a clean, diffused warm beige or light tan. Soft focus, shallow depth of field, ethereal atmosphere, luxurious, serene, high key lighting. Keep the original face from the uploaded photo unchanged.",
        "studio_serious": "Hyper-realistic 8K fashion portrait of a woman sitting sideways on an old wooden chair, arms wrapped loosely around her torso. Sharp skin detail with natural texture, peach fuzz, realistic gloss highlights. Lighting: single dramatic spotlight cutting across her face, harsh shadows behind. Outfit: dark green vintage blouse with textured fabric folds. Expression: raw vulnerability, thoughtful, slightly sad. Atmosphere: theatrical, intimate, dusty old studio. Keep original face from uploaded photo.",
        "field_portrait": "Hyper-realistic 8K editorial image with woman portrait from uploaded photo, golden prairie at sunset, cinematic sunlight casting soft and dramatic shadows, soft ringlets framing face, warm-glow skin with subtle blush, flowy linen dress with delicate floral embroidery and realistic folds, intense dreamy gaze into distance, editorial Vogue/Bazaar femininity, cinematic fashion elegance, soft breeze moving hair. Shot on 85mm lens. Keep original face from uploaded photo unchanged.",
        "snow_heart": "Use the user's appearance 1:1 — face, skin, hair, and body without any changes. Create a bright winter mobile photo shot from inside a snowbank through a heart-shaped hole. The snow frame is soft, uneven, with gentle highlights. Low-angle upward shot. The subject stands outside the snowbank, slightly leaning toward the camera, centered in the frame. Foreground (hands, peace sign, accessories) appears larger due to perspective. Soft reflected winter light, realistic skin with subtle cold glow. The woman smiles and shows a peace sign with both hands. She wears a black coat, pink top, bright pink necklace, and black gloves. Her hair and coat are lightly dusted with snowflakes. Background: clean blue winter sky and diffused cold light. Light snow sparkle. Sharp focus in the center and soft blur on the edges of the snow frame enhance the effect of shooting through a 'hole'. Style: realistic, fresh, atmospheric, like a trendy candid mobile photo. Do not change the user's face — preserve exact facial features, expression, and proportions from the uploaded photo.",
        "winter_glamour": "Use the user's appearance 1:1 — face, skin, hair, and body without any changes. Close-up portrait of a woman, face turned sideways, eyes closed, expression calm and sensual. She has long wavy hair and glowing soft makeup. She wears a luxurious white fluffy faux fur cape with long pile, elegantly draped off her shoulders. One hand is slightly visible, holding the fur, with dark nail polish. Background: dark festive bokeh with blurred golden lights and subtle white-silver Christmas tree elements. Light snowfall creates a magical winter atmosphere. Lighting: soft studio lighting with a pinpoint silver highlight illuminating the face, creating beautiful reflections and soft shadows. Overall style: winter glamour and elegant fashion photography with shallow depth of field, sharp focus on the subject, and smooth, realistic photo quality. Keep original face from uploaded photo unchanged."
    },
    "male_portrait": {
        "sweater_portrait": "Hyper realistic fashion beauty portrait. Skin: natural matte depth, soft micro-texture. Clothing: oversized beige cashmere sweater (luxury knit texture visible). Hair: soft brushed-back waves. Expression: gentle fashion melancholy. Lighting: soft cinematic light, warm creamy highlights. Atmosphere: minimal luxury studio, quiet and elegant. POV: mid-close portrait with shallow DOF. Use the original face from the uploaded photo.",
        "serious_portrait": "Ultra-realistic avant-garde portrait. Skin: crispy detail, realistic micro-shadows. Clothing: asymmetrical structured shirt with stiff folds (designer piece). Hair: slick side-parted. Expression: detached high-fashion emotionlessness. Lighting: dramatic directional light, geometric shadow shapes. Atmosphere: modern architectural studio mood. POV: close shoulder-up, slightly low angle. Use the original face from the uploaded photo.",
        "funny_portrait": "Hyper realistic portrait, ultra-sharp. Skin: dynamic realistic movement lines, natural shine on cheeks. Male model in a casual hoodie with realistic cotton fleece texture. Hair: curly voluminous style. Expression: open joyful laughter, raw emotion, teeth visible. Lighting: bright soft key light, boosting vibrance. Atmosphere: alive energetic studio, sense of warmth and spontaneity. POV: eye-level, close portrait. Use the original face from the uploaded photo.",
        "street_portrait": "Use 100% face from the uploaded photo unchanged. Close-up portrait of a handsome man, wearing dark patterned open-collar shirt with top buttons undone, thin gold chain necklace, dark charcoal wool jacket with zipper slightly open, serious confident expression, soft warm sunlight from the side casting sharp shadows, standing against a tree trunk in blurred outdoor background, cinematic fashion portrait, high contrast, rich tones, photorealistic, ultra detailed, film-like texture, 8k. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "business_city": "Use 100% face from the uploaded photo unchanged. Photorealistic portrait of man from uploaded photo, wearing luxurious dark navy patterned tuxedo jacket with black satin lapels over crisp white dress shirt, thoughtful pose with hand touching chin, leaning slightly on a modern balcony railing, soft diffused natural daylight, blurred city skyline background, cinematic mood, high contrast, ultra-sharp skin details and fabric texture, 8k hyperrealistic, shot on Canon EOS R5, 85mm lens, f/1.4, shallow depth of field. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "casual_portrait": "Use 100% face from the uploaded photo unchanged. A man with a confident slight smirk, wearing an oversized beige/light taupe shacket (shirt-jacket) with flap pockets, unbuttoned, over a white or light gray crew-neck t-shirt, high-waisted cream/off-white tailored pleated trousers, clean white minimalist sneakers. He is standing in a narrow historic street in Milan, Italy, with blurred old European buildings and greenery in the background. Lighting: soft natural daylight, warm neutral tones. Style: cinematic shallow depth of field, fashion editorial photography, photorealistic, sharp details, 85mm portrait lens. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "sunset_desert": "Use 100% face from the uploaded photo unchanged. A stylish handsome man, wearing an all-black elegant suit with black shirt, standing alone in a vast desert landscape at golden hour sunset, dramatic warm sunlight behind him creating strong backlighting and rim light, cinematic atmosphere, moody and sophisticated vibe, desert dunes in the background, soft haze, high fashion editorial style, shot on 85mm lens, sharp details, cinematic color grading, luxurious and mysterious mood. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "winter_business": "Hyper-realistic winter portrait of the same man from the uploaded photo - 100% identical facial features. He sits calmly on a wooden bench or a snow-covered stone edge, holding one side of his coat near his chest with one hand while the other hand rests relaxed on his leg. A golden wristwatch is visible on his left wrist. Snowflakes gently fall around him and softly settle on his hair, cap, and coat, enhancing the cold, serene atmosphere. Behind him: small European buildings and snow-covered trees with a cinematic bokeh background. Lighting: soft, cool natural daylight highlighting snow texture and clothing details. Mood: elegant, peaceful, emotionally warm despite the winter cold. Ultra-realistic, refined, cinematic tone. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "cafe_terrace": "Use 100% face from the uploaded photo unchanged. A stylish young man sitting outdoors at a modern café terrace, relaxed pose with one leg crossed over the other, wearing a dark green velvet varsity jacket, white hoodie underneath, dark slim jeans, white sneakers, black smartwatch, sunglasses, short dark wavy hair and trimmed beard, holding a phone in one hand and reaching for a coffee takeaway cup with the other, natural daylight, stone wall and tree in the background, cinematic photography, high detail, sharp focus, 85mm lens. The photo was taken from a professional, low angle. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "motorcycle_portrait": "Use 100% face from the uploaded photo unchanged. Hyper-realistic cinematic portrait shot in a dim indoor parking garage at night. A young man sits casually on a white Ducati Panigale V2 with red rims. His expression is calm and composed. He is wearing a white and grey Nike windbreaker jacket, black pants, black riding gloves, and white Nike high-top sneakers. His hands are clasped loosely in front of him while sitting on the motorcycle seat. The lighting is dark and dramatic, with deep shadows and a single soft directional light illuminating the subject and bike. High-contrast tones, muted background, cinematic shading, and a cool color palette. The Ducati bike details (red wheels, aerodynamic fairings, bold side graphics) are clearly visible. The mood is mysterious, stylish, and urban. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "window_cafe": "Use 100% face from the uploaded photo unchanged. A photorealistic, cinematic portrait of a stylish man. He sits inside a moody café, shot from outside through a large glass window. Strong, directional sunlight illuminates his face, creating high contrast and deep shadows. The window shows subtle vertical reflections. The composition features a heavily blurred foreground. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "sunset_street": "A handsome young man from uploaded photo, walking confidently down a city street at golden hour sunset, warm cinematic lighting with strong lens flare from the low sun behind him, wearing an oversized beige/khaki jacket over a loose white t-shirt, baggy black cargo pants, and clean white sneakers, hands in pockets, serious and slightly moody expression, shallow depth of field with beautiful bokeh in the background, trees and blurred cars on the sides, professional portrait photography, highly detailed, realistic, 8k, wearing sunglasses. Use 100% face from the uploaded photo unchanged. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "contemplation": "Use 100% face from the uploaded photo unchanged. A man from uploaded photo, intense and sultry gaze directed upward toward the camera, full lips slightly parted, wearing a dark charcoal gray plaid suit jacket over a black turtleneck, low-angle dramatic portrait shot from below, golden hour sunset lighting streaming through large modern glass windows behind him, warm orange and amber cinematic backlight creating a glowing halo effect around his hair and shoulders, high-contrast moody atmosphere, soft bokeh on the background windows, ultra-realistic, photorealistic, fashion editorial style, 8k detail, shot on 85mm lens, subtle film grain. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "sky_background": "A cinematic portrait of a man from uploaded photo, wearing a varsity jacket, looking up slightly with a confident expression. The scene was captured at sunset with dramatic whitish-blue clouds filling the sky, background of cold mountains, and warm tone of sunrise radiating soft light on the face and clothes, creating a dreamy mood and atmosphere. The angle is low, making the subject look contemplative and heroic towards the wide sky, shot on Sony Alpha 7 Mark V. Use 100% face from the uploaded photo unchanged. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo.",
        "rock_portrait": "Use 100% face from the uploaded photo unchanged. Ultra-realistic cinematic portrait of uploaded man in profile view, wearing a plain black jacket. He has thick, voluminous hair. His head is slightly tilted upward, with a calm and confident expression. Lighting setup: dramatic orange spotlight glowing behind his head, creating a radiant circular aura effect, contrasted against a dark background. Do not change the face — preserve exact facial structure, expression, and proportions from the original photo."
    },
    "studio": {
        "bw_woman_black_dress": "Use subject’s face from uploaded photo. Black and white studio portrait, the woman with softly curled hair sitting gracefully on the floor, leaning on one arm while her other hand rests lightly on her waist. She wears a black silk slip dress with thin straps, her gaze calm and confident, body slightly turned, soft light highlighting the gentle shine of the silk and the texture of her curls, elegant and cinematic composition.",
        "bw_woman_black_dress_2": "Full-body black-and-white studio shot of the woman with softly curled hair standing confidently in a black silk slip dress with thin straps. One leg slightly forward, shoulders relaxed, gaze turned away from the camera. Soft spotlight highlights the fluid movement of the fabric and the shine of her curls, creating a balanced, fine art cinematic composition. Use subject’s face from uploaded photo unchanged.",
        "bw_man_suit": "Use subject’s face from uploaded photo unchanged. Black and white fine art studio portrait of a man sitting on the floor against a plain wall, black suit and unbuttoned white shirt, sleeves slightly rolled, thoughtful gaze away from the camera, natural pose, soft diffused light, emotional cinematic tone. Keep original facial features, expression, and proportions exactly as in the uploaded photo.",
        "bw_man_suit_2": "Use subject’s face from uploaded photo unchanged. Black and white low-angle studio shot of a man in a black suit and slightly unbuttoned white shirt, standing confidently with one hand in pocket, looking down toward the camera, white background, strong directional lighting from above creating elegant shadows, editorial fashion mood. Keep original facial features, expression, and proportions exactly as in the uploaded photo."
    }
}

substyle_titles = {
    # Новогодний
    "snow": "❄️ Со снегом", "tree": "🎄 У ёлки", "fireplace": "🔥 У камина",
    "outdoor_snow": "🌲 На улице со снегом", "sparkler": "🎇 С бенгальским огнем",
    "sparkler_tree": "🎄 С бенгальским огнем у ёлки", "winter_portrait": "❄️ Зимний портрет",
    "snowflake_portrait": "❄️ Портрет со снежинками", "christmas_market": "🎁 Новогодняя ярмарка",
    "ny_90s_style1": "🪩 Новый год 90-х, стиль 1", "ny_900s_style2": "🪩 Новый год 90-х, стиль 2",
    # Елочная игрушка
    "classic": "🪵 Классическая", "angel": "👼 Ангел", "snowman": "⛄ Снеговик",
    # Премиум
    "golden_hour": "🌅 Золотой час", "monochrome": "🖤 Монохром", "urban": "🏙️ Урбан",
    "cinematic_neon": "🎞️ Киношный неон",
    # Фотостудия
    "white": "⬜ Белый фон", "grey": "⏺️ Серый фон", "gradient": "🔽 Градиент",
    # Киберпанк
    "neon_rain": "🌧️ Неон в дожде", "hologram": "🌀 Голограмма", "samurai": "⚔️ Самурай",
    # Женский портрет
    "warm_sweater": "🧶 Теплый портрет в свитере", "sensual_portrait": "🖤 Чувственный портрет",
    "tender_portrait": "✨ Нежный портрет", "denim_portrait": "👖 Джинсовый портрет",
    "rock_portrait": "🎸 Рок-портрет", "cityscape_portrait": "🌆 Мегаполис",
    "black_panther": "🗝️ Черная пантера", "winter_car_portrait": "🚙 Зимой в дорогой машине",
    "ski_resort": "⛷️ Горнолыжная трасса", "ice_fairy_tale": "🧊 Ледяная сказка",
    "winter_cozy": "🧦 Теплая зима", "sunlight_glow": "☀️ В лучах солнца",
    "studio_serious": "🪑 Серьёзный в студии", "field_portrait": "🌼 В поле",
    "snow_heart": "🤍 Снежное сердце", "winter_glamour": "🎇 Зимний гламур",
    # Мужской портрет
    "sweater_portrait": "🧶 Портрет в свитере", "serious_portrait": "🙎‍♂️ Серьёзный портрет",
    "funny_portrait": "😁 Забавный портрет", "street_portrait": "🧥 Уличный портрет",
    "business_city": "🏙️ Деловой портрет в мегаполисе", "casual_portrait": "👟 Кэжуал",
    "sunset_desert": "🌅 Закат в пустыне", "winter_business": "❄️ Зимний деловой портрет",
    "cafe_terrace": "☕️ Уличная кофейня", "motorcycle_portrait": "🏍️ На мотоцикле",
    "window_cafe": "🪟 В окне ресторана", "sunset_street": "🌇 В лучах солнца",
    "contemplation": "✊ Размышление", "sky_background": "🌫️ На фоне неба",
    "rock_portrait": "🎸 Рок-портрет",
    # Студийное
    "bw_woman_black_dress": "⚫️ Ч/б женский в черном платье",
    "bw_woman_black_dress_2": "⚫️ Ч/б женский в черном платье 2",
    "bw_man_suit": "⚫️ Ч/б мужской в строгом костюме",
    "bw_man_suit_2": "⚫️ Ч/б мужской в строгом костюме 2"
}

# === ОБРАБОТЧИКИ ===
@router.message(Command("start"))
async def send_welcome(message: Message, state: FSMContext):
    await state.set_state(UserFlow.awaiting_consent)
    await message.answer(
        "📸 Привет! Загрузи фото — создам стильную аватарку!\n\n"
        "⚠️ Я использую твоё фото только для генерации и удаляю его сразу после обработки.\n\n"
        "Нажми «Принимаю», чтобы продолжить (согласен с "
        "[Политикой конфиденциальности](https://telegra.ph/Politika-konfidencialnosti-12-06-68)):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Принимаю")]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

@router.message(UserFlow.awaiting_consent, F.text == "Принимаю")
async def consent_accepted(message: Message, state: FSMContext):
    await state.set_state(UserFlow.awaiting_photo)
    await message.answer("✅ Отлично! Отправь мне своё фото.")

@router.message(UserFlow.awaiting_consent)
async def consent_not_given(message: Message):
    await message.answer("Пожалуйста, нажми «Принимаю», чтобы продолжить.")

@router.message(UserFlow.awaiting_photo, F.content_type == ContentType.PHOTO)
async def handle_photo(message: Message, state: FSMContext):
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        await bot.download_file(file_info.file_path, tmp.name)
        image_path = tmp.name
    await state.update_data(image_path=image_path)
    await state.set_state(UserFlow.awaiting_main_style)
    buttons = [[KeyboardButton(text=title)] for title in MAIN_STYLES.values()]
    await message.answer("Выбери основной стиль:", reply_markup=ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True))

@router.message(UserFlow.awaiting_main_style)
async def handle_main_style(message: Message, state: FSMContext):
    main_style_key = None
    for key, title in MAIN_STYLES.items():
        if title == message.text:
            main_style_key = key
            break
    if not main_style_key or main_style_key not in SUBSTYLES:
        await message.answer("Пожалуйста, выбери стиль из списка.")
        return
    await state.update_data(main_style=main_style_key)
    await state.set_state(UserFlow.awaiting_substyle)
    substyles = SUBSTYLES[main_style_key]
    buttons = [[KeyboardButton(text=substyle_titles.get(k, k))] for k in substyles.keys()]
    await message.answer("Выбери вариант:", reply_markup=ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True))

@router.message(UserFlow.awaiting_substyle)
async def handle_substyle(message: Message, state: FSMContext):
    user_data = await state.get_data()
    main_style = user_data.get("main_style")
    image_path = user_data.get("image_path")
    if not main_style or not image_path or not os.path.exists(image_path):
        await message.answer("Ошибка. Начни сначала: /start")
        await state.clear()
        return
    substyle_key = None
    for key, title in substyle_titles.items():
        if title == message.text and key in SUBSTYLES.get(main_style, {}):
            substyle_key = key
            break
    if not substyle_key:
        await message.answer("Выбери вариант из списка.")
        return

    log_generation(main_style, substyle_key, success=False)
    prompt = SUBSTYLES[main_style][substyle_key]
    await message.reply("🔄 Генерирую... (~45 сек)")

    try:
        await load_model()
        output = pipe(
            prompt=prompt,
            ip_adapter_image=Image.open(image_path),
            negative_prompt="blurry, distorted face, extra fingers, bad anatomy, low quality, text, watermark",
            num_inference_steps=30,
            guidance_scale=7.5
        ).images[0]
        
        output_path = tempfile.mktemp(suffix=".jpg")
        output.save(output_path)
        
        user_id = message.from_user.id
        balance = await get_user_balance(user_id)
        
        if balance > 0:
            await message.answer_photo(photo=URLInputFile(output_path), caption="✨ Оригинал в 4K!")
            await update_user_balance(user_id, balance - 1)
            log_generation(main_style, substyle_key, success=True)
        else:
            preview_path = add_watermark(output_path)
            await message.answer_photo(
                photo=FSInputFile(preview_path),
                caption="🖼️ Это превью. Купи пакет, чтобы получить 4K без водяного знака!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Купить пакет", callback_data="show_payment")]
                ])
            )
            os.remove(preview_path)
            log_generation(main_style, substyle_key, success=False)
            
    except Exception as e:
        print(f"Ошибка генерации: {e}")
        await message.reply("⚠️ Ошибка сервера. Попробуй позже.")

    finally:
        if os.path.exists(image_path):
            os.remove(image_path)
        if 'output_path' in locals() and os.path.exists(output_path):
            os.remove(output_path)
        await state.clear()
        await message.answer("Хочешь создать ещё? Просто отправь новое фото!")

# === ОПЛАТА ===
@router.callback_query(F.data == "show_payment")
async def show_payment_options(callback: CallbackQuery):
    buttons = []
    for key, packet in PACKETS.items():
        buttons.append([InlineKeyboardButton(
            text=f"{packet['label']} — {packet['price'] // 100} ₽",
            callback_data=f"buy_{key}"
        )])
    await callback.message.answer(
        "Выбери пакет, чтобы получать 4K изображения без водяного знака:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("buy_"))
async def process_payment(callback: CallbackQuery):
    packet_key = callback.data.split("_")[1]
    packet = PACKETS[packet_key]
    prices = [LabeledPrice(label=packet["label"], amount=packet["price"])]
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title="Пакет генераций",
        description=f"{packet['label']} — {packet['generations']} изображений в 4K",
        payload=f"packet_{packet_key}_{callback.from_user.id}",
        provider_token="",  # Обязательно пусто для Telegram Payments!
        currency="RUB",
        prices=prices,
        start_parameter="lumify-packet",
        need_name=False,
        need_email=False,
        need_phone_number=False,
        need_shipping_address=False,
        is_flexible=False
    )
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(pre_checkout_q: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message, state: FSMContext):
    payload = message.successful_payment.invoice_payload
    user_id = message.from_user.id
    packet_key = payload.split("_")[1]
    generations = PACKETS[packet_key]["generations"]
    await update_user_balance(user_id, generations)
    await message.answer(
        f"✅ Оплата прошла успешно! Тебе доступно {generations} генераций в 4K.\n"
        "Отправь фото, чтобы начать!"
    )

# === ОСТАЛЬНОЕ ===
@router.message()
async def fallback(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer(
            "👋 Привет! Нажми /start, чтобы начать создавать аватарки.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="/start")]],
                resize_keyboard=True
            )
        )
    else:
        await message.answer("Пожалуйста, следуй инструкциям.")

dp.include_router(router)

async def main():
    print("🤖 Бот запущен. Ожидание фото...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
