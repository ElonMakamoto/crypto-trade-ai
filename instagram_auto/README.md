# instagram_auto

지금 뜨는 뉴스를 [@pubity](https://instagram.com/pubity) 스타일 이미지와 릴스로 만들어 **5시간마다** 인스타그램에 자동 업로드하는 봇입니다.
설명 페이지와 최근 게시물은 **https://chedlab.org/instagram** 에 표시되며, 봇이 실행될 때마다 자동으로 업데이트됩니다.

## 동작 순서

1. **뉴스 수집**: Google News RSS (톱뉴스, 연예, 스포츠, 테크, 과학)를 가져옵니다. 키는 필요 없습니다.
2. **AI 선택과 문구 작성**: `GOOGLE_API_KEY`로 Gemini가 가장 바이럴할 기사를 고르고 대문자 헤드라인, 강조 단어, 캡션, 해시태그, 릴스용 문장을 씁니다.
3. **이미지**: 기사의 대표 사진(og:image)을 쓰고, 없으면 Wikimedia Commons에서 찾습니다. 1080×1350 피드 이미지로 만듭니다.
4. **릴스**: 1080×1920, 8초 줌인 영상에 헤드라인과 스토리 문장을 넣습니다. `assets/music/*.mp3`가 있으면 배경음악으로 씁니다.
5. **업로드**: 한 번 실행할 때 피드 게시물 1개와 릴스 1개를 올립니다 (`POST_MODE`). 올린 기사는 `state/posted.json`에 기록해 중복을 막습니다.
6. **웹사이트 갱신**: `public/instagram/feed.json`과 `media/`를 갱신해 커밋하면 Cloudflare가 자동으로 다시 배포합니다.

## 설정 (GitHub Actions, 5시간마다 자동)

`.github/workflows/instagram-auto.yml`이 `0 */5 * * *` (UTC 0, 5, 10, 15, 20시)에 실행됩니다.
저장소 **Settings → Secrets and variables → Actions**에 다음을 추가하세요.

| 종류 | 이름 | 값 |
|---|---|---|
| Secret | `GOOGLE_API_KEY` | Google AI Studio API 키 |
| Secret | `IG_USERNAME`, `IG_PASSWORD` | 인스타그램 로그인 (instagrapi 방식) |
| Secret | `IG_SESSION_JSON` | (선택) 로컬에서 한 번 로그인 후 생긴 `state/ig_session.json` 내용. 로그인 차단을 줄여 줍니다 |
| Secret | `IG_ACCESS_TOKEN`, `IG_USER_ID` | (Graph API 방식일 때) |
| Variable | `IG_BACKEND` | `instagrapi` (기본) 또는 `graph` |
| Variable | `BRAND_HANDLE` | 이미지에 들어갈 계정 이름, 예: `@chedlab` |
| Variable | `ACCENT_COLOR`, `POST_MODE` | (선택) 강조 색상, `both`/`post`/`reel` |

Actions 탭 → **Instagram Auto** → **Run workflow**로 바로 실행할 수 있습니다 (`dry_run`을 켜면 업로드 없이 이미지와 사이트만 만듭니다).

> 워크플로는 기본 브랜치(`main`)에 있어야 스케줄이 동작합니다.

### 업로드 방식 선택

- **instagrapi (기본)**: 아이디/비밀번호만 있으면 됩니다. 비공식 API라서 인스타그램이 로그인 확인(챌린지)을 요구하거나 계정을 제한할 수 있습니다. 클라우드 서버에서 처음 로그인하면 차단되기 쉬우니, 로컬에서 한 번 로그인한 세션을 `IG_SESSION_JSON`으로 넣는 것을 권장합니다.
- **Graph API (공식, 안정적)**: 비즈니스/크리에이터 계정과 Facebook 페이지 연결, Meta 앱의 장기 액세스 토큰이 필요합니다. 릴스는 파일을 직접 올리고, 피드 이미지는 공개 URL이 필요해서 `https://chedlab.org/instagram/media/`에 먼저 배포한 뒤 그 주소로 올립니다.

## 로컬 실행

```bash
cd instagram_auto
pip install -r requirements.txt   # ffmpeg도 필요합니다
cp .env.example .env              # 키 입력
python main.py --dry-run          # 업로드 없이 output/ 에 이미지/릴스 생성
python main.py                    # 한 번 업로드
python main.py --loop             # 5시간마다 계속 실행
```

## 파일

| 파일 | 역할 |
|---|---|
| `news.py` | Google News 트렌딩 수집, 기사 사진 찾기 |
| `ai.py` | Gemini로 기사 선택과 헤드라인, 캡션 작성 |
| `render.py` | Pubity 스타일 피드 이미지와 릴스 오버레이 |
| `reel.py` | ffmpeg로 릴스 영상 생성 |
| `poster.py` | instagrapi / Graph API 업로드 |
| `main.py` | 전체 실행, 사이트 갱신, 중복 방지 |
| `../public/instagram/` | chedlab.org/instagram 페이지 |

## 주의

- 뉴스 사진과 기사의 저작권은 각 언론사에 있습니다. 출처를 캡션에 자동으로 넣지만, 상업적으로 운영한다면 라이선스를 확인하세요.
- 폰트: Anton, Montserrat (SIL Open Font License, `fonts/OFL.txt`).
