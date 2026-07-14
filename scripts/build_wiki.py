import json
import re
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from source import prydwen, starrailres, translate

OUTPUT_FILE = BASE_DIR / "data" / "character_wiki.html"
JSON_OUTPUT_FILE = BASE_DIR / "data" / "character_wiki.json"
PROGRESS_FILE = BASE_DIR / "data" / "wiki_build_progress.log"

RELIC_SLOTS = ["상의", "신발", "구체", "매듭"]

# 통용 스탯 약어는 영문 잔여로 보지 않고, 소문자가 포함된
# 일반 영어 단어가 남은 경우만 재번역한다.
_ENGLISH_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_ALLOWED_ENGLISH_WORDS = {"pt", "Dr"}
_PROSE_FIELDS = {"description", "effect", "bonus_2", "bonus_4", "substat_priority", "desc"}
_PROSE_CONTAINERS = {"relic_opts", "stat_targets"}


def _has_residual_english(text):
    """한국어 번역문에 일반 영어 구절이 남았는지 감지.

    HP/ATK/SPD 같은 대문자 약어는 허용하고, Rate/until/Build 등
    소문자가 든 영문 단어는 재번역 대상으로 본다.
    """
    if not isinstance(text, str):
        return False
    return any(
        not word.isupper() and word not in _ALLOWED_ENGLISH_WORDS
        for word in _ENGLISH_WORD_RE.findall(text)
    )


def _retry_residual_english(data):
    """완성된 캐릭터 데이터의 설명형 필드를 최종 검수하고 재번역.

    반환값은 (재번역 시도 횟수, 재번역 후에도 영어가 남은 횟수).
    """
    retried = 0
    remaining = 0

    def retry_value(value, concise=False):
        nonlocal retried, remaining
        if not isinstance(value, str) or not _has_residual_english(value):
            return value
        retried += 1
        result = translate.translate_to_ko(value, concise=concise, retry=True)
        if _has_residual_english(result):
            remaining += 1
        return result

    def walk(value, parent_key=None):
        if isinstance(value, dict):
            for key, child in value.items():
                if parent_key in _PROSE_CONTAINERS and isinstance(child, str):
                    value[key] = retry_value(child)
                elif key in _PROSE_FIELDS:
                    value[key] = retry_value(child, concise=(key == "desc"))
                elif key in _PROSE_CONTAINERS:
                    value[key] = walk(child, parent_key=key)
                elif isinstance(child, (dict, list)):
                    walk(child, parent_key=key)
            return value
        if isinstance(value, list):
            for i, child in enumerate(value):
                value[i] = walk(child, parent_key=parent_key)
            return value
        if parent_key in _PROSE_CONTAINERS:
            return retry_value(value)
        return value

    walk(data)
    return retried, remaining


def _translate_stat_target_line(line):
    """'CRIT RATE: 80%+ (comment)' 형태의 목표 스탯 줄에서 스탯명은 사전으로, 나머지는 영어가 섞여 있으면
    전체를 통번역함 (단순 숫자/기호만 있으면 API 호출 없이 그대로 둠)"""
    if ":" not in line:
        return translate.translate_to_ko(line) if re.search(r"[A-Za-z]{2,}", line) else line
    label, _, rest = line.partition(":")
    kr_label = prydwen.STAT_NAME_KR.get(label.strip().upper(), label.strip())
    rest = rest.strip()

    if re.search(r"[A-Za-z]{2,}", rest):
        rest = translate.translate_to_ko(rest)

    return f"{kr_label}: {rest}"


def _translate_name(en_name):
    """고유명사(캐릭터/광추/유물세트) 영문명을 한글로 번역"""
    return translate.translate_to_ko(en_name, name_mode=True)


def _build_slug_to_kr_name_map(all_characters):
    """prydwen 슬러그 -> 한글 캐릭터명. StarRailRes 인덱스 + 수동 별칭(MANUAL_SLUG_ALIASES) 우선,
    둘 다 없는 신규/콜라보 캐릭터는 영문명을 번역해서 채움"""
    merged = dict(starrailres.get_character_slug_map())
    for kr_name, slug in prydwen.MANUAL_SLUG_ALIASES.items():
        merged[slug] = kr_name

    for c in all_characters:
        if c["slug"] not in merged:
            merged[c["slug"]] = _translate_name(c["en_name"])

    return merged


