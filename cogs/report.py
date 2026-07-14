import os

import discord
from discord import app_commands
from discord.ext import commands


async def _get_report_recipient(bot: commands.Bot) -> discord.User:
    """환경 변수로 지정한 계정, 없으면 디스코드 애플리케이션 소유자에게 전달."""
    configured_id = os.getenv("REPORT_USER_ID")
    if configured_id:
        try:
            user_id = int(configured_id)
        except ValueError:
            user_id = None
        if user_id:
            return bot.get_user(user_id) or await bot.fetch_user(user_id)

    app_info = await bot.application_info()
    return app_info.owner


class ErrorReportModal(discord.ui.Modal, title="오류 제보"):
    summary = discord.ui.TextInput(
        label="어떤 오류가 발생했나요?",
        placeholder="문제가 발생한 명령어와 증상을 적어주세요.",
        style=discord.TextStyle.paragraph,
        min_length=5,
        max_length=1000,
    )
    steps = discord.ui.TextInput(
        label="재현 방법 (선택)",
        placeholder="오류가 발생하기 전 어떤 동작을 했는지 적어주세요.",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )
    reference = discord.ui.TextInput(
        label="스크린샷 링크 등 참고 자료 (선택)",
        placeholder="이미지 링크나 추가 설명을 적어주세요.",
        required=False,
        max_length=500,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild_text = "개인 메시지"
        if interaction.guild:
            guild_text = f"{interaction.guild.name} (`{interaction.guild.id}`)"

        channel_text = "알 수 없음"
        if interaction.channel:
            channel_name = getattr(interaction.channel, "name", "DM")
            channel_text = f"{channel_name} (`{interaction.channel.id}`)"

        embed = discord.Embed(
            title="🚨 새로운 봇 오류 제보",
            description=self.summary.value,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="제보자",
            value=f"{interaction.user.mention}\n{interaction.user} (`{interaction.user.id}`)",
            inline=False,
        )
        embed.add_field(name="서버", value=guild_text, inline=False)
        embed.add_field(name="채널", value=channel_text, inline=False)
        if self.steps.value:
            embed.add_field(name="재현 방법", value=self.steps.value, inline=False)
        if self.reference.value:
            embed.add_field(name="참고 자료", value=self.reference.value, inline=False)
        embed.set_footer(text="/오류제보로 접수됨")

        try:
            recipient = await _get_report_recipient(self.bot)
            await recipient.send(embed=embed)
        except (discord.HTTPException, discord.Forbidden, discord.NotFound):
            await interaction.followup.send(
                "제보를 전달하지 못했습니다. 잠시 후 다시 시도해주세요.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "오류 제보가 봇 관리자에게 전달되었습니다. 감사합니다!",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        if interaction.response.is_done():
            await interaction.followup.send("제보 처리 중 오류가 발생했습니다.", ephemeral=True)
        else:
            await interaction.response.send_message("제보 처리 중 오류가 발생했습니다.", ephemeral=True)


class ReportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="오류제보", description="봇 사용 중 발견한 오류를 관리자에게 제보합니다")
    async def report_error(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ErrorReportModal(self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(ReportCog(bot))
