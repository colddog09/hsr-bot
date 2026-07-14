import cloudscraper
import html as html_module
import json
import re
import time
import urllib.parse
from functools import wraps
from typing import Optional, Dict, List, Any
from bs4 import BeautifulSoup

from source import starrailres

CACHE = {}
CACHE_TTL = 6 * 3600
PRYDWEN_CHARACTER_URL = "https://www.prydwen.gg/star-rail/characters/{tag}"
PRYDWEN_CLOUDFRONT_URL = "https://d2ankz0m1a0dsp.cloudfront.net/star-rail/characters/{tag}/"

TEAM_KEYS = ["mocTeams", "pfTeams", "asTeams", "aaTeams"]

def ttl_cache(seconds: int):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}_{args}_{kwargs}"
            now = time.time()

            if cache_key in CACHE:
                result, timestamp = CACHE[cache_key]
                if now - timestamp < seconds:
                    return result

            result = func(*args, **kwargs)
            CACHE[cache_key] = (result, now)
            return result
        return wrapper
    return decorator

def _extract_teams(html: str, key: str) -> List[Dict[str, Any]]:
    """prydwen 캐릭터 페이지에 내장된 Next.js 스트리밍 페이로드에서 팀 조합 배열 추출"""
    m = re.search(r'\\"' + key + r'\\":\[', html)
    if not m:
        return []

    start = m.end() - 1
    depth = 0
    i = start
    while i < len(html):
        if html[i] == "[":
            depth += 1
        elif html[i] == "]":
            depth -= 1
            if depth == 0:
                break
        i += 1

    segment = html[start:i + 1].replace('\\"', '"')
    teams = []
    for obj_m in re.finditer(r"\{[^{}]*\}", segment):
        obj = obj_m.group(0)
        chars = re.findall(r'"char_(?:one|two|three|four|five)":"([a-z0-9\-]+)"', obj)
        rank_m = re.search(r'"rank":(\d+)', obj)
        if chars:
            teams.append({"chars": chars, "rank": int(rank_m.group(1)) if rank_m else 999})
    return teams

def _find_next_f_chunk(html: str, marker: str) -> Optional[str]:
    """페이지에 내장된 Next.js 스트리밍 페이로드(self.__next_f.push) 중 marker가 포함된 청크를 찾아
    이스케이프를 풀고 순수 JSON 문자열로 반환"""
    idx = html.find(marker)
    if idx == -1:
        return None
    prefix = 'self.__next_f.push([1,"'
    start = html.rfind(prefix, 0, idx)
    if start == -1:
        return None
    str_start = start + len(prefix)
    i = str_start
    while i < len(html):
        if html[i] == "\\":
            i += 2
            continue
        if html[i] == '"':
            break
        i += 1
    raw = html[str_start:i]
    try:
        return json.loads('"' + raw + '"')
    except (json.JSONDecodeError, ValueError):
        return None

def _extract_json_array(clean_text: str, key: str) -> List[Any]:
    """이스케이프가 풀린 순수 JSON 텍스트에서 "key":[...] 배열을 찾아 파싱 (문자열 내 대괄호는 무시)"""
    m = re.search(r'"' + key + r'":\[', clean_text)
    if not m:
        return []
    start = m.end() - 1
    depth = 0
    i = start
    in_string = False
    escaped = False
    while i < len(clean_text):
        ch = clean_text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    break
        i += 1
    segment = clean_text[start:i + 1]
    try:
        return json.loads(segment)
    except json.JSONDecodeError:
        return []

def _strip_html(text: Optional[str]) -> str:
    """prydwen 스킬/세트 효과 설명에 섞인 HTML 태그를 제거하고 엔티티를 언이스케이프"""
    if not text:
        return ""
    plain = re.sub(r"<[^>]+>", "", text)
    return html_module.unescape(plain).strip()

