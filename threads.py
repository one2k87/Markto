# -*- coding: utf-8 -*-
"""⑥ 스레드(Threads) 게시 — 비구글 유입용.

핀터레스트와 다른 점 두 가지가 설계를 바꾼다.

1. **앱 심사가 없다.** 본인 계정(앱 소유자 또는 Threads Tester)에 올리는 것은 승인 없이
   바로 된다. 그래서 핀터레스트 standard 승인을 기다리는 동안에도 유입을 만들 수 있다.

2. **토큰이 스스로 갱신된다 — 그리고 그게 함정이다.** 장기 토큰의 수명은 60일이고,
   `GET /refresh_access_token` 은 *새 토큰 문자열* 을 돌려준다. 핀터레스트처럼
   "리프레시 토큰은 고정, 액세스 토큰만 재발급" 구조가 아니다. 즉 **갱신 결과를 어딘가에
   되돌려 써두지 않으면 60일 뒤 조용히 죽는다.** 워크플로는 성공으로 끝나고 글만 안 올라간다.

   이 저장소는 **공개(public)** 라 토큰을 파일로 커밋할 수 없다. 그래서 갱신값은
   GitHub Secret 으로 되돌려 쓴다(워크플로의 `gh secret set` 단계). 그 경로를 안 쓰면
   만료 14일 전부터 텔레그램으로 경고해 사람이 재발급하게 한다 — 조용히 죽는 것만은 막는다.

필요한 시크릿
  THREADS_TOKEN       : 장기 액세스 토큰(60일). developers.facebook.com 에서 1회 발급.
  THREADS_USER_ID     : 선택. 없으면 `/me` 로 조회한다.
  SECRETS_PAT         : 선택. 있으면 갱신된 토큰을 시크릿에 자동으로 되돌려 쓴다.
                        (fine-grained PAT, 이 저장소의 Secrets: read & write 하나면 충분)

문서 실측 2026-10-13: 게시는 2단계(컨테이너 생성 → 게시), 24시간 250건, 본문 500자.
"""
import os
import time

import requests

import common

API = "https://graph.threads.net/v1.0"
REFRESH_URL = "https://graph.threads.net/refresh_access_token"

WARN_DAYS = 14          # 만료가 이만큼 남으면 경고한다
MIN_REFRESH_AGE = 60 * 60 * 24   # 발급 24시간 뒤부터 갱신 가능(문서)
TEXT_MAX = 500          # 본문 상한(문서)


def token():
    t = os.getenv("THREADS_TOKEN", "").strip()
    if not t:
        raise SystemExit(
            "THREADS_TOKEN 시크릿이 없습니다.\n"
            "→ developers.facebook.com 에서 Threads 앱을 만들고 장기 토큰을 1회 발급해\n"
            "   깃허브 시크릿에 THREADS_TOKEN 이름으로 넣으세요.")
    return t


def _get(path, tok, **params):
    params["access_token"] = tok
    r = requests.get(f"{API}/{path.lstrip('/')}", params=params, timeout=30)
    return r


def me(tok=None):
    """토큰이 **실제로 누구인지** 묻는다. (id, username)"""
    r = _get("me", tok or token(), fields="id,username")
    if r.status_code != 200:
        raise SystemExit(f"Threads /me 실패 {r.status_code}: {r.text[:300]}")
    j = r.json()
    return j.get("id"), j.get("username", "")


def user_id(tok=None, expect=None):
    """게시 대상 Threads 사용자 id.

    expect 가 주어지면 **반드시 확인한다.** 개발자 계정(앱 소유자)과 게시 계정은 서로
    다른 것이 정상이지만, 토큰을 잘못 받으면 개인 계정에 글이 올라간다 — 되돌릴 수 없는
    사고라, 한 번의 왕복을 쓰더라도 확인하고 간다. (핀터레스트 스코프 사고의 교훈:
    사람이 손대기 전에 코드가 먼저 확인한다.)
    """
    uid = os.getenv("THREADS_USER_ID", "").strip()
    if uid and not expect:
        return uid
    got_id, got_name = me(tok)
    if expect and got_name and got_name.lstrip("@").lower() != expect.lstrip("@").lower():
        raise SystemExit(
            f"토큰의 주인이 '{got_name}' 입니다 — 설정에 적힌 '{expect}' 가 아닙니다.\n"
            "이 토큰으로 올리면 **엉뚱한 계정에 글이 올라갑니다**. 게시를 중단합니다.\n"
            "스레드에서 계정을 바꾼 뒤 토큰을 다시 받으세요.")
    return uid or got_id


