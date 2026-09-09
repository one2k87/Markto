# -*- coding: utf-8 -*-
"""마크토 앱 아이콘 — 파스텔 오렌지(#F5A46A) 바탕 + '한 장을 여러 곳으로 뿌린다' 모티프.

파스텔 위에는 흰 글자를 쓰지 않는다(대비 2.02:1로 안 읽힘 — 실측).
진한 브라운 #4A3728을 쓰면 5.57:1로 안전하다.
재생성: python3 brand_icons.py
"""
from PIL import Image, ImageDraw

PASTEL = (245, 164, 106)      # #F5A46A 마크토 메인
DEEP   = (194, 102, 46)       # #C2662E 진한 톤(작은 글자·선)
INK    = (74, 55, 40)         # #4A3728 파스텔 위 글자
CREAM  = (255, 247, 240)      # #FFF7F0
SS = 4


def icon(size, bg=PASTEL, radius_ratio=0.22):
    S = size * SS
    im = Image.new("RGB", (S, S), bg)
    d = ImageDraw.Draw(im)
    # 왼쪽: 핀 한 장 (2:3 세로 카드)
    cw, ch = int(S * .26), int(S * .39)
    cx, cy = int(S * .22), (S - ch) // 2
    d.rounded_rectangle((cx, cy, cx + cw, cy + ch), radius=int(S * .045), fill=CREAM)
    # 카드 안 텍스트 줄 두 개 — '글자가 박힌 핀'을 암시
    for i, w in enumerate((.62, .40)):
        y = cy + int(ch * (.30 + i * .22))
        d.rounded_rectangle((cx + int(cw * .16), y,
                             cx + int(cw * .16) + int(cw * .68 * w), y + int(ch * .075)),
                            radius=int(S * .008), fill=INK)
    # 오른쪽: 퍼져나가는 세 점 (뿌린다)
    for i, (fx, fy, r) in enumerate(((.56, .50, .052), (.74, .32, .042), (.74, .68, .042))):
        px, py, pr = int(S * fx), int(S * fy), int(S * r)
        d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=INK if i == 0 else CREAM)
    # 연결선
    for fx, fy in ((.74, .32), (.74, .68)):
        d.line([(int(S * .56), int(S * .50)), (int(S * fx), int(S * fy))],
               fill=CREAM, width=int(S * .017))
    out = im.resize((size, size), Image.LANCZOS)
    # 라운드 마스크
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, S, S), radius=int(S * radius_ratio), fill=255)
    rounded = Image.new("RGB", (size, size), CREAM)
    rounded.paste(out, (0, 0), m.resize((size, size), Image.LANCZOS))
    return rounded


for n in (192, 512):
    icon(n).save(f"dashboard/icons/icon-{n}.png", optimize=True)
# 애플 터치 아이콘은 iOS가 자체적으로 라운드를 깎으므로 정사각(라운드 없음)으로 둔다
icon(180, radius_ratio=0.001).save("dashboard/icons/apple-touch-icon.png", optimize=True)
print("아이콘 3종 생성 완료")
