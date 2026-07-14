import discord
from discord.ext import commands
from discord import app_commands

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="도움말", description="봇이 지원하는 명령어 목록을 보여줍니다")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="붕괴: 스타레일 봇 명령어",
            description="사용 가능한 명령어 목록입니다",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="🧑‍🚀 캐릭터",
            value=(
                "`/육성방법` 기본 정보·광추·유물·성흔·특성·추천파티를 보여줍니다"
            ),
            inline=False
        )

        embed.add_field(
            name="📰 정보",
            value=(
                "`/리딤코드` 현재 유효한 리딤코드 목록을 보여줍니다\n"
                "`/패치정보` 버전 업데이트, 혼돈·허구·종말·이상중재 갱신, 뽑기 배너 교체 일정을 보여줍니다\n"
                "`/최근공지` 호요랩 공식 공지 최신 목록을 보여줍니다"
            ),
            inline=False
        )

        embed.add_field(
            name="⚙️ 관리 (서버 관리 권한 필요)",
            value="`/공지채널` 패치·공지·공식 YouTube 알림을 받을 채널을 지정합니다",
            inline=False
        )

        embed.add_field(
            name="🛠️ 지원",
            value="`/오류제보` 봇 사용 중 발견한 오류를 관리자에게 전달합니다",
            inline=False
        )

        embed.set_footer(text="오류가 있다면 /오류제보를 이용해주세요")
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
