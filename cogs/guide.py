import asyncio
import json
import sys
from pathlib import Path

import discord
from discord.ext import commands
from discord import app_commands
from source import utils, wiki

BASE_DIR = Path(__file__).resolve().parent.parent
BUILD_WIKI_SCRIPT = BASE_DIR / "scripts" / "build_wiki.py"
WIKI_JSON_FILE = BASE_DIR / "data" / "character_wiki.json"

_wiki_build_lock = asyncio.Lock()

ITEM_TYPE_OPTIONS = [
    ("기본정보", "all"),
    ("광추", "weapon"),
    ("유물", "relic"),
    ("성흔", "eidolon"),
    ("특성", "trace"),
    ("추천파티", "party"),
]

def _summary(d: dict) -> str:
    return " · ".join(filter(None, [d.get("element"), d.get("path"), d.get("role")])) or "정보 없음"

def _weapon_detail_embed(char_name: str, w: dict) -> discord.Embed:
    embed = discord.Embed(title=f"{w['name']}", color=discord.Color.blue())
    if w.get("icon"):
        embed.set_thumbnail(url=w["icon"])
    stats = []
    if w.get("hp") is not None:
        stats.append(f"체력 {w['hp']}")
    if w.get("atk") is not None:
        stats.append(f"공격력 {w['atk']}")
    if w.get("def") is not None:
        stats.append(f"방어력 {w['def']}")
    if stats:
        embed.add_field(name="📊 능력치 (Lv.80 만돌파 기준)", value=" / ".join(stats), inline=False)
    embed.add_field(name="✨ 효과", value=w.get("effect") or "정보 없음", inline=False)
    embed.set_footer(text="데이터 출처: prydwen.gg")
    return embed

def _relic_detail_embed(detail: dict) -> discord.Embed:
    embed = discord.Embed(title=f"{detail['name']}", color=discord.Color.blue())
    if detail.get("icon"):
        embed.set_thumbnail(url=detail["icon"])
    if detail.get("bonus_2"):
        embed.add_field(name="2세트 효과", value=detail["bonus_2"], inline=False)
    if detail.get("bonus_4"):
        embed.add_field(name="4세트 효과", value=detail["bonus_4"], inline=False)
    if not detail.get("bonus_2") and not detail.get("bonus_4"):
        embed.add_field(name="효과", value="정보 없음", inline=False)
    embed.set_footer(text="데이터 출처: prydwen.gg")
    return embed

