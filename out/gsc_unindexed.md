# 픽담 GSC 미색인 분석 — 2026-10-12 (마크토 추출)

색인 **36** / 미색인 **30**. 사유별 내역과, 사람이 손댈 대상만 추렸습니다.

| 사유 | 건수 | 성격 |
|---|---|---|
| 발견됨 — 현재 색인이 생성되지 않음 | **16** | 구글이 URL은 알지만 **크롤링조차 안 함**. 크롤 예산 문제 → 수동 색인 요청·IndexNow가 직접 듣는 유형 |
| 크롤링됨 — 현재 색인이 생성되지 않음 | **7** | 크롤은 했는데 구글이 **가치 판단으로 거부**. 본문 문제 |
| 리디렉션이 포함된 페이지 | 3 | 301 정리의 정상 결과 |
| 찾을 수 없음(404) | 2 | 내려간 글 |
| 'NOINDEX' 태그에 의해 제외 | 1 | ⚠️ 의도인지 사고인지 미확인 |
| 적절한 표준 태그가 포함된 대체 페이지 | 1 | 정상 |
| 사용자가 선택한 표준이 없는 **중복 페이지** | **0 · 통과** ✅ | 9월 비데 4중복이 해소됐다는 증거 |

## ① 수동 색인 요청 대상 — 실제 글 8건

「발견됨」 16건에서 카테고리·정책 페이지를 뺀 것입니다. **크롤을 못 받은 상태라 요청이 가장 잘 듣습니다.**

1. https://pickdam.com/bathroom-mini/
2. https://pickdam.com/can-opener-comparison-types/
3. https://pickdam.com/kitchen-tools-material-guide/
4. https://pickdam.com/one-person-food-waste-disposer-low-noise-tips/
5. https://pickdam.com/one-person-seasoning-storage/
6. https://pickdam.com/single-household-mini-washer-boil-wash/
7. https://pickdam.com/spice-jar-material-guide/
8. https://pickdam.com/sprayer-glass-plastic-kitchen/

「크롤링됨」 7건 중 실제 글 2건 — 이쪽은 요청보다 **본문 보강**이 먼저입니다.

9. https://pickdam.com/entryway-sensor-light-electricity-cost/
10. https://pickdam.com/single-household-mini-induction-kitchen/

**요청 방법**: GSC 상단 검색창에 주소를 붙여넣고 **[색인 생성 요청]**.
하루 요청 수에 한도가 있으니 위에서부터 차례로.

## ② 색인 노이즈 — 피드 2건 (픽토 소관)

| URL | 실측 |
|---|---|
| `pickdam.com/high-efficiency-appliance-energy-cashback-2026-09/feed/` | HTTP 200, `application/rss+xml` |
| `pickdam.com/comments/feed/` | HTTP 200, `application/rss+xml` |

`robots.txt`에 피드 차단이 없어 구글이 색인 대상으로 잡고 있습니다(현재 Disallow는 `/wp-admin/` 뿐).
색인될 이유가 없고 **미색인 숫자만 부풀립니다.** 피드에 `noindex` 헤더를 주거나
robots.txt에 `Disallow: */feed/`를 넣으면 정리됩니다.

## ③ 확인되지 않은 것

- **NOINDEX 1건** — 어느 페이지인지 확인하지 않았습니다. 의도적이면 그대로 두면 됩니다.
- **카테고리 7건**(`/category/living-kitchen/...`)과 `/guides/`, `/privacy-policy/` — 얇은 목록·정책
  페이지라 색인 안 되는 게 이상하지 않습니다. 굳이 요청할 필요 없다고 봅니다.

## 오경보였던 것 (기록용)

`pickdam.com/jeseupgi-20l-uri-jip-pyeongsue-matneun-yongryang-seontaek/` 가 제습기 글로 또 하나
보여서 근접중복을 의심했으나, 실측 결과 **301 → `/dehumidifier-20l-electricity-bill-30pyeong/`**
였습니다. 픽토가 슬러그를 영문으로 바꾸며 남긴 정상 리다이렉트입니다. 공개 글 34편 중 제습기는 #222 하나뿐입니다.