def compose(post, site, cfg=None):
    """글 하나 → 스레드 본문. 링크는 맨 끝에 둔다(미리보기 카드가 거기 붙는다).

    제목을 그대로 쓰지 않는 이유: 스레드 피드는 검색 결과가 아니라 대화다. 'OO 비교'
    같은 제목은 스크롤에 묻힌다. 답변 블록과 같은 원칙 — 숫자나 결론을 앞에 둔다.
    """
    url = common.with_utm(post["url"], site, "threads")
    head = (post.get("seo_desc") or post.get("excerpt") or post.get("title") or "").strip()
    head = common.strip_html(head)
    # 링크와 줄바꿈 자리를 빼고 본문을 자른다
    room = TEXT_MAX - len(url) - 2
    if len(head) > room:
        head = head[:max(0, room - 1)].rstrip() + "…"
    return f"{head}\n\n{url}"


def publish_one(text, tok=None, uid=None):
    """컨테이너 생성 → 게시. 성공하면 게시된 글의 id를 돌려준다."""
    tok = tok or token()
    uid = uid or user_id(tok)

    c = requests.post(f"{API}/{uid}/threads",
                      data={"media_type": "TEXT", "text": text, "access_token": tok},
                      timeout=30)
    if c.status_code != 200:
        print(f"[threads] 컨테이너 생성 실패 {c.status_code}: {c.text[:300]}")
        return None
    cid = c.json().get("id")
    if not cid:
        print(f"[threads] 컨테이너 id 없음: {c.text[:200]}")
        return None

    # 문서 권장: 컨테이너 생성 후 약 30초 뒤 게시. 서버가 아직 처리 중이면 게시가 실패한다.
    time.sleep(int(os.getenv("THREADS_PUBLISH_DELAY", "30")))

    p = requests.post(f"{API}/{uid}/threads_publish",
                      data={"creation_id": cid, "access_token": tok}, timeout=30)
    if p.status_code != 200:
        print(f"[threads] 게시 실패 {p.status_code}: {p.text[:300]}")
        return None
    return p.json().get("id")


# ── 토큰 수명 관리 ────────────────────────────────────────────────────────────

def refresh(tok=None):
    """장기 토큰 갱신. 성공하면 (새 토큰, 남은 초). 실패하면 (None, None).

    **새 토큰 문자열이 바뀐다.** 호출한 쪽이 반드시 어딘가에 저장해야 한다.
    """
    tok = tok or token()
    r = requests.get(REFRESH_URL,
                     params={"grant_type": "th_refresh_token", "access_token": tok},
                     timeout=30)
    if r.status_code != 200:
        print(f"[threads] 토큰 갱신 실패 {r.status_code}: {r.text[:300]}")
        return None, None
    j = r.json()
    return j.get("access_token"), j.get("expires_in")


def _warn(days):
    common.telegram_msg(
        f"[마크토] 스레드 토큰이 {days}일 뒤 만료됩니다.\n"
        "자동 되돌려쓰기(SECRETS_PAT)가 꺼져 있어 사람이 재발급해야 합니다.\n"
        "developers.facebook.com → 앱 → Threads → 토큰 재발급 후 "
        "깃허브 시크릿 THREADS_TOKEN 을 교체하세요.\n"
        "만료된 토큰은 갱신할 수 없습니다 — 만료 전에 처리해야 합니다.")


def rotate(write_path=None):
    """매 실행 호출. 갱신하고, 새 값을 워크플로가 집어갈 수 있게 남긴다.

    write_path 가 주어지면 거기에 새 토큰을 쓴다(워크플로가 `gh secret set` 으로 올린다).
    그 경로가 없으면 만료가 가까울 때 텔레그램으로 경고만 한다.
    """
    new, ttl = refresh()
    if not new:
        return False
    days = int((ttl or 0) / 86400)
    print(f"[threads] 토큰 갱신 — 남은 수명 {days}일")

    if write_path:
        with open(write_path, "w", encoding="utf-8") as f:
            f.write(new)
        return True

    if days <= WARN_DAYS:
        _warn(days)
    return True


