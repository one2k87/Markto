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


class _Resp:
    """requests 응답 대역 — 네트워크 없이 상태코드·본문만 흉내낸다."""

    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


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

    def tearDown(self):
        common.ROOT = self.real_root
        common.wp_posts = self.real_wp
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


if __name__ == "__main__":
    unittest.main()


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
        import oauth_setup
        got = set(oauth_setup.SCOPES.split(","))
        self.assertEqual(got, {"boards:read", "pins:read", "pins:write"})
        self.assertFalse([s for s in got if "secret" in s], "비공개 스코프를 요청하고 있다")
