import asyncio
import json
from pathlib import Path

import discord
from discord.ext import commands, tasks

from source import config, youtube


STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "youtube_state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"YouTube 상태 로드 실패: {e}")
    return {"last_video_id": None}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _new_videos(videos: list, last_video_id: str | None) -> list:
    if not videos or last_video_id is None:
        return []
    for index, video in enumerate(videos):
        if video["video_id"] == last_video_id:
            return videos[:index]
    # 기존 ID가 목록 밖으로 밀렸을 때 과거 영상 전부를 보내지 않는다.
    return videos[:1]


def _build_embed(video: dict) -> discord.Embed:
    embed = discord.Embed(
        title="🎬 붕괴: 스타레일 새 영상",
        description=f"[{video['title']}]({video['url']})",
        url=video["url"],
        color=discord.Color.red(),
    )
    if video.get("published"):
        embed.add_field(name="업로드", value=video["published"], inline=False)
    embed.set_image(url=video["thumbnail"])
    embed.set_footer(text="데이터 출처: 붕괴: 스타레일 한국 공식 YouTube")
    return embed


class YouTubeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_youtube.start()

    def cog_unload(self):
        self.check_youtube.cancel()

    @tasks.loop(minutes=10)
    async def check_youtube(self):
        videos = await asyncio.to_thread(youtube.get_latest_videos, 10)
        if not videos:
            return

        state = _load_state()
        last_video_id = state.get("last_video_id")
        if last_video_id is None:
            _save_state({"last_video_id": videos[0]["video_id"]})
            return

        new_videos = _new_videos(videos, last_video_id)
        for guild in self.bot.guilds:
            channel_id = config.get_notify_channel(guild.id)
            if not channel_id:
                continue
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue
            for video in reversed(new_videos):
                try:
                    await channel.send(embed=_build_embed(video))
                except (discord.Forbidden, discord.HTTPException) as e:
                    print(f"YouTube 알림 전송 실패 ({guild.id}/{channel_id}): {e}")

        if new_videos:
            _save_state({"last_video_id": videos[0]["video_id"]})

    @check_youtube.before_loop
    async def before_check_youtube(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(YouTubeCog(bot))
