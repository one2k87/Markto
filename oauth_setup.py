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
API_PROD = "https://api.pinterest.com/v5"
API_SANDBOX = "https://api-sandbox.pinterest.com/v5"
API = API_PROD          # --sandbox 로 바뀐다 (main 에서 set_env)


def set_env(sandbox):
    """API 호스트를 프로덕션/샌드박스로 바꾼다.

    **왜 필요한가(2026-10-30 실측).** Trial 액세스로 프로덕션에 핀을 만들면
      403 {"code":29, "Apps with Trial access may not create Pins in production
            https://api.pinterest.com - use API Sandbox https://api-sandbox.pinterest.com instead."}
    로 거절당한다. 즉 **Trial 상태에서는 샌드박스에서만 핀을 만들 수 있고**,
    standard 승인용 데모 영상도 샌드박스로 찍는 수밖에 없다.
    두 호스트 모두 미인증 호출에 401 을 돌려주는 것까지 직접 확인했다.

    주의: **토큰 교환도 같은 호스트로 가야 한다.** 샌드박스 토큰과 프로덕션 토큰은
    별개이고, 샌드박스 보드 목록도 프로덕션과 따로 논다(비어 있는 게 정상).
    """
    global API
    API = API_SANDBOX if sandbox else API_PROD
    return API
