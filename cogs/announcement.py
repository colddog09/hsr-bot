import asyncio
import json
from pathlib import Path

import discord
from discord.ext import commands, tasks
from discord import app_commands

from source import config, hoyolab

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "announcement_state.json"

def _load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_post_id": None}

def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

async def _build_embed(post: dict) -> discord.Embed:
    embed = discord.Embed(
        title=post["subject"],
        description=f"🔗 [공지 바로가기]({post['url']})",
        url=post["url"],
        color=discord.Color.blue()
    )

    cover = await asyncio.to_thread(hoyolab.get_post_cover_image, post["post_id"])
    if cover:
        embed.set_image(url=cover)

    embed.set_footer(text="데이터 출처: HoYoLAB 공식 공지")
    return embed

class AnnouncementCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_announcements.start()

    def cog_unload(self):
        self.check_announcements.cancel()

    @app_commands.command(name="최근공지", description="호요랩 붕괴: 스타레일 공식 공지 최신 목록을 보여줍니다")
    async def recent_announcements(self, interaction: discord.Interaction):
        await interaction.response.defer()

        posts = await asyncio.to_thread(hoyolab.get_latest_announcements, 5)
        if not posts:
            await interaction.followup.send("공지 정보를 불러올 수 없습니다")
            return

        embed = discord.Embed(title="호요랩 최근 공지", color=discord.Color.blue())
        for post in posts:
            embed.add_field(
                name=post["subject"],
                value=f"[바로가기]({post['url']})",
                inline=False
            )
        embed.set_footer(text="데이터 출처: HoYoLAB 공식 공지")
        await interaction.followup.send(embed=embed)

    @tasks.loop(minutes=30)
    async def check_announcements(self):
        posts = await asyncio.to_thread(hoyolab.get_latest_announcements, 10)
        if not posts:
            return

        state = _load_state()
        last_id = state.get("last_post_id")

        if last_id is None:
            state["last_post_id"] = posts[0]["post_id"]
            _save_state(state)
            return

        new_posts = [p for p in posts if p["post_id"] > last_id]
        if not new_posts:
            return

        new_posts.sort(key=lambda p: p["post_id"])

        for guild in self.bot.guilds:
            channel_id = config.get_notify_channel(guild.id)
            if not channel_id:
                continue

            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            for post in new_posts:
                await channel.send(embed=await _build_embed(post))

        state["last_post_id"] = max(p["post_id"] for p in new_posts)
        _save_state(state)

    @check_announcements.before_loop
    async def before_check_announcements(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(AnnouncementCog(bot))
