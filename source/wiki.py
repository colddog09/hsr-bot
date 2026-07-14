import json
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
WIKI_FILE = BASE_DIR / "data" / "character_wiki.json"

_cache = None


def load() -> dict:
    global _cache
    if _cache is None:
        if WIKI_FILE.exists():
            with open(WIKI_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        else:
            _cache = {}
    return _cache


def get_character(name: str) -> Optional[dict]:
    return load().get(name)


def reload():
    global _cache
    _cache = None
