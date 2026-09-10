# Markto (마크토)

**발행된 글을 핀터레스트에 자동으로 뿌려 픽담 유입을 만드는 도구.**
글을 쓰지 않는다(스크립토·픽토의 일). 상품을 팔지 않는다(캐스토의 일).

- 기획: `_Master_Context/markto_기획_브리프.md`
- 진행 기록·인수인계: `_Master_Context/markto_context.md`
- 성공 지표: **핀 클릭 수 / 사이트 세션 유입** (팔로워 수가 아니다)

## 파이프라인

```
① 수집   collect.py    pickdam.com/wp-json/wp/v2/posts → 아직 핀 없는 글만 → data/queue.json
② 문구   make_pin.py   LLM: 이미지 문구(22자)·핀 제목(40자)·설명(200자)·해시태그
③ 이미지 pin_image.py  PIL 1000×1500(2:3) 픽담 그린 타이포 카드
④ 게시   make_pin.py   텔레그램 전송(수동 게시) → API 승인 후 publish.py 자동 게시
⑤ 기록   data/pins.json
⑥ 통보   indexnow.py   발행 글을 네이버·빙에 즉시 알림 (구글은 IndexNow를 받지 않는다)
```

## 실행

```bash
pip install -r requirements.txt

python collect.py              # 큐 만들기
python make_pin.py --dry       # LLM·전송 없이 이미지만 (디자인 확인)
python make_pin.py 1           # 1건 만들어 텔레그램으로 전송
python -m unittest discover -s tests
```

자동 실행은 `.github/workflows/daily-pin.yml` — 매일 **10:20 KST**.

## 설정 (`markto.json`)

| 키 | 뜻 |
|---|---|
| `sites[].enabled` | 대상 사이트. **1단계는 픽담만 true.** 원더랜드는 계정·소유권 확인 후 true로 바꾸면 코드 수정 없이 합류 |
| `sites[].brand` | 핀 팔레트. 픽담 그린 `#12503A`·`#2E9E6B`·`#F7F5EF` — 블로그 리디자인·로고와 **같은 값이어야** 핀→사이트 이동에 이질감이 없다 |
| `quota.per_day` | 하루 상한(기본 3). 코드가 강제한다 |
| `indexnow.enabled` | 색인 통보 on/off |
| `sites[].indexnow_key` | IndexNow 키. **비밀이 아니다** — 규격상 `https://<사이트>/<키>.txt` 에 공개로 올려야 소유 증명이 된다. 키 파일이 없으면 `indexnow.py`가 통보를 건너뛴다 |
| `quota.min_hours_between_same_post` | 같은 글 재게시 최소 간격(기본 720시간=30일) |
| `publish.mode` | `telegram`(현재) / `pinterest`(API 승인 후) |
| `publish.access_tier` | `trial`(현재) / `standard`. **trial 핀은 Sandbox라 만든 사람만 보인다** — 그래서 standard가 아니면 코드가 게시를 거부한다 |

## 시크릿 (GitHub Actions)

| 이름 | 지금 필요? | 비고 |
|---|---|---|
| `LLM_API_KEY` | 예 | Gemini. 캐스토와 같은 값 (`공유_경계.md`) |
| `LLM_MODEL` | 선택 | 기본 `gemini-2.5-flash` |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | 예 | 수동 게시용 전송 |
| `PINTEREST_APP_ID` / `PINTEREST_APP_SECRET` | 승인 후 | 앱 자격증명 |
| `PINTEREST_REFRESH_TOKEN` | 승인 후 | `python oauth_setup.py` 가 발급한다. **액세스 토큰은 30일이면 죽어서** 시크릿에 박지 않고 매 실행마다 새로 받는다 |
| `PINTEREST_BOARD_ID_PICKDAM` | 승인 후 | 없으면 보드 이름으로 조회 |

키가 하나도 없어도 파이프라인은 죽지 않는다 — 폴백 문구로 이미지를 만들고 전송만 건너뛴다.

## 알아둘 함정 (실측)

- **러너에 컬러 이모지 폰트가 없다.** 이미지 안 이모지는 두부(⃞)로 렌더된다.
  LLM이 규칙을 어겨도 `strip_emoji()`가 마지막에 걷어낸다.
- **NotoSansCJK ttc의 한국어 페이스 인덱스는 패키지 버전마다 다르다**(이 환경 KR=1,
  Picto 브랜드 스크립트가 쓰던 값은 2). 인덱스를 상수로 박으면 어느 날 일본어 폰트로
  조용히 바뀐다 — `kr_index()`가 이름으로 찾는다.
- **Gemini 2.5 Flash는 사고 토큰이 maxOutputTokens에 포함**되어 긴 JSON이 잘린다.
  `thinkingBudget=0` + MAX_TOKENS 재시도.
- **GitHub Actions에서 `git add`에 없는 경로를 나열하면 pathspec 에러**가 나고 `|| true`가
  그걸 삼켜 커밋이 조용히 건너뛰어진다. `git add -A data`로 붙인다.
- **Pinterest trial 등급의 핀은 Sandbox — 만든 사람에게만 보인다**(공식 문서, 2026-09-09).
  trial로 자동 게시를 켜면 아무도 못 보는 핀을 만들면서 큐를 태운다(핀 완료로 기록돼 30일간 재시도 없음).
  `publish.access_tier`가 `standard`가 아니면 `publish.py`가 게시를 거부한다.
  계정·API 준비 절차는 `docs/핀터레스트_계정_준비.md`.

## 하지 말아야 할 것

- 같은 글을 하루에 여러 번·여러 계정에 반복 게시 (핀터레스트 스팸 판정 1순위)
- 남의 이미지를 가져다 핀으로 만들기
- 콕픽 계정(@kokpick_kr)·Casto 레포 수정 — 캐스토 전담 영역이다
