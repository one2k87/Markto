# -*- coding: utf-8 -*-
"""① 발행 글 수집 → ② 소재 선별 — 아직 핀을 만들지 않은 글을 큐로 만든다.

사용:  python collect.py            (enabled 사이트 전부)
       python collect.py pickdam    (한 사이트만)

출력:  data/queue.json  — [{site,id,title,url,excerpt,date,categories}], 오래된 글 우선.
근거:  오래된 글 우선인 이유는 새 글은 어차피 발행 직후 자연 노출을 받고,
       묻혀 있는 글일수록 핀 한 장이 만드는 유입의 증분이 크기 때문이다.
"""
import sys
from datetime import datetime

import common


def already_pinned_ids(pins, site_key, min_hours=720):
    """이미 핀을 만든 글 id 집합. min_hours가 지난 글은 재게시 후보로 다시 풀어준다."""
    now = common.now_kst()
    out = set()
    for p in pins.get("pins", []):
        if p.get("site") != site_key:
            continue
        try:
            made = datetime.fromisoformat(p["made_at"])
        except (KeyError, ValueError):
            out.add(p.get("post_id"))
            continue
        if made.tzinfo is None:
            made = made.replace(tzinfo=common.KST)
        if (now - made).total_seconds() < min_hours * 3600:
            out.add(p.get("post_id"))
    return out


def build_queue(only_site=None):
    c = common.cfg()
    col = c["collect"]
    pins = common.load_json("pins.json", {"pins": []})
    min_hours = c["quota"]["min_hours_between_same_post"]

    queue = []
    for site in common.sites(c):
        if only_site and site["key"] != only_site:
            continue
        posts = common.wp_posts(site, per_page=col["per_page"], pages=col["max_pages"])
        if not posts:
            print(f"[collect] {site['key']}: 글 0편 — 사이트 응답을 확인하세요")
            continue
        done = already_pinned_ids(pins, site["key"], min_hours)
        fresh = [p for p in posts if p["id"] not in done and p["title"]]
        if col.get("min_days_old"):
            cut = common.now_kst().timestamp() - col["min_days_old"] * 86400
            fresh = [p for p in fresh
                     if _ts(p["date"]) and _ts(p["date"]) <= cut]
        # 오래된 글 우선 (date 오름차순)
        fresh.sort(key=lambda p: p.get("date") or "")
        print(f"[collect] {site['key']}: 발행 {len(posts)}편 · 이미 핀 {len(done)}편 · 대기 {len(fresh)}편")
        queue.extend(fresh)

    common.save_json("queue.json", {"built_at": common.now_kst().isoformat(timespec="seconds"),
                                    "items": queue})
    print(f"[collect] 큐 {len(queue)}편 → data/queue.json")
    return queue


def _ts(iso):
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    build_queue(sys.argv[1] if len(sys.argv) > 1 else None)
