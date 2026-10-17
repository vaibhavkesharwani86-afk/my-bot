import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
import asyncio
import os
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeAudioClip
from moviepy.audio.fx.all import audio_loop
from google import genai
from aiohttp import web

TELEGRAM_BOT_TOKEN = "8645345885:AAGhqrGJbEYpk4PFBiG-_H4F-OdD_rykWIM"
GEMINI_API_KEY = "AQ.Ab8RN6KpLtolnmE6Xbhs21tNMsIUJ0qrWs6IB63BRwOyKVh_vw"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

class EditState(StatesGroup):
    waiting_for_voice = State()
    waiting_for_bg = State()
    waiting_for_images = State()
    waiting_for_transcript = State()
    waiting_for_transition = State()

USER_DATA = {}

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
    
    await message.reply("Voiceover save ho gaya!\n\n2. Ab halki Background Music (.mp3) bhejo (agar nahi chahiye toh /skip likho).")
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
        
    await message.reply("Music ready!\n\n3. Ab saari Images bhejo.\nJab sab images upload ho jayein, tab type karo: /done_images")
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

@dp.message(EditState.waiting_for_images, Command("done_images"))
async def done_images(message: types.Message, state: FSMContext):
    await message.reply("Images mil gayi!\n\n4. Ab video ki Transcript Text paste karke send karo.")
    await state.set_state(EditState.waiting_for_transcript)

@dp.message(EditState.waiting_for_transcript)
async def handle_transcript(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    USER_DATA[user_id]["transcript"] = message.text
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Crossfade (Smooth Dissolve)", callback_data="tr_crossfade")],
        [InlineKeyboardButton(text="Fade to Black", callback_data="tr_fadeblack")],
        [InlineKeyboardButton(text="Slide Left", callback_data="tr_slide")]
    ])
    await message.reply("5. Video ke liye Transition Style select karo:", reply_markup=kb)
    await state.set_state(EditState.waiting_for_transition)

@dp.callback_query(EditState.waiting_for_transition)
async def render_video_task(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    transition_choice = callback.data.replace("tr_", "")
    await callback.message.edit_text("Processing shuru ho gayi hai! AI sequence match aur video render kar raha hai, 1-2 minute wait karein...")
    
    data = USER_DATA[user_id]
    voice_clip = AudioFileClip(data["voice"])
    total_duration = voice_clip.duration
    images = data["images"]
    n_images = len(images)
    
    time_per_image = total_duration / max(1, n_images)
    
    prompt = f"""
    Images: {images}
    Transcript: "{data['transcript']}"
    Sort and align these image paths with the transcript context.
    Return JSON list only: ["workspace_{user_id}/img_0.jpg", ...]
    """
    try:
        res = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        ordered_images = json.loads(res.text)
    except:
        ordered_images = images

    clips = []
    for img in ordered_images:
        if os.path.exists(img):
            clip = ImageClip(img).set_duration(time_per_image).resize(height=1080).crossfadein(0.5 if transition_choice == "crossfade" else 0.1)
            clips.append(clip)
            
    final_video = concatenate_videoclips(clips, method="compose")
    
    if data.get("bg") and os.path.exists(data["bg"]):
        bg_clip = AudioFileClip(data["bg"]).volumex(0.12).set_duration(total_duration)
        final_audio = CompositeAudioClip([voice_clip, bg_clip])
    else:
        final_audio = voice_clip

    final_video = final_video.set_audio(final_audio)
    out_path = f"workspace_{user_id}/output.mp4"
    final_video.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", preset="ultrafast")
    
    video_file = types.FSInputFile(out_path)
    await callback.message.reply_video(video=video_file, caption="Yeh lijiye aapki video ready hai!")
    await state.clear()

async def handle_ping(request):
    return web.Response(text="Bot is online!")

async def run_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await asyncio.gather(
        dp.start_polling(bot),
        run_server()
    )

if __name__ == "__main__":
    asyncio.run(main())
    
