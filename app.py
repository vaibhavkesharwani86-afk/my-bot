import os
import asyncio
from PIL import Image

# Pillow patch
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

@dp.message(Command("developer"))
async def dev_cmd(message: types.Message):
    await message.reply(
        "Hey! 👋\n\nMain hoon **Vaibhav Kesharwani** (aka **Madmax**), Class 11th student jo automation & bots banata hai! 🫣\n\nBaki nhi bataunga.. Hehe✨",
        parse_mode="Markdown"
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.reply(
        "🎬 **Shorts Video Editor Bot** 🎬\n\n1. `/start` dabayein.\n2. Voiceover (.mp3) bhejein.\n3. Background music bhejein ya `/skip` karein.\n4. Photos upload karein aur `/done_images` likhein.\n\nBot bina crash hue 20-30 second mein ready 9:16 vertical shorts de dega!",
        parse_mode="Markdown"
    )

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    USER_DATA[user_id] = {"images": []}
    os.makedirs(f"workspace_{user_id}", exist_ok=True)
    await message.reply("Namaste! Shorts Video Editor Bot active hai.\n\n1. Sabse pehle apna Voiceover Audio (.mp3) bhejo.")
    await state.set_state(EditState.waiting_for_voice)

@dp.message(EditState.waiting_for_voice, F.audio | F.voice | F.document)
async def handle_voice(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    file_id = message.audio.file_id if message.audio else (message.voice.file_id if message.voice else message.document.file_id)
    file = await bot.get_file(file_id)
    voice_path = f"workspace_{user_id}/voice.mp3"
    await bot.download_file(file.file_path, voice_path)
    USER_DATA[user_id]["voice"] = voice_path
    await message.reply("Voiceover mil gaya!\n\n2. Ab Background Music (.mp3) bhejo ya na chahiye ho toh /skip likho.")
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
    await message.reply("Music set! Ab Photos ek-ek karke bhejo.\nSab upload hone ke baad type karo: /done_images")
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

@dp.message(EditState.waiting_for_images, Command("done_images"))
async def done_images(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = USER_DATA.get(user_id, {})
    
    if not data.get("images"):
        await message.reply("Pehle kam se kam ek photo bhejo!")
        return

    voice_clip = AudioFileClip(data["voice"])
    total_dur = voice_clip.duration
    
    status_msg = await message.reply(
        f"⏳ **Shorts Render Shuru!**\n\n"
        f"⏱ **Estimated Time:** Lagbhag **20 se 30 second**\n"
        f"📊 **Duration:** {int(total_dur)}s\n\n"
        f"Voice-matched cuts aur transitions lag rahe hain... 🎬",
        parse_mode="Markdown"
    )

    W, H = 720, 1280
    num_imgs = len(data["images"])
    clip_dur = total_dur / num_imgs
    visuals = []
    
    for p in data["images"]:
        img_arr = prepare_base_image(p, W, H)
        clip = ImageClip(img_arr).set_duration(clip_dur + 0.3).crossfadein(0.3)
        visuals.append(clip)
    
    final_video = concatenate_videoclips(visuals, method="compose", padding=-0.3).set_duration(total_dur)
    
    if data.get("bg") and os.path.exists(data["bg"]):
        bg_clip = AudioFileClip(data["bg"]).volumex(0.12).set_duration(total_dur)
        final_video = final_video.set_audio(CompositeAudioClip([voice_clip, bg_clip]))
    else:
        final_video = final_video.set_audio(voice_clip)

    out_path = f"workspace_{user_id}/output.mp4"
    
    # Low-RAM settings: Single thread + ultrafast (RAM usage < 180MB)
    final_video.write_videofile(
        out_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        threads=1
    )
    
    # RAM free karein
    final_video.close()
    voice_clip.close()
    for v in visuals:
        v.close()
        
    vid_file = FSInputFile(out_path)
    await message.answer_video(video=vid_file, caption="Ye rahi aapki ready Shorts video! 🎬", request_timeout=300)
    await status_msg.delete()
    await state.clear()

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
    
