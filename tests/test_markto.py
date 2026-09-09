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
