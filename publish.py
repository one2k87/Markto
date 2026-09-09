# -*- coding: utf-8 -*-
"""⑤ 게시 — Pinterest API v5 자동 게시.

**현재는 잠들어 있다.** markto.json의 publish.mode가 "telegram"인 동안에는 호출되지 않는다.
standard 승인이 나면 access_tier를 "standard"로, mode를 "pinterest"로 바꾸면 전환이 끝난다.
그 전에는 텔레그램으로 받아 폰에서 수동 게시한다(캐스토가 같은 방식으로 굴러가는 검증된 폴백).

필요한 시크릿 (`oauth_setup.py`가 한 번에 뽑아준다)
  PINTEREST_APP_ID / PINTEREST_APP_SECRET : 앱 자격증명
  PINTEREST_REFRESH_TOKEN                 : 리프레시 토큰
  PINTEREST_BOARD_ID_<KEY>                : 사이트별 보드 id (없으면 이름으로 조회)

**왜 액세스 토큰을 시크릿에 직접 넣지 않는가.** v5 액세스 토큰의 수명은 2,592,000초(30일)다.
시크릿에 박아두면 승인받고 한 달 뒤 **조용히** 멈춘다 — 워크플로는 성공으로 끝나고 핀만 안
올라간다. 그래서 실행할 때마다 리프레시 토큰으로 액세스 토큰을 새로 받는다.
(PINTEREST_TOKEN 을 넣어두면 그 값을 그대로 쓴다 — 수동 1회 시험용 우회로다.)
"""
import base64
import os
import time

import requests

import common

_cached = {"token": None, "at": 0}
_ACCESS_TTL = 20 * 60          # 한 번 실행 안에서만 재사용한다(넉넉히 20분)


def _app():
    aid = os.getenv("PINTEREST_APP_ID", "").strip()
    sec = os.getenv("PINTEREST_APP_SECRET", "").strip()
    if not (aid and sec):
        raise SystemExit(
            "PINTEREST_APP_ID / PINTEREST_APP_SECRET 시크릿이 없습니다.\n"
            "→ 로컬에서 `python oauth_setup.py` 를 한 번 돌리면 넣을 값 3개를 출력합니다.")
    return aid, sec


def _basic():
    aid, sec = _app()
    return {"Authorization": "Basic " + base64.b64encode(f"{aid}:{sec}".encode()).decode()}


def access_token(force=False):
    """리프레시 토큰 → 액세스 토큰. 한 실행 안에서는 캐시해 재발급을 반복하지 않는다."""
    direct = os.getenv("PINTEREST_TOKEN", "").strip()
    if direct:
        return direct                      # 수동 시험용 우회로

    now = time.time()
    if not force and _cached["token"] and now - _cached["at"] < _ACCESS_TTL:
        return _cached["token"]

    refresh = os.getenv("PINTEREST_REFRESH_TOKEN", "").strip()
    if not refresh:
        raise SystemExit(
            "PINTEREST_REFRESH_TOKEN 시크릿이 없습니다.\n"
            "→ 로컬에서 `python oauth_setup.py` 를 돌려 발급받으세요.")

    base = common.cfg()["publish"]["pinterest_api"]
    r = requests.post(f"{base}/oauth/token", headers=_basic(),
                      data={"grant_type": "refresh_token", "refresh_token": refresh},
                      timeout=30)
    if r.status_code != 200:
        # 리프레시 실패는 사람이 개입해야 낫는다(만료·앱 시크릿 교체·권한 회수).
        # 조용히 지나가면 그날부터 핀이 0건이 되므로 텔레그램으로 깨운다.
        msg = (f"[마크토] 핀터레스트 토큰 갱신 실패 {r.status_code}\n{r.text[:300]}\n"
               "→ 로컬에서 `python oauth_setup.py` 를 다시 돌려 "
               "PINTEREST_REFRESH_TOKEN 시크릿을 갱신하세요.")
        print(msg)
        common.telegram_msg(msg)
        raise SystemExit("리프레시 토큰으로 액세스 토큰을 받지 못했습니다")

    j = r.json()
    # **리프레시 토큰이 회전(rotate)되어 돌아오는 경우가 있다.** 그러면 시크릿에 든 옛 값은
    # 언젠가 죽는다 — 자동으로 고칠 방법이 없으니(시크릿 쓰기 권한이 없다) 사람에게 알린다.
    new_refresh = j.get("refresh_token")
    if new_refresh and new_refresh != refresh:
        common.telegram_msg(
            "[마크토] 핀터레스트가 새 리프레시 토큰을 발급했습니다.\n"
            "GitHub Secrets 의 PINTEREST_REFRESH_TOKEN 을 갱신하지 않으면 "
            "지금 값은 만료 후 죽습니다.\n"
            "→ 로컬에서 `python oauth_setup.py` 를 다시 돌리세요.")
    _cached.update(token=j["access_token"], at=now)
    return _cached["token"]