async def _build_detail_embeds(char_name: str, d: dict, item_type: str, selection: str = None) -> tuple:
    if item_type == "weapon" and selection:
        w = next((w for w in d.get("weapons", []) if w["name"] == selection), None)
        if w:
            return [_weapon_detail_embed(char_name, w)], None

    if item_type == "relic" and selection:
        for detail in (d.get("relic_detail"), d.get("ornament_detail")):
            if detail and detail["name"] == selection:
                return [_relic_detail_embed(detail)], None

    embed = discord.Embed(
        title=f"{char_name} 육성 가이드",
        color=discord.Color.blue()
    )
    file = None

    if d.get("unreleased"):
        embed.description = "🚧 미출시 캐릭터입니다. 정식 출시 후 정보가 제공됩니다."
        if d.get("portrait"):
            embed.set_thumbnail(url=d["portrait"])
        embed.set_footer(text="데이터 출처: prydwen.gg")
        return [embed], file

    if item_type == "all":
        embed.description = _summary(d)
        if d.get("description"):
            embed.add_field(name="📖 캐릭터 설명", value=d["description"][:1024], inline=False)
        if d.get("portrait"):
            embed.set_thumbnail(url=d["portrait"])

    elif item_type == "eidolon":
        eidolons = d.get("eidolons", [])
        if eidolons:
            for e in eidolons:
                embed.add_field(name=f"E{e['level']} {e['name']}", value=e["desc"][:1024], inline=False)
        else:
            embed.add_field(name="🔮 성흔", value="정보 없음", inline=False)

    elif item_type == "trace":
        if d.get("stat_targets"):
            embed.add_field(name="🎯 목표 스탯", value="\n".join(d["stat_targets"]), inline=True)
        else:
            embed.add_field(name="🎯 목표 스탯", value="정보 없음", inline=False)

    elif item_type == "relic":
        opts = d.get("relic_opts", {})
        embed.add_field(
            name="🧩 유물 / 장신구",
            value=f"**4세트:** {d.get('relic_set') or '정보 없음'}\n**장신구:** {d.get('ornament_set') or '정보 없음'}",
            inline=False
        )
        embed.add_field(
            name="⚙️ 부위별 주옵 우선순위",
            value="\n".join(f"**{k}:** {v or '정보 없음'}" for k, v in opts.items()),
            inline=False
        )
        embed.add_field(name="✨ 유효 부옵 우선순위", value=d.get("substat_priority") or "정보 없음", inline=False)
        embed.set_footer(text="아래 메뉴에서 항목을 고르면 세트 효과를 볼 수 있습니다")

        icon_pairs = [
            (d.get("relic_set"), d.get("relic_icon")),
            (d.get("ornament_set"), d.get("ornament_icon")),
        ]
        icon_pairs = [(name, icon) for name, icon in icon_pairs if icon]
        if icon_pairs:
            buf = await asyncio.to_thread(utils.build_icon_strip_image, icon_pairs, show_labels=False)
            file = discord.File(buf, filename="relics.png")
            embed.set_image(url="attachment://relics.png")

    elif item_type == "weapon":
        weapons = d.get("weapons", [])
        names = [w["name"] for w in weapons]
        weapon_value = " > ".join(names) if names else "정보 없음"
        embed.add_field(name="🗡️ 광추 (사용량 순)", value=weapon_value, inline=False)
        if names:
            embed.set_footer(text="아래 메뉴에서 광추를 고르면 능력치/효과를 볼 수 있습니다")

        icon_pairs = [(w["name"], w["icon"]) for w in weapons if w.get("icon")]
        if icon_pairs:
            buf = await asyncio.to_thread(utils.build_icon_strip_image, icon_pairs, show_labels=False)
            file = discord.File(buf, filename="weapons.png")
            embed.set_image(url="attachment://weapons.png")

    elif item_type == "party":
        teams = d.get("party_teams") or []
        if teams:
            selected_index = 0
            if selection and selection.startswith("party:"):
                try:
                    selected_index = int(selection.partition(":")[2])
                except ValueError:
                    selected_index = 0
            selected_index = min(max(selected_index, 0), len(teams) - 1)
            team = teams[selected_index]
            embed.add_field(
                name=f"🤝 추천 파티 ({selected_index + 1}/{len(teams)})",
                value=team.get("display") or "정보 없음",
                inline=False,
            )
            icon_pairs = [
                (member["name"], member["portrait"])
                for member in team.get("members", [])
                if member.get("portrait")
            ]
            if icon_pairs:
                buf = await asyncio.to_thread(utils.build_icon_strip_image, icon_pairs, show_labels=False)
                file = discord.File(buf, filename="party.png")
                embed.set_image(url="attachment://party.png")
            if len(teams) > 1:
                embed.set_footer(text="아래 메뉴에서 다른 추천 조합을 선택할 수 있습니다")
        else:
            embed.add_field(name="🤝 추천 파티", value="정보 없음", inline=False)

    if not embed.footer.text:
        embed.set_footer(text="데이터 출처: prydwen.gg")
    return [embed], file

