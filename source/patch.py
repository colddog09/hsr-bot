import cloudscraper
import re
import time
from datetime import datetime, date, timedelta
from functools import wraps
from typing import Optional, Dict, Any

CACHE = {}
CACHE_TTL = 6 * 3600

BANNERS_URL = "https://www.prydwen.gg/star-rail/banners"

def ttl_cache(seconds: int):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}"
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

def _parse_date(text: str) -> Optional[date]:
    text = text.replace("Expected", "").strip()
    try:
        return datetime.strptime(text, "%b %d, %Y").date()
    except ValueError:
        return None

def _extract_section(html: str, section_id: str) -> Optional[Dict[str, Any]]:
    idx = html.find(f'id="{section_id}"')
    if idx == -1:
        return None

    chunk = html[idx:idx + 2000]
    m = re.search(
        r'<h3>Patch ([\d.]+)(?: Phase (\d))?</h3>.*?data-range-na="([^"]+)"',
        chunk, re.S
    )
    if not m:
        print(f"패치 일정 파싱 실패: id={section_id} 구간에서 패턴 불일치")
        return None

    version, phase, date_range = m.groups()

    if "–" in date_range:
        start_text, end_text = [p.strip() for p in date_range.split("–")]
    else:
        start_text, end_text = date_range, None

    return {
        "version": version,
        "phase": int(phase) if phase else None,
        "start_date": _parse_date(start_text),
        "end_date": _parse_date(end_text) if end_text else None,
        "raw_range": date_range,
    }

PHASE_DAYS = 21  # 절반 패치(뽑기 배너 교체) 주기
CYCLE_DAYS = 42  # 전체 패치(엔드게임 모드 로테이션) 주기

# 6주 주기 안에서 각 모드가 도는 시점(패치 시작일 기준 오프셋, 일 단위)
MODE_OFFSETS = {
    "종말의 부재": 0,    # Apocalyptic Shadow
    "허구서사": 14,       # Pure Fiction
    "혼돈의 기억": 28,    # Memory of Chaos
    "이상 중재": 0,        # Anomaly Arbitration (버전 시작과 동일)
}

def _next_occurrence(cycle_start: date, offset_days: int) -> date:
    candidate = cycle_start + timedelta(days=offset_days)
    while candidate < date.today():
        candidate += timedelta(days=CYCLE_DAYS)
    return candidate

@ttl_cache(CACHE_TTL)
def get_patch_schedule() -> Optional[Dict[str, Any]]:
    """
    현재/다음 패치 일정 + 파생 정보 조회.
    반환: {
        "current": {...}, "next": {...},
        "gacha_update": date,       # 다음 뽑기 배너 교체일 (항상 실측)
        "version_update": date,     # 다음 정식 버전(전체 패치) 시작일
        "version_update_estimated": bool,  # 실측 데이터가 없어 3주 주기로 추정한 값이면 True
        "mode_updates": {"혼돈의 기억": date, "허구서사": date, "종말의 부재": date, "이상 중재": date},
    }
    """
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(BANNERS_URL, timeout=20)
        resp.raise_for_status()
        html = resp.text

        current = _extract_section(html, "current-banners")
        next_patch = _extract_section(html, "next-banner")

        if not current and not next_patch:
            return None

        result = {"current": current, "next": next_patch}

        gacha_update = None
        if next_patch and next_patch.get("start_date"):
            gacha_update = next_patch["start_date"]
        elif current and current.get("end_date"):
            gacha_update = current["end_date"]
        result["gacha_update"] = gacha_update

        version_update = None
        version_estimated = False
        if next_patch and current and next_patch.get("version") != current.get("version"):
            version_update = next_patch.get("start_date")
        elif gacha_update:
            version_update = gacha_update + timedelta(days=PHASE_DAYS)
            version_estimated = True

        result["version_update"] = version_update
        result["version_update_estimated"] = version_estimated

        cycle_start = None
        if current and current.get("start_date"):
            if current.get("phase") == 2:
                cycle_start = current["start_date"] - timedelta(days=PHASE_DAYS)
            else:
                cycle_start = current["start_date"]

        mode_updates = {}
        if cycle_start:
            for mode_name, offset_days in MODE_OFFSETS.items():
                mode_updates[mode_name] = _next_occurrence(cycle_start, offset_days)
        result["mode_updates"] = mode_updates

        return result
    except Exception as e:
        print(f"패치 일정 조회 실패: {e}")
        return None
