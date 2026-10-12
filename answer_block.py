# -*- coding: utf-8 -*-
"""답변 블록 생성 — 글마다 "질문 하나 + 숫자가 앞에 오는 즉답 + 적용 조건"을 뽑는다.

**마크토는 만들기만 하고 본문에는 넣지 않는다.** 삽입은 픽토 소관이다(공유_경계 4절).
결과는 `data/answer_blocks.json` 과 사람이 읽을 `out/answer_blocks.md` 로 남기고,
픽토는 레포 raw 주소로 가져간다.

왜 만드는가(2026-10-11 실측). 픽담 GSC 상위 노출 검색어에 **문장형 질문**이 섞여 있다 —
「냉장고 구독과 카드 무이자 할부 중 어떤 게 유리한가요?」「가전의 경우 무이자 할부랑
구독형의 총비용 비교해줘.」, 심지어 「네」(게재순위 2.0). 사람이 검색창에 "네"라고 치지
않는다. **AI Mode·AI Overviews의 내부 쿼리**가 GSC에 기록되는 것으로 보이고, 같은 기간
생성형 AI 기능 노출이 0 → 6으로 올라왔다. 즉 픽담은 이미 "답변 재료"로 읽히고 있다.

조사(2026-10-01)에서 네이버 AI 브리핑도 인용 272건 중 **외부 자체도메인이 45건(16.5%)**,
그중 **Top10 밖이 49.3%** 였다. 순위를 못 올려도 인용될 수 있다는 뜻이고, 인용되려면
**핵심 답이 도입부에 즉시 있고 적용 조건·예외가 명시**돼 있어야 한다는 것이 권고였다.
그 형태를 글마다 하나씩 만들어 두는 것이 이 스크립트다.

    python answer_block.py            # 아직 안 만든 글 중 설정의 max_per_run 만큼
    python answer_block.py --all      # 전부 다시 만든다(프롬프트를 고쳤을 때)
    python answer_block.py --dry      # LLM 없이 어떤 글이 대상인지만 출력

정직하게: 이 블록을 넣는다고 인용이 보장되지 않는다. 상관관계 근거이고,
구글·네이버가 재평가하는 데 수 주가 걸린다. 다만 **지금 구조로는 인용될 길이 없다.**
"""
import argparse
import io
import json
import os
import sys

import common

STATE = "answer_blocks.json"      # data/answer_blocks.json
OUT_MD = "answer_blocks.md"       # out/answer_blocks.md — 픽토가 읽을 사람용 사본

PROMPT = """너는 한국어 생활가전 구매결정 블로그의 편집자다.
아래 글을 읽고 **AI 검색이 인용하기 좋은 형태**의 답변 블록을 만든다.

제목: {title}
요약: {desc}
본문 발췌: {body}

규칙
- question: 이 글이 답하는 질문 **하나**. 사람이 실제로 말하듯 자연스러운 문장으로
  (예: "정수기 필터는 몇 개월마다 갈아야 하나요?"). 글 제목을 그대로 베끼지 마라.
- answer: **2문장.** 첫 문장에 숫자나 기준이 바로 나와야 한다. 돌려 말하지 마라.
  "이 글에서는", "알아보겠습니다" 같은 표현 금지.
- conditions: 이 답이 **달라지는 조건이나 예외** 1~2개. 구체적인 수치·상황으로.
  해당 사항이 정말 없으면 빈 문자열.
- 글에 없는 숫자를 지어내지 마라. 근거가 없으면 숫자 없이 기준만 써라.

JSON만 출력한다:
{{"question": "...", "answer": "...", "conditions": "..."}}"""


def body_text(url, limit=1800):
    """본문 앞부분. 답을 지어내지 않도록 LLM에게 실제 문장을 준다."""
    import re
    m = common.page_meta(url)
    if not m["ok"]:
        return None, m
    try:
        import requests
        h = requests.get(url, timeout=20, headers={"User-Agent": "markto/1.0"}).text
    except Exception:                         # noqa: BLE001
        return "", m
    h = re.sub(r"<(script|style|nav|header|footer)[\s\S]*?</\1>", " ", h, flags=re.I)
    t = common.strip_html(h)
    return t[:limit], m


