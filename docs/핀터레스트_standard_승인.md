# 핀터레스트 API standard 승인 절차

trial 등급의 핀은 **Sandbox** — 만든 사람에게만 보인다. 자동 게시를 켜려면 standard가 필요하다.
(공식 문서: "all Pins and Boards created with Trial access are only visible to their creator
as Sandbox entities")

심사에서 떨어지는 사유는 사실상 두 개뿐이다.
**① 영상에 OAuth 동의 화면이 없다. ② 앱 정보·개인정보처리방침이 부실하다.**
아래 순서는 그 둘을 정면으로 막도록 짜여 있다.

---

## 1. 앱 연결 요청 (developers.pinterest.com/apps)

**2026-09-10 화면 실측.** 예전 "Create app"이 아니라 **[앱 연결]** 버튼이고, 이건 그 자리에서
앱이 만들어지는 게 아니라 **핀터레스트가 심사하는 요청**이다("한 번에 하나의 진행 중인 연결
요청과 하나의 업그레이드 요청이 있을 수 있습니다"). 즉 심사가 **두 번** 있다 — 연결 → 업그레이드.

**이 폼에는 리다이렉트 URI·스코프 칸이 없다.** 그건 연결이 승인된 뒤 앱 상세 화면에서 넣는다.
그래서 `oauth_setup.py`는 연결 승인 전에는 돌릴 수 없다(앱 ID·시크릿이 아직 없다).

### 폼에 넣을 값

| 칸 | 값 | 주의 |
|---|---|---|
| 앱 아이콘 | 픽담 로고(선택) | 핀터레스트 로고·워드마크는 금지 |
| **앱 이름** | `Pickdam Markto` | **회사명이 그대로 들어가야 하고** "Pinterest"라는 단어는 금지 |
| **회사명** | `Pickdam` | **`픽담`(2자)은 제출이 거부된다 — "이름의 길이는 3-100자여야 합니다"(2026-09-10 실측).** 핀터레스트가 `픽담`으로 미리 채워두는데 그대로 두면 막힌다. 도메인과 같은 `Pickdam`으로 쓴다 |
| **회사 웹사이트** | `https://pickdam.com` | **`http://`로 미리 채워져 있다 — 반드시 `https`로 고친다.** 사이트 소유권 확인 때와 같은 함정 |
| **개인정보처리방침 링크** | `https://pickdam.com/privacy-policy/` | 2026-09-09 발행 완료 |
| **앱 목적** | 아래 원문 | 모호하면 그것만으로 거절된다 |
| 개발자 목적 | **개인 API 액세스(개인용 단일 사용)** | 마크토는 운영자 본인만 쓴다 |
| **사용 사례** | **핀 만들기 및 일정** (Pinterest에 콘텐츠 게시) | 하나만 고른다 — 광고·전자상거래는 해당 없음 |
| **독자** | **비즈니스** (목표 달성을 위해 Pinterest를 사용하는 기업) | 픽담이 유일한 사용자다 |
| **핀/또는 보드 데이터 읽기** | **예, 제 것입니다.** | 기본값이 "아니요"인데 **그대로 두면 안 된다** — 보드 목록 조회(`GET /v5/boards`)가 막힌다 |

### 앱 목적 (그대로 붙여넣는다)

> Markto is a first-party publishing tool for pickdam.com, a Korean product-research blog
> owned and operated by me. It is used only by me, on my own Pinterest business account.
>
> When a new article is published on pickdam.com, Markto generates a 1000x1500 Pin image and
> Korean copy from that article and creates a Pin on my own board "픽담 살까 말까", linking
> back to the source article.
>
> All content is original to pickdam.com. Markto does not read, repin or redistribute other
> users' content, does not post to any account other than my own, and is not offered as a
> service to third parties. Volume is capped in code at 3 Pins per day, and the same article
> is never re-pinned within 30 days.
>
> Endpoints used: GET /v5/boards (locate the target board), POST /v5/pins (create the Pin),
> POST /v5/oauth/token (refresh the access token).

**"내 사이트 글을 내 보드에 올린다"는 사실이 문장에 드러나는 것**이 핵심이다.

## 1-2. 연결 승인 후 — 리다이렉트 URI 설정

앱 상세 화면에서 리다이렉트 URI에 **`http://localhost:8085/`** 를 넣는다.
**끝 슬래시까지 글자 그대로.** 핀터레스트 공식 quickstart가 쓰는 값이라 HTTPS 서버도
도메인도 필요 없다. 여기서 앱 ID와 시크릿을 받아 2번(영상)으로 간다.

스코프는 `boards:read`, `pins:read`, `pins:write` 셋만 — 그 이상 요청하지 않는다.

## 2. 개인정보처리방침 확인

`https://pickdam.com/privacy-policy/` — **2026-09-09 발행 완료**(로그아웃 상태 200 실측).
문서 요건: "loads completely, is publicly accessible and is hosted on a domain that is
clearly associated with your company or app". 픽담 도메인에 있으므로 연관성 요건은 충족된다.

## 3. OAuth 실행 + 화면 녹화 ← 여기서 갈린다

터미널에서:

```bash
cd Markto
export PINTEREST_APP_ID=<앱 ID>
export PINTEREST_APP_SECRET=<앱 시크릿>
python oauth_setup.py --demo-pin
```

**녹화 순서 (맥: `Cmd+Shift+5`)**

1. 녹화 시작
2. 터미널에서 위 명령 실행 — 브라우저가 열린다
3. **핀터레스트 동의 화면이 화면에 보이는 상태로 2~3초 머문다** ← 이 장면이 없으면 떨어진다.
   요청 스코프 목록이 함께 찍히도록 스크롤하지 않는다
4. **[동의(Allow)]** 클릭 → 브라우저에 "마크토 인증 완료" 페이지
5. 터미널로 돌아가 보드 목록이 출력되는 것을 보여준다 (= 살아있는 API 응답)
6. `[demo] 게시 성공 — pin_id=...` 줄까지 보여준다
7. 출력된 핀 주소(`pinterest.com/pin/...`)를 브라우저에서 열어 **실제 핀을 보여준다**
8. 녹화 종료

**잘라내야 하는 구간**: 터미널 마지막에 리프레시 토큰이 평문으로 찍힌다. 제출 전 그 부분을
편집으로 잘라낸다(앱 시크릿은 `getpass`로 받으므로 애초에 화면에 안 찍힌다).

거절 통보에 실제로 적히는 문구는 `"did not show full Oauth flow"`,
`"did not show Pinterest integration"` 두 개다. 3번이 전자를, 6~7번이 후자를 막는다.

## 4. 제출

**내 앱** → 앱 카드에서 **업그레이드 요청** → 정보 확인 → 영상 업로드 → 제출.
(이 화면은 연결이 승인된 뒤에만 나타나므로 2026-09-10 시점에 실물을 확인하지 못했다 —
메뉴 이름이 다르면 화면을 보고 다시 맞춘다.)
검토는 수시로 돌고 결과는 이메일로 온다.

## 5. 승인 후 전환 (코드 수정 없음)

GitHub Secrets에 `oauth_setup.py` 출력값 3개를 넣는다.

```
PINTEREST_APP_ID
PINTEREST_APP_SECRET
PINTEREST_REFRESH_TOKEN
PINTEREST_BOARD_ID_PICKDAM   (선택 — 없으면 보드 이름으로 조회한다)
```

그리고 `markto.json` 두 글자:

```json
"publish": { "mode": "pinterest", "access_tier": "standard" }
```

**첫 전환은 반드시 1건으로 시험한다** — `publish.py`는 아직 실제 게시로 검증되지 않았다.
`▶ Run workflow` 에 `1`을 넣고 돌려 `pin_id`가 `data/pins.json`에 남는지 확인한다.

## 알아둘 것 — 토큰은 만료된다

| | 수명 | 대응 |
|---|---|---|
| 액세스 토큰 | 30일 | **시크릿에 넣지 않는다.** 매 실행마다 리프레시로 새로 받는다 |
| 리프레시 토큰 | 만료 있음 | 갱신 실패·회전 시 텔레그램으로 알림이 온다 → `oauth_setup.py` 재실행 |

리프레시 토큰을 GitHub Secrets에 자동 반영할 방법은 없다(시크릿 쓰기 권한이 없다).
그래서 `publish.access_token()`이 **회전과 실패를 둘 다 텔레그램으로 알린다** — 알림 없이
지나가면 어느 날 워크플로는 초록인데 핀만 0건이 되는 조용한 고장이 난다.