@ttl_cache(CACHE_TTL)
def get_item_details(char_name: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """캐릭터 페이지에 내장된 광추/유물세트 전체 데이터베이스에서 능력치/효과 설명을 추출
    반환: {"light_cones": {영문명: {...}}, "relic_sets": {영문명: {...}}}"""
    tag = _resolve_slug(char_name)
    if not tag:
        return None

    try:
        html = _fetch_character_html(tag)
        chunk = _find_next_f_chunk(html, '\\"lightCones\\":[')
        if chunk is None:
            # CloudFront의 Gatsby 원본 페이지 폴백. 카드 내의 효과 문구를
            # 직접 읽어 최신 Next.js 페이지와 동일한 형태로 만든다.
            soup = BeautifulSoup(html, "html.parser")
            light_cones = {}
            cone_root = soup.find("div", class_=lambda c: c and "build-cones" in c)
            if cone_root:
                for card in cone_root.find_all("div", class_="single-cone"):
                    names = list(dict.fromkeys(
                        img["alt"] for img in card.find_all("img") if img.get("alt")
                    ))
                    if not names:
                        continue
                    desc_el = card.find(class_=lambda c: c and "hsr-set-description" in c)
                    light_cones[names[0]] = {
                        "desc": desc_el.get_text(" ", strip=True) if desc_el else "",
                        "hp_max": None,
                        "atk_max": None,
                        "def_max": None,
                        "rarity": None,
                    }

            relic_sets = {}
            relic_root = soup.find("div", class_=lambda c: c and "build-relics" in c)
            if relic_root:
                for card in relic_root.find_all("div", class_="single-cone"):
                    names = list(dict.fromkeys(
                        img["alt"] for img in card.find_all("img") if img.get("alt")
                    ))
                    if not names:
                        continue
                    desc_el = card.find(class_=lambda c: c and "hsr-set-description" in c)
                    desc = desc_el.get_text(" ", strip=True) if desc_el else ""
                    bonus_2 = re.search(r"\(2\)\s*(.*?)(?=\s*\(4\)|$)", desc)
                    bonus_4 = re.search(r"\(4\)\s*(.*)$", desc)
                    relic_sets[names[0]] = {
                        "type": None,
                        "bonus_2": bonus_2.group(1).strip() if bonus_2 else "",
                        "bonus_4": bonus_4.group(1).strip() if bonus_4 else "",
                    }
            return {"light_cones": light_cones, "relic_sets": relic_sets}

        light_cones = {}
        for lc in _extract_json_array(chunk, "lightCones"):
            data = lc.get("data", {})
            light_cones[lc["name"]] = {
                "desc": _strip_html(data.get("skill_description")),
                "hp_max": data.get("hp_max"),
                "atk_max": data.get("atk_max"),
                "def_max": data.get("def_max"),
                "rarity": data.get("rarity"),
            }

        relic_sets = {}
        for rs in _extract_json_array(chunk, "relicSets"):
            data = rs.get("data", {})
            relic_sets[rs["name"]] = {
                "type": data.get("type"),
                "bonus_2": _strip_html(data.get("bonus_2")),
                "bonus_4": _strip_html(data.get("bonus_4")),
            }

        return {"light_cones": light_cones, "relic_sets": relic_sets}
    except Exception as e:
        print(f"prydwen 아이템 상세 스크래핑 실패 ({char_name}): {e}")
        return None

@ttl_cache(CACHE_TTL)
def _fetch_character_html(tag: str) -> str:
    scraper = cloudscraper.create_scraper()
    try:
        resp = scraper.get(PRYDWEN_CHARACTER_URL.format(tag=tag), timeout=20)
        resp.raise_for_status()
        if "Just a moment..." not in resp.text:
            return resp.text
    except Exception as primary_error:
        print(f"prydwen 기본 호스트 실패 ({tag}), 원본 호스트로 재시도: {primary_error}")

    fallback = scraper.get(PRYDWEN_CLOUDFRONT_URL.format(tag=tag), timeout=30)
    fallback.raise_for_status()
    if "Just a moment..." in fallback.text:
        raise RuntimeError("Prydwen 원본 호스트에서 Cloudflare 차단 페이지 반환")
    return fallback.text

def _fetch_teams_by_tag(tag: str) -> List[Dict[str, Any]]:
    html = _fetch_character_html(tag)
    all_teams = []
    for key in TEAM_KEYS:
        all_teams.extend(_extract_teams(html, key))
    if not all_teams:
        # Gatsby 원본 페이지의 팀 표시는 링크 4개로 구성된다.
        soup = BeautifulSoup(html, "html.parser")
        for row in soup.find_all("div", class_="team-row"):
            slugs = []
            for link in row.find_all("a", href=True):
                marker = "/star-rail/characters/"
                if marker not in link["href"]:
                    continue
                slug = link["href"].split(marker, 1)[1].strip("/")
                if slug and slug not in slugs:
                    slugs.append(slug)
            if slugs:
                all_teams.append({"chars": slugs, "rank": 999})
    return all_teams

@ttl_cache(CACHE_TTL)
def get_all_characters() -> List[Dict[str, str]]:
    """prydwen.gg 전체 캐릭터 목록 페이지에서 (영문명, 슬러그) 목록을 스크래핑"""
    scraper = cloudscraper.create_scraper()
    resp = scraper.get("https://www.prydwen.gg/star-rail/characters", timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    seen = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/star-rail/characters/" not in href:
            continue
        slug = href.rstrip("/").split("/star-rail/characters/")[-1]
        if not slug:
            continue
        img = a.find("img", alt=True)
        if not img or not img["alt"]:
            continue
        seen[slug] = img["alt"]

    return [{"en_name": name, "slug": slug} for slug, name in seen.items()]

# StarRailRes 인덱스에 아직 없거나(콜라보/신규/변형 캐릭터) 표기가 달라서(레이시오/음월/블랙스완/토파즈 등)
# 자동 매칭이 안 되는 캐릭터를 위한 수동 prydwen 슬러그 매핑
MANUAL_SLUG_ALIASES = {
    "망귀인": "tingyun-fugue",
    "레이시오": "dr-ratio",
    "음월": "imbibitor-lunae",
    "블랙스완": "black-swan",
    "토파즈": "topaz",
    "애쉬베일": "ashveil",
    "어벤츄린•웨이브": "aventurine-waveflair",
    "길가메시": "gilgamesh",
    "에바네시아": "evanescia",
    "히메코•노바": "himeko-nova",
    "천야•블레이드": "blade-mortenax",
    "로빈•서머레토": "robin-summeretto",
    "은랑 LV.999": "silver-wolf-lv-999",
    "토오사카 린": "rin-tohsaka",
    "개척자•환락": "trailblazer-elation",
    "개척자•기억": "trailblazer-remembrance",
    "개척자•파멸": "trailblazer-destruction",
    "개척자•보존": "trailblazer-preservation",
    "개척자•화합": "trailblazer-harmony",
    "Mar.7•보존": "march-7th",
    "Mar.7•수렵": "march-7th-swordmaster",
    "에버나이트": "march-7th-evernight",
}

def _resolve_slug(char_name: str) -> Optional[str]:
    """캐릭터 한글명 -> prydwen.gg 슬러그. 수동 별칭 우선, 없으면 StarRailRes 인덱스 대조"""
    if char_name in MANUAL_SLUG_ALIASES:
        return MANUAL_SLUG_ALIASES[char_name]
    slug_map = starrailres.get_character_slug_map()
    name_to_slug = {v: k for k, v in slug_map.items()}
    return name_to_slug.get(char_name)

PATH_KR = {
    "Destruction": "파멸", "Hunt": "수렵", "Erudition": "지식", "Harmony": "화합",
    "Nihility": "허무", "Preservation": "보존", "Abundance": "풍요", "Remembrance": "기억",
    "Elation": "환락",
}
ELEMENT_KR = {
    "Physical": "물리", "Fire": "화", "Ice": "빙", "Lightning": "뇌",
    "Wind": "풍", "Quantum": "양자", "Imaginary": "허수",
}
ROLE_KR = {
    "Damage dealer": "딜러", "Sub-DPS": "서브딜러", "Support": "서포터",
    "Amplifier": "버퍼", "Healer": "힐러", "Shielder": "쉴더", "Debuffer": "디버퍼",
}

def get_character_profile(char_name: str) -> Optional[Dict[str, str]]:
    """prydwen.gg 캐릭터 페이지에서 원소/운명의 길/역할군을 스크래핑해 한글로 변환"""
    tag = _resolve_slug(char_name)
    if not tag:
        return None

    try:
        html = _fetch_character_html(tag)
        soup = BeautifulSoup(html, "html.parser")

        intro = soup.find("div", class_="character-intro")
        element, path = None, None
        if intro:
            text = intro.get_text(" ", strip=True)
            m = re.search(r"from the (\w+) element who follows the Path of (\w+)", text)
            if m:
                element = ELEMENT_KR.get(m.group(1), m.group(1))
                path = PATH_KR.get(m.group(2), m.group(2))

        role = None
        role_el = soup.find(class_="role")
        if role_el:
            role_text = role_el.get_text(strip=True)
            role = ROLE_KR.get(role_text, role_text)

        return {"element": element, "path": path, "role": role}
    except Exception as e:
        print(f"prydwen 프로필 스크래핑 실패 ({char_name}): {e}")
        return None

def _find_h2(soup: BeautifulSoup, text: str):
    # 현재 Next.js 페이지는 h2, CloudFront Gatsby 원본은 h6/
    # div.content-header를 사용한다. 구체적인 헤딩을 먼저 찾는다.
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if heading.get_text(" ", strip=True) == text:
            return heading
    for header in soup.find_all("div", class_=lambda c: c and "content-header" in c):
        if header.get_text(" ", strip=True) == text:
            return header
    return None

def _entries_after(h2, stop_at_next_h2: bool = True):
    """h2 다음부터 다음 h2 전까지의 태그들을 문서 순서대로 반환"""
    if h2 is None:
        return []
    result = []
    for el in h2.find_all_next():
        if stop_at_next_h2 and el.name == "h2":
            break
        result.append(el)
    return result

def _decode_image_src(src: Optional[str]) -> Optional[str]:
    """Next.js 이미지 프록시 URL(/_next/image?url=...)에서 실제 cdn 이미지 URL을 디코딩"""
    if not src:
        return None
    parsed = urllib.parse.urlparse(src)
    qs = urllib.parse.parse_qs(parsed.query)
    if "url" in qs:
        return qs["url"][0]
    return src if src.startswith("http") else None

def _extract_ranked_cones(h2) -> List[Dict[str, Any]]:
    """'Best Light Cones'/'Best Relic Sets' 아래 single-cone 카드에서 (이름, 사용률%, 아이콘URL) 추출"""
    entries = []
    cards = []
    if h2 and h2.name == "h6" and h2.parent and "build-cones" in (h2.parent.get("class") or []):
        # Gatsby에서는 추천 각 항목이 별도 detailed-cones 형제로 배치된다.
        for sibling in h2.find_next_siblings():
            if sibling.name == "h6":
                break
            if sibling.name == "div" and "detailed-cones" in (sibling.get("class") or []):
                cards.extend(sibling.find_all("div", class_="single-cone", recursive=False))
    else:
        cards = [
            el for el in _entries_after(h2)
            if el.name == "div" and "single-cone" in (el.get("class") or [])
        ]

    for card in cards:
        imgs = [img for img in card.find_all("img") if img.get("alt")]
        if not imgs:
            continue
        names = list(dict.fromkeys(img["alt"] for img in imgs))
        icon = _decode_image_src(imgs[0].get("src"))
        pct_box = card.find("div", class_=lambda c: c and "percentage" in c)
        pct = pct_box.find("p").get_text(strip=True) if pct_box and pct_box.find("p") else None
        entries.append({"name": " + ".join(names), "percent": pct, "icon": icon})
    return entries

def _extract_relic_and_ornament(h2) -> tuple:
    """'Best Relic Sets' 아래 detailed-cones 컨테이너 2개(4세트용/장신구용)를 각각 분리 추출"""
    if h2 is None:
        return [], []
    def _cards_to_entries(container):
        entries = []
        for card in container.find_all("div", class_="single-cone", recursive=False):
            imgs = [img for img in card.find_all("img") if img.get("alt")]
            if not imgs:
                continue
            names = list(dict.fromkeys(img["alt"] for img in imgs))
            icon = _decode_image_src(imgs[0].get("src"))
            pct_box = card.find("div", class_=lambda c: c and "percentage" in c)
            pct = pct_box.find("p").get_text(strip=True) if pct_box and pct_box.find("p") else None
            entries.append({"name": " + ".join(names), "percent": pct, "icon": icon})
        return entries

    if h2.name == "h6" and h2.parent and "build-relics" in (h2.parent.get("class") or []):
        def entries_for_section(title):
            heading = next(
                (x for x in h2.parent.find_all("h6", recursive=False)
                 if x.get_text(" ", strip=True) == title),
                None,
            )
            if heading is None:
                return []
            result = []
            for sibling in heading.find_next_siblings():
                if sibling.name == "h6":
                    break
                if sibling.name == "div" and "detailed-cones" in (sibling.get("class") or []):
                    result.extend(_cards_to_entries(sibling))
            return result

        return entries_for_section("Best Relic Sets"), entries_for_section("Best Planetary Sets")

    containers = []
    for el in _entries_after(h2):
        if el.name == "div" and el.get("class") == ["detailed-cones", "moc", "extra", "planar"]:
            containers.append(el)

    relic_entries = _cards_to_entries(containers[0]) if len(containers) > 0 else []
    ornament_entries = _cards_to_entries(containers[1]) if len(containers) > 1 else []
    return relic_entries, ornament_entries

SLOT_KR = {"Body": "상의", "Feet": "신발", "Planar Sphere": "구체", "Link Rope": "매듭"}

def _extract_main_stat_priority(h2) -> Dict[str, str]:
    """'Best Stats' 섹션 상단의 부위별(상의/신발/구체/매듭) 주옵 우선순위를 한글로 추출"""
    if h2 is None:
        return {}
    container = h2.find_next("div", class_=lambda c: c and "main-stats" in c)
    if container is None:
        return {}
    result = {}
    for box in container.find_all("div", class_="box"):
        header_el = box.find(class_=lambda c: c and "stats-header" in c)
        if not header_el:
            continue
        header = header_el.get_text(strip=True)
        full = box.get_text(" ", strip=True)
        rest = full[len(header):].strip()
        slot_kr = SLOT_KR.get(header, header)
        result[slot_kr] = _translate_stat_priority(rest) if rest else "정보 없음"
    return result

def _extract_stat_targets(h2) -> List[str]:
    """'Best Stats' 섹션의 목표 스탯 범위(HP/DEF/ATK/CRIT RATE/CRIT DMG/SPD) 추출"""
    if h2 is None:
        return []
    main_container = h2.find_next("div", class_=lambda c: c and "main-stats" in c)
    if main_container is None:
        return []
    tab_inside = main_container.find_parent("div", class_=lambda c: c and "tab-inside" in c)
    if tab_inside is None:
        return []
    raw_list = tab_inside.find("div", class_=lambda c: c and "raw" in c and "list" in c)
    if raw_list is None:
        return []
    return [li.get_text(" ", strip=True) for li in raw_list.find_all("li")]

STAT_NAME_KR = {
    "HP": "체력", "HP%": "체력%",
    "ATK": "공격력", "ATK%": "공격력%",
    "DEF": "방어력", "DEF%": "방어력%",
    "SPD": "속도", "SPEED": "속도", "BASE SPEED": "기본 속도", "BASE": "기본",
    "CRIT RATE": "치명타 확률", "CRIT DMG": "치명타 피해",
    "EFFECT HIT RATE": "효과 적중", "EFFECT HIT RATING": "효과 적중", "EHR": "효과 적중",
    "EFFECT RES": "효과 저항", "EFF RES": "효과 저항", "EFF RES%": "효과 저항%",
    "BREAK EFFECT": "격파 특효", "BREAK EFFECT%": "격파 특효%",
    "ENERGY REGENERATION RATE": "에너지 회복 효율", "ENERGY REGEN": "에너지 회복 효율",
    "ENERGY REGEN RATE": "에너지 회복 효율", "ER": "에너지 회복 효율",
    "OUTGOING HEALING BOOST": "치유량 보너스", "HEALING BOOST": "치유량 보너스",
    "OUTGOING HEALING": "치유량 보너스",
    "PHYSICAL DMG": "물리 피해량", "FIRE DMG": "화속성 피해량", "ICE DMG": "빙속성 피해량",
    "LIGHTNING DMG": "뇌속성 피해량", "WIND DMG": "풍속성 피해량", "QUANTUM DMG": "양자 피해량",
    "IMAGINARY DMG": "허수 피해량",
    "ANYTHING": "아무거나", "DEFENSIVE STATS": "방어 스탯",
    "OR": "또는", "AND": "그리고",
}

def _translate_stat_priority(text: str) -> str:
    """'SPD (설명) > CRIT RATE = CRIT DMG > ATK%' 같은 영문 부옵/주옵 우선순위 문자열에서
    괄호 설명을 지우고, 영문 단어(구간)만 사전 대조해 한글로 치환 (구분자 >, =, /, [, ] 등은 그대로 둠)"""
    text = re.sub(r"\([^)]*\)", "", text)

    def repl(m: re.Match) -> str:
        word = m.group(0)
        key = re.sub(r"\s+", " ", word).strip().upper()
        return STAT_NAME_KR.get(key, word)

    return re.sub(r"[A-Za-z]+(?: [A-Za-z]+)*", repl, text)

def _extract_substat_priority(soup: BeautifulSoup) -> Optional[str]:
    """'Substats: SPD > CRIT RATE = CRIT DMG > ATK%' 형태의 유효 부옵 우선순위 텍스트를 스크래핑해 한글로 변환"""
    for box in soup.find_all("div", class_=lambda c: c and "sub-stats" in c):
        text = box.get_text(" ", strip=True)
        if text.lower().startswith("substats:"):
            raw = re.sub(r"(?i)^substats:\s*", "", text)
            return _translate_stat_priority(raw)
    return None

def _extract_priority_lines(h2) -> List[str]:
    """'Best Stats' 섹션의 스킬/성유물 우선순위(box.sub-stats) 텍스트 추출"""
    if h2 is None:
        return []
    container = h2.find_next("div", class_=lambda c: c and "build-stats" in c)
    if container is None:
        return []
    lines = []
    for box in container.find_all("div", class_=lambda c: c and "sub-stats" in c):
        t = box.get_text(" ", strip=True)
        if t and t not in lines:
            lines.append(t)
    return lines

@ttl_cache(CACHE_TTL)
def get_character_stats(char_name: str) -> Optional[Dict[str, Any]]:
    """prydwen.gg 캐릭터 페이지에서 광추/유물세트 사용률, 부위별 주옵/스킬/성유물 우선순위를 스크래핑"""
    tag = _resolve_slug(char_name)
    if not tag:
        return None

    try:
        html = _fetch_character_html(tag)
        soup = BeautifulSoup(html, "html.parser")

        stats_h2 = _find_h2(soup, "Best Stats")
        relic_sets, ornament_sets = _extract_relic_and_ornament(_find_h2(soup, "Best Relic Sets"))

        return {
            "light_cones": _extract_ranked_cones(_find_h2(soup, "Best Light Cones"))[:5],
            "relic_sets": relic_sets,
            "ornament_sets": ornament_sets,
            "main_stat_priority": _extract_main_stat_priority(stats_h2),
            "stat_targets": _extract_stat_targets(stats_h2),
            "priority_lines": _extract_priority_lines(stats_h2),
            "substat_priority": _extract_substat_priority(soup),
        }
    except Exception as e:
        print(f"prydwen 스탯 스크래핑 실패 ({char_name}): {e}")
        return None

@ttl_cache(CACHE_TTL)
def get_character_eidolons(char_name: str) -> Optional[List[Dict[str, Any]]]:
    """prydwen.gg 캐릭터 페이지에서 성흔(E1~E6) 이름과 효과 설명을 스크래핑 (영문)"""
    tag = _resolve_slug(char_name)
    if not tag:
        return None

    try:
        html = _fetch_character_html(tag)
        soup = BeautifulSoup(html, "html.parser")

        container = soup.find("div", class_=lambda c: c and "skills" in c and "eidolons" in c)
        if container is None:
            return None

        eidolons = []
        for i, card in enumerate(container.find_all("div", class_="box"), start=1):
            name_el = card.find(class_=lambda c: c and "skill-name" in c)
            desc_el = card.find("div", class_=lambda c: c and "skill-with-coloring" in c)
            if not name_el or not desc_el:
                continue
            eidolons.append({
                "level": i,
                "name": name_el.get_text(strip=True),
                "desc": desc_el.get_text(" ", strip=True),
            })
        return eidolons or None
    except Exception as e:
        print(f"prydwen 성흔 스크래핑 실패 ({char_name}): {e}")
        return None

@ttl_cache(CACHE_TTL)
def get_character_intro(char_name: str) -> Optional[str]:
    """prydwen.gg 캐릭터 페이지 상단의 캐릭터 소개문을 스크래핑 (영문)"""
    tag = _resolve_slug(char_name)
    if not tag:
        return None

    try:
        html = _fetch_character_html(tag)
        soup = BeautifulSoup(html, "html.parser")

        container = (
            soup.find("div", class_="char-intro")
            or soup.find("div", class_="character-intro")
        )
        if container is None:
            return None
        text = container.get_text(" ", strip=True)
        return text or None
    except Exception as e:
        print(f"prydwen 캐릭터 소개 스크래핑 실패 ({char_name}): {e}")
        return None

@ttl_cache(CACHE_TTL)
def get_character_portrait(char_name: str) -> Optional[str]:
    """StarRailRes 인덱스에 없는 캐릭터(콜라보/변형 등)를 위한 prydwen 페이지 og:image 썸네일 URL"""
    tag = _resolve_slug(char_name)
    if not tag:
        return None

    try:
        html = _fetch_character_html(tag)
        soup = BeautifulSoup(html, "html.parser")
        og = soup.find("meta", property="og:image")
        return og.get("content") if og else None
    except Exception as e:
        print(f"prydwen 썸네일 스크래핑 실패 ({char_name}): {e}")
        return None

KIT_LABELS = ["기본 공격", "전투 스킬", "필살기", "특수 능력", "비전투 스킬"]

@ttl_cache(CACHE_TTL)
def get_character_kit(char_name: str) -> Optional[List[Dict[str, Any]]]:
    """prydwen.gg 캐릭터 페이지에서 기본공격/스킬/필살기/특수능력/비전투스킬 설명을 스크래핑 (영문)"""
    tag = _resolve_slug(char_name)
    if not tag:
        return None

    try:
        html = _fetch_character_html(tag)
        soup = BeautifulSoup(html, "html.parser")

        container = None
        for el in soup.find_all("div", class_=lambda c: c and "skills" in c):
            classes = el["class"]
            if "traces" not in classes and "eidolons" not in classes:
                container = el
                break
        if container is None:
            return None

        kit = []
        for i, card in enumerate(container.find_all("div", class_="box")):
            name_el = card.find(class_=lambda c: c and "skill-name" in c)
            desc_el = card.find("div", class_=lambda c: c and "skill-with-coloring" in c)
            if not name_el or not desc_el:
                continue
            label = KIT_LABELS[i] if i < len(KIT_LABELS) else f"스킬 {i + 1}"
            kit.append({
                "label": label,
                "name": name_el.get_text(strip=True),
                "desc": desc_el.get_text(" ", strip=True),
            })
        return kit or None
    except Exception as e:
        print(f"prydwen 스킬 스크래핑 실패 ({char_name}): {e}")
        return None

def _slug_to_name(slug: str, slug_map: Dict[str, str]) -> str:
    if slug in slug_map:
        return slug_map[slug]
    return " ".join(part.capitalize() for part in slug.split("-"))

def get_party_recommendation(char_name: str, limit: int = 3) -> Optional[List[Dict[str, Any]]]:
    """반환: [{"display": "캐릭1 · 캐릭2 · ...", "chars": [(name, slug), ...]}, ...]"""
    tag = _resolve_slug(char_name)
    if not tag:
        return None

    try:
        teams = _fetch_teams_by_tag(tag)
    except Exception as e:
        print(f"팀 추천 실패 ({char_name}): {e}")
        return None

    if not teams:
        return None

    teams.sort(key=lambda t: t["rank"])

    slug_map = starrailres.get_character_slug_map()
    results = []
    seen = set()
    for team in teams:
        combo = tuple(sorted(team["chars"]))
        if combo in seen:
            continue
        seen.add(combo)
        named = [(_slug_to_name(slug, slug_map), slug) for slug in team["chars"]]
        results.append({
            "display": " · ".join(name for name, _ in named),
            "chars": named,
        })
        if len(results) >= limit:
            break

    return results or None
