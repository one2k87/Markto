# -*- coding: utf-8 -*-
"""Pinterest OAuth 1회 설정 — 리프레시 토큰을 받아온다.

**이 스크립트를 실행하는 화면이 그대로 standard 승인 제출 영상이 된다.**
핀터레스트 심사에서 떨어지는 1순위 사유가 "동의 화면(OAuth consent)이 영상에 없음"이라
브라우저에 실제 동의 화면을 띄우고, 승인 직후 살아있는 API를 호출하는 순서로 짜여 있다.

    python oauth_setup.py             # 동의 화면 → 토큰 → 보드 목록 조회까지
    python oauth_setup.py --demo-pin  # 위 + 실제 핀 1건 생성 (영상 촬영용, 권장)

리다이렉트 URI는 **http://localhost:8085/** 다 — 핀터레스트 공식 quickstart가 쓰는 값이라
HTTPS 서버도 도메인도 필요 없다. developers.pinterest.com 앱 설정에 **글자 그대로** 같은
값을 넣어야 한다(끝의 슬래시까지).

출력된 PINTEREST_REFRESH_TOKEN 을 GitHub Secrets에 넣으면 워크플로가 매 실행마다
액세스 토큰을 새로 발급받는다(액세스 토큰은 30일이면 죽으므로 리프레시가 필수다).
"""
import argparse
import base64
import getpass
import json
import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

PORT = 8085
REDIRECT_URI = f"http://localhost:{PORT}/"
OAUTH_URL = "https://www.pinterest.com/oauth/"
API = "https://api.pinterest.com/v5"
SCOPES = "boards:read,pins:read,pins:write"
# pins:read 를 함께 받는다 — 게시 후 핀이 실제로 살아있는지 확인하는 데 쓴다.
# 문서 권장대로 필요한 최소 스코프만 요청한다(user_accounts, secret 계열은 받지 않는다).

DONE_HTML = """<!doctype html><meta charset="utf-8">
<title>마크토 인증 완료</title>
<body style="font:16px/1.6 -apple-system,system-ui,sans-serif;background:#F7F5EF;
             color:#12503A;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center">
  <div style="font-size:40px">&#10003;</div>
  <h1 style="font-size:20px;margin:.4em 0">마크토 인증 완료</h1>
  <p style="color:#4A3728">터미널로 돌아가세요.</p>
</div></body>"""


class _Handler(BaseHTTPRequestHandler):
    """리다이렉트로 돌아온 code 를 받아내는 1회용 서버."""

    def log_message(self, *_a):
        pass                      # code 가 콘솔·영상에 찍히지 않게 접속 로그를 끈다

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        self.server.oauth_error = (q.get("error") or [None])[0]
        got_state = (q.get("state") or [None])[0]
        code = (q.get("code") or [None])[0]
        # state 검증 — 다른 곳에서 유도된 리다이렉트를 코드로 착각하지 않도록
        self.server.auth_code = code if got_state == self.server.want_state else None
        self.server.state_ok = got_state == self.server.want_state
        body = DONE_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def app_credentials():
    """앱 ID·시크릿. 환경변수 우선, 없으면 물어본다.

    시크릿은 getpass 로 받는다 — **화면 녹화 중에 시크릿이 찍히면 안 되기 때문이다.**
    """
    app_id = os.getenv("PINTEREST_APP_ID") or input("Pinterest 앱 ID: ").strip()
    secret = os.getenv("PINTEREST_APP_SECRET") or getpass.getpass(
        "Pinterest 앱 시크릿 (입력해도 화면에 보이지 않습니다): ").strip()
    if not (app_id and secret):
        sys.exit("앱 ID와 시크릿이 필요합니다 — developers.pinterest.com/apps 에서 확인하세요")
    return app_id, secret


def basic_auth(app_id, secret):
    raw = f"{app_id}:{secret}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def get_auth_code(app_id):
    """브라우저에 동의 화면을 띄우고 code 를 받아온다."""
    state = secrets.token_hex(16)
    url = OAUTH_URL + "?" + urlencode({
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    })
    srv = HTTPServer(("localhost", PORT), _Handler)
    srv.want_state, srv.auth_code, srv.oauth_error, srv.state_ok = state, None, None, False

    print(f"\n브라우저에서 핀터레스트 동의 화면을 엽니다 (리다이렉트 {REDIRECT_URI})")
    print("→ 화면 녹화를 지금 켜두세요. 이 동의 화면이 심사에 필요한 장면입니다.\n")
    if not webbrowser.open_new(url):
        print("브라우저가 자동으로 열리지 않았습니다. 아래 주소를 직접 여세요:\n" + url)

    try:
        srv.handle_request()      # 리다이렉트가 올 때까지 블록
    except KeyboardInterrupt:
        sys.exit("\n중단했습니다.")
    finally:
        srv.server_close()        # 포트를 물고 있지 않도록 (재실행 시 8085 충돌 방지)

    if srv.oauth_error:
        sys.exit(f"핀터레스트가 인증을 거부했습니다: {srv.oauth_error}")
    if not srv.state_ok:
        sys.exit("state 불일치 — 인증을 중단했습니다. 스크립트를 다시 실행하세요.")
    if not srv.auth_code:
        sys.exit("리다이렉트에 code 가 없습니다. 앱의 리다이렉트 URI가 "
                 f"'{REDIRECT_URI}' 와 글자 그대로 같은지 확인하세요(끝 슬래시 포함).")
    return srv.auth_code


