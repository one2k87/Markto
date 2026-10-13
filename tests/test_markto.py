# -*- coding: utf-8 -*-
"""마크토 테스트 — 네트워크·LLM 없이 도는 것만 담는다.

실행: python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common          # noqa: E402
import collect         # noqa: E402
import make_pin        # noqa: E402
import pin_image       # noqa: E402
import indexnow        # noqa: E402


class _Resp:
    """requests 응답 대역 — 네트워크 없이 상태코드·본문만 흉내낸다."""

    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Base(unittest.TestCase):
    """data/를 임시 폴더로 갈아끼워 실제 상태 파일을 건드리지 않는다."""

    def setUp(self):
        self.real_root = common.ROOT
        self.real_wp = common.wp_posts
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"))
        shutil.copy(os.path.join(self.real_root, "markto.json"), self.tmp)
        common.ROOT = self.tmp
        make_pin.OUT = os.path.join(self.tmp, "out")
        # 테스트가 실제 LLM·텔레그램을 부르지 않도록 시크릿을 잠시 걷어낸다
        # (러너에는 시크릿이 있으므로 이 격리가 없으면 CI에서 진짜 API를 때린다)
        self.env = {k: os.environ.pop(k, None)
                    for k in ("LLM_API_KEY", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID")}
        # 생사 확인은 기본으로 "살아있음"을 돌려준다. 실제로 네트워크를 때리면
        # 테스트가 느려지고(막힌 환경에서 타임아웃마다 15초) 외부 상태에 의존하게 된다.
        # 가드 자체는 TestLiveGuard가 requests를 직접 대역으로 바꿔 검증한다.
        self.real_is_live = common.is_live
        common.is_live = lambda url, timeout=15: True
        self.real_page_meta = common.page_meta
        common.page_meta = lambda url, timeout=20: {"ok": True, "status": 200,
                                                    "title": "", "desc": ""}

    def tearDown(self):
        common.ROOT = self.real_root
        common.wp_posts = self.real_wp
        common.is_live = self.real_is_live
        common.page_meta = self.real_page_meta
        make_pin.OUT = os.path.join(self.real_root, "out")
        for k, v in self.env.items():
            if v is not None:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, pid=1, title="자취방 전기밥솥 고르는 기준", site="pickdam"):
        return {"id": pid, "site": site, "title": title,
                "url": f"https://pickdam.com/?p={pid}", "excerpt": "요약입니다",
                "date": "2026-09-01T07:00:00", "categories": []}


class TestConfig(Base):
    def test_1단계는_픽담_한_사이트만_활성(self):
        act = [s["key"] for s in common.sites()]
        self.assertEqual(act, ["pickdam"])

    def test_핀_비율은_2대3_고정(self):
        p = common.cfg()["pin"]
        self.assertAlmostEqual(p["width"] / p["height"], 2 / 3, places=6)


class TestUtm(Base):
    def test_utm이_붙는다(self):
        s = common.site_by_key("pickdam")
        self.assertIn("utm_source=pinterest", common.with_utm("https://pickdam.com/a/", s))

    def test_이미_utm이_있으면_덧붙이지_않는다(self):
        s = common.site_by_key("pickdam")
        u = "https://pickdam.com/a/?utm_source=x"
        self.assertEqual(common.with_utm(u, s), u)

    def test_쿼리가_있으면_앰퍼샌드로_잇는다(self):
        s = common.site_by_key("pickdam")
        self.assertIn("?p=3&utm_source=", common.with_utm("https://pickdam.com/?p=3", s))


class TestHtml(Base):
    def test_태그와_엔티티를_지운다(self):
        self.assertEqual(common.strip_html("<p>가&amp;나  <b>다</b></p>"), "가&나 다")


class TestCollect(Base):
    def test_이미_핀을_만든_글은_큐에서_빠진다(self):
        posts = [self.post(1), self.post(2)]
        common.save_json("pins.json", {"pins": [{
            "site": "pickdam", "post_id": 1,
            "made_at": common.now_kst().isoformat(timespec="seconds")}]})
        common.wp_posts = lambda site, **kw: list(posts)
        q = collect.build_queue()
        self.assertEqual([i["id"] for i in q], [2])

    def test_30일이_지나면_재게시_후보로_풀린다(self):
        old = (common.now_kst() - timedelta(days=40)).isoformat(timespec="seconds")
        common.save_json("pins.json", {"pins": [{"site": "pickdam", "post_id": 1, "made_at": old}]})
        common.wp_posts = lambda site, **kw: [self.post(1)]
        q = collect.build_queue()
        self.assertEqual([i["id"] for i in q], [1])

    def test_오래된_글이_먼저_나온다(self):
        a, b = self.post(1), self.post(2)
        a["date"], b["date"] = "2026-09-05T00:00:00", "2026-08-01T00:00:00"
        common.wp_posts = lambda site, **kw: [a, b]
        q = collect.build_queue()
        self.assertEqual([i["id"] for i in q], [2, 1])


class TestQuota(Base):
    def setUp(self):
        super().setUp()
        common.save_json("queue.json", {"items": [self.post(i) for i in range(1, 9)]})

    def test_실행당_건수를_지킨다(self):
        made = make_pin.run(2, dry=False)
        self.assertEqual(len(made), 2)

    def test_하루_상한을_넘기지_않는다(self):
        cap = common.cfg()["quota"]["per_day"]
        make_pin.run(cap, dry=False)
        self.assertEqual(make_pin.run(3, dry=False), [])

    def test_소진된_글은_큐에서_제거된다(self):
        made = make_pin.run(1, dry=False)
        left = {i["id"] for i in common.load_json("queue.json", {"items": []})["items"]}
        self.assertNotIn(made[0]["post_id"], left)

    def test_같은_글을_두_번_만들지_않는다(self):
        a = make_pin.run(1, dry=False)
        b = make_pin.run(1, dry=False)
        self.assertNotEqual(a[0]["post_id"], b[0]["post_id"])


class TestGallery(Base):
    """대시보드 갤러리 — 최근 N장만 남기고, 테스트가 실제 레포를 오염시키지 않는지."""

    def test_핀_이미지가_갤러리로_복사된다(self):
        common.save_json("queue.json", {"items": [self.post(1)]})
        make_pin.run(1, dry=False)
        gal = os.path.join(self.tmp, "dashboard", "pins")
        self.assertEqual(len(os.listdir(gal)), 1)

    def test_갤러리는_실제_레포를_건드리지_않는다(self):
        # gallery_dir()이 호출 시점에 common.ROOT를 읽어야 한다(상수로 굳히면 실제 레포에 쓴다)
        self.assertTrue(make_pin.gallery_dir().startswith(self.tmp))

    def test_오래된_이미지는_상한만큼만_남는다(self):
        import time
        gal = os.path.join(self.tmp, "dashboard", "pins")
        os.makedirs(gal, exist_ok=True)
        src = os.path.join(self.tmp, "seed.png")
        with open(src, "wb") as f:
            f.write(b"x")
        for i in range(5):
            with open(os.path.join(gal, f"old{i}.png"), "wb") as f:
                f.write(b"x")
            os.utime(os.path.join(gal, f"old{i}.png"), (1000 + i, 1000 + i))
        make_pin.publish_to_gallery(src, keep=3)
        self.assertEqual(len(os.listdir(gal)), 3)


class TestCopy(Base):
    def test_이모지는_문구에서_제거된다(self):
        self.assertEqual(make_pin.strip_emoji("좋아요 👍 정말 ✅"), "좋아요 정말")

    def test_키가_없으면_폴백_문구로_계속_간다(self):
        c = make_pin.make_copy(self.post(), common.site_by_key("pickdam"), common.cfg())
        self.assertTrue(c["_fallback"])
        self.assertTrue(c["title"])

    def test_폴백_제목은_낱말_중간에서_끊지_않는다(self):
        long = "새 아파트 시스템 가전, 2026년 9월 4인 가족 기준 1,000만원 절약하는 설치 전략"
        c = make_pin.fallback_copy({"title": long, "excerpt": ""}, common.site_by_key("pickdam"))
        self.assertLessEqual(len(c["title"]), 40)
        self.assertFalse(c["title"].endswith(" "))
        self.assertTrue(long.startswith(c["title"]))

    def test_짧은_제목은_그대로_둔다(self):
        c = make_pin.fallback_copy({"title": "건조기 필터", "excerpt": ""},
                                   common.site_by_key("pickdam"))
        self.assertEqual(c["title"], "건조기 필터")

    def test_캡션에_링크와_보드가_들어간다(self):
        site = common.site_by_key("pickdam")
        cfg = common.cfg()
        cap = make_pin.caption(self.post(), make_pin.make_copy(self.post(), site, cfg, dry=True),
                               site, cfg)
        self.assertIn("utm_source=pinterest", cap)
        self.assertIn(site["board"], cap)


class TestAccessTier(Base):
    """trial 등급으로 자동 게시가 켜지는 사고를 막는 가드."""

    def test_trial이면_게시를_거부한다(self):
        import publish
        cfg = common.cfg()
        cfg["publish"]["access_tier"] = "trial"
        with self.assertRaises(SystemExit):
            publish.require_standard_access(cfg)

    def test_standard이면_통과한다(self):
        import publish
        cfg = common.cfg()
        cfg["publish"]["access_tier"] = "standard"
        publish.require_standard_access(cfg)      # 예외 없이 통과해야 한다

    def test_등급이_비어_있으면_trial로_간주한다(self):
        import publish
        cfg = common.cfg()
        cfg["publish"].pop("access_tier", None)
        with self.assertRaises(SystemExit):
            publish.require_standard_access(cfg)

    def test_기본_설정은_아직_trial이다(self):
        self.assertEqual(common.cfg()["publish"]["access_tier"], "trial")


class TestTelegramEnv(Base):
    """시크릿에 공백·따옴표가 섞여 들어오는 흔한 사고를 코드가 흡수하는지."""

    def test_공백과_따옴표를_떼낸다(self):
        os.environ["TELEGRAM_TOKEN"] = '  "123:abc"\n'
        os.environ["TELEGRAM_CHAT_ID"] = " '-1001234' "
        try:
            tok, chat = common._tg()
            self.assertEqual(tok, "123:abc")
            self.assertEqual(chat, "-1001234")
        finally:
            os.environ.pop("TELEGRAM_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)

    def test_값이_없으면_빈_문자열(self):
        self.assertEqual(common._tg(), ("", ""))


class TestImage(Base):
    def test_핀은_1000x1500으로_저장된다(self):
        from PIL import Image
        p = os.path.join(self.tmp, "out", "t.png")
        cfg = common.cfg()
        pin_image.render_pin(p, common.site_by_key("pickdam"), "무선 청소기 살까 말까",
                             subtitle="세 가지만 보면 됩니다", kicker="주방", cfg_pin=cfg["pin"])
        self.assertEqual(Image.open(p).size, (1000, 1500))

    def test_긴_제목도_카드_밖으로_넘치지_않는다(self):
        from PIL import Image
        p = os.path.join(self.tmp, "out", "long.png")
        cfg = common.cfg()
        long_title = "자취방 좁은 주방에서도 자리 안 차지하는 전기밥솥 고르는 기준 다섯 가지 정리"
        pin_image.render_pin(p, common.site_by_key("pickdam"), long_title, cfg_pin=cfg["pin"])
        im = Image.open(p).convert("RGB")
        # 카드(크림) 아래 여백 줄에 딥그린 배경만 남아야 한다 = 글자가 카드를 뚫지 않았다
        row = [im.getpixel((x, int(1500 * .77))) for x in range(60, 940, 20)]
        self.assertTrue(all(px == tuple(common.site_by_key("pickdam")["brand"]["bg"]) for px in row))

    def test_한국어_페이스를_인덱스로_박지_않고_이름으로_찾는다(self):
        p = pin_image.font_file("NotoSansCJK-Bold.ttc")
        from PIL import ImageFont
        fam = ImageFont.truetype(p, 12, index=pin_image.kr_index(p)).getname()[0]
        self.assertIn("KR", fam)


class TestPinterestToken(Base):
    """액세스 토큰 30일 만료 사고를 막는 층. 네트워크는 부르지 않는다."""

    def setUp(self):
        super().setUp()
        import publish
        self.publish = publish
        publish._cached.update(token=None, at=0)
        self.saved = {k: os.environ.pop(k, None) for k in
                      ("PINTEREST_TOKEN", "PINTEREST_REFRESH_TOKEN",
                       "PINTEREST_APP_ID", "PINTEREST_APP_SECRET")}

    def tearDown(self):
        self.publish._cached.update(token=None, at=0)
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        super().tearDown()

    def test_PINTEREST_TOKEN이_있으면_그대로_쓴다(self):
        """수동 1회 시험용 우회로 — 네트워크를 타지 않아야 한다."""
        os.environ["PINTEREST_TOKEN"] = "직접넣은토큰"
        self.assertEqual(self.publish.access_token(), "직접넣은토큰")

    def test_리프레시_토큰이_없으면_바로_멈춘다(self):
        os.environ["PINTEREST_APP_ID"] = "app"
        os.environ["PINTEREST_APP_SECRET"] = "sec"
        with self.assertRaises(SystemExit):
            self.publish.access_token()

    def test_앱_자격증명이_없으면_바로_멈춘다(self):
        os.environ["PINTEREST_REFRESH_TOKEN"] = "rt"
        with self.assertRaises(SystemExit):
            self.publish.access_token()

    def test_리프레시로_액세스_토큰을_받아_캐시한다(self):
        """같은 실행 안에서 여러 핀을 올려도 토큰 발급은 한 번뿐이어야 한다."""
        os.environ.update(PINTEREST_APP_ID="app", PINTEREST_APP_SECRET="sec",
                          PINTEREST_REFRESH_TOKEN="rt")
        calls = []

        def fake_post(url, headers=None, data=None, timeout=None):
            calls.append((url, data))
            return _Resp(200, {"access_token": "새토큰", "expires_in": 2592000})

        real = self.publish.requests.post
        self.publish.requests.post = fake_post
        try:
            self.assertEqual(self.publish.access_token(), "새토큰")
            self.assertEqual(self.publish.access_token(), "새토큰")
        finally:
            self.publish.requests.post = real
        self.assertEqual(len(calls), 1, "액세스 토큰을 매번 새로 받고 있다")
        self.assertTrue(calls[0][0].endswith("/oauth/token"))
        self.assertEqual(calls[0][1]["grant_type"], "refresh_token")

    def test_갱신_실패는_조용히_지나가지_않는다(self):
        """실패를 삼키면 그날부터 핀이 0건인데 워크플로는 초록으로 끝난다."""
        os.environ.update(PINTEREST_APP_ID="app", PINTEREST_APP_SECRET="sec",
                          PINTEREST_REFRESH_TOKEN="rt")
        sent = []
        real_post, real_tg = self.publish.requests.post, self.publish.common.telegram_msg
        self.publish.requests.post = lambda *a, **k: _Resp(401, {"message": "expired"})
        self.publish.common.telegram_msg = lambda m: sent.append(m)
        try:
            with self.assertRaises(SystemExit):
                self.publish.access_token()
        finally:
            self.publish.requests.post = real_post
            self.publish.common.telegram_msg = real_tg
        self.assertTrue(sent, "갱신 실패를 알리지 않았다")
        self.assertIn("oauth_setup.py", sent[0])

    def test_리프레시_토큰이_회전되면_사람에게_알린다(self):
        """새 리프레시 토큰은 시크릿에 자동 반영할 수 없다 — 알리지 않으면 언젠가 죽는다."""
        os.environ.update(PINTEREST_APP_ID="app", PINTEREST_APP_SECRET="sec",
                          PINTEREST_REFRESH_TOKEN="옛토큰")
        sent = []
        real_post, real_tg = self.publish.requests.post, self.publish.common.telegram_msg
        self.publish.requests.post = lambda *a, **k: _Resp(
            200, {"access_token": "a", "refresh_token": "새리프레시"})
        self.publish.common.telegram_msg = lambda m: sent.append(m)
        try:
            self.publish.access_token()
        finally:
            self.publish.requests.post = real_post
            self.publish.common.telegram_msg = real_tg
        self.assertTrue(sent, "리프레시 토큰 회전을 알리지 않았다")
        self.assertIn("PINTEREST_REFRESH_TOKEN", sent[0])

    def test_같은_리프레시_토큰이_돌아오면_알리지_않는다(self):
        os.environ.update(PINTEREST_APP_ID="app", PINTEREST_APP_SECRET="sec",
                          PINTEREST_REFRESH_TOKEN="rt")
        sent = []
        real_post, real_tg = self.publish.requests.post, self.publish.common.telegram_msg
        self.publish.requests.post = lambda *a, **k: _Resp(
            200, {"access_token": "a", "refresh_token": "rt"})
        self.publish.common.telegram_msg = lambda m: sent.append(m)
        try:
            self.publish.access_token()
        finally:
            self.publish.requests.post = real_post
            self.publish.common.telegram_msg = real_tg
        self.assertFalse(sent, "회전이 없었는데 알림을 보냈다")


class TestOauthSetup(Base):
    """제출 영상용 스크립트 — 잘못된 값으로 심사에 나가지 않도록 상수를 고정한다."""

    def test_리다이렉트는_공식_quickstart와_같은_값(self):
        import oauth_setup
        self.assertEqual(oauth_setup.REDIRECT_URI, "http://localhost:8085/")

    def test_최소_스코프만_요청한다(self):
        """boards:write 가 빠지면 POST /v5/pins 가 401 로 거절당한다(2026-10-13 실측).
        데모 녹화 1회를 통째로 날린 원인이라 상수로 고정해 둔다."""
        import oauth_setup
        got = set(oauth_setup.SCOPES.split(","))
        self.assertEqual(got, {"boards:read", "boards:write", "pins:read", "pins:write"})
        self.assertFalse([s for s in got if "secret" in s], "비공개 스코프를 요청하고 있다")
        self.assertNotIn("user_accounts:read", got, "심사에 불필요한 스코프를 요청하고 있다")


class TestIndexNow(Base):
    """색인 통보. 네트워크 없이 대역으로만 검증한다."""

    def setUp(self):
        super().setUp()
        import indexnow
        self.ix = indexnow

    def test_설정이_켜져_있고_두_엔드포인트를_쓴다(self):
        c = common.cfg()["indexnow"]
        self.assertTrue(c["enabled"])
        self.assertIn("https://searchadvisor.naver.com/indexnow", c["endpoints"])
        self.assertTrue(any("indexnow.org" in e for e in c["endpoints"]))

    def test_구글_엔드포인트는_넣지_않는다(self):
        """구글은 IndexNow를 받지 않는다 — 넣어두면 매 실행마다 실패 로그만 쌓인다."""
        eps = " ".join(common.cfg()["indexnow"]["endpoints"])
        self.assertNotIn("google", eps.lower())

    def test_키가_있는_사이트는_규격에_맞는_형식이다(self):
        """키가 없는 사이트는 정상이다 — 아직 키 파일을 안 올린 사이트는 건너뛴다."""
        keyed = [s for s in common.cfg()["sites"] if s.get("indexnow_key")]
        self.assertTrue(keyed, "키를 가진 사이트가 하나도 없습니다")
        for s in keyed:
            self.assertRegex(s["indexnow_key"], r"^[0-9a-f-]{8,128}$",
                             f"{s['key']} 키 형식이 규격에 맞지 않습니다")

    def test_키_없는_사이트는_조용히_건너뛴다(self):
        """매일 도는 작업이라, 아직 준비 안 된 사이트가 로그를 오염시키면 안 된다."""
        site = dict(common.site_by_key("pickdam"))
        site.pop("indexnow_key", None)
        called = []
        real = self.ix.requests.get
        self.ix.requests.get = lambda *a, **k: called.append(1) or _Resp(200, {})
        try:
            ok, msg = self.ix.key_file_ok(site)
        finally:
            self.ix.requests.get = real
        self.assertFalse(ok)
        self.assertEqual(called, [], "키가 없는데 네트워크를 때렸다")

    def test_키_파일이_없으면_통보하지_않는다(self):
        """이게 없으면 키 파일을 안 올린 채 매일 403을 받는다."""
        site = common.site_by_key("pickdam")
        real = self.ix.requests.get
        self.ix.requests.get = lambda *a, **k: _Resp(404, {})
        try:
            ok, msg = self.ix.key_file_ok(site)
        finally:
            self.ix.requests.get = real
        self.assertFalse(ok)
        self.assertIn("404", msg)

    def test_키_파일_내용이_다르면_거부한다(self):
        site = common.site_by_key("pickdam")
        real = self.ix.requests.get
        r = _Resp(200, {})
        r.text = "다른값"
        self.ix.requests.get = lambda *a, **k: r
        try:
            ok, msg = self.ix.key_file_ok(site)
        finally:
            self.ix.requests.get = real
        self.assertFalse(ok)

    def test_본문에_host_key_keyLocation_urlList가_모두_들어간다(self):
        """하나라도 빠지면 422로 조용히 거절된다."""
        site = common.site_by_key("pickdam")
        sent = []
        real = self.ix.requests.post
        self.ix.requests.post = lambda ep, **k: (sent.append((ep, k.get("json"))), _Resp(200, {}))[1]
        try:
            n = self.ix.submit(site, ["https://pickdam.com/a/"], ["https://e1", "https://e2"])
        finally:
            self.ix.requests.post = real
        self.assertEqual(n, 2, "엔드포인트 두 곳 모두에 보내지 않았다")
        body = sent[0][1]
        self.assertEqual(body["host"], "pickdam.com")
        self.assertEqual(body["key"], site["indexnow_key"])
        self.assertIn(site["indexnow_key"] + ".txt", body["keyLocation"])
        self.assertEqual(body["urlList"], ["https://pickdam.com/a/"])

    def test_202도_성공으로_센다(self):
        """IndexNow는 202(접수됨)를 정상 응답으로 쓴다. 실패로 세면 기록이 안 남는다."""
        site = common.site_by_key("pickdam")
        real = self.ix.requests.post
        self.ix.requests.post = lambda ep, **k: _Resp(202, {})
        try:
            n = self.ix.submit(site, ["https://pickdam.com/a/"], ["https://e1"])
        finally:
            self.ix.requests.post = real
        self.assertEqual(n, 1)

    def test_이미_보낸_URL은_다시_보내지_않는다(self):
        common.save_json(self.ix.STATE, {"sent": ["https://pickdam.com/a/"]})
        site = common.site_by_key("pickdam")
        calls = []
        real_get, real_post = self.ix.requests.get, self.ix.requests.post
        keyr = _Resp(200, {})
        keyr.text = site["indexnow_key"]

        def fake_get(url, **k):
            if url.endswith(".txt"):
                return keyr
            r = _Resp(200, [{"link": "https://pickdam.com/a/"}, {"link": "https://pickdam.com/b/"}])
            return r

        self.ix.requests.get = fake_get
        self.ix.requests.post = lambda ep, **k: (calls.append(k.get("json")), _Resp(200, {}))[1]
        try:
            self.ix.run()
        finally:
            self.ix.requests.get, self.ix.requests.post = real_get, real_post
        urls = [u for c in calls for u in c["urlList"]]
        self.assertIn("https://pickdam.com/b/", urls)
        self.assertNotIn("https://pickdam.com/a/", urls, "이미 보낸 URL을 다시 보냈다")

    def test_거절당하면_기록하고_알린다(self):
        """조용한 실패가 6주를 삼킨 적이 있다(원더랜드 422, 8/31~10/12)."""
        site = common.site_by_key("pickdam")
        alerts = []
        real_get, real_post = self.ix.requests.get, self.ix.requests.post
        real_tg = common.telegram_msg
        keyr = _Resp(200, {})
        keyr.text = site["indexnow_key"]
        bad = _Resp(422, {})
        bad.text = "Invalid urls"
        self.ix.requests.get = lambda url, **k: (
            keyr if url.endswith(".txt") else _Resp(200, [{"link": "https://pickdam.com/z/"}]))
        self.ix.requests.post = lambda ep, **k: bad
        common.telegram_msg = lambda t: alerts.append(t)
        try:
            self.ix.run()
        finally:
            self.ix.requests.get, self.ix.requests.post = real_get, real_post
            common.telegram_msg = real_tg
        st = common.load_json(self.ix.STATE, {})
        self.assertIn("last_run", st, "거절 결과가 상태 파일에 남지 않았다")
        self.assertTrue(any(r["status"] == 422 for r in st["last_run"]["results"]))
        self.assertTrue(alerts, "거절당했는데 텔레그램 알림이 없다")
        self.assertIn("422", alerts[0])

    def test_성공해도_실행기록을_남긴다(self):
        site = common.site_by_key("pickdam")
        real_get, real_post = self.ix.requests.get, self.ix.requests.post
        keyr = _Resp(200, {})
        keyr.text = site["indexnow_key"]
        self.ix.requests.get = lambda url, **k: (
            keyr if url.endswith(".txt") else _Resp(200, [{"link": "https://pickdam.com/z/"}]))
        self.ix.requests.post = lambda ep, **k: _Resp(200, {})
        try:
            self.ix.run()
        finally:
            self.ix.requests.get, self.ix.requests.post = real_get, real_post
        st = common.load_json(self.ix.STATE, {})
        self.assertTrue(st.get("last_run", {}).get("results"))
        self.assertTrue(all(r["ok"] for r in st["last_run"]["results"]))

    def test_max_per_run을_넘기지_않는다(self):
        site = common.site_by_key("pickdam")
        cap = common.cfg()["indexnow"]["max_per_run"]
        many = [{"link": f"https://pickdam.com/p{i}/"} for i in range(cap + 10)]
        calls = []
        real_get, real_post = self.ix.requests.get, self.ix.requests.post
        keyr = _Resp(200, {})
        keyr.text = site["indexnow_key"]
        self.ix.requests.get = lambda url, **k: keyr if url.endswith(".txt") else _Resp(200, many)
        self.ix.requests.post = lambda ep, **k: (calls.append(k.get("json")), _Resp(200, {}))[1]
        try:
            self.ix.run()
        finally:
            self.ix.requests.get, self.ix.requests.post = real_get, real_post
        for c in calls:
            self.assertLessEqual(len(c["urlList"]), cap)


class TestLiveGuard(Base):
    """내려간 글로 핀을 만들지 않는다. 2026-09-15 실측 사고에서 나온 층."""

    def setUp(self):
        super().setUp()
        common.is_live = self.real_is_live      # 이 묶음만 진짜 가드를 검증한다
        common.page_meta = self.real_page_meta

    def test_200이_아니면_죽은_글로_본다(self):
        real = common.requests.head
        common.requests.head = lambda *a, **k: _Resp(404, {})
        try:
            self.assertFalse(common.is_live("https://pickdam.com/gone/"))
        finally:
            common.requests.head = real

    def test_200이면_살아있는_글이다(self):
        real = common.requests.head
        common.requests.head = lambda *a, **k: _Resp(200, {})
        try:
            self.assertTrue(common.is_live("https://pickdam.com/alive/"))
        finally:
            common.requests.head = real

    def test_HEAD를_막는_서버는_GET으로_다시_본다(self):
        """405를 죽은 글로 세면 멀쩡한 사이트가 통째로 막힌다."""
        real_h, real_g = common.requests.head, common.requests.get
        common.requests.head = lambda *a, **k: _Resp(405, {})
        common.requests.get = lambda *a, **k: _Resp(200, {})
        try:
            self.assertTrue(common.is_live("https://pickdam.com/no-head/"))
        finally:
            common.requests.head, common.requests.get = real_h, real_g

    def test_네트워크가_막히면_통과시킨다(self):
        """확인 못 했다는 이유로 정상 글을 막으면 파이프라인이 통째로 선다."""
        real = common.requests.head

        def boom(*a, **k):
            raise common.requests.RequestException("no egress")

        common.requests.head = boom
        try:
            self.assertTrue(common.is_live("https://pickdam.com/whatever/"))
        finally:
            common.requests.head = real

    def test_내려간_글은_핀을_만들지_않는다(self):
        """이게 없으면 404를 가리키는 핀이 보드에 올라간다(핀 #164 실측)."""
        import make_pin
        common.save_json("queue.json", {"items": [
            {"id": 901, "site": "pickdam", "title": "내려간 글", "excerpt": "x",
             "url": "https://pickdam.com/gone/", "date": "2026-09-01T00:00:00", "categories": []},
        ]})
        real = common.requests.get
        common.requests.get = lambda *a, **k: _Resp(404, {})
        try:
            made = make_pin.run(1)
        finally:
            common.requests.get = real
        self.assertEqual(made, [], "내려간 글로 핀을 만들었다")

class TestSeoCopy(Base):
    """핀 문구의 원천을 Rank Math 값으로 바꾼 층(2026-09-16 픽토 통보 → 10-11 반영)."""

    def setUp(self):
        super().setUp()
        common.page_meta = self.real_page_meta

    def _html(self, title, desc):
        r = _Resp(200, {})
        r.text = (f'<html><head><title>{title}</title>'
                  f'<meta name="description" content="{desc}"></head><body>x</body></html>')
        return r

    def test_라이브_HTML에서_제목과_설명을_읽는다(self):
        real = common.requests.get
        common.requests.get = lambda *a, **k: self._html("짧은 검색용 제목", "답이 앞에 오는 설명")
        try:
            m = common.page_meta("https://pickdam.com/a/")
        finally:
            common.requests.get = real
        self.assertTrue(m["ok"])
        self.assertEqual(m["title"], "짧은 검색용 제목")
        self.assertEqual(m["desc"], "답이 앞에 오는 설명")

    def test_HTML_엔티티를_푼다(self):
        """&amp;가 그대로 핀에 찍히면 사람이 쓴 글로 안 보인다."""
        real = common.requests.get
        common.requests.get = lambda *a, **k: self._html("A &amp; B", "3mm &lt; 틈새")
        try:
            m = common.page_meta("https://pickdam.com/a/")
        finally:
            common.requests.get = real
        self.assertEqual(m["title"], "A & B")
        self.assertIn("<", m["desc"])

    def test_폴백_문구가_SEO값을_우선한다(self):
        post = self.post()
        post["seo_title"] = "정수기 필터 교체 주기 3개월"
        post["seo_desc"] = "침전 필터만으로는 물맛이 안 돌아옵니다."
        c = make_pin.fallback_copy(post, common.site_by_key("pickdam"))
        self.assertEqual(c["title"], "정수기 필터 교체 주기 3개월")
        self.assertIn("침전 필터", c["description"])

    def test_SEO값이_없으면_기존_경로를_쓴다(self):
        """픽토가 아직 못 채운 글이 있어도 파이프라인이 서면 안 된다."""
        c = make_pin.fallback_copy(self.post(), common.site_by_key("pickdam"))
        self.assertTrue(c["title"])
        self.assertTrue(c["description"])

class TestAnswerBlock(Base):
    """답변 블록 생성. 마크토는 만들기만 하고 본문에는 넣지 않는다."""

    def setUp(self):
        super().setUp()
        import answer_block
        self.ab = answer_block
        self.real_body = self.ab.body_text
        self.ab.body_text = lambda url, limit=1800: ("본문입니다", {"title": "제목", "desc": "요약"})

    def tearDown(self):
        self.ab.body_text = self.real_body
        super().tearDown()

    def _posts(self, n):
        common.wp_posts = lambda site, **k: [self.post(pid=i, title=f"글 {i}") for i in range(1, n + 1)]

    def test_설정이_픽담만_대상으로_둔다(self):
        """원더랜드 본문은 S 소관이다 — 마크토가 블록을 만들 대상이 아니다."""
        self.assertEqual(common.cfg()["answer_block"]["sites"], ["pickdam"])

    def test_max_per_run을_넘기지_않는다(self):
        self._posts(20)
        real = common.llm_json
        common.llm_json = lambda p, **k: {"question": "질문?", "answer": "답.", "conditions": ""}
        try:
            blocks = self.ab.run()
        finally:
            common.llm_json = real
        self.assertLessEqual(len(blocks), common.cfg()["answer_block"]["max_per_run"])

    def test_답이_비면_버린다(self):
        """빈 블록을 본문 맨 위에 넣으면 글이 망가진다."""
        self._posts(3)
        real = common.llm_json
        common.llm_json = lambda p, **k: {"question": "질문?", "answer": "  "}
        try:
            blocks = self.ab.run()
        finally:
            common.llm_json = real
        self.assertEqual(blocks, {})

    def test_내려간_글은_건너뛴다(self):
        self._posts(2)
        self.ab.body_text = lambda url, limit=1800: (None, {"ok": False, "status": 404})
        blocks = self.ab.run()
        self.assertEqual(blocks, {})

    def test_LLM이_실패해도_나머지를_계속한다(self):
        """한 글의 실패가 그날 작업 전체를 멈추면 안 된다."""
        self._posts(3)
        calls = {"n": 0}
        real = common.llm_json

        def flaky(p, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("쿼터 초과")
            return {"question": "질문?", "answer": "답.", "conditions": "조건"}

        common.llm_json = flaky
        try:
            blocks = self.ab.run()
        finally:
            common.llm_json = real
        self.assertEqual(len(blocks), 2, "첫 글 실패 뒤 나머지를 포기했다")

    def test_마크다운_사본을_남긴다(self):
        """픽토가 그대로 보고 옮길 수 있어야 한다."""
        self._posts(1)
        real = common.llm_json
        common.llm_json = lambda p, **k: {"question": "몇 개월마다 갈아야 하나요?",
                                          "answer": "3개월입니다.", "conditions": "4인 가구 기준"}
        try:
            self.ab.run()
        finally:
            common.llm_json = real
        import io as _io
        md = _io.open(os.path.join(common.ROOT, "out", self.ab.OUT_MD), encoding="utf-8").read()
        self.assertIn("몇 개월마다 갈아야 하나요?", md)
        self.assertIn("4인 가구 기준", md)


class TestThreads(Base):
    """스레드 게시 — 네트워크 없이 조립 규칙과 토큰 수명 처리만 검증한다."""

    def setUp(self):
        super().setUp()
        import threads
        self.t = threads

    def test_본문은_500자를_넘지_않고_링크가_끝에_온다(self):
        site = {"key": "pickdam", "url": "https://pickdam.com",
                "utm": "utm_source=threads&utm_medium=social"}
        post = {"url": "https://pickdam.com/a/", "seo_desc": "가" * 900, "title": "제목"}
        out = self.t.compose(post, site)
        self.assertLessEqual(len(out), self.t.TEXT_MAX)
        # 링크는 반드시 **맨 끝** — 스레드는 본문 끝 링크에만 미리보기 카드를 붙인다.
        self.assertTrue(out.rstrip().endswith(
            "https://pickdam.com/a/?utm_source=threads&utm_medium=social"), out[-80:])
        self.assertIn("…", out, "잘렸으면 말줄임표가 있어야 한다")

    def test_설명이_없으면_요약_그다음_제목을_쓴다(self):
        site = {"key": "pickdam", "url": "https://pickdam.com", "utm": "x=1"}
        out = self.t.compose({"url": "https://pickdam.com/a/", "title": "제목만 있음"}, site)
        self.assertIn("제목만 있음", out)

    def test_토큰이_없으면_즉시_멈춘다(self):
        import os
        old = os.environ.pop("THREADS_TOKEN", None)
        try:
            with self.assertRaises(SystemExit):
                self.t.token()
        finally:
            if old is not None:
                os.environ["THREADS_TOKEN"] = old

    def test_갱신에_실패하면_거짓을_돌려준다(self):
        self.t.refresh = lambda tok=None: (None, None)
        self.assertFalse(self.t.rotate())

    def test_갱신값은_파일로_넘긴다_공개저장소라_커밋할_수_없다(self):
        import os, tempfile
        self.t.refresh = lambda tok=None: ("NEWTOKEN", 60 * 86400)
        d = tempfile.mkdtemp()
        p = os.path.join(d, "tok")
        self.assertTrue(self.t.rotate(p))
        self.assertEqual(io_open_read(p), "NEWTOKEN")

    def test_만료가_가까우면_경고한다(self):
        sent = []
        self.t.refresh = lambda tok=None: ("NEWTOKEN", 3 * 86400)
        self.t.common.telegram_msg = lambda m: sent.append(m)
        self.t.rotate()
        self.assertTrue(sent and "만료" in sent[0])


def io_open_read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    unittest.main()
