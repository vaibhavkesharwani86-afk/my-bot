import os
import asyncio
from PIL import Image

# Pillow 10+ patch
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip
from moviepy.audio.AudioClip import CompositeAudioClip
import numpy as np
from aiohttp import web

TELEGRAM_BOT_TOKEN = "8645345885:AAGhqrGJbEYpk4PFBiG-_H4F-OdD_rykWIM"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

USER_DATA = {}

class EditState(StatesGroup):
    waiting_for_voice = State()
    waiting_for_bg = State()
    waiting_for_images = State()

# --- COMMANDS ---
@dp.message(Command("developer"))
async def dev_cmd(message: types.Message):
    await message.reply(
        "Hey! 👋\n\nMain hoon **Vaibhav Kesharwani** (aka **Madmax**), Class 11th student jo automation & bots banata hai! 🫣\n\nBaki nhi bataunga.. Hehe✨",
        parse_mode="Markdown"
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.reply(
        "🎬 **Auto Video Editor Bot** 🎬\n\n1. `/start` dabayein.\n2. Voiceover audio (.mp3) bhejein.\n3. Background music bhejein ya `/skip` karein.\n4. Photos upload karein aur `/done_images` likhein.\n\nBot smooth Zoom In/Out effects ke sath clean video bana dega!",
        parse_mode="Markdown"
    )

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    USER_DATA[user_id] = {"images": []}
    os.makedirs(f"workspace_{user_id}", exist_ok=True)
    await message.reply("Namaste! Automated Video Editor Bot active hai.\n\n1. Sabse pehle apna Voiceover Audio (.mp3) bhejo.")
    await state.set_state(EditState.waiting_for_voice)

# --- MEDIA HANDLERS ---
@dp.message(EditState.waiting_for_voice, F.audio | F.voice | F.document)
async def handle_voice(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    file_id = message.audio.file_id if message.audio else (message.voice.file_id if message.voice else message.document.file_id)
    file = await bot.get_file(file_id)
    voice_path = f"workspace_{user_id}/voice.mp3"
    await bot.download_file(file.file_path, voice_path)
    USER_DATA[user_id]["voice"] = voice_path
    await message.reply("Voiceover save ho gaya!\n\n2. Ab Background Music (.mp3) bhejo (agar nahi chahiye toh /skip likho).")
    await state.set_state(EditState.waiting_for_bg)

@dp.message(EditState.waiting_for_bg)
async def handle_bg(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if message.text == "/skip":
        USER_DATA[user_id]["bg"] = None
    else:
        file_id = message.audio.file_id if message.audio else message.document.file_id
        file = await bot.get_file(file_id)
        bg_path = f"workspace_{user_id}/bg.mp3"
        await bot.download_file(file.file_path, bg_path)
        USER_DATA[user_id]["bg"] = bg_path
    await message.reply("Music set ho gaya!\n\n3. Ab Photos ek-ek karke bhejo.\nSab upload hone ke baad likho: /done_images")
    await state.set_state(EditState.waiting_for_images)

@dp.message(EditState.waiting_for_images, F.photo | F.document)
async def handle_images(message: types.Message):
    user_id = message.from_user.id
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    file = await bot.get_file(file_id)
    img_idx = len(USER_DATA[user_id]["images"])
    img_path = f"workspace_{user_id}/img_{img_idx}.jpg"
    await bot.download_file(file.file_path, img_path)
    USER_DATA[user_id]["images"].append(img_path)
    await message.reply(f"Photo #{img_idx+1} save ho gayi! Aur bhejo ya /done_images likho.")

# --- ZOOM IN / ZOOM OUT PROCESSING ---
def prepare_base_image(img_path, target_w=720, target_h=1280):
    with Image.open(img_path) as im:
        im = im.convert("RGB")
        img_w, img_h = im.size
        ratio = max(target_w / img_w, target_h / img_h)
        new_w, new_h = int(img_w * ratio), int(img_h * ratio)
        im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        im = im.crop((left, top, left + target_w, top + target_h))
        return np.array(im)

def create_zoom_clip(img_arr, duration, zoom_in=True, w=720, h=1280):
    clip = ImageClip(img_arr).set_duration(duration)
    # Smooth Zoom In vs Zoom Out
    if zoom_in:
        clip = clip.resize(lambda t: 1.0 + 0.08 * (t / duration))
    else:
        clip = clip.resize(lambda t: 1.08 - 0.08 * (t / duration))
    return clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=w, height=h).crossfadein(0.3)

# --- VIDEO RENDER ---
@dp.message(EditState.waiting_for_images, Command("done_images"))
async def done_images(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = USER_DATA.get(user_id, {})
    
    if not data.get("images"):
        await message.reply("Pehle kam se kam ek photo toh bhejo!")
        return

    voice_clip = AudioFileClip(data["voice"])
    total_dur = voice_clip.duration
    
    status_msg = await message.reply(
        f"⏳ **Video Creation Shuru Ho Gayi Hai!**\n\n"
        f"⏱ **Estimated Time:** Lagbhag **40 se 50 second**\n"
        f"📊 **Video Duration:** {int(total_dur)} seconds\n\n"
        f"Smooth Zoom Effects apply ho rahe hain... Bas thoda sa wait karein! 🎬",
        parse_mode="Markdown"
    )

    W, H = 720, 1280
    num_imgs = len(data["images"])
    clip_dur = total_dur / num_imgs
    visuals = []
    
    for i, p in enumerate(data["images"]):
        img_arr = prepare_base_image(p, W, H)
        # Alternate Zoom In aur Zoom Out
        is_zoom_in = (i % 2 == 0)
        visuals.append(create_zoom_clip(img_arr, clip_dur + 0.3, zoom_in=is_zoom_in, w=W, h=H))
    
    final_video = concatenate_videoclips(visuals, method="compose", padding=-0.3).set_duration(total_dur)
    
    # Audio Mix
    if data.get("bg") and os.path.exists(data["bg"]):
        bg_clip = AudioFileClip(data["bg"]).volumex(0.12).set_duration(total_dur)
        final_video = final_video.set_audio(CompositeAudioClip([voice_clip, bg_clip]))
    else:
        final_video = final_video.set_audio(voice_clip)

    out_path = f"workspace_{user_id}/output.mp4"
    final_video.write_videofile(
        out_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        threads=2
    )
    
    vid_file = FSInputFile(out_path)
    await message.answer_video(video=vid_file, caption="Ye rahi aapki cinematic zoom video! 🎬", request_timeout=300)
    await status_msg.delete()
    await state.clear()

# --- KEEP-ALIVE SERVER ---
async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def run_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        run_server()
    )

if __name__ == "__main__":
    asyncio.run(main())
    
