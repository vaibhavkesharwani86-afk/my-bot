import os
import asyncio
from PIL import Image, ImageDraw, ImageFont

# Pillow 10+ compatibility fix
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile
from moviepy.editor import ImageClip, CompositeVideoClip, concatenate_videoclips, AudioFileClip
from moviepy.audio.AudioClip import CompositeAudioClip
from groq import Groq
import numpy as np
from aiohttp import web

TELEGRAM_BOT_TOKEN = "8645345885:AAGhqrGJbEYpk4PFBiG-_H4F-OdD_rykWIM"
GROQ_API_KEY = "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"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
groq_client = Groq(api_key=GROQ_API_KEY)

USER_DATA = {}

class EditState(StatesGroup):
    waiting_for_voice = State()
    waiting_for_bg = State()
    waiting_for_images = State()

@dp.message(Command("developer"))
async def dev_cmd(message: types.Message):
    await message.reply(
        "Hey! 👋\n\nMain hoon **Vaibhav Kesharwani** (aka **Madmax**), Class 11th student jo automation & bots build karta hai! 🫣\n\nAur main kuch nahi bataunga... Hehee! ✨",
        parse_mode="Markdown"
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.reply(
        "🎬 **Auto Video Editor Bot - Guide** 🎬\n\n"
        "1. `/start` dabakar session shuru karein.\n"
        "2. Voiceover Audio (.mp3) upload karein.\n"
        "3. Background Music upload karein ya `/skip` karein.\n"
        "4. Images upload karein aur phir `/done_images` likhein.\n\n"
        "Bot motions aur subtitles add karke video bhej dega!",
        parse_mode="Markdown"
    )

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    USER_DATA[user_id] = {"images": []}
    os.makedirs(f"workspace_{user_id}", exist_ok=True)
    await message.reply("Namaste! Automated Video Editor Bot active hai.\n\n1. Sabse pehle apna Voiceover Audio (.mp3) bhejo.")
    await state.set_state(EditState.waiting_for_voice)

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
    await message.reply(f"Image #{img_idx+1} save ho gayi! Aur images bhejo ya /done_images likho.")

def get_whisper_subtitles(audio_path):
    try:
        with open(audio_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(audio_path, file.read()),
                model="whisper-large-v3",
                response_format="verbose_json",
                timestamp_granularities=["segment"]
            )
        return transcription.segments
    except Exception as e:
        print(f"Whisper Error: {e}")
        return []

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

def create_documentary_clip(img_arr, duration, zoom_in=True, w=720, h=1280):
    clip = ImageClip(img_arr).set_duration(duration)
    if zoom_in:
        clip = clip.resize(lambda t: 1.0 + 0.05 * (t / duration))
    else:
        clip = clip.resize(lambda t: 1.06 - 0.05 * (t / duration))
    return clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=w, height=h).crossfadein(0.4)

def burn_subtitles_on_frame(frame, t, segments, w=720, h=1280):
    current_text = ""
    for seg in segments:
        if seg['start'] <= t <= seg['end']:
            current_text = seg['text'].strip()
            break
            
    if not current_text:
        return frame
        
    img = Image.fromarray(frame)
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("font.ttf", 38)
    except:
        font = ImageFont.load_default()
        
    bbox = draw.textbbox((0, 0), current_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_x = (w - text_w) // 2
    text_y = int(h * 0.78)
    
    stroke_w = 3
    for dx in range(-stroke_w, stroke_w + 1):
        for dy in range(-stroke_w, stroke_w + 1):
            draw.text((text_x + dx, text_y + dy), current_text, font=font, fill="black")
            
    draw.text((text_x, text_y), current_text, font=font, fill="#FFD700")
    return np.array(img)

@dp.message(EditState.waiting_for_images, Command("done_images"))
async def done_images(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = USER_DATA.get(user_id, {})
    
    if not data.get("images"):
        await message.reply("Pehle kam se kam ek photo toh bhejo!")
        return

    voice_clip = AudioFileClip(data["voice"])
    total_dur = voice_clip.duration
    
    est_total_seconds = int((total_dur * 3.5) + 6)
    est_min = est_total_seconds // 60
    est_sec = est_total_seconds % 60
    time_str = f"{est_min} minute {est_sec} second" if est_min > 0 else f"{est_sec} second"

    status_msg = await message.reply(
        f"⏳ **Video Creation Shuru Ho Gayi Hai!**\n\n"
        f"⏱ **Estimated Time:** Lagbhag **{time_str}**\n"
        f"📊 **Video Duration:** {int(total_dur)} seconds\n\n"
        f"Aap aaram se itne time baad check karein, video ready mil jayegi! 🎬",
        parse_mode="Markdown"
    )

    W, H = 720, 1280
    num_imgs = len(data["images"])
    clip_dur = total_dur / num_imgs
    visuals = []
    
    for i, p in enumerate(data["images"]):
        img_arr = prepare_base_image(p, W, H)
        visuals.append(create_documentary_clip(img_arr, clip_dur + 0.4, zoom_in=(i % 2 == 0), w=W, h=H))
    
    final_visual = concatenate_videoclips(visuals, method="compose", padding=-0.4).set_duration(total_dur)
    segments = get_whisper_subtitles(data["voice"])
    final_video = final_visual.fl(lambda gf, t: burn_subtitles_on_frame(gf(t), t, segments, W, H))
    
    if data.get("bg") and os.path.exists(data["bg"]):
        bg_clip = AudioFileClip(data["bg"]).volumex(0.12).set_duration(total_dur)
        final_video = final_video.set_audio(CompositeAudioClip([voice_clip, bg_clip]))
    else:
        final_video = final_video.set_audio(voice_clip)
        
    out_path = f"workspace_{user_id}/output.mp4"
    final_video.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", preset="ultrafast", threads=2)
    
    vid_file = FSInputFile(out_path)
    await message.answer_video(video=vid_file, caption="Ye rahi aapki documentary video! 🎬", request_timeout=300)
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
