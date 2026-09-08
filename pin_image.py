# -*- coding: utf-8 -*-
"""핀 이미지 렌더러 — 1000×1500(2:3) 세로 이미지 한 장.

설계 원칙
- **핀은 이미지 안의 글자로 읽힌다.** 사진이 아니라 큰 한글 타이포가 주인공이다.
- **이모지 금지.** 러너에 컬러 이모지 폰트가 없어 두부(⃞)로 렌더된다(캐스토 실측).
  강조는 도형(막대·점·라운드 칩)과 한글로만 한다.
- **팔레트는 사이트 브랜드에 고정.** 픽담 그린(#12503A·#2E9E6B·#F7F5EF)은
  블로그 리디자인·로고와 같은 값이라 핀 → 사이트 이동 시 이질감이 없다.
- 도형은 SS배 확대해 그린 뒤 축소(계단 제거), 글자는 1배에서 직접 그린다(선명도 유지).
"""
import os
import glob

from PIL import Image, ImageDraw, ImageFont

SS = 3                      # 도형 슈퍼샘플링 배율
_FONT_CACHE = {}


# ── 폰트 ────────────────────────────────────────────────────────────────
def font_file(name):
    """폰트 파일 경로를 찾는다. 러너(ubuntu-latest, fonts-noto-cjk)와 로컬 모두 대응."""
    cands = [
        f"/usr/share/fonts/opentype/noto/{name}",
        f"/usr/share/fonts/truetype/noto/{name}",
        f"/usr/share/fonts/opentype/noto/cjk/{name}",
    ]
    for p in cands:
        if os.path.exists(p):
            return p
    hit = glob.glob(f"/usr/share/fonts/**/{name}", recursive=True)
    if hit:
        return hit[0]
    raise FileNotFoundError(f"{name} 를 찾지 못했습니다. 러너에 fonts-noto-cjk 설치가 필요합니다")


def kr_index(path):
    """ttc 안에서 **한국어 페이스의 인덱스를 이름으로 찾아낸다.**

    함정: NotoSansCJK ttc의 페이스 순서는 폰트 패키지 버전마다 다르다
    (실측: 이 컨테이너는 KR=1, Picto 브랜드 스크립트가 쓰던 값은 2).
    인덱스를 상수로 박으면 어느 날 일본어 폰트로 조용히 바뀌어 렌더된다.
    """
    for i in range(12):
        try:
            f = ImageFont.truetype(path, 12, index=i)
        except (OSError, ValueError):
            break
        fam = (f.getname()[0] or "")
        if "KR" in fam and "Mono" not in fam:
            return i
    return 0


def font(name, size):
    key = (name, size)
    if key not in _FONT_CACHE:
        p = font_file(name)
        _FONT_CACHE[key] = ImageFont.truetype(p, size, index=kr_index(p))
    return _FONT_CACHE[key]


# ── 텍스트 배치 ─────────────────────────────────────────────────────────
def _w(draw, text, f):
    return draw.textbbox((0, 0), text, font=f)[2]


def wrap(draw, text, f, max_w):
    """공백 기준 줄바꿈. 한 어절이 폭을 넘으면 글자 단위로 쪼갠다(한국어 긴 합성어 대응)."""
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if _w(draw, trial, f) <= max_w or not cur:
            if _w(draw, trial, f) <= max_w:
                cur = trial
                continue
            # 어절 하나가 이미 폭을 넘는다 → 글자 단위
            if cur:
                lines.append(cur)
                cur = ""
            piece = ""
            for ch in word:
                if _w(draw, piece + ch, f) <= max_w or not piece:
                    piece += ch
                else:
                    lines.append(piece)
                    piece = ch
            cur = piece
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_lines(draw, text, name, max_w, max_h, hi, lo, line_gap=1.22, max_lines=5):
    """상자(max_w × max_h)에 들어가는 가장 큰 글자 크기를 찾아 (font, lines)를 돌려준다."""
    best = None
    for size in range(hi, lo - 1, -2):
        f = font(name, size)
        lines = wrap(draw, text, f, max_w)
        if len(lines) > max_lines:
            continue
        h = len(lines) * size * line_gap
        if h <= max_h:
            return f, lines
        best = (f, lines)
    return best if best else (font(name, lo), wrap(draw, text, font(name, lo), max_w))