def _log(msg):
    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


def _portrait_for(name):
    return starrailres.get_character_icon_by_name(name) or prydwen.get_character_portrait(name)


def gather_character(name, slug_to_kr_name):
    data = {"name": name}

    profile = prydwen.get_character_profile(name) or {}
    data["path"] = profile.get("path") or ""
    data["element"] = profile.get("element") or ""
    role = profile.get("role")
    if role and re.search(r"[A-Za-z]", role):
        role = _translate_name(role)
    data["role"] = role or ""

    data["portrait"] = _portrait_for(name)

    intro = prydwen.get_character_intro(name)
    data["description"] = translate.translate_to_ko(intro) if intro else None

    stats = prydwen.get_character_stats(name)
    item_details = prydwen.get_item_details(name) or {"light_cones": {}, "relic_sets": {}}
    lc_details = item_details["light_cones"]
    rs_details = item_details["relic_sets"]

    # weapon
    en_to_kr = starrailres.get_light_cone_en_to_kr_map()
    weapons = []
    if stats and stats.get("light_cones"):
        for lc in stats["light_cones"]:
            en_name = lc["name"]
            kr_name = en_to_kr.get(en_name) or _translate_name(en_name)
            icon = lc.get("icon") or starrailres.get_light_cone_icon(kr_name)
            detail = lc_details.get(en_name)
            weapons.append({
                "name": kr_name,
                "icon": icon,
                "effect": translate.translate_to_ko(detail["desc"]) if detail and detail.get("desc") else None,
                "hp": detail.get("hp_max") if detail else None,
                "atk": detail.get("atk_max") if detail else None,
                "def": detail.get("def_max") if detail else None,
            })
    data["weapons"] = weapons

    # relic set / ornament set (사용률 1위)
    relic_en_to_kr = starrailres.get_relic_set_en_to_kr_map()

    def _top_set_detail(entries, bonus_keys):
        if not entries:
            return None
        top = entries[0]
        en_name = top["name"]
        kr_name = relic_en_to_kr.get(en_name) or _translate_name(en_name)
        icon = top.get("icon") or starrailres.get_relic_set_icon(kr_name)
        detail = rs_details.get(en_name, {})
        result = {"name": kr_name, "icon": icon}
        for key in bonus_keys:
            text = detail.get(key)
            result[key] = translate.translate_to_ko(text) if text else None
        return result

    relic_detail = _top_set_detail(stats.get("relic_sets") if stats else None, ["bonus_2", "bonus_4"])
    ornament_detail = _top_set_detail(stats.get("ornament_sets") if stats else None, ["bonus_2"])

    data["relic_set"] = relic_detail["name"] if relic_detail else ""
    data["ornament_set"] = ornament_detail["name"] if ornament_detail else ""
    data["relic_icon"] = relic_detail["icon"] if relic_detail else None
    data["ornament_icon"] = ornament_detail["icon"] if ornament_detail else None
    data["relic_detail"] = relic_detail
    data["ornament_detail"] = ornament_detail

    main_stat_priority = stats.get("main_stat_priority") if stats else {}
    data["relic_opts"] = {slot: main_stat_priority.get(slot, "정보 없음") for slot in RELIC_SLOTS}

    data["substat_priority"] = stats.get("substat_priority") if stats else None

    # eidolons
    eidolons = prydwen.get_character_eidolons(name)
    eidolon_entries = []
    if eidolons:
        for e in [x for x in eidolons if x["level"] in (1, 2, 4, 6)]:
            eidolon_entries.append({
                "level": e["level"],
                "name": translate.translate_to_ko(e["name"]),
                "desc": translate.translate_to_ko(e["desc"], concise=True),
            })
    data["eidolons"] = eidolon_entries

    # trace targets
    if stats and stats.get("stat_targets"):
        data["stat_targets"] = [_translate_stat_target_line(l) for l in stats["stat_targets"]]
    else:
        data["stat_targets"] = None

    # party recommendation
    teams = prydwen.get_party_recommendation(name)
    party_teams = []
    if teams:
        for team in teams:
            members = []
            for member_name, slug in team.get("chars", []):
                kr_name = slug_to_kr_name.get(slug, member_name)
                members.append({"name": kr_name, "portrait": _portrait_for(kr_name)})
            display = " · ".join(m["name"] for m in members) if members else team.get("display", "")
            party_teams.append({"display": display, "members": members})
    data["party_teams"] = party_teams

    return data


