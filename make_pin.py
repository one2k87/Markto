# -*- coding: utf-8 -*-
"""③ 문구 생성 → ④ 핀 이미지 → ⑤ 게시(텔레그램) → ⑥ 기록.

사용:  python make_pin.py            (설정의 per_run 만큼)
       python make_pin.py 1          (건수 지정)
       python make_pin.py 1 --dry    (LLM·전송 없이 이미지만 — 디자인 확인용)

핀터레스트 스팸 판정을 피하려고 **상한을 코드가 강제한다**: 하루 per_day건,
같은 글 재게시는 min_hours_between_same_post 이후에만. 사람이 실수로 여러 번
돌려도 초과분은 만들지 않는다.
"""
import glob
import os
import re
import shutil
import sys

import common
import pin_image

OUT = os.path.join(common.ROOT, "out")
GALLERY_KEEP = 30


def gallery_dir():
    """대시보드 갤러리 경로. **호출 시점에** common.ROOT를 읽는다.

    모듈 상수로 굳히면 테스트가 common.ROOT를 임시 폴더로 갈아끼워도 상수는 실제 레포를
    가리켜, 테스트가 진짜 dashboard/pins/에 파일을 쓴다(2026-09-09 실측: 커밋 직전에
    테스트 잔재 3장이 스테이징돼 있었다).
    """
    return os.path.join(common.ROOT, "dashboard", "pins")


def publish_to_gallery(path, keep=GALLERY_KEEP):
    """핀 이미지를 대시보드가 볼 수 있는 곳으로 복사하고, 최근 keep장만 남긴다.

    out/은 커밋하지 않는다(.gitignore) — 레포가 이미지로 불어나면 곤란하다.
    다만 대시보드에서 이미지를 보고 폰으로 저장하는 것이 수동 게시의 핵심 동작이라,
    최근 것만 레포에 둔다(3건/일 × 30장 ≈ 1.5MB로 묶인다).
    """
    gal = gallery_dir()
    os.makedirs(gal, exist_ok=True)
    dst = os.path.join(gal, os.path.basename(path))
    shutil.copyfile(path, dst)
    imgs = sorted(glob.glob(os.path.join(gal, "*.png")), key=os.path.getmtime)
    for old in imgs[:-keep]:
        try:
            os.remove(old)
        except OSError:
            pass          # 지우지 못해도 파이프라인을 세우지 않는다(다음 실행이 다시 시도한다)
    return dst

PROMPT = """너는 한국 핀터레스트에서 블로그 유입을 만드는 카피라이터다.
아래 글 하나를 핀으로 만들 문구를 쓴다.

[글 제목] {title}
[글 요약] {excerpt}
[사이트] {site_name} — {tagline}

규칙
- image_text: **핀 이미지 안에 크게 들어갈 문구.** 22자 이내. 검색어가 아니라 '멈추게 하는 말'.
  글 제목을 그대로 베끼지 말고, 독자가 궁금해할 지점 하나로 좁힌다. 물음표는 최대 1개.
- title: 핀 제목. 40자 이내. 사람들이 검색할 법한 말이 앞쪽에 오게 쓴다.
- description: 200자 이내. 첫 문장에 핵심 검색 키워드를 자연스럽게 넣고,
  글을 열면 무엇을 알 수 있는지 구체적으로 쓴다. 과장·낚시 금지.
- kicker: 이미지 안 작은 칩에 넣을 분류. 2~6자(예: 주방, 살까 말까, 생활 점검).
- hashtags: 한국어 해시태그 {tag_n}개. # 없이 단어만. 너무 일반적인 것(#일상) 금지.

금지
- 이모지를 절대 쓰지 않는다(이미지·문구 모두). 렌더링이 깨진다.
- 가격·할인율 등 시간이 지나면 틀려질 수치를 단정하지 않는다.

JSON 스키마: {{"image_text":"","title":"","description":"","kicker":"","hashtags":[]}}"""


def fallback_copy(post, site, tag_n=4):
    """LLM 없이도 파이프라인이 굴러가게 하는 최소 문구.
    (키 미등록·쿼터 초과 상황에서 '아무것도 안 만들어짐'보다 낫다. 품질은 LLM 경로가 담당한다.)"""
    t = re.sub(r"\s*[\|\-–—]\s*.*$", "", post["title"]).strip()
    return {
        "image_text": t[:22],
        "title": post["title"][:40],
        "description": (post.get("excerpt") or post["title"])[:200],
        "kicker": site.get("tagline", "")[:6],
        "hashtags": [],
        "_fallback": True,
    }


