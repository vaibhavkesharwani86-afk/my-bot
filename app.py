import os
import asyncio
import subprocess
from PIL import Image

# Pillow patch
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile
from aiohttp import web

TELEGRAM_BOT_TOKEN = "8645345885:AAGhqrGJbEYpk4PFBiG-_H4F-OdD_rykWIM"

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
USER_DATA = {}

class EditState(StatesGroup):
    waiting_for_voice = State()
    waiting_for_bg = State()
    waiting_for_images = State()

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    USER_DATA[user_id] = {"images": []}
    os.makedirs(f"workspace_{user_id}", exist_ok=True)
    await message.reply("Namaste! 10-15 images wale Shorts ke liye bot ready hai.\n\n1. Pehle Voiceover (.mp3) bhejein.")
    await state.set_state(EditState.waiting_for_voice)

@dp.message(EditState.waiting_for_voice, F.audio | F.voice | F.document)
async def handle_voice(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    file_id = message.audio.file_id if message.audio else (message.voice.file_id if message.voice else message.document.file_id)
    file = await bot.get_file(file_id)
    voice_path = f"workspace_{user_id}/voice.mp3"
    await bot.download_file(file.file_path, voice_path)
    USER_DATA[user_id]["voice"] = voice_path
    await message.reply("Voiceover mil gaya!\n\n2. Ab Background Music bhejo ya /skip likho.")
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
    await message.reply("Music set! Ab Photos ek-ek karke bhejo.\nSabhi upload hone ke baad type karo: /done_images")
    await state.set_state(EditState.waiting_for_images)

@dp.message(EditState.waiting_for_images, F.photo | F.document)
async def handle_images(message: types.Message):
    user_id = message.from_user.id
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    file = await bot.get_file(file_id)
    img_idx = len(USER_DATA[user_id]["images"])
    img_path = f"workspace_{user_id}/img_{img_idx:03d}.jpg"
    await bot.download_file(file.file_path, img_path)
    
    # 9:16 exact vertical resize
    with Image.open(img_path) as im:
        im = im.convert("RGB")
        target_w, target_h = 720, 1280
        ratio = max(target_w / im.size[0], target_h / im.size[1])
        new_w, new_h = int(im.size[0] * ratio), int(im.size[1] * ratio)
        im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        im = im.crop((left, top, left + target_w, top + target_h))
        im.save(img_path, quality=90)

    USER_DATA[user_id]["images"].append(img_path)
    await message.reply(f"Photo #{img_idx+1} save ho gayi! Aur bhejo ya /done_images likho.")

def get_audio_duration(path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return float(res.stdout.strip())

@dp.message(EditState.waiting_for_images, Command("done_images"))
async def done_images(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = USER_DATA.get(user_id, {})
    if not data.get("images"):
        await message.reply("Kam se kam ek photo bhejo!")
        return

    status_msg = await message.reply("⏳ **Video Fast Render Ho Rahi Hai...**\n\nDirect hardware encoding chal rahi hai, sirf 15-20 second lagenge! 🎬", parse_mode="Markdown")

    total_dur = get_audio_duration(data["voice"])
    num_imgs = len(data["images"])
    clip_dur = total_dur / num_imgs

    # FFmpeg concat file create
    concat_txt = f"workspace_{user_id}/input.txt"
    with open(concat_txt, "w") as f:
        for p in data["images"]:
            abs_p = os.path.abspath(p)
            f.write(f"file '{abs_p}'\n")
            f.write(f"duration {clip_dur}\n")
        f.write(f"file '{os.path.abspath(data['images'][-1])}'\n")

    out_path = f"workspace_{user_id}/output.mp4"
    
    # Direct C-level FFmpeg render (RAM sirf 60MB lega)
    if data.get("bg") and os.path.exists(data["bg"]):
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
            "-i", data["voice"], "-i", data["bg"],
            "-filter_complex", f"[2:a]volume=0.12[bg];[1:a][bg]amix=inputs=2:duration=first[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            "-t", str(total_dur),
            out_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
            "-i", data["voice"],
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            "-t", str(total_dur),
            out_path
        ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
    await asyncio.gather(dp.start_polling(bot), run_server())

if __name__ == "__main__":
    asyncio.run(main())
