# -*- coding: utf-8 -*-
"""마크토 공용 유틸 — 설정 로드 · WP REST 수집 · LLM(Gemini) · 텔레그램 · 상태 파일.

다른 SolvUp 레포(Scripto/Picto/Casto)와 코드를 공유하지 않는다. 레포가 다르므로
'구조만 가져오고 코드는 각자 둔다'가 원칙이다(기획 브리프 4장). 의존성은 requests·Pillow뿐.
"""
import json
import os
import re
import time
import html as _html
from datetime import datetime, timezone, timedelta

import requests

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))


# ── 설정 ────────────────────────────────────────────────────────────────
def cfg(path=None):
    with open(path or os.path.join(ROOT, "markto.json"), encoding="utf-8") as f:
        return json.load(f)


def sites(c=None, only_enabled=True):
    """대상 사이트 목록. 1단계는 픽담 하나만 enabled=true다."""
    c = c or cfg()
    return [s for s in c["sites"] if s.get("enabled") or not only_enabled]


def site_by_key(key, c=None):
    for s in (c or cfg())["sites"]:
        if s["key"] == key:
            return s
    raise KeyError(f"markto.json에 사이트 '{key}'가 없습니다")


def now_kst():
    return datetime.now(KST)


def today_kst():
    return now_kst().strftime("%Y-%m-%d")


# ── 상태 파일 (data/*.json) ─────────────────────────────────────────────
def data_path(name):
    return os.path.join(ROOT, "data", name)


def load_json(name, default):
    p = data_path(name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        # 상태 파일이 깨졌다고 파이프라인을 세우지 않는다. 다만 조용히 넘기면
        # '핀 기록 소실 → 같은 글 재게시(스팸 판정)'로 이어지므로 반드시 알린다.
        print(f"[data] {name} 파싱 실패 — 기본값으로 진행하지만 기록이 유실됐을 수 있습니다")
        return default


def save_json(name, obj):
    p = data_path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)   # 쓰다 죽어도 원본이 남도록 원자적 교체