def render_html(all_data):
    def esc(s):
        if s is None:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    nav_items = "".join(f'<a href="#char-{i}">{esc(d["name"])}</a>' for i, d in enumerate(all_data))

    sections = []
    for i, d in enumerate(all_data):
        weapons_html = ""
        for w in d["weapons"]:
            icon_html = f'<img src="{esc(w["icon"])}" class="wicon" alt="">' if w.get("icon") else ""
            weapons_html += f'<span class="wpn" title="{esc(w.get("effect"))}">{icon_html}{esc(w["name"])}</span>'

        eidolons_html = ""
        for e in d["eidolons"]:
            eidolons_html += f'<div class="eidolon"><b>E{e["level"]} {esc(e["name"])}</b><p>{esc(e["desc"])}</p></div>'

        relic_opts_html = "".join(
            f"<li><b>{k}:</b> {esc(v) or '정보 없음'}</li>" for k, v in d["relic_opts"].items()
        )

        stat_targets_html = ""
        if d["stat_targets"]:
            stat_targets_html = "<ul>" + "".join(f"<li>{esc(s)}</li>" for s in d["stat_targets"]) + "</ul>"
        else:
            stat_targets_html = "<p>정보 없음</p>"

        portrait_html = f'<img src="{esc(d["portrait"])}" class="portrait" alt="">' if d["portrait"] else ""

        party_html = ""
        if d.get("party_teams"):
            rows = [f"<li>{esc(team['display'])}</li>" for team in d["party_teams"]]
            party_html = f'<h3>추천 파티</h3><ul>{"".join(rows)}</ul>'

        desc_html = f'<p class="desc">{esc(d["description"])}</p>' if d["description"] else ""

        summary = " · ".join(filter(None, [d.get("element"), d.get("path"), d.get("role")])) or "정보 없음"

        section = f'''
        <section id="char-{i}" class="char-card">
            <div class="char-header">
                {portrait_html}
                <div>
                    <h2>{esc(d["name"])}</h2>
                    <p class="summary">{esc(summary)}</p>
                </div>
            </div>
            {desc_html}
            <h3>광추</h3>
            <div class="weapons">{weapons_html or "정보 없음"}</div>
            <h3>유물 / 장신구</h3>
            <p><b>4세트:</b> {esc(d["relic_set"]) or "정보 없음"} &nbsp; <b>장신구:</b> {esc(d["ornament_set"]) or "정보 없음"}</p>
            <ul>{relic_opts_html}</ul>
            <p><b>유효 부옵 우선순위:</b> {esc(d["substat_priority"]) or "정보 없음"}</p>
            <h3>성흔</h3>
            {eidolons_html or "<p>정보 없음</p>"}
            <h3>목표 스탯</h3>
            {stat_targets_html}
            {party_html}
        </section>
        '''
        sections.append(section)

    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>HSR 육성 가이드 위키</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #1e1f22; color: #ddd; }}