SCOPES = "boards:read,boards:write,pins:read,pins:write"
AUTH_TIMEOUT = 180       # 동의 화면을 띄워놓고 기다리는 최대 시간(초)
# pins:read 를 함께 받는다 — 게시 후 핀이 실제로 살아있는지 확인하는 데 쓴다.
# boards:write 가 필요한 이유(2026-10-13 실측): pins:write 만으로 POST /v5/pins 를 치면
#   401 {"code":3, ... Missing: ['boards:write']}
# 로 거절당한다. 핀을 '보드에' 꽂는 행위를 Pinterest 는 보드 쓰기로 본다 — 문서의
# 스코프 표만 보고 pins:write 만 요청했다가 데모 녹화 1회를 통째로 날렸다.
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
    try:
        srv = HTTPServer(("localhost", PORT), _Handler)
    except OSError as e:          # noqa: BLE001 — 녹화 중에 트레이스백이 뜨면 다시 찍어야 한다
        sys.exit(f"포트 {PORT}를 열 수 없습니다({e}).\n"
                 f"이전 실행이 남아 있을 수 있습니다. 터미널에서 "
                 f"`lsof -ti tcp:{PORT} | xargs kill` 를 돌린 뒤 다시 실행하세요.")
    srv.timeout = AUTH_TIMEOUT
    srv.want_state, srv.auth_code, srv.oauth_error, srv.state_ok = state, None, None, False

    print(f"\n브라우저에서 핀터레스트 동의 화면을 엽니다 (리다이렉트 {REDIRECT_URI})")
    print("→ 화면 녹화를 지금 켜두세요. 이 동의 화면이 심사에 필요한 장면입니다.\n")
    if not webbrowser.open_new(url):
        print("브라우저가 자동으로 열리지 않았습니다. 아래 주소를 직접 여세요:\n" + url)

    try:
        srv.handle_request()      # 리다이렉트가 올 때까지 블록(최대 AUTH_TIMEOUT초)
    except KeyboardInterrupt:
        sys.exit("\n중단했습니다.")
    finally:
        srv.server_close()        # 포트를 물고 있지 않도록 (재실행 시 8085 충돌 방지)

    if not (srv.auth_code or srv.oauth_error or srv.state_ok):
        sys.exit(f"{AUTH_TIMEOUT}초 안에 동의가 오지 않았습니다. 녹화를 멈추고 다시 실행하세요.")

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
    ap.add_argument("--preflight", action="store_true",
                    help="녹화 전 점검만 한다 — 인증도 게시도 하지 않는다")
    ap.add_argument("--sandbox", action="store_true",
                    help="샌드박스로 돈다. Trial 액세스에서 핀을 만들 수 있는 유일한 길이다.")
    args = ap.parse_args()

    if args.preflight:
        sys.exit(0 if _preflight() else 1)

    set_env(args.sandbox)
    if args.sandbox:
        print("\n[샌드박스 모드] 핀은 api-sandbox.pinterest.com 에 만들어집니다.")
        print("  Trial 액세스는 프로덕션에 핀을 만들 수 없습니다(403 code 29, 2026-10-30 실측).")
        print("  샌드박스 보드·핀은 프로덕션과 별개이고 만든 사람에게만 보입니다.\n")

    app_id, secret = app_credentials()
    tok = exchange(app_id, secret, get_auth_code(app_id))
    access, refresh = tok["access_token"], tok.get("refresh_token")

    print("\n인증 성공.")
    print("  스코프:", tok.get("scope", "?"))
    granted = (tok.get("scope") or "").replace(",", " ").split()
    missing = [s for s in ("pins:write", "boards:write") if s not in granted]
    if missing:
        sys.exit(f"{', '.join(missing)} 가 부여되지 않았습니다 — 이 토큰으로는 핀을 만들 수 없습니다.\n"
                 "개발자 포털의 [토큰 생성] 단축 버튼으로 받은 토큰이 아닌지,\n"
                 "동의 화면에서 권한을 모두 허용했는지 확인하고 다시 실행하세요.\n"
                 "(둘 다 필요합니다 — 핀을 보드에 꽂는 데 boards:write 가 걸립니다. 2026-10-13 실측)")
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

    board_name = args.board
    if args.sandbox and not boards:
        boards, board_name = _ensure_sandbox_board(hdr, args.board or common_board_name())

    if args.demo_pin:
        _demo_pin(hdr, boards, board_name)

    out = {
        "refresh_token": refresh,
        "scope": tok.get("scope"),
        "refresh_token_expires_at": tok.get("refresh_token_expires_at"),
        "boards": {it["name"]: it["id"] for it in boards},
    }
    name = "pinterest_token_sandbox.json" if args.sandbox else "pinterest_token.json"
    # 샌드박스 토큰은 프로덕션에서 쓸 수 없다. 같은 파일에 덮어쓰면 승인 뒤에
    # 죽은 토큰을 시크릿에 넣게 된다 — 파일을 아예 분리한다.
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)         # 자격증명 파일은 본인만 읽게 (.gitignore 에도 있다)

    print("\n" + "=" * 64)
    print("GitHub Secrets 에 넣을 값 3개 —", os.path.basename(path), "에도 저장했습니다")
    print("=" * 64)
    print("  PINTEREST_APP_ID         =", app_id)
    print("  PINTEREST_APP_SECRET     = (앱 시크릿 — 방금 입력한 값)")
    masked = (refresh[:8] + "…" + refresh[-4:]) if len(refresh) > 16 else "(짧음)"
    print(f"  PINTEREST_REFRESH_TOKEN  = {masked}   ← 전체 값은 {os.path.basename(path)} 안에")
    for it in boards:
        print(f"  PINTEREST_BOARD_ID_?     = {it['id']}   ← '{it['name']}' 보드")
    print(f"\n리프레시 토큰은 화면에 찍지 않았습니다 — 녹화 그대로 제출하셔도 됩니다.")
    print(f"전체 값은 터미널에서 `cat {os.path.basename(path)}` 로 보거나 파일을 열어 복사하세요.")


