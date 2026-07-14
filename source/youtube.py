import json
import re
from typing import Any, Dict, List

import requests


CHANNEL_HANDLE = "Honkaistarrail_kr"
CHANNEL_URL = f"https://www.youtube.com/@{CHANNEL_HANDLE}"
CHANNEL_VIDEOS_URL = f"{CHANNEL_URL}/videos"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def _initial_data(html: str) -> dict:
    match = re.search(r"var ytInitialData = ({.*?});</script>", html)
    if not match:
        match = re.search(r"ytInitialData\s*=\s*({.*?});</script>", html)
    if not match:
        raise ValueError("YouTube ytInitialData를 찾을 수 없습니다")
    return json.loads(match.group(1))


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _text(value: dict) -> str:
    if not isinstance(value, dict):
        return ""
    if value.get("content"):
        return str(value["content"])
    return "".join(run.get("text", "") for run in value.get("runs", []))


def _parse_videos(html: str, limit: int = 10) -> List[Dict[str, str]]:
    data = _initial_data(html)
    videos = []
    seen = set()

    for node in _walk(data):
        model = node.get("lockupViewModel")
        if model:
            video_id = model.get("contentId")
            metadata = model.get("metadata", {}).get("lockupMetadataViewModel", {})
            title = _text(metadata.get("title", {}))
            rows = metadata.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
            published = ""
            if rows:
                parts = rows[0].get("metadataParts", [])
                if len(parts) >= 2:
                    published = _text(parts[-1].get("text", {}))
        else:
            # YouTube의 기존 videoRenderer 포맷도 함께 지원한다.
            model = node.get("videoRenderer") or node.get("gridVideoRenderer")
            if not model:
                continue
            video_id = model.get("videoId")
            title = _text(model.get("title", {}))
            published = _text(model.get("publishedTimeText", {}))

        if not video_id or not title or video_id in seen:
            continue
        seen.add(video_id)
        videos.append({
            "video_id": video_id,
            "title": title,
            "published": published,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        })
        if len(videos) >= limit:
            break

    return videos


def get_latest_videos(limit: int = 10) -> List[Dict[str, str]]:
    """붕괴: 스타레일 한국 공식 채널의 최신 영상을 반환."""
    try:
        response = requests.get(CHANNEL_VIDEOS_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return _parse_videos(response.text, limit)
    except Exception as e:
        print(f"YouTube 최신 영상 조회 실패: {e}")
        return []
