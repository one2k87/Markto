# -*- coding: utf-8 -*-
"""⑤ 게시 — Pinterest API v5 자동 게시.

**현재는 잠들어 있다.** markto.json의 publish.mode가 "telegram"인 동안에는 호출되지 않는다.
Pinterest developers 앱이 승인(trial→standard)되면 시크릿 2개를 넣고 mode를 "pinterest"로
바꾸는 것으로 전환이 끝난다. 그 전에는 텔레그램으로 받아 폰에서 수동 게시한다(캐스토가
같은 방식으로 굴러가고 있는 검증된 폴백).

필요한 시크릿
  PINTEREST_TOKEN        : OAuth 액세스 토큰 (스코프: boards:read, pins:write)
  PINTEREST_BOARD_ID_<KEY> : 사이트별 보드 id. 예) PINTEREST_BOARD_ID_PICKDAM
                             없으면 boards 목록에서 markto.json의 board 이름으로 찾는다.

주의: 이 파일은 아직 **실제 호출로 검증되지 않았다**(계정·앱 승인 대기). 첫 전환 때는
반드시 1건으로 시험하고, 성공 응답의 pin id를 data/pins.json에 남기는지 확인할 것.
"""
import base64
import os

import requests

import common


def _token():
    t = os.getenv("PINTEREST_TOKEN", "")
    if not t:
        raise SystemExit("PINTEREST_TOKEN 시크릿이 없습니다 (아직 API 승인 전이면 mode=telegram 유지)")
    return t


def _headers():
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def find_board_id(site, cfg):
    """사이트별 보드 id. 환경변수 우선, 없으면 이름으로 조회."""
    env = os.getenv(f"PINTEREST_BOARD_ID_{site['key'].upper()}", "")
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


def publish_pin(image_path, copy, post, site, cfg):
    """핀 1건 게시. 성공하면 pin id 문자열, 실패하면 False.

    이미지는 base64로 직접 올린다(외부에 이미지 URL을 두지 않아도 되므로 경로가 단순하다).
    """
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
    r = requests.post(f"{base}/pins", headers=_headers(), json=body, timeout=120)
    if r.status_code in (200, 201):
        pid = r.json().get("id")
        print(f"[pinterest] 게시 성공 pin_id={pid}")
        return pid
    print(f"[pinterest] 게시 실패 {r.status_code}: {r.text[:300]}")
    common.telegram_msg(f"[마크토] 핀터레스트 게시 실패 {r.status_code}\n{post['title']}\n{r.text[:300]}")
    return False
