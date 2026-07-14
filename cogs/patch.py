import asyncio
import json
from datetime import date
from pathlib import Path

import discord
from discord.ext import commands, tasks
from discord import app_commands

from source import config, patch

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "patch_notify_state.json"
MODE_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "mode_notify_state.json"

def _load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_notified_version": None}

def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def _load_mode_state() -> dict:
    if MODE_STATE_FILE.exists():
        with open(MODE_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_mode_state(state: dict):
    MODE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MODE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def _d_day(target: date) -> str:
    diff = (target - date.today()).days
    if diff > 0:
        return f"D-{diff}"
    if diff == 0:
        return "D-Day"
    return f"D+{-diff}"

class PatchCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_patch.start()
        self.check_mode_updates.start()

    def cog_unload(self):
        self.check_patch.cancel()
        self.check_mode_updates.cancel()

    @app_commands.command(name="공지채널", description="패치·공지·공식 YouTube 알림 채널을 지정합니다")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(채널="공지를 받을 채널")
    async def set_notify_channel(
        self,
        interaction: discord.Interaction,
        채널: discord.TextChannel
    ):
        config.set_notify_channel(interaction.guild_id, 채널.id)
        await interaction.response.send_message(f"✅ 공지 채널이 {채널.mention}(으)로 설정됐습니다")

    @app_commands.command(name="패치정보", description="현재/다음 패치 및 혼돈·허구·종말·이상중재 갱신 일정을 알려줍니다")
    async def patch_info(self, interaction: discord.Interaction):
        await interaction.response.defer()

        schedule = await asyncio.to_thread(patch.get_patch_schedule)
        if not schedule:
            await interaction.followup.send("패치 일정 정보를 불러올 수 없습니다")
            return

        embed = discord.Embed(title="붕괴: 스타레일 패치 일정", color=discord.Color.blue())

        current = schedule.get("current")
        if current:
            phase_text = f" Phase {current['phase']}" if current.get("phase") else ""
            embed.description = f"현재 버전: **{current['version']}{phase_text}** ({current.get('raw_range', '정보 없음')})"

        version_update = schedule.get("version_update")
        if version_update:
            mark = " (추정)" if schedule.get("version_update_estimated") else ""
            embed.add_field(
                name="🆙 버전 업데이트",
                value=f"{version_update.strftime('%Y-%m-%d')}{mark} ({_d_day(version_update)})",
                inline=False
            )

        mode_updates = schedule.get("mode_updates", {})
        mode_emoji = {
            "혼돈의 기억": "🌀",
            "허구서사": "📖",
            "종말의 부재": "☠️",
            "이상 중재": "⚖️",
        }
        for mode_name, emoji in mode_emoji.items():
            mode_date = mode_updates.get(mode_name)
            if not mode_date:
                continue
            embed.add_field(
                name=f"{emoji} {mode_name} 갱신",
                value=f"{mode_date.strftime('%Y-%m-%d')} ({_d_day(mode_date)})",
                inline=True
            )

        gacha_update = schedule.get("gacha_update")
        if gacha_update:
            embed.add_field(
                name="🎰 뽑기 배너 교체",
                value=f"{gacha_update.strftime('%Y-%m-%d')} ({_d_day(gacha_update)})",
                inline=False
            )

        embed.set_footer(text="데이터 출처: prydwen.gg · (추정) 표시는 실제 공지 전 주기 기반 예상치")
        await interaction.followup.send(embed=embed)

    @tasks.loop(hours=12)
    async def check_patch(self):
        schedule = await asyncio.to_thread(patch.get_patch_schedule)
        next_patch = schedule.get("next") if schedule else None
        if not next_patch or not next_patch.get("start_date"):
            return

        if next_patch["start_date"] > date.today():
            return

        state = _load_state()
        if state.get("last_notified_version") == next_patch["version"]:
            return

        sent = False
        for guild in self.bot.guilds:
            channel_id = config.get_notify_channel(guild.id)
            if not channel_id:
                continue

            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            embed = discord.Embed(
                title=f"🎉 패치 {next_patch['version']} 업데이트!",
                description="종말의 부재 / 이상 중재가 함께 갱신됩니다",
                color=discord.Color.gold()
            )
            embed.set_footer(text="데이터 출처: prydwen.gg")
            await channel.send(embed=embed)
            sent = True

        if sent:
            state["last_notified_version"] = next_patch["version"]
            _save_state(state)

    @check_patch.before_loop
    async def before_check_patch(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=12)
    async def check_mode_updates(self):
        schedule = await asyncio.to_thread(patch.get_patch_schedule)
        mode_updates = schedule.get("mode_updates", {}) if schedule else {}
        if not mode_updates:
            return

        state = _load_mode_state()
        today = date.today()
        due = [
            (mode, d) for mode, d in mode_updates.items()
            if d <= today and state.get(mode) != d.isoformat()
        ]
        if not due:
            return

        for guild in self.bot.guilds:
            channel_id = config.get_notify_channel(guild.id)
            if not channel_id:
                continue

            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue

            for mode, _ in due:
                embed = discord.Embed(
                    title=f"🔁 {mode} 갱신!",
                    description=f"{mode}가 새로운 콘텐츠로 갱신됐습니다",
                    color=discord.Color.teal()
                )
                embed.set_footer(text="6주 주기 로테이션 기준 자동 계산")
                await channel.send(embed=embed)

        for mode, d in due:
            state[mode] = d.isoformat()
        _save_mode_state(state)

    @check_mode_updates.before_loop
    async def before_check_mode_updates(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(PatchCog(bot))