def make_block(post, dry=False):
    body, meta = body_text(post["url"])
    if body is None:
        return None, "글이 내려갔습니다(비200)"
    if dry:
        return {"question": "(dry)", "answer": "", "conditions": ""}, None
    p = PROMPT.format(title=meta.get("title") or post["title"],
                      desc=meta.get("desc") or post.get("excerpt", ""),
                      body=body)
    try:
        j = common.llm_json(p, max_tokens=700, temperature=0.4)
    except Exception as e:                    # noqa: BLE001 — 한 글 실패가 전체를 막지 않는다
        return None, f"LLM 실패: {e}"
    q = (j.get("question") or "").strip()
    a = (j.get("answer") or "").strip()
    if not (q and a):
        return None, "질문 또는 답이 비었습니다"
    return {"question": q[:120], "answer": a[:400],
            "conditions": (j.get("conditions") or "").strip()[:300]}, None


def write_markdown(blocks):
    """픽토가 보고 그대로 옮겨 붙일 수 있는 형태."""
    path = os.path.join(common.ROOT, "out", OUT_MD)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["# 답변 블록 (마크토 생성 · 삽입은 픽토)", "",
             "각 글 **맨 위**에 넣을 블록입니다. 질문은 h2나 굵은 글씨로, 답은 첫 문단으로,",
             "조건은 그 아래 한 줄로 두면 됩니다. 본문에 이미 같은 내용이 있으면 중복시키지 말고",
             "그 문단을 위로 올려 주세요.", ""]
    for key, b in sorted(blocks.items(), key=lambda kv: -int(kv[0].split(":")[1])):
        lines += [f"## {b['title']}", f"`{b['url']}`", "",
                  f"**{b['question']}**", "", b["answer"]]
        if b.get("conditions"):
            lines += ["", f"> 적용 조건: {b['conditions']}"]
        lines += ["", "---", ""]
    io.open(path, "w", encoding="utf-8").write("\n".join(lines))
    return path


def run(remake=False, dry=False):
    cfg = common.cfg()
    conf = cfg.get("answer_block") or {}
    if not conf.get("enabled", True):
        print("[answer] 꺼져 있습니다 (markto.json의 answer_block.enabled)")
        return {}
    cap = int(conf.get("max_per_run", 5))
    only = conf.get("sites") or ["pickdam"]

    blocks = common.load_json(STATE, {})
    made, failed = 0, []
    for site in cfg["sites"]:
        if site["key"] not in only:
            continue
        posts = common.wp_posts(site, per_page=50, pages=2)
        for post in posts:
            if made >= cap:
                break
            key = f"{site['key']}:{post['id']}"
            if key in blocks and not remake:
                continue
            b, err = make_block(post, dry=dry)
            if err:
                failed.append((key, err))
                print(f"[answer] {key} 건너뜀 — {err}")
                continue
            b.update(title=post["title"], url=post["url"])
            blocks[key] = b
            made += 1
            print(f"[answer] {key} · {b['question']}")

    if not dry and blocks:
        # 새로 만든 게 없어도 마크다운은 항상 써 둔다 — 워크플로가 이 경로를 커밋 대상으로
        # 잡고 있어서, 파일이 사라지면 pathspec 에러로 커밋이 통째로 조용히 건너뛰어진다.
        if made:
            common.save_json(STATE, blocks)
        print(f"[answer] {made}건 생성 · 누적 {len(blocks)}건 → {write_markdown(blocks)}")
    else:
        print(f"[answer] {made}건 생성 (누적 {len(blocks)}건)")
    if failed:
        print(f"[answer] 실패 {len(failed)}건")
    return blocks


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="이미 만든 글도 다시 만든다")
    ap.add_argument("--dry", action="store_true", help="LLM 없이 대상만 확인")
    a = ap.parse_args()
    run(remake=a.all, dry=a.dry)