# ── 워드프레스 REST 수집 ────────────────────────────────────────────────
def strip_html(s):
    """WP가 주는 rendered 필드에서 태그·엔티티·공백을 정리한다."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def wp_posts(site, per_page=50, pages=4, timeout=30):
    """공개 WP REST에서 글 목록을 가져온다(인증 불필요 = 자격증명을 다루지 않는다).

    반환: [{id, title, url, excerpt, date, categories}] — 최신순.
    사이트가 죽어 있으면 빈 목록을 돌려주고 호출부가 판단하게 한다(예외로 액션을 붉히지 않는다).
    """
    out, seen = [], set()
    for page in range(1, pages + 1):
        url = f"{site['api']}/posts"
        params = {"per_page": per_page, "page": page, "_fields": "id,link,title,excerpt,date,categories,status"}
        try:
            r = requests.get(url, params=params, timeout=timeout,
                             headers={"User-Agent": "markto/1.0 (+https://pickdam.com)"})
        except requests.RequestException as e:
            print(f"[wp] {site['key']} 요청 실패: {e}")
            break
        if r.status_code == 400:
            break              # page 범위를 넘어서면 400 — 정상 종료 조건
        if r.status_code != 200:
            print(f"[wp] {site['key']} HTTP {r.status_code} — 수집 중단")
            break
        try:
            items = r.json()
        except ValueError:
            print(f"[wp] {site['key']} JSON 아님 — 수집 중단")
            break
        if not items:
            break
        for it in items:
            pid = it.get("id")
            if pid in seen:
                continue
            seen.add(pid)
            out.append({
                "id": pid,
                "site": site["key"],
                "title": strip_html((it.get("title") or {}).get("rendered", "")),
                "url": it.get("link", ""),
                "excerpt": strip_html((it.get("excerpt") or {}).get("rendered", "")),
                "date": it.get("date", ""),
                "categories": it.get("categories", []),
            })
        if len(items) < per_page:
            break
    return out


def with_utm(url, site):
    """핀 → 사이트 유입을 애널리틱스에서 분리 측정하기 위한 UTM 부착.
    성공 지표가 '핀 클릭·세션 유입'이므로 UTM 없이는 이 툴의 성과를 증명할 수 없다."""
    utm = site.get("utm")
    if not utm or not url:
        return url
    if "utm_source=" in url:
        return url
    return url + ("&" if "?" in url else "?") + utm


# ── LLM (Gemini REST) ───────────────────────────────────────────────────
def llm(prompt, max_tokens=2000, temperature=0.7, retries=3, json_mode=False):
    """Gemini generateContent 단순 REST 호출.

    **thinking 함정(캐스토 실측)**: Gemini 2.5 Flash는 사고 토큰이 maxOutputTokens에
    포함되어 긴 JSON이 중간에서 잘린다. thinkingBudget=0으로 사고를 끄고,
    finishReason=MAX_TOKENS면 한도를 올려 재시도한다(잘린 JSON을 조용히 넘기지 않는다).
    """
    key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL") or "gemini-2.5-flash"   # 시크릿 미등록 시 env가 빈 문자열 → or 필수
    if not key:
        raise SystemExit("LLM_API_KEY 시크릿이 없습니다")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    gen = {"maxOutputTokens": max_tokens, "temperature": temperature,
           "thinkingConfig": {"thinkingBudget": 0}}
    if json_mode:
        gen["responseMimeType"] = "application/json"
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen}
    r = None
    for i in range(retries):
        r = requests.post(url, json=body, timeout=120,
                          headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        if r.status_code == 400 and "thinking" in r.text.lower():
            print("[llm] thinkingConfig 미지원 모델 — 옵션 제거 후 재시도")
            gen.pop("thinkingConfig", None)
            continue
        if r.status_code == 200:
            try:
                cand = r.json()["candidates"][0]
                text = cand["content"]["parts"][0]["text"]
                if cand.get("finishReason") == "MAX_TOKENS":
                    print(f"[llm] 출력이 한도({gen['maxOutputTokens']})에서 잘림 — 한도를 올려 재시도")
                    gen["maxOutputTokens"] = min(gen["maxOutputTokens"] * 2, 16000)
                    continue
                return text
            except (KeyError, IndexError, TypeError):
                pass
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"LLM 호출 실패: {getattr(r, 'status_code', '?')} {getattr(r, 'text', '')[:200]}")


def llm_json(prompt, **kw):
    """JSON 응답 강제 + 코드펜스 제거 후 파싱."""
    kw.setdefault("json_mode", True)
    t = llm(prompt + "\n\n[출력] 순수 JSON만. 코드블록·설명 금지.", **kw).strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
    return json.loads(t.strip())


# ── 텔레그램 (Pinterest API 승인 전 게시 경로) ──────────────────────────
def telegram_photo(path, caption=""):
    tok, chat = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not (tok and chat):
        print("[tg] 토큰 없음 — 전송 생략")
        return False
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto",
                          data={"chat_id": chat, "caption": caption[:1024]},
                          files={"photo": f}, timeout=120)
    print("[tg] sendPhoto", r.status_code)
    if r.status_code != 200:
        print("[tg]", r.text[:300])
    return r.status_code == 200


def telegram_document(path, caption=""):
    """핀 원본(1000×1500)을 압축 없이 받기 위한 경로.
    sendPhoto는 텔레그램이 재압축하므로 그대로 업로드하면 화질이 떨어진다."""
    tok, chat = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not (tok and chat):
        return False
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendDocument",
                          data={"chat_id": chat, "caption": caption[:1024]},
                          files={"document": f}, timeout=120)
    print("[tg] sendDocument", r.status_code)
    return r.status_code == 200


def telegram_msg(text):
    tok, chat = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not (tok and chat):
        return False
    requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                  data={"chat_id": chat, "text": text[:4000]}, timeout=30)
    return True