def _roundrobin(items, order):
    """사이트별로 번갈아 꺼낸다.

    큐(collect.py)는 사이트 묶음 순서로 쌓인다 — 픽담 35편 다음에 원더랜드 48편.
    그걸 그대로 앞에서부터 쓰면 **앞 사이트가 다 떨어질 때까지 뒷 사이트는 한 번도
    올라가지 않는다.** 하루 2건이면 픽담만 17일, 그 사이 애드센스 심사 대상인
    원더랜드 유입은 0이다(2026-10-14). order 는 markto.json threads.sites 순서.
    """
    buckets = {}
    for it in items:
        buckets.setdefault(it.get("site"), []).append(it)
    keys = [k for k in order if k in buckets] + [k for k in buckets if k not in order]
    out = []
    while any(buckets[k] for k in keys):
        for k in keys:
            if buckets[k]:
                out.append(buckets[k].pop(0))
    return out


def run(limit=None):
    """큐에서 글을 꺼내 스레드에 올린다. 핀 기록(pins.json)과 별도 장부를 쓴다."""
    c = common.cfg()
    conf = c.get("threads", {})
    if not conf.get("enabled"):
        print("[threads] markto.json 에서 꺼져 있습니다 — 건너뜁니다.")
        return 0

    state = common.load_json("threads.json", {"posts": []})
    done = {(p["site"], p["post_id"]) for p in state["posts"]}
    # 큐의 모양은 collect.py 가 정한다 — {"built_at":…, "items":[…]}.
    # 2026-10-13 첫 시험 게시가 여기서 KeyError('posts') 로 죽었다. make_pin.py 와
    # 같은 키를 쓴다고 가정하지 말고, 실제 파일을 보고 맞춘다.
    queue = common.load_json("queue.json", {"items": []}).get("items", [])
    if not queue:
        print("[threads] 큐가 비었습니다 — 먼저 collect.py 를 실행하세요")
        return 0

    want = limit or conf.get("per_run", 2)
    order = conf.get("sites") or []
    only = set(order)
    tok, uid, n = token(), None, 0

    for post in _roundrobin(queue, order):
        if n >= want:
            break
        key = (post.get("site"), post.get("id"))
        if key in done or (only and post.get("site") not in only):
            continue
        site = common.site_by_key(post["site"], c)
        if not site:
            continue
        # 채널별 차단. 큐에는 있어도 이 채널이 꺼진 사이트는 올리지 않는다.
        if not common.site_on(site, "threads"):
            continue

        meta = common.page_meta(post["url"])
        if not meta["ok"]:
            print(f"[threads] {post['url']} 가 살아있지 않습니다 — 건너뜁니다.")
            continue
        post["seo_desc"] = meta["desc"]

        uid = uid or user_id(tok, conf.get("expect_username"))
        text = compose(post, site, c)
        pid = publish_one(text, tok, uid)
        if not pid:
            continue

        state["posts"].append({
            "site": post["site"], "post_id": post["id"], "thread_id": pid,
            "at": common.now_kst().isoformat(timespec="seconds"),
        })
        print(f"[threads] {post['site']}#{post['id']} → {pid}")
        n += 1

    common.save_json("threads.json", state)
    print(f"[threads] {n}건 게시")
    return n


def whoami():
    """게시하지 않고 토큰의 주인만 확인한다. 첫 연결 점검용.

    핀터레스트 때 '리허설은 돌렸다'면서 실제 게시 경로를 타지 않아 사용자가 녹화를
    한 번 날렸다. 그 실수를 반복하지 않으려고, 글을 올리기 **전에** 돌려보는 길을 둔다.
    """
    c = common.cfg()
    want = (c.get("threads") or {}).get("expect_username")
    uid, name = me()
    print(f"[threads] 토큰 주인: @{name} (id={uid})")
    if want:
        ok = name and name.lstrip("@").lower() == want.lstrip("@").lower()
        print(f"[threads] 설정 기대값: @{want} → {'일치 ✅' if ok else '불일치 ❌'}")
        if not ok:
            raise SystemExit("이 토큰으로 올리면 엉뚱한 계정에 글이 올라갑니다.")
    return uid, name


if __name__ == "__main__":
    import sys
    if "--whoami" in sys.argv:
        whoami()
    elif "--rotate" in sys.argv:
        i = sys.argv.index("--rotate")
        rotate(sys.argv[i + 1] if len(sys.argv) > i + 1 else None)
    else:
        run(int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None)
