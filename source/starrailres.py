import re
import requests
import time
from functools import wraps
from pathlib import Path
from typing import Optional, Dict, Any

CACHE = {}
CACHE_TTL = 6 * 3600

BASE = "https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/index_new/kr"
BASE_EN = "https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/index_new/en"
CDN_BASE = "https://cdn.jsdelivr.net/gh/Mar-7th/StarRailRes@master"

ICON_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "icon_cache"

def ttl_cache(seconds: int):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}_{args}"
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

@ttl_cache(CACHE_TTL)
def _load_index(filename: str, base: str = BASE) -> Dict[str, Any]:
    try:
        resp = requests.get(f"{base}/{filename}", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"StarRailRes 인덱스 로드 실패 ({filename}): {e}")
        return {}

def _slugify(name: str) -> str:
    """영문 이름을 prydwen.gg 스타일 URL 슬러그로 변환 (예: 'Dan Heng • Permansor Terrae' -> 'dan-heng-permansor-terrae')"""
    slug = name.lower().replace("•", " ").replace(".", "")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug

def _candidate_names(value: str) -> list:
    """시트 셀에 여러 후보가 줄바꿈/쉼표로 들어있으면 전부 리스트로 분리"""
    return [p.strip() for p in value.replace(",", "\n").split("\n") if p.strip()]

def _find_icon(index: Dict[str, Any], name: str) -> Optional[str]:
    for target in _candidate_names(name):
        for entry in index.values():
            entry_name = entry.get("name", "")
            if entry_name == target or target in entry_name:
                return f"{CDN_BASE}/{entry['icon']}"
    return None

def get_light_cone_icon(name: str) -> Optional[str]:
    if not name:
        return None
    return _find_icon(_load_index("light_cones.json"), name)

@ttl_cache(CACHE_TTL)
def get_light_cone_en_to_kr_map() -> Dict[str, str]:
    """광추 영문명 -> 한글명 매핑 (같은 id의 kr/en 인덱스를 대조)"""
    kr_index = _load_index("light_cones.json", BASE)
    en_index = _load_index("light_cones.json", BASE_EN)
    result = {}
    for char_id, kr_entry in kr_index.items():
        en_entry = en_index.get(char_id)
        if en_entry and en_entry.get("name") and kr_entry.get("name"):
            result[en_entry["name"]] = kr_entry["name"]
    return result

def get_relic_set_icon(name: str) -> Optional[str]:
    if not name:
        return None
    return _find_icon(_load_index("relic_sets.json"), name)

@ttl_cache(CACHE_TTL)
def get_relic_set_en_to_kr_map() -> Dict[str, str]:
    """유물/장신구 세트 영문명 -> 한글명 매핑 (같은 id의 kr/en 인덱스를 대조)"""
    kr_index = _load_index("relic_sets.json", BASE)
    en_index = _load_index("relic_sets.json", BASE_EN)
    result = {}
    for set_id, kr_entry in kr_index.items():
        en_entry = en_index.get(set_id)
        if en_entry and en_entry.get("name") and kr_entry.get("name"):
            result[en_entry["name"]] = kr_entry["name"]
    return result

@ttl_cache(CACHE_TTL)
def get_character_slug_map() -> Dict[str, str]:
    """prydwen.gg 스타일 슬러그(영문명 기반) -> 캐릭터 한글명 매핑. 변형 캐릭(위상변이 등)까지 커버함"""
    kr_index = _load_index("characters.json", BASE)
    en_index = _load_index("characters.json", BASE_EN)

    slug_map = {}
    for char_id, kr_entry in kr_index.items():
        en_entry = en_index.get(char_id)
        if not en_entry or not en_entry.get("name"):
            continue
        slug_map[_slugify(en_entry["name"])] = kr_entry["name"]
    return slug_map

@ttl_cache(CACHE_TTL)
def get_character_icon_by_slug_map() -> Dict[str, str]:
    """prydwen.gg 스타일 슬러그 -> 캐릭터 아이콘 이미지 URL"""
    kr_index = _load_index("characters.json", BASE)
    en_index = _load_index("characters.json", BASE_EN)

    result = {}
    for char_id, kr_entry in kr_index.items():
        en_entry = en_index.get(char_id)
        if not en_entry or not en_entry.get("name") or not kr_entry.get("icon"):
            continue
        result[_slugify(en_entry["name"])] = f"{CDN_BASE}/{kr_entry['icon']}"
    return result

@ttl_cache(CACHE_TTL)
def get_character_icon_by_name_map() -> Dict[str, str]:
    """캐릭터 한글명 -> 캐릭터 아이콘 이미지 URL"""
    kr_index = _load_index("characters.json", BASE)
    return {
        entry["name"]: f"{CDN_BASE}/{entry['icon']}"
        for entry in kr_index.values()
        if entry.get("icon")
    }

# 시트 표기와 StarRailRes 인덱스 표기가 달라서 매칭 안 되는 캐릭터용 별칭
ICON_NAME_ALIASES = {
    "망귀인": "정운 • 일탈",
    "레이시오": "Dr. 레이시오",
    "음월": "단항•음월",
    "블랙스완": "블랙 스완",
    "토파즈": "토파즈&복순이",
}

def get_character_icon_by_name(name: str) -> Optional[str]:
    icon_map = get_character_icon_by_name_map()
    if name in icon_map:
        return icon_map[name]
    alias = ICON_NAME_ALIASES.get(name)
    return icon_map.get(alias) if alias else None

def fetch_icon_bytes(url: str) -> Optional[bytes]:
    """아이콘 이미지를 로컬 캐시에서 읽고, 없으면 다운로드해서 저장 후 반환"""
    if not url:
        return None

    filename = url.replace(f"{CDN_BASE}/", "").replace("/", "_")
    path = ICON_CACHE_DIR / filename

    if path.exists():
        return path.read_bytes()

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        return resp.content
    except Exception as e:
        print(f"아이콘 다운로드 실패 ({url}): {e}")
        return None
