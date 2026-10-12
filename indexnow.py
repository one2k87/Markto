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
RUNS_KEEP = 14           # 최근 실행 기록(조용한 실패 추적용)
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


def submit(site, urls, endpoints, dry=False, log=None):
    """한 사이트의 URL 묶음을 각 엔드포인트에 통보. 성공한 엔드포인트 수를 돌려준다.

    IndexNow는 200과 202를 모두 성공으로 본다(202 = 접수됨, 나중에 처리).

    `log` 리스트를 주면 엔드포인트별 결과를 {ep, status, n, body}로 쌓는다.
    **조용한 실패를 막기 위해서다** — 원더랜드가 2026-08-31~10-12에 루트 글마다
    422를 받고도 "가동 중"으로 보였다(키 파일이 루트가 아니면 그 디렉터리 하위
    URL만 수리된다는 규칙을 몰랐다). 상태 코드를 남기지 않으면 6주가 그냥 간다.
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
        good = r.status_code in (200, 202)
        if good:
            ok += 1
            print(f"[indexnow] {ep} → {r.status_code} ({len(urls)}건)")
        else:
            # 400=형식, 403=키 불일치, 422=host/키 불일치(키 파일 경로 범위 포함), 429=너무 잦음
            print(f"[indexnow] {ep} → {r.status_code} {r.text[:200]}")
        if log is not None:
            log.append({"site": site["key"], "ep": ep, "status": r.status_code,
                        "n": len(urls), "ok": good,
                        "body": "" if good else r.text[:160]})
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

    sent_now, runlog = [], []
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

        if submit(site, todo, endpoints, dry=dry, log=runlog) and not dry:
            sent_now += todo

    if not dry:
        # 통보한 게 없어도 **결과는 남긴다** — "안 보냈음"과 "보냈는데 거절당함"은 다르다
        if sent_now:
            merged = state.get("sent", []) + [u for u in sent_now if u not in done]
            state["sent"] = merged[-KEEP:]
            state["last_at"] = common.now_kst().isoformat(timespec="seconds")
        if runlog:
            state["last_run"] = {"at": common.now_kst().isoformat(timespec="seconds"),
                                 "results": runlog}
            state["runs"] = (state.get("runs", []) + [state["last_run"]])[-RUNS_KEEP:]
        if sent_now or runlog:
            common.save_json(STATE, state)
        rejected = [x for x in runlog if not x["ok"]]
        if rejected:
            lines = [f"  {x['site']} {x['ep'].split('//')[-1][:28]} → {x['status']} {x['body'][:70]}"
                     for x in rejected[:6]]
            msg = ("[마크토] IndexNow 거절 — 색인 통보가 먹히지 않고 있습니다.\n"
                   + "\n".join(lines)
                   + "\n422는 보통 키 파일 위치 문제입니다: 키가 루트에 없으면 "
                     "그 디렉터리 하위 URL만 수리됩니다.")
            print(msg)
            common.telegram_msg(msg)
    print(f"[indexnow] {len(sent_now)}건 통보")
    return sent_now


if __name__ == "__main__":
    run(send_all="--all" in sys.argv, dry="--dry" in sys.argv)
