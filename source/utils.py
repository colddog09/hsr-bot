import io
import json
import discord
from pathlib import Path
from typing import List
from PIL import Image, ImageDraw, ImageFont
from source import starrailres

BASE_DIR = Path(__file__).resolve().parent.parent
WIKI_FILE = BASE_DIR / "data" / "character_wiki.json"

CHARACTER_CACHE = None

ICON_SIZE = 128
ICON_PADDING = 12
ICON_LABEL_HEIGHT = 34

FONT_PATH = BASE_DIR / "data" / "fonts" / "NanumGothic-Regular.ttf"
_ICON_LABEL_FONT = ImageFont.truetype(str(FONT_PATH), 24) if FONT_PATH.exists() else ImageFont.load_default()

def build_icon_strip_image(items: list, show_labels: bool = False) -> io.BytesIO:
    """(이름, 아이콘URL) 목록을 받아 한 장으로 나란히 합성한 이미지 반환"""
    icons = []
    for name, icon_url in items:
        img = None
        icon_bytes = starrailres.fetch_icon_bytes(icon_url)
        if icon_bytes:
            try:
                img = Image.open(io.BytesIO(icon_bytes)).convert("RGBA").resize((ICON_SIZE, ICON_SIZE))
            except Exception as e:
                print(f"아이콘 처리 실패 ({name}): {e}")
        icons.append((name, img))

    label_height = ICON_LABEL_HEIGHT if show_labels else 0
    width = len(icons) * ICON_SIZE + (len(icons) + 1) * ICON_PADDING
    height = ICON_SIZE + label_height + ICON_PADDING * 2
    canvas = Image.new("RGBA", (width, height), (47, 49, 54, 255))
    draw = ImageDraw.Draw(canvas)
    font = _ICON_LABEL_FONT

    x = ICON_PADDING
    for name, img in icons:
        if img:
            canvas.paste(img, (x, ICON_PADDING), img)
        else:
            draw.rectangle(
                [x, ICON_PADDING, x + ICON_SIZE, ICON_PADDING + ICON_SIZE],
                fill=(60, 60, 60, 255)
            )
            draw.line([x, ICON_PADDING, x + ICON_SIZE, ICON_PADDING + ICON_SIZE], fill=(200, 60, 60, 255), width=5)
            draw.line([x + ICON_SIZE, ICON_PADDING, x, ICON_PADDING + ICON_SIZE], fill=(200, 60, 60, 255), width=5)

        if show_labels:
            text_w = draw.textlength(name, font=font)
            draw.text(
                (x + ICON_SIZE / 2 - text_w / 2, ICON_PADDING + ICON_SIZE + 4),
                name, fill=(255, 255, 255, 255), font=font
            )
        x += ICON_SIZE + ICON_PADDING

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf

def warm_icon_cache():
    """위키 데이터에 등장하는 모든 아이콘 URL을 미리 다운로드해 로컬 캐시에 저장 (봇 시작 시 호출)"""
    from source import wiki

    urls = set()
    for d in wiki.load().values():
        urls.add(d.get("portrait"))
        urls.add(d.get("relic_icon"))
        urls.add(d.get("ornament_icon"))
        for w in d.get("weapons", []):
            urls.add(w.get("icon"))
        for team in d.get("party_teams", []):
            for m in team.get("members", []):
                urls.add(m.get("portrait"))
    urls.discard(None)

    fetched = sum(1 for url in urls if starrailres.fetch_icon_bytes(url))
    print(f"아이콘 캐시 예열 완료: {len(urls)}개 중 {fetched}건 다운로드")

def load_characters() -> List[dict]:
    """위키 데이터에서 캐릭터 목록 로드 (character_wiki.json 기준)"""
    global CHARACTER_CACHE
    if CHARACTER_CACHE is None:
        try:
            with open(WIKI_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            CHARACTER_CACHE = [{"name": name} for name in data.keys()]
        except Exception as e:
            print(f"캐릭터 목록 로드 오류: {e}")
            CHARACTER_CACHE = []
    return CHARACTER_CACHE

def reload_characters():
    global CHARACTER_CACHE
    CHARACTER_CACHE = None

async def character_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[discord.app_commands.Choice[str]]:
    characters = load_characters()
    matches = [
        c["name"] for c in characters
        if current.lower() in c["name"].lower()
    ][:25]

    return [discord.app_commands.Choice(name=name, value=name) for name in matches]