nav {{ position: sticky; top: 0; background: #1e1f22; padding: 10px 0; border-bottom: 1px solid #444; margin-bottom: 20px; max-height: 120px; overflow-y: auto; }}
nav a {{ color: #7ab; margin-right: 10px; text-decoration: none; font-size: 13px; }}
.char-card {{ border: 1px solid #444; border-radius: 8px; padding: 16px; margin-bottom: 24px; background: #2b2d31; }}
.char-header {{ display: flex; align-items: center; gap: 12px; }}
.portrait {{ width: 80px; height: 80px; object-fit: cover; border-radius: 8px; }}
.summary {{ color: #aaa; margin: 4px 0; }}
.desc {{ font-size: 14px; color: #ccc; }}
.weapons {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.wpn {{ display: flex; align-items: center; gap: 4px; background: #3a3c41; padding: 4px 8px; border-radius: 6px; font-size: 13px; }}
.wicon {{ width: 24px; height: 24px; border-radius: 4px; }}
.eidolon {{ background: #35373c; border-radius: 6px; padding: 8px; margin: 6px 0; font-size: 13px; }}
h2 {{ margin: 0; }}
h3 {{ margin-top: 16px; margin-bottom: 4px; font-size: 15px; color: #ccb; }}
</style>
</head>
<body>
<h1>HSR 육성 가이드 위키</h1>
<nav>{nav_items}</nav>
{"".join(sections)}
</body>
</html>'''


def main():
    previous_data = {}
    if JSON_OUTPUT_FILE.exists():
        try:
            previous_data = json.loads(JSON_OUTPUT_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"기존 위키 로드 실패, 새로 구축: {e}", flush=True)

    def quality(d):
        """스크래핑 장애 시 빈 데이터가 정상본을 덮어쓰지 않게 비교."""
        if not isinstance(d, dict):
            return 0
        return sum(bool(d.get(key)) for key in (
            "path", "element", "description", "weapons", "relic_set",
            "ornament_set", "eidolons", "stat_targets", "party_teams",
        ))

    requested_names = set(sys.argv[1:])
    PROGRESS_FILE.write_text("", encoding="utf-8")
    if requested_names:
        if not previous_data:
            raise RuntimeError("지정 캐릭터 갱신은 기존 위키 데이터가 필요합니다")
        slug_to_kr_name = dict(starrailres.get_character_slug_map())
        slug_to_kr_name.update({slug: name for name, slug in prydwen.MANUAL_SLUG_ALIASES.items()})
        all_characters = []
        for name in previous_data:
            slug = prydwen._resolve_slug(name) or f"local-{len(all_characters)}"
            slug_to_kr_name[slug] = name
            all_characters.append({"slug": slug, "en_name": name})
        unknown = requested_names - previous_data.keys()
        if unknown:
            raise RuntimeError(f"기존 위키에 없는 캐릭터: {', '.join(sorted(unknown))}")
        _log(f"지정 {len(requested_names)}명 처리 시작: {', '.join(requested_names)}")
    else:
        all_characters = prydwen.get_all_characters()
        _log(f"총 {len(all_characters)}명 처리 시작 (prydwen 전체 목록)")
        slug_to_kr_name = _build_slug_to_kr_name_map(all_characters)

    all_data = []
    for i, c in enumerate(all_characters):
        t0 = time.time()
        name = slug_to_kr_name[c["slug"]]
        if requested_names and name not in requested_names:
            all_data.append(previous_data[name])
            continue
        try:
            d = gather_character(name, slug_to_kr_name)
            retried, remaining = _retry_residual_english(d)
            previous = previous_data.get(name)
            preserved = False
            if previous and quality(d) < quality(previous):
                d = previous
                preserved = True
            all_data.append(d)
            safety_log = f", 재번역 {retried}건" if retried else ""
            if remaining:
                safety_log += f", 영문 잔여 {remaining}건"
            if preserved:
                safety_log += ", 기존 정상본 보존"
            _log(f"[{i+1}/{len(all_characters)}] {name} 완료 ({time.time()-t0:.1f}s{safety_log})")
        except Exception as e:
            previous = previous_data.get(name)
            if previous:
                all_data.append(previous)
                _log(f"[{i+1}/{len(all_characters)}] {name} 실패, 기존 정상본 보존: {e}")
            else:
                _log(f"[{i+1}/{len(all_characters)}] {name} 실패: {e}")

    html = render_html(all_data)
    html_tmp = OUTPUT_FILE.with_suffix(OUTPUT_FILE.suffix + ".tmp")
    html_tmp.write_text(html, encoding="utf-8")
    html_tmp.replace(OUTPUT_FILE)

    wiki_index = {d["name"]: d for d in all_data}
    json_tmp = JSON_OUTPUT_FILE.with_suffix(JSON_OUTPUT_FILE.suffix + ".tmp")
    with open(json_tmp, "w", encoding="utf-8") as f:
        json.dump(wiki_index, f, ensure_ascii=False, indent=2)
    json_tmp.replace(JSON_OUTPUT_FILE)

    _log(f"완료: {OUTPUT_FILE}, {JSON_OUTPUT_FILE}")


if __name__ == "__main__":
    main()
