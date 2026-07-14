import cloudscraper
import time
from bs4 import BeautifulSoup
from functools import wraps
from typing import List, Dict

CACHE = {}
CACHE_TTL = 1 * 3600

CODES_URL = "https://honkai-star-rail.fandom.com/wiki/Redemption_Code"

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

def _clean_duration(cell) -> str:
    cell = BeautifulSoup(str(cell), "html.parser")
    for tag in cell.find_all("span", class_="mobile-only"):
        tag.decompose()
    for tag in cell.find_all("span", class_="custom-tt-wrapper"):
        tag.decompose()
    text = cell.get_text(" ", strip=True)
    return "상시" if "indefinite" in text else text

@ttl_cache(CACHE_TTL)
def get_redemption_codes() -> List[Dict[str, str]]:
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(CODES_URL, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="wikitable")
        tbody = table.find("tbody")
        rows = (tbody or table).find_all("tr")[1:]

        codes = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            duration = _clean_duration(cells[3])
            if "Expired" in duration:
                continue

            code_tag = cells[0].find("code")
            if not code_tag:
                continue

            code = code_tag.get_text(strip=True)
            link_tag = cells[0].find("a", href=lambda h: h and "hoyoverse.com/gift" in h)
            link = link_tag["href"] if link_tag else f"https://hsr.hoyoverse.com/gift?code={code}"

            reward = ", ".join(
                span.get_text(strip=True)
                for span in cells[2].find_all("span", class_="item-text")
            )

            codes.append({
                "code": code,
                "reward": reward or "정보 없음",
                "duration": duration,
                "link": link,
            })

        return codes
    except Exception as e:
        print(f"리딤코드 조회 실패: {e}")
        return []
