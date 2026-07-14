import json
import requests
from typing import Any, Dict, List, Optional

NEWS_URL = "https://bbs-api-os.hoyolab.com/community/post/wapi/getNewsList"
POST_FULL_URL = "https://bbs-api-os.hoyolab.com/community/post/wapi/getPostFull"
GIDS_HSR = 6

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "x-rpc-language": "ko-kr",
}

def get_latest_announcements(limit: int = 10) -> List[Dict[str, Any]]:
    """호요랩 붕괴: 스타레일 공식 공지 최신순 조회"""
    try:
        resp = requests.get(
            NEWS_URL,
            params={"gids": GIDS_HSR, "page_size": limit, "type": 1},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("list", [])

        result = []
        for item in posts:
            post = item.get("post", {})
            post_id = post.get("post_id")
            if not post_id:
                continue
            result.append({
                "post_id": int(post_id),
                "subject": post.get("subject", "제목 없음"),
                "content": post.get("content", ""),
                "created_at": post.get("created_at"),
                "url": f"https://www.hoyolab.com/article/{post_id}",
            })
        return result
    except Exception as e:
        print(f"호요랩 공지 조회 실패: {e}")
        return []

def get_post_cover_image(post_id: int) -> Optional[str]:
    """게시글 본문(structured_content)에서 첫 번째 이미지를 배너용으로 추출"""
    try:
        resp = requests.get(
            POST_FULL_URL,
            params={"post_id": post_id},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        post = resp.json().get("data", {}).get("post", {}).get("post", {})
        structured = post.get("structured_content", "")
        if not structured:
            return None

        blocks = json.loads(structured)
        for block in blocks:
            insert = block.get("insert")
            if isinstance(insert, dict) and insert.get("image"):
                return insert["image"]
        return None
    except Exception as e:
        print(f"호요랩 게시글 이미지 조회 실패 ({post_id}): {e}")
        return None
