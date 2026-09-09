# 핀터레스트 API standard 승인 절차

trial 등급의 핀은 **Sandbox** — 만든 사람에게만 보인다. 자동 게시를 켜려면 standard가 필요하다.
(공식 문서: "all Pins and Boards created with Trial access are only visible to their creator
as Sandbox entities")

심사에서 떨어지는 사유는 사실상 두 개뿐이다.
**① 영상에 OAuth 동의 화면이 없다. ② 앱 정보·개인정보처리방침이 부실하다.**
아래 순서는 그 둘을 정면으로 막도록 짜여 있다.

---

## 1. 앱 등록 (developers.pinterest.com/apps)

**Create app** 후 아래 값을 그대로 넣는다.

| 항목 | 값 |
|---|---|
| Redirect URI | `http://localhost:8085/` — **끝 슬래시까지 글자 그대로.** 핀터레스트 공식 quickstart가 쓰는 값이라 HTTPS 서버가 필요 없다 |
| Privacy policy | `https://pickdam.com/privacy-policy/` |
| Scopes | `boards:read`, `pins:read`, `pins:write` — 그 이상 요청하지 않는다(문서가 최소 스코프를 권한다) |

앱 설명문 (그대로 붙여넣는다):

> Markto is a first-party publishing tool for pickdam.com, a Korean product-research blog
> owned and operated by the applicant. When a new article is published on pickdam.com,
> Markto generates a 1000x1500 Pin image and Korean copy from that article and creates a Pin
> on the applicant's own Pinterest board ("픽담 살까 말까"), linking back to the source article.
>
> All content is original to pickdam.com. Markto does not read, repin, or redistribute other
> users' content, does not post to accounts other than the applicant's own, and does not
> offer any service to third parties. Daily volume is capped in code at 3 Pins per day, and
> the same article is never re-pinned within 30 days.
>
> Endpoints used: GET /v5/boards (locate the target board), POST /v5/pins (create the Pin),
> POST /v5/oauth/token (refresh the access token).

설명문이 모호하면 그것만으로 거절된다. **"내 사이트 글을 내 보드에 올린다"는 사실이 문장에
드러나는 것**이 핵심이다.

## 2. 개인정보처리방침 확인

`https://pickdam.com/privacy-policy/` 가 **로그인 없이 열리는지** 직접 확인한다.
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

My apps → 앱 카드의 **Upgrade** → 정보 확인 → 영상 업로드 → Submit.
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