def make_copy(post, site, cfg, dry=False):
    if dry or not os.getenv("LLM_API_KEY"):
        return fallback_copy(post, site, cfg["pin"]["hashtags_max"])
    p = PROMPT.format(title=post["title"], excerpt=(post.get("excerpt") or "")[:600],
                      site_name=site["name"], tagline=site.get("tagline", ""),
                      tag_n=cfg["pin"]["hashtags_max"])
    try:
        j = common.llm_json(p, max_tokens=1200, temperature=0.8)
    except Exception as e:                       # noqa: BLE001 — 어떤 실패든 폴백으로 계속 간다
        print(f"[copy] LLM 실패({e}) — 폴백 문구 사용")
        return fallback_copy(post, site, cfg["pin"]["hashtags_max"])
    j["image_text"] = strip_emoji(j.get("image_text") or post["title"])[:26]
    j["title"] = strip_emoji(j.get("title") or post["title"])[:cfg["pin"]["title_max"]]
    j["description"] = strip_emoji(j.get("description") or "")[:cfg["pin"]["desc_max"]]
    j["kicker"] = strip_emoji(j.get("kicker") or "")[:8]
    tags = [strip_emoji(str(t)).lstrip("#").strip() for t in (j.get("hashtags") or [])]
    j["hashtags"] = [t for t in tags if t][:cfg["pin"]["hashtags_max"]]
    return j


_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\U00002190-\U000021FF⬀-⯿]")


def strip_emoji(s):
    """LLM이 규칙을 어기고 이모지를 넣어도 이미지에 두부(⃞)가 찍히지 않도록 마지막 방어선."""
    return re.sub(r"\s+", " ", _EMOJI.sub("", s or "")).strip()


def caption(post, copy, site, cfg):
    """텔레그램으로 보낼 수동 게시용 안내문. 폰에서 그대로 복사해 핀에 붙여넣는다."""
    tags = " ".join("#" + t for t in copy.get("hashtags", []))
    link = common.with_utm(post["url"], site)
    # 머리에 앱 표기를 붙인다 — 네 앱이 텔레그램 한 채널을 공유하므로(공유_경계.md 1절)
    return (f"📌 마크토 · [핀 준비] {site['name']} · 보드: {site.get('board', '')}\n\n"
            f"■ 제목\n{copy['title']}\n\n"
            f"■ 설명\n{copy['description']}\n{tags}\n\n"
            f"■ 링크\n{link}\n\n"
            f"(원문: {post['title']})")


def run(n=None, dry=False):
    cfg = common.cfg()
    q = common.load_json("queue.json", {"items": []})
    items = q.get("items", [])
    if not items:
        print("[make] 큐가 비었습니다 — 먼저 collect.py를 실행하세요")
        return []

    pins = common.load_json("pins.json", {"pins": []})
    today = common.today_kst()
    made_today = sum(1 for p in pins["pins"] if str(p.get("made_at", ""))[:10] == today)
    room = max(0, cfg["quota"]["per_day"] - made_today)
    want = n if n is not None else cfg["quota"]["per_run"]
    want = min(want, room)
    if want <= 0:
        print(f"[make] 오늘 상한({cfg['quota']['per_day']}건) 도달 — 생성하지 않습니다")
        return []

    done_ids = {(p.get("site"), p.get("post_id")) for p in pins["pins"]}
    made = []
    for post in items:
        if len(made) >= want:
            break
        if (post["site"], post["id"]) in done_ids:
            continue
        site = common.site_by_key(post["site"], cfg)
        copy = make_copy(post, site, cfg, dry=dry)
        path = os.path.join(OUT, f"pin_{post['site']}_{post['id']}.png")
        pin_image.render_pin(path, site, copy["image_text"],
                             subtitle=copy["title"] if copy["title"] != copy["image_text"] else "",
                             kicker=copy.get("kicker", ""), cfg_pin=cfg["pin"])
        print(f"[make] {post['site']}#{post['id']} → {os.path.basename(path)} · {copy['title']}")
        if not dry:
            publish_to_gallery(path)      # 대시보드에서 보고 폰으로 저장하기 위한 사본

        sent = False
        if not dry and cfg["publish"]["mode"] == "telegram":
            sent = common.telegram_photo(path, caption(post, copy, site, cfg))
        elif not dry and cfg["publish"]["mode"] == "pinterest":
            import publish
            sent = publish.publish_pin(path, copy, post, site, cfg)

        rec = {
            "site": post["site"], "post_id": post["id"], "post_title": post["title"],
            "url": common.with_utm(post["url"], site),
            "pin_title": copy["title"], "pin_desc": copy["description"],
            "hashtags": copy.get("hashtags", []), "image": os.path.relpath(path, common.ROOT),
            "made_at": common.now_kst().isoformat(timespec="seconds"),
            "sent": bool(sent), "mode": cfg["publish"]["mode"],
            "pin_id": None, "posted_at": None,
        }
        if copy.get("_fallback"):
            rec["fallback_copy"] = True
        if not dry:
            pins["pins"].append(rec)
        made.append(rec)

    if not dry:
        common.save_json("pins.json", pins)
        # 큐에서 소진분 제거 — 다음 실행이 같은 글을 다시 집지 않도록
        used = {(m["site"], m["post_id"]) for m in made}
        q["items"] = [it for it in items if (it["site"], it["id"]) not in used]
        common.save_json("queue.json", q)
    print(f"[make] {len(made)}건 생성 (오늘 누적 {made_today + len(made)}/{cfg['quota']['per_day']})")
    return made


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(int(args[0]) if args else None, dry="--dry" in sys.argv)
