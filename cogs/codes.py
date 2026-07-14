import asyncio

import discord
from discord.ext import commands
from discord import app_commands
from source import codes

class CodesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="리딤코드", description="현재 유효한 리딤코드를 보여줍니다")
    async def redemption_codes(self, interaction: discord.Interaction):
        await interaction.response.defer()

        code_list = await asyncio.to_thread(codes.get_redemption_codes)
        if not code_list:
            await interaction.followup.send("현재 유효한 리딤코드가 없습니다")
            return

        embed = discord.Embed(
            title="붕괴: 스타레일 리딤코드",
            color=discord.Color.blue()
        )

        for code_data in code_list:
            link = code_data.get("link")
            value = code_data.get("reward", "정보 없음")
            if link:
                value += f"\n[바로 입력하기]({link})"
            embed.add_field(
                name=code_data.get("code", "Unknown"),
                value=value,
                inline=False
            )

        embed.set_footer(text="데이터 출처: Honkai: Star Rail Wiki (Fandom)")
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(CodesCog(bot))
