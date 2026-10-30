# -*- coding: utf-8 -*-
"""⑦ 스레드 상품 포스트 — 쿠팡 수수료(B 경로)로 가는 유일한 '사람 앞 표면'.

설계 근거(2026-10-30 F 지시 · `_Master_Context/SolvUp_수익설계_ABC.md` B1):
스레드는 팔로워 0인데도 추천 피드로 6일 122명에게 도달했다. 지금 우리 채널 중
사람이 실제로 보는 유일한 표면이고, B1(첫 주문)의 가장 짧은 길이다.

**링크는 쿠팡으로 바로 걸지 않는다.** 픽담 글로 보낸다. 이유 둘 —
  ① 글 안에 픽토가 넣은 상품 링크와 고지문이 이미 있다(이중 관리 안 함).
  ② 같은 클릭이 사이트 유입으로도 잡힌다(A1 '비구글 유입' 게이트와 한 번에).
글이 없는 제품은 `/kok/`(콕픽 모아보기)로 보낸다.

**고지 문구는 첫 줄 고정이다.** 파트너스 「내 정보 관리」 화면 실측(2026-10-30):
"등록하지 않은 채널에서 광고 활동을 하면 부정행위로 간주될 수 있으며" — 채널 등록과
고지는 같이 가는 요건이다. 문구를 줄이거나 뒤로 미루지 않는다.

제품 대장은 **픽토의 공개 저장소에서 읽는다**(README 규칙 8-5: 4개 앱 레포는 Public이라
산출물을 토큰 없이 읽을 수 있다). 픽토 폴더를 직접 참조하지 않는 이유는 공유_경계 4절 —
라인끼리 파일 경로로 묶이지 않는다.
"""
import os
import re

import requests

import common

PRODUCTS_URL = ("https://raw.githubusercontent.com/one2k87/Picto/main/data/products.json")
DISCLOSURE = ("이 게시물은 쿠팡 파트너스 활동의 일환으로, "
              "이에 따른 일정액의 수수료를 제공받습니다.")
TEXT_MAX = 500
STATE = "product_posts.json"


def products(url=None):
    """픽토 대장에서 링크가 채워진 제품만 가져온다."""
    r = requests.get(url or PRODUCTS_URL, timeout=30)
    if r.status_code != 200:
        print(f"[product] 제품 대장을 못 읽었습니다 {r.status_code} — 건너뜁니다.")
        return []
    items = (r.json() or {}).get("products") or []
    # coupang_url 이 빈 제품은 글에도 링크가 안 들어간다 — 보낼 곳이 없으므로 제외.
    return [p for p in items if isinstance(p, dict) and p.get("coupang_url") and p.get("name")]


def find_post(prod, site, posts):
    """이 제품을 다루는 픽담 글을 찾는다. match 낱말이 제목에 있으면 그 글."""
    words = [w for w in (prod.get("match") or []) if w]
    for p in posts:
        title = common.strip_html(p.get("title") or "")
        if any(w in title for w in words):
            return p
    return None


def compose(prod, link, site, desc=""):
    """고지 → 문제 한 줄 → 가격대 → 링크. 링크는 맨 끝(미리보기 카드가 거기 붙는다).

    본문은 **글의 Rank Math 설명**을 1순위로 쓴다. 제품 대장의 price_band 는 대부분
    비어 있고, 제품명만 쓰면 모든 포스트가 "OO — 기준입니다"로 똑같이 시작한다.
    2026-10-19 인사이트 실측에서 조회 46을 받은 유일한 글만 첫 줄에 숫자·고유명사가
    있었고 나머지 11편은 같은 틀로 시작해 1~5조회에 그쳤다. 같은 실수를 반복하지 않는다.
    """
    url = common.with_utm(link, site, "threads")
    head = (desc or prod.get("hook") or prod.get("note") or "").strip()
    head = common.strip_html(head)
    if not head:
        head = f"{prod['name']} — 사기 전에 따져본 기준입니다."
    band = (prod.get("price_band") or "").strip()
    body = head if not band else f"{head}\n가격대 {band}"

    room = TEXT_MAX - len(DISCLOSURE) - len(url) - 4
    if len(body) > room:
        body = body[:max(0, room - 1)].rstrip() + "…"
    return f"{DISCLOSURE}\n\n{body}\n\n{url}"


def run(limit=None):
    c = common.cfg()
    conf = (c.get("threads") or {}).get("product") or {}
    if not conf.get("enabled"):
        print("[product] markto.json 에서 꺼져 있습니다 — 건너뜁니다.")
        return 0

    site = common.site_by_key(conf.get("site", "pickdam"), c)
    if not common.site_on(site, "threads"):
        print(f"[product] {site['name']} 의 스레드 채널이 꺼져 있습니다 — 건너뜁니다.")
        return 0

    state = common.load_json(STATE, {"posts": []})
    done = {p["key"] for p in state["posts"]}
    items = [p for p in products() if p.get("key") not in done]
    if not items:
        # 전부 한 번씩 돌았으면 장부를 비우고 다시 돈다 — 제품 수가 유한하기 때문.
        if state["posts"]:
            print("[product] 제품 한 바퀴를 다 돌아 장부를 비웁니다.")
            state = {"posts": []}
            items = products()
        if not items:
            print("[product] 올릴 제품이 없습니다.")
            return 0

    posts = common.wp_posts(site, per_page=50, pages=2) or []
    fallback = site["url"].rstrip("/") + conf.get("fallback_path", "/kok/")

    want = limit if limit is not None else conf.get("per_run", 2)
    tok, uid, n = None, None, 0
    import threads
    tok = threads.token()

    for prod in items:
        if n >= want:
            break
        hit = find_post(prod, site, posts)
        link = hit["url"] if hit else fallback
        meta = common.page_meta(link)
        if not meta["ok"]:
            print(f"[product] {link} 가 살아있지 않습니다 — 건너뜁니다.")
            continue
        uid = uid or threads.user_id(tok)
        text = compose(prod, link, site, meta.get("desc", ""))
        pid = threads.publish_one(text, tok, uid)
        if not pid:
            continue
        state["posts"].append({
            "key": prod["key"], "name": prod["name"], "thread_id": pid,
            "link": link, "matched_post": (hit or {}).get("id"),
            "at": common.now_kst().isoformat(timespec="seconds"),
        })
        print(f"[product] {prod['key']} → {pid}  ({'글' if hit else '/kok/'})")
        n += 1

    common.save_json(STATE, state)
    print(f"[product] {n}건 게시")
    return n


if __name__ == "__main__":
    import sys
    run(int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None)
