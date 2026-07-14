import os
import json
import hashlib
import requests
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_FILE = BASE_DIR / "data" / "translation_cache.json"

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

_cache = None

def _load_cache() -> dict:
    global _cache
    if _cache is None:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        else:
            _cache = {}
    return _cache

def _save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def translate_to_ko(
    text: str,
    concise: bool = False,
    name_mode: bool = False,
    retry: bool = False,
) -> str:
    """Gemini(저가 모델)로 영어 텍스트를 한국어로 번역. 키 없거나 실패하면 원문 그대로 반환
    concise=True면 핵심만 한 문장으로 간단히 요약 번역함
    name_mode=True면 캐릭터/광추/유물세트 등 고유명사 이름만 짧게 번역함 (설명문으로 착각해 엉뚱한 내용을 생성하는 것을 방지)"""
    if not text:
        return text

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return text

    cache = _load_cache()
    mode_prefix = "name:" if name_mode else ("concise:" if concise else "")
    if retry:
        mode_prefix = "retry:v3:" + mode_prefix
    key = hashlib.sha256((mode_prefix + text).encode("utf-8")).hexdigest()
    if key in cache:
        return cache[key]

    if retry:
        instruction = (
            "다음은 붕괴: 스타레일 게임 텍스트의 1차 한국어 번역 결과인데, 번역되지 않은 영어 구절이 남아 있어. "
            "영어 구절까지 포함해 문장 전체를 자연스러운 한국어로 다시 번역해줘. "
            "HP, ATK, DEF, SPD, CRIT, EHR, ERR 같은 게임 스탯 약어와 숫자·기호는 그대로 남겨도 되지만, "
            "pt와 공식 캐릭터명 'Dr. 레이시오'는 그대로 두어도 돼. "
            "그 외 영문 고유명사·스킬명은 뜻을 번역하거나 한글 음역만 남기고 괄호 속 영문 원어 병기도 제거해. "
            "예를 들어 '불길을 통한 인내(Tenax Per Ignem)'는 '불길을 통한 인내'로만 출력해. "
            "일반 영어 단어나 문장은 남기지 마. 번역 결과만 한 줄로 출력해.\n\n"
        )
    elif name_mode:
        instruction = (
            "다음은 붕괴: 스타레일의 캐릭터/광추/유물 세트 등의 고유명사(이름)야. "
            "설명이나 효과 텍스트가 아니라 순수 이름이니, 이 이름 하나만 한국 커뮤니티에서 통용되는 한글 표기로 번역해줘. "
            "번역된 이름 하나만 딱 출력하고, 다른 설명이나 문장을 절대 추가하지 마.\n\n"
        )
    elif concise:
        instruction = (
            "다음 붕괴: 스타레일 성흔(Eidolon) 효과 설명을 핵심만 한국어 한 문장으로 간단히 요약 번역해줘. "
            "수치, 조건은 살리되 군더더기 설명은 빼고, 게임 용어(스킬명, 스탯명 등)는 한국 커뮤니티에서 통용되는 표현을 써. "
            "번역 결과 문장만 딱 출력해. 여러 버전 제시하지 말고, 설명/주석/마크다운/따옴표 붙이지 말고, "
            "요약문 단 하나만 줄바꿈 없이 출력해.\n\n"
        )
    else:
        instruction = (
            "다음 붕괴: 스타레일 게임 텍스트를 자연스러운 한국어 한 문단으로 번역해줘. "
            "게임 용어(스킬명, 스탯명 등)는 한국 커뮤니티에서 통용되는 표현을 쓰고, "
            "번역 결과 문장만 딱 출력해. 여러 버전 제시하지 말고, 설명/주석/마크다운/따옴표 붙이지 말고, "
            "번역문 단 하나만 줄바꿈 없이 출력해.\n\n"
        )

    try:
        resp = requests.post(
            GEMINI_URL,
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": instruction + text}]}]},
            timeout=15
        )
        resp.raise_for_status()
        translated = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        cache[key] = translated
        _save_cache(cache)
        return translated
    except Exception as e:
        print(f"Gemini 번역 실패: {e}")
        return text
