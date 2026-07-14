import json
from pathlib import Path
from typing import Optional

CONFIG_FILE = Path(__file__).resolve().parent.parent / "data" / "bot_config.json"

def _load() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save(config: dict):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def get_notify_channel(guild_id: int) -> Optional[int]:
    config = _load()
    channel_id = config.get(str(guild_id), {}).get("notify_channel_id")
    return int(channel_id) if channel_id else None

def set_notify_channel(guild_id: int, channel_id: int):
    config = _load()
    config.setdefault(str(guild_id), {})["notify_channel_id"] = channel_id
    _save(config)