# ── 브랜드 마크(가격표 + 체크) ──────────────────────────────────────────
def tag_mark(size, brand, on_dark=True):
    """픽담 로고와 같은 모티프(가격표+체크)를 size×size 투명 이미지로.
    Picto/brand/make_brand_images.py의 형태를 마크토 규격에 맞춰 다시 그린 것이다."""
    S = size * SS
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    acc = tuple(brand["accent"])
    cream = tuple(brand["cream"])
    hole = tuple(brand["bg"]) if on_dark else cream
    L, T, R, B = int(S * .10), int(S * .22), int(S * .90), int(S * .78)
    tip = int(S * .13)
    d.rounded_rectangle((L + tip // 2, T, R, B), radius=int(S * .11), fill=acc)
    d.polygon([(L, (T + B) // 2), (L + tip, T + int(S * .02)), (L + tip, B - int(S * .02))], fill=acc)
    hx, hy, hr = L + int(S * .14), (T + B) // 2, int(S * .040)
    d.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=hole)
    cx, cy = (hx + hr + R) // 2, (T + B) // 2
    s, w = int(S * .30), int(S * .058)
    d.line([(cx - s * .46, cy + s * .02), (cx - s * .10, cy + s * .36)], fill=cream, width=w, joint="curve")
    d.line([(cx - s * .10, cy + s * .36), (cx + s * .50, cy - s * .38)], fill=cream, width=w, joint="curve")
    return im.resize((size, size), Image.LANCZOS)


# ── 핀 한 장 ────────────────────────────────────────────────────────────
def render_pin(out_path, site, title, subtitle="", kicker="", cfg_pin=None):
    """핀 이미지를 만들어 저장하고 경로를 돌려준다.

    title    : 이미지 안의 큰 글자(핀 제목과 같은 문구). 40자 이내 권장.
    subtitle : 카드 아래 한 줄 보조 문구(없어도 된다).
    kicker   : 카드 위 작은 칩 문구(카테고리·성격). 없으면 사이트 태그라인.
    """
    p = cfg_pin or {}
    W = int(p.get("width", 1000))
    H = int(p.get("height", 1500))
    bold = p.get("font_bold", "NotoSansCJK-Bold.ttc")
    reg = p.get("font_regular", "NotoSansCJK-Regular.ttc")
    b = site["brand"]
    BG, ACC, CREAM, MUTED = (tuple(b["bg"]), tuple(b["accent"]),
                             tuple(b["cream"]), tuple(b["muted"]))

    # ① 도형 레이어 — SS배로 그려 축소(라운드 코너 계단 제거)
    shp = Image.new("RGB", (W * SS, H * SS), BG)
    sd = ImageDraw.Draw(shp)
    M = int(W * .07) * SS                                   # 좌우 여백
    card_t, card_b = int(H * .215) * SS, int(H * .745) * SS  # 카드 상·하단
    sd.rounded_rectangle((M, card_t, W * SS - M, card_b), radius=int(W * .045) * SS, fill=CREAM)
    # 상단 얇은 액센트 바 — 브랜드 색을 한 줄로 못박는다
    sd.rectangle((0, 0, W * SS, int(H * .011) * SS), fill=ACC)
    # 하단 액센트 블록 (도메인 표기 자리)
    sd.rectangle((0, int(H * .905) * SS, W * SS, H * SS), fill=ACC)
    shp = shp.resize((W, H), Image.LANCZOS)

    im = shp
    d = ImageDraw.Draw(im)
    pad = int(W * .07)
    inner_w = W - 2 * pad - int(W * .06)

    # ② 상단 — 브랜드 마크 + 워드마크
    mark = int(W * .085)
    im.paste(tag_mark(mark, b, on_dark=True), (pad, int(H * .075)), tag_mark(mark, b, on_dark=True))
    fw = font(bold, int(W * .052))
    d.text((pad + mark + int(W * .028), int(H * .075) + mark // 2), site.get("wordmark", site["name"]),
           font=fw, fill=CREAM, anchor="lm")

    # ③ 카드 안 — 킥커 칩 + 큰 제목 (블록 전체를 카드 안에서 수직 중앙 정렬)
    #    글자 수가 들쭉날쭉해도(한 줄짜리 제목 ~ 다섯 줄짜리 제목) 무게 중심이 흔들리지 않는다.
    card_top, card_bot = int(H * .215), int(H * .745)
    cx0 = pad + int(W * .055)
    chip_text = (kicker or site.get("tagline", "")).strip()
    chip_h = int(W * .056) if chip_text else 0
    chip_gap = int(H * .030) if chip_text else 0
    ul_gap, ul_h = int(H * .042), int(H * .008)

    avail_h = (card_bot - card_top) - 2 * int(H * .055) - chip_h - chip_gap - ul_gap - ul_h
    ft, lines = fit_lines(d, title, bold, inner_w, avail_h,
                          hi=int(W * .098), lo=int(W * .046), max_lines=5)
    lh = ft.size * 1.22
    title_h = int(len(lines) * lh)
    block_h = chip_h + chip_gap + title_h + ul_gap + ul_h
    y = card_top + ((card_bot - card_top) - block_h) // 2

    if chip_text:
        fc = font(bold, int(W * .030))
        tw = _w(d, chip_text, fc)
        d.rounded_rectangle((cx0, y, cx0 + tw + int(W * .052), y + chip_h), radius=chip_h // 2, fill=ACC)
        d.text((cx0 + int(W * .026), y + chip_h // 2), chip_text, font=fc, fill=CREAM, anchor="lm")
        y += chip_h + chip_gap

    for ln in lines:
        d.text((cx0, y), ln, font=ft, fill=BG)
        y += lh

    # 제목 아래 짧은 액센트 밑줄 — 시선의 끝을 만든다
    ul_y = int(y + ul_gap - lh * .22)   # 마지막 줄의 행간 여백만큼 되돌려 실제 글자 밑에 붙인다
    d.rounded_rectangle((cx0, ul_y, cx0 + int(W * .16), ul_y + ul_h),
                        radius=ul_h // 2, fill=ACC)

    # ④ 카드 아래 — 보조 한 줄
    if subtitle:
        fs, slines = fit_lines(d, subtitle, reg, W - 2 * pad, int(H * .085),
                               hi=int(W * .040), lo=int(W * .026), max_lines=2)
        y = int(H * .782)
        for ln in slines:
            d.text((pad, y), ln, font=fs, fill=MUTED)
            y += fs.size * 1.30

    # ⑤ 하단 액센트 블록 — 도메인(출처)
    fd = font(bold, int(W * .038))
    dom = site["url"].replace("https://", "").replace("http://", "").rstrip("/")
    d.text((W // 2, int(H * .905) + (H - int(H * .905)) // 2), dom,
           font=fd, fill=CREAM, anchor="mm")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    im.save(out_path, "PNG", optimize=True)
    return out_path
