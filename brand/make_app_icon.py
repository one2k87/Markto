# -*- coding: utf-8 -*-
"""핀터레스트 개발자 앱 아이콘 — **크롭 안전판.**

왜 따로 만드는가. `Picto/brand/make_brand_images.py`의 로고는 마크가 캔버스의 76%를 차지해
가장자리에 거의 붙어 있다. 핀터레스트는 아이콘을 둥근 사각형으로, 프로필은 원으로 잘라서
보여주는데 그러면 **가격표의 뾰족한 왼쪽 끝이 잘려나가 체크만 남는다**(2026-09-09 프로필,
2026-09-10 개발자 앱 아이콘에서 연속 실측).

여기서는 같은 마크를 캔버스의 66%로 줄여 가운데에 놓는다. 그러면 마크 모서리까지의 거리가
반지름의 0.41이라 **원으로 잘라도 사각형으로 잘라도 형태가 온전히 남는다.**

    python3 brand/make_app_icon.py        # brand/pickdam-app-icon-512.png

색과 형태는 픽담 브랜드와 **같은 값**이어야 한다 — 원본은 Picto/brand/make_brand_images.py다.
저기가 바뀌면 여기도 바꾼다(공유_경계.md 4절에 따라 픽토 파일은 건드리지 않는다).
"""
import os

from PIL import Image, ImageDraw

BG = (18, 80, 58)          # 픽담 딥 그린
ACC = (46, 158, 107)       # 포인트 그린
CREAM = (247, 245, 239)
SS = 4                     # 슈퍼샘플링 배율(가장자리 계단 제거)

MARK_RATIO = 0.66          # 마크가 차지할 최종 캔버스 대비 폭. 0.76이면 크롭에 잘린다.


def tag_mark(size):
    """가격표 + 체크. 투명 배경, 끈 구멍은 BG로 채운다(BG 캔버스 위에 얹으면 구멍처럼 보인다)."""
    S = size * SS
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    L, T, R, B = int(S * 0.12), int(S * 0.22), int(S * 0.88), int(S * 0.78)
    tip = int(S * 0.12)
    d.rounded_rectangle((L + tip // 2, T, R, B), radius=int(S * 0.10), fill=ACC)
    d.polygon([(L, (T + B) // 2), (L + tip, T + int(S * 0.02)),
               (L + tip, B - int(S * 0.02))], fill=ACC)
    hx, hy, hr = L + int(S * 0.13), (T + B) // 2, int(S * 0.038)
    d.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=BG)
    cx, cy = (hx + hr + R) // 2, (T + B) // 2
    s, w = int(S * 0.30), int(S * 0.055)
    d.line([(cx - s * 0.46, cy + s * 0.02), (cx - s * 0.10, cy + s * 0.36)],
           fill=CREAM, width=w, joint="curve")
    d.line([(cx - s * 0.10, cy + s * 0.36), (cx + s * 0.50, cy - s * 0.38)],
           fill=CREAM, width=w, joint="curve")
    return im.resize((size, size), Image.LANCZOS)


def app_icon(size):
    """BG로 꽉 찬 정사각. 모서리는 둥글리지 않는다 — 플랫폼이 알아서 자른다.

    직접 둥글리면 플랫폼의 곡률과 어긋나 흰 귀퉁이가 비친다.
    """
    im = Image.new("RGB", (size, size), BG)
    inner = int(round(size * MARK_RATIO / 0.76))   # 마크는 제 캔버스의 76%를 차지한다
    m = tag_mark(inner)
    off = (size - inner) // 2
    im.paste(m, (off, off), m)
    return im


def safe_margin(size):
    """마크 모서리에서 캔버스 중심까지의 거리를 반지름 대비 비율로. 1.0 미만이면 원 크롭 안전."""
    w = MARK_RATIO
    h = w * (0.78 - 0.22) / (0.88 - 0.12)          # 원본 마크의 세로/가로 비
    return ((w / 2) ** 2 + (h / 2) ** 2) ** 0.5 / 0.5


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for n in (512, 192):
        p = os.path.join(here, f"pickdam-app-icon-{n}.png")
        app_icon(n).save(p, optimize=True)
        print(os.path.basename(p), os.path.getsize(p), "bytes")
    print(f"원 크롭 여유: 마크 모서리가 반지름의 {safe_margin(512):.2f}배 지점 (1.00 미만이면 안전)")