class GuidePaginator(discord.ui.View):
    def __init__(self, char_name: str, item_type: str, d: dict):
        super().__init__(timeout=180)
        self.char_name = char_name
        self.item_type = item_type
        self.d = d
        self.selection = None
        self.item_buttons = []
        self._rebuild_components()

    def _rebuild_components(self):
        self.clear_items()
        self.item_buttons = []

        for index, (label, value) in enumerate(ITEM_TYPE_OPTIONS):
            style = discord.ButtonStyle.primary if value == self.item_type else discord.ButtonStyle.secondary
            # Discord는 한 행에 버튼을 최대 5개까지만 허용한다.
            # 가능한 한 가로로 모아 표시하고, 마지막 추천파티만 다음 행에 둔다.
            button = discord.ui.Button(label=label, style=style, row=index // 5)
            button.callback = self._make_item_type_callback(value)
            self.add_item(button)
            self.item_buttons.append(button)

        if self.item_type == "weapon":
            options = [discord.SelectOption(label=w["name"], value=w["name"]) for w in self.d.get("weapons", [])][:25]
            if options:
                select = discord.ui.Select(placeholder="광추를 선택하면 능력치/효과를 볼 수 있어요", options=options, row=2)
                select.callback = self._make_select_callback()
                self.add_item(select)

        elif self.item_type == "relic":
            options = []
            for detail in (self.d.get("relic_detail"), self.d.get("ornament_detail")):
                if detail:
                    options.append(discord.SelectOption(label=detail["name"], value=detail["name"]))
            if options:
                select = discord.ui.Select(placeholder="유물/장신구를 선택하면 세트 효과를 볼 수 있어요", options=options, row=2)
                select.callback = self._make_select_callback()
                self.add_item(select)

        elif self.item_type == "party":
            teams = self.d.get("party_teams") or []
            options = [
                discord.SelectOption(
                    label=f"추천 조합 {index + 1}",
                    description=(team.get("display") or "정보 없음")[:100],
                    value=f"party:{index}",
                )
                for index, team in enumerate(teams[:25])
            ]
            if len(options) > 1:
                select = discord.ui.Select(
                    placeholder="다른 추천 조합을 선택하세요",
                    options=options,
                    row=2,
                )
                select.callback = self._make_select_callback()
                self.add_item(select)

    def _make_item_type_callback(self, item_type: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            self.item_type = item_type
            self.selection = None
            self._rebuild_components()
            embeds, file = await self.build_embeds()
            await interaction.edit_original_response(embeds=embeds, attachments=[file] if file else [], view=self)
        return callback

    def _make_select_callback(self):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            self.selection = interaction.data["values"][0]
            embeds, file = await self.build_embeds()
            await interaction.edit_original_response(embeds=embeds, attachments=[file] if file else [], view=self)
        return callback

    async def build_embeds(self) -> tuple:
        return await _build_detail_embeds(self.char_name, self.d, self.item_type, self.selection)

class GuideCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="육성방법", description="캐릭터의 육성 방법을 알려줍니다")
    @app_commands.autocomplete(캐릭터=utils.character_autocomplete)
    async def guide(
        self,
        interaction: discord.Interaction,
        캐릭터: str
    ):
        await interaction.response.defer()

        d = wiki.get_character(캐릭터)
        if not d:
            await interaction.followup.send(f"캐릭터 '{캐릭터}' 위키 정보를 찾을 수 없습니다. (`build_wiki.py` 갱신 필요할 수 있음)")
            return

        view = GuidePaginator(캐릭터, "all", d)
        embeds, file = await view.build_embeds()
        if file:
            await interaction.followup.send(embeds=embeds, file=file, view=view)
        else:
            await interaction.followup.send(embeds=embeds, view=view)

    @app_commands.command(name="위키갱신", description="캐릭터 육성 위키 데이터를 prydwen.gg 기준으로 새로 갱신합니다 (관리자 전용)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(캐릭터="특정 캐릭터만 갱신하려면 이름 입력 (비우면 전체 갱신, 시간이 오래 걸릴 수 있음)")
    async def rebuild_wiki(
        self,
        interaction: discord.Interaction,
        캐릭터: str = None
    ):
        if _wiki_build_lock.locked():
            await interaction.response.send_message("이미 위키 갱신이 진행 중입니다. 완료될 때까지 기다려주세요.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"위키 갱신을 시작합니다{f' ({캐릭터})' if 캐릭터 else ' (전체, 시간이 오래 걸릴 수 있습니다)'}. 완료되면 이 채널에 알려드립니다."
        )

        async def run_build():
            async with _wiki_build_lock:
                before = {}
                if WIKI_JSON_FILE.exists():
                    try:
                        before = json.loads(WIKI_JSON_FILE.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        before = {}

                args = [sys.executable, str(BUILD_WIKI_SCRIPT)]
                if 캐릭터:
                    args.append(캐릭터)
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=str(BASE_DIR),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                stdout, _ = await proc.communicate()

                if proc.returncode == 0:
                    wiki.reload()
                    utils.reload_characters()

                    after = {}
                    if WIKI_JSON_FILE.exists():
                        try:
                            after = json.loads(WIKI_JSON_FILE.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            after = {}

                    added = sorted(set(after) - set(before))
                    changed = sorted(
                        name for name in (set(after) & set(before))
                        if after[name] != before[name]
                    )

                    lines = [f"✅ 위키 갱신 완료{f' ({캐릭터})' if 캐릭터 else ''}"]
                    if added:
                        lines.append(f"신규 캐릭터 ({len(added)}): " + ", ".join(added[:20]) + (" 외" if len(added) > 20 else ""))
                    if changed:
                        lines.append(f"내용 변경 ({len(changed)}): " + ", ".join(changed[:20]) + (" 외" if len(changed) > 20 else ""))
                    if not added and not changed:
                        lines.append("변경된 내용 없음 (기존과 동일)")
                    await interaction.channel.send("\n".join(lines))
                else:
                    tail = stdout.decode(errors="ignore")[-1500:] if stdout else "(출력 없음)"
                    await interaction.channel.send(f"❌ 위키 갱신 실패 (exit {proc.returncode})\n```{tail}```")

        asyncio.create_task(run_build())

async def setup(bot):
    await bot.add_cog(GuideCog(bot))