def exchange(app_id, secret, code):
    r = requests.post(f"{API}/oauth/token", headers=basic_auth(app_id, secret),
                      data={"grant_type": "authorization_code",
                            "code": code, "redirect_uri": REDIRECT_URI}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"토큰 교환 실패 {r.status_code}: {r.text[:300]}")
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-pin", action="store_true",
                    help="인증 직후 실제 핀 1건을 만든다 (심사 영상용)")
    ap.add_argument("--board", default="", help="핀을 올릴 보드 이름 (기본: markto.json 값)")
    args = ap.parse_args()

    app_id, secret = app_credentials()
    tok = exchange(app_id, secret, get_auth_code(app_id))
    access, refresh = tok["access_token"], tok.get("refresh_token")

    print("\n인증 성공.")
    print("  스코프:", tok.get("scope", "?"))
    print("  액세스 토큰 만료:", tok.get("expires_in", "?"), "초")
    if not refresh:
        sys.exit("리프레시 토큰이 오지 않았습니다 — 앱 설정에서 refreshable 을 확인하세요.")

    hdr = {"Authorization": f"Bearer {access}"}
    b = requests.get(f"{API}/boards", headers=hdr, params={"page_size": 25}, timeout=30)
    if b.status_code != 200:
        sys.exit(f"보드 조회 실패 {b.status_code}: {b.text[:300]}")
    boards = b.json().get("items", [])
    print(f"\n보드 {len(boards)}개:")
    for it in boards:
        print(f"  - {it['name']}  (id={it['id']})")

    if args.demo_pin:
        _demo_pin(hdr, boards, args.board)

    out = {
        "refresh_token": refresh,
        "scope": tok.get("scope"),
        "refresh_token_expires_at": tok.get("refresh_token_expires_at"),
        "boards": {it["name"]: it["id"] for it in boards},
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pinterest_token.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)         # 자격증명 파일은 본인만 읽게 (.gitignore 에도 있다)

    print("\n" + "=" * 64)
    print("GitHub Secrets 에 넣을 값 3개 —", os.path.basename(path), "에도 저장했습니다")
    print("=" * 64)
    print("  PINTEREST_APP_ID         =", app_id)
    print("  PINTEREST_APP_SECRET     = (앱 시크릿 — 방금 입력한 값)")
    print("  PINTEREST_REFRESH_TOKEN  =", refresh)
    for it in boards:
        print(f"  PINTEREST_BOARD_ID_?     = {it['id']}   ← '{it['name']}' 보드")
    print("\n리프레시 토큰은 화면에 노출됐습니다 — 녹화 영상에서 이 부분은 잘라내세요.")


def _demo_pin(hdr, boards, board_name):
    """영상용 핀 1건. 마크토가 만든 최근 이미지를 그대로 쓴다."""
    import glob
    import common                 # markto.json·UTM 등 기존 설정을 그대로 재사용

    cfg = common.cfg()
    site = common.site_by_key("pickdam", cfg)
    want = board_name or site.get("board", "")
    bid = next((it["id"] for it in boards if it["name"].strip() == want.strip()), None)
    if not bid:
        print(f"\n[demo] 보드 '{want}' 를 찾지 못해 핀 생성을 건너뜁니다.")
        return

    imgs = sorted(glob.glob(os.path.join(common.ROOT, "dashboard", "pins", "*.png")),
                  key=os.path.getmtime)
    if not imgs:
        print("\n[demo] 핀 이미지가 없습니다 — 먼저 `python make_pin.py 1` 을 돌리세요.")
        return

    pins = common.load_json("pins.json", {"pins": []})
    last = pins["pins"][-1] if pins["pins"] else {}
    body = {
        "board_id": bid,
        "title": (last.get("pin_title") or "픽담 살까 말까")[:100],
        "description": (last.get("pin_desc") or "")[:800],
        "link": last.get("url") or site["url"],
        "media_source": {"source_type": "image_base64", "content_type": "image/png",
                         "data": base64.b64encode(open(imgs[-1], "rb").read()).decode()},
    }
    print(f"\n[demo] 핀 생성 중 — 보드 '{want}', 이미지 {os.path.basename(imgs[-1])}")
    r = requests.post(f"{API}/pins", headers={**hdr, "Content-Type": "application/json"},
                      json=body, timeout=120)
    if r.status_code in (200, 201):
        pid = r.json().get("id")
        print(f"[demo] 게시 성공 — pin_id={pid}")
        print(f"[demo] https://www.pinterest.com/pin/{pid}/ 를 영상에서 함께 보여주세요.")
    else:
        print(f"[demo] 게시 실패 {r.status_code}: {r.text[:300]}")


if __name__ == "__main__":
    main()
