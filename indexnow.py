# -*- coding: utf-8 -*-
"""IndexNow — 발행된 글을 네이버·빙에 **즉시** 알린다.

왜 필요한가(2026-09-10 실측). 픽담은 글 16편 중 구글 색인 5편이었다. 사이트맵도, 서치콘솔도
멀쩡했는데 **로봇이 아직 안 온 것**이 원인이다. 신생 사이트의 크롤 예산은 원래 인색하다.
IndexNow는 그 기다림을 건너뛴다 — "이 URL이 새로 생겼다"고 검색엔진에 직접 통보한다.

    python indexnow.py            # 아직 안 알린 최근 글을 통보
    python indexnow.py --all      # 사이트맵 전체를 다시 통보(첫 도입 때 한 번)
    python indexnow.py --dry      # 무엇을 보낼지만 출력

**구글은 IndexNow를 받지 않는다.** 구글용 통보 수단은 사이트맵뿐이고, Indexing API는
채용공고·라이브영상 전용이라 일반 글에 쓰면 규정 위반이다. 여기서는 네이버·빙만 노린다.

키는 비밀이 아니다 — 규격상 `https://<사이트>/<키>.txt` 에 공개로 올려야 소유 증명이 된다.
그래서 markto.json에 그대로 둔다. 키 파일이 없으면 통보는 조용히 거절되므로,
이 스크립트는 **보내기 전에 키 파일부터 확인한다.**
"""
import json
import os
import sys

import requests

import common

STATE = "indexnow.json"          # data/indexnow.json — 이미 통보한 URL
KEEP = 500                       # 기록은 최근 500건만 남긴다(무한히 불어나지 않게)


def key_file_ok(site):
    """`https://<사이트>/<키>.txt` 가 키를 그대로 돌려주는지. 아니면 통보해봐야 소용없다."""
    key = (site.get("indexnow_key") or "").strip()
    if not key:
        return False, "markto.json에 indexnow_key가 없습니다"
    url = f"{site['url'].rstrip('/')}/{key}.txt"
    try:
        r = requests.get(url, timeout=20)
    except requests.RequestException as e:      # noqa: BLE001
        return False, f"{url} 요청 실패: {e}"
    if r.status_code != 200:
        return False, f"{url} → HTTP {r.status_code} (키 파일을 먼저 올려야 합니다)"
    if r.text.strip() != key:
        return False, f"{url} 내용이 키와 다릅니다"
    return True, url


def recent_urls(site, limit=50):
    """WP REST에서 최근 글 주소. 사이트맵을 파싱하지 않는 이유는 collect.py와 같은 경로를
    쓰기 위해서다 — 발행 목록의 진실은 한 곳(WP REST)에서만 온다."""
    api = site["api"].rstrip("/")
    r = requests.get(f"{api}/posts", params={"per_page": limit, "_fields": "link,date"},
                     timeout=30, headers={"User-Agent": "markto/1.0"})
    r.raise_for_status()
    return [p["link"] for p in r.json() if p.get("link")]


def submit(site, urls, endpoints, dry=False):
    """한 사이트의 URL 묶음을 각 엔드포인트에 통보. 성공한 엔드포인트 수를 돌려준다.

    IndexNow는 200과 202를 모두 성공으로 본다(202 = 접수됨, 나중에 처리).
    """
    key = site["indexnow_key"]
    host = site["url"].split("//", 1)[-1].strip("/")
    body = {
        "host": host,
        "key": key,
        "keyLocation": f"{site['url'].rstrip('/')}/{key}.txt",
        "urlList": urls,
    }
    if dry:
        print(f"[indexnow] (dry) {host} {len(urls)}건 → {', '.join(endpoints)}")
        for u in urls:
            print("   ", u)
        return len(endpoints)

    ok = 0
    for ep in endpoints:
        try:
            r = requests.post(ep, json=body, timeout=30,
                              headers={"Content-Type": "application/json; charset=utf-8"})
        except requests.RequestException as e:   # noqa: BLE001 — 한 엔드포인트 실패가 나머지를 막지 않는다
            print(f"[indexnow] {ep} 요청 실패: {e}")
            continue
        if r.status_code in (200, 202):
            ok += 1
            print(f"[indexnow] {ep} → {r.status_code} ({len(urls)}건)")
        else:
            # 400=형식, 403=키 불일치, 422=host/키 불일치, 429=너무 잦음
            print(f"[indexnow] {ep} → {r.status_code} {r.text[:200]}")
    return ok


def run(send_all=False, dry=False):
    cfg = common.cfg()
    conf = cfg.get("indexnow") or {}
    if not conf.get("enabled"):
        print("[indexnow] 꺼져 있습니다 (markto.json의 indexnow.enabled)")
        return []

    endpoints = conf.get("endpoints") or []
    cap = int(conf.get("max_per_run", 20))
    state = common.load_json(STATE, {"sent": []})
    done = set(state.get("sent", []))

    sent_now = []
    for site in cfg["sites"]:
        if not site.get("indexnow_key"):
            continue                              # 키가 없는 사이트는 조용히 건너뛴다
        ok, info = key_file_ok(site)
        if not ok:
            print(f"[indexnow] {site['name']} 건너뜀 — {info}")
            continue

        try:
            urls = recent_urls(site)
        except Exception as e:                    # noqa: BLE001
            print(f"[indexnow] {site['name']} 글 목록 실패: {e}")
            continue

        todo = urls if send_all else [u for u in urls if u not in done]
        todo = todo[:cap]
        if not todo:
            print(f"[indexnow] {site['name']} 새로 알릴 글 없음")
            continue

        if submit(site, todo, endpoints, dry=dry) and not dry:
            sent_now += todo

    if sent_now and not dry:
        merged = state.get("sent", []) + [u for u in sent_now if u not in done]
        state["sent"] = merged[-KEEP:]
        state["last_at"] = common.now_kst().isoformat(timespec="seconds")
        common.save_json(STATE, state)
    print(f"[indexnow] {len(sent_now)}건 통보")
    return sent_now


if __name__ == "__main__":
    run(send_all="--all" in sys.argv, dry="--dry" in sys.argv)