def _ensure_sandbox_board(hdr, want):
    """샌드박스에 쓸 보드를 확보한다. (boards, 쓸 이름) 을 돌려준다.

    **2026-10-30 실측의 모순**: 샌드박스에서 `GET /v5/boards` 는 **0개**를 돌려주는데
    같은 이름으로 `POST /v5/boards` 를 치면
      400 {"code":58,"message":"Try a different name. You already have a board with this name!"}
    가 온다. 목록에 안 보이는데 이름은 이미 점유돼 있다 — 원인은 모른다(비공개 보드가
    기본 목록에서 빠지거나, 생성 쪽이 프로덕션 이름과 충돌을 보는 것으로 보인다).
    **원인을 모르는 채로도 녹화가 끝까지 가야 하므로 양쪽을 다 견디게 만든다.**
      ① privacy=ALL 로 한 번 더 조회한다(실패해도 무시)
      ② 그래도 없으면 만든다. 이름이 겹치면 **뒤에 날짜를 붙여 다시 시도**한다.
      ③ 만들어진 보드는 POST 응답으로 받으므로 목록이 계속 비어 있어도 상관없다.
    """
    r = requests.get(f"{API}/boards", headers=hdr,
                     params={"page_size": 25, "privacy": "ALL"}, timeout=30)
    if r.status_code == 200:
        got = r.json().get("items", [])
        if got:
            print(f"[샌드박스] 보드 {len(got)}개를 다시 조회해 찾았습니다.")
            return got, want

    stamp = common_today()
    for name in (want, f"{want} (API 시연)", f"{want} {stamp}"):
        cb = requests.post(f"{API}/boards", headers={**hdr, "Content-Type": "application/json"},
                           json={"name": name, "description": "마크토 API 연동 시연용"},
                           timeout=30)
        if cb.status_code in (200, 201):
            b = cb.json()
            print(f"[샌드박스] 보드 생성됨 — {b.get('name')} (id={b.get('id')})")
            return [b], b.get("name") or name
        try:
            code = cb.json().get("code")
        except Exception:                                   # noqa: BLE001
            code = None
        if code == 58:
            print(f"[샌드박스] '{name}' 은 이미 쓰는 이름입니다 — 다른 이름으로 시도합니다.")
            continue
        sys.exit(f"샌드박스 보드 생성 실패 {cb.status_code}: {cb.text[:300]}")
    sys.exit("샌드박스 보드를 확보하지 못했습니다 — 이름 후보가 모두 겹칩니다.")


def common_today():
    import common
    return common.now_kst().strftime("%Y%m%d-%H%M")


def common_board_name():
    import common
    return (common.site_by_key("pickdam", common.cfg()).get("board") or "마크토 시연").strip()


def _preflight():
    """녹화를 켜기 **전에** 돌리는 점검. 인증도 게시도 하지 않는다.

    이게 왜 있냐면: 2026-10-13에 스코프가 모자라 데모 핀이 401로 죽는 바람에 녹화를
    통째로 날렸고, 10/19에는 최근 핀이 전부 원더랜드라 데모가 조용히 건너뛰어질
    상태였다. **사람이 녹화를 켜기 전에 기계가 먼저 확인한다.**
    """
    import glob
    import socket
    import common

    ok = True

    def line(good, msg):
        nonlocal ok
        print(("  ✅ " if good else "  ❌ ") + msg)
        if not good:
            ok = False

    print("\n녹화 전 점검\n" + "-" * 48)

    line("boards:write" in SCOPES and "pins:write" in SCOPES,
         f"요청 스코프: {SCOPES}")
    line(True, "Trial 액세스 → 핀은 샌드박스(api-sandbox.pinterest.com)에 만듭니다. "
               "프로덕션은 403 code 29 로 막힙니다(2026-10-30 실측).")

    s = socket.socket()
    try:
        s.bind(("localhost", PORT))
        line(True, f"포트 {PORT} 비어 있음 (리다이렉트 {REDIRECT_URI})")
    except OSError:
        line(False, f"포트 {PORT} 가 이미 쓰이는 중 — `lsof -ti tcp:{PORT} | xargs kill`")
    finally:
        s.close()

    has_id = bool(os.getenv("PINTEREST_APP_ID"))
    print(("  ✅ " if has_id else "  ·  ") +
          ("앱 ID 가 환경변수에 있음" if has_id else "앱 ID·시크릿은 실행 중에 물어봅니다(시크릿은 화면에 안 보임)"))

    cfg = common.cfg()
    pins = common.load_json("pins.json", {"pins": []})["pins"]
    found = False
    for site in common.sites(cfg, channel="pinterest"):
        for rec in reversed(pins):
            if not isinstance(rec, dict) or rec.get("dead_link"):
                continue
            if rec.get("site") != site["key"]:
                continue
            img = os.path.join(common.ROOT, "dashboard", "pins",
                               f"pin_{rec['site']}_{rec['post_id']}.png")
            if os.path.exists(img):
                line(True, f"데모 핀 준비됨 — {site['name']} #{rec['post_id']} "
                           f"/ 보드 '{site.get('board','')}' / {os.path.basename(img)}")
                print(f"       제목: {(rec.get('pin_title') or '')[:48]}")
                print(f"       링크: {rec.get('url','')[:72]}")
                found = True
                break
        if found:
            break
    if not found:
        line(False, "데모에 쓸 핀이 없습니다 — `python make_pin.py 1` 을 먼저 돌리세요")

    print("-" * 48)
    print("전부 ✅ 이면 녹화를 켜고 `python oauth_setup.py --demo-pin` 을 실행하세요.\n"
          if ok else "❌ 를 먼저 해결하세요. 지금 녹화하면 또 날립니다.\n")
    return ok


