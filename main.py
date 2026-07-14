import os
import asyncio
from datetime import datetime
from pathlib import Path
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from source import utils

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@tasks.loop(minutes=5)
async def heartbeat():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[하트비트 {now}] 정상 작동 중 (서버 {len(bot.guilds)}개 접속)")

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} 로그인됨")
    asyncio.create_task(asyncio.to_thread(utils.warm_icon_cache))
    if not heartbeat.is_running():
        heartbeat.start()

async def load_cogs():
    cogs_dir = BASE_DIR / "cogs"
    for filename in os.listdir(cogs_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            try:
                await bot.load_extension(f"cogs.{filename[:-3]}")
                print(f"Cog 로드됨: {filename[:-3]}")
            except Exception as e:
                print(f"Cog 로드 실패 ({filename[:-3]}): {e}")

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN 환경변수가 없습니다. .env 파일을 확인하세요.")

    async with bot:
        await load_cogs()
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