def _headers(json_body=False):
    h = {"Authorization": f"Bearer {access_token()}"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def find_board_id(site, cfg):
    """사이트별 보드 id. 환경변수 우선, 없으면 이름으로 조회."""
    env = os.getenv(f"PINTEREST_BOARD_ID_{site['key'].upper()}", "").strip()
    if env:
        return env
    base = cfg["publish"]["pinterest_api"]
    r = requests.get(f"{base}/boards", headers=_headers(), params={"page_size": 100}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"보드 조회 실패 {r.status_code}: {r.text[:200]}")
    want = (site.get("board") or "").strip()
    for b in r.json().get("items", []):
        if b.get("name", "").strip() == want:
            return b["id"]
    raise RuntimeError(f"보드 '{want}' 를 찾지 못했습니다 — 핀터레스트에서 먼저 만들어 주세요")


def require_standard_access(cfg):
    """**trial 등급에서는 게시를 거부한다.**

    Pinterest 공식 문서: "all Pins and Boards created with Trial access are only visible to
    their creator as Sandbox entities" (2026-09-09 확인). trial로 자동 게시를 켜면
    ①아무도 볼 수 없는 핀이 만들어지고 ②make_pin이 그 글을 '핀 완료'로 기록해 큐에서 빼버려
    30일간 재시도도 안 된다. 즉 조용히 백로그를 태운다 — 그래서 코드가 막는다.
    """
    tier = (cfg["publish"].get("access_tier") or "trial").lower()
    if tier != "standard":
        raise SystemExit(
            "Pinterest 앱이 아직 standard 등급이 아닙니다(현재: %s).\n"
            "trial 등급의 핀은 Sandbox라 만든 사람만 볼 수 있어 유입이 0입니다.\n"
            "→ markto.json의 publish.mode는 \"telegram\"으로 두고 수동 게시를 유지하세요.\n"
            "   승인 절차는 docs/핀터레스트_standard_승인.md 를 보세요." % tier)


def publish_pin(image_path, copy, post, site, cfg):
    """핀 1건 게시. 성공하면 pin id 문자열, 실패하면 False.

    이미지는 base64로 직접 올린다(외부에 이미지 URL을 두지 않아도 되므로 경로가 단순하다).
    """
    require_standard_access(cfg)
    base = cfg["publish"]["pinterest_api"]
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = {
        "board_id": find_board_id(site, cfg),
        "title": copy["title"][:100],
        "description": copy["description"][:800],
        "link": common.with_utm(post["url"], site),
        "media_source": {"source_type": "image_base64", "content_type": "image/png", "data": b64},
    }
    r = requests.post(f"{base}/pins", headers=_headers(json_body=True), json=body, timeout=120)
    if r.status_code in (200, 201):
        pid = r.json().get("id")
        print(f"[pinterest] 게시 성공 pin_id={pid}")
        return pid
    print(f"[pinterest] 게시 실패 {r.status_code}: {r.text[:300]}")
    common.telegram_msg(f"[마크토] 핀터레스트 게시 실패 {r.status_code}\n{post['title']}\n{r.text[:300]}")
    return False