def _demo_pin(hdr, boards, board_name):
    """영상용 핀 1건. 마크토가 만든 최근 이미지를 그대로 쓴다."""
    import glob
    import common                 # markto.json·UTM 등 기존 설정을 그대로 재사용

    cfg = common.cfg()
    # 보드가 **실제로 존재하는** 사이트만 데모 대상이 된다.
    # 2026-10-19 실측 사고 직전: 10/14에 원더랜드 핀을 켜면서 최근 핀이 전부 원더랜드가
    # 됐는데, 옛 조건이 "가장 최근 핀이 픽담이어야 한다"였다. 그대로 녹화했다면 심사에
    # 꼭 필요한 '핀 생성' 장면이 **또** 안 찍혔을 것이다(10/13에 같은 이유로 1회 날림).
    names = {it["name"].strip(): it["id"] for it in boards}
    site, want, bid = None, "", None
    for s in common.sites(cfg, channel="pinterest"):
        cand = (board_name or s.get("board", "")).strip()
        if cand in names:
            site, want, bid = s, cand, names[cand]
            break
    if not bid:
        have = ", ".join(names) or "(없음)"
        print(f"\n[demo] 쓸 수 있는 보드가 없어 핀 생성을 건너뜁니다. 계정의 보드: {have}")
        return
    print(f"[demo] 대상 사이트: {site['name']} · 보드 '{want}'")

    # 이미지와 문구는 **같은 글의 것**이어야 한다. 예전에는 '가장 새 이미지'와
    # '대장의 마지막 줄'을 따로 집어서, 둘이 어긋나면 A의 그림에 B의 제목·링크가
    # 붙은 핀이 심사 영상에 찍힐 수 있었다. 그리고 dead_link(원글이 내려간 글)는
    # 건너뛴다 — 404를 가리키는 핀을 심사자에게 보여줄 수는 없다(#164 사고).
    pins = common.load_json("pins.json", {"pins": []})["pins"]
    chosen, img = None, None
    for rec in reversed(pins):
        if not isinstance(rec, dict) or rec.get("dead_link"):
            continue
        if rec.get("site") != site["key"]:
            continue              # 그림과 문구는 같은 글, 그리고 보드와 같은 사이트 것이어야 한다
        cand = os.path.join(common.ROOT, "dashboard", "pins",
                            f"pin_{rec.get('site')}_{rec.get('post_id')}.png")
        if os.path.exists(cand):
            chosen, img = rec, cand
            break
    if not chosen:
        print(f"\n[demo] {site['name']} 의 쓸 수 있는 핀(이미지+문구 한 쌍)이 없습니다 — "
              f"먼저 `python make_pin.py 1` 을 돌리세요.")
        return

    body = {
        "board_id": bid,
        "title": (chosen.get("pin_title") or "픽담 살까 말까")[:100],
        "description": (chosen.get("pin_desc") or "")[:800],
        "link": chosen.get("url") or site["url"],
        "media_source": {"source_type": "image_base64", "content_type": "image/png",
                         "data": base64.b64encode(open(img, "rb").read()).decode()},
    }
    print(f"\n[demo] 핀 생성 중 — 보드 '{want}', 이미지 {os.path.basename(img)}")
    print(f"[demo]   제목: {body['title']}")
    print(f"[demo]   링크: {body['link']}")
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
