# instagram_auto

자연재해 뉴스를 [@pubity](https://instagram.com/pubity) 스타일 이미지와 릴스로 만들어 **English · 한국어 · 日本語** 세 인스타그램 계정에 자동으로 올리는 **Windows 앱**입니다. 세 채널은 같은 뉴스를 각자의 언어로 쓰고, 사진 순서를 조금씩 다르게 해서 각자 정한 시간에 올립니다.

- 다운로드와 설명: **https://chedlab.org/instagram**
- 직접 받기: [InstagramAuto.exe](https://github.com/ElonMakamoto/crypto-trade-ai/releases/download/instagram-auto-latest/InstagramAuto.exe)

## 화면

- 채널 3개(English, 한국어, 日本語)가 나란히 보입니다. 채널마다 **▶ 자동 시작**, **🎬 릴스**, **🖼 게시물**, **👁 미리보기** 버튼, 미리보기, 로그가 따로 있습니다.
- **⚙ 설정**을 누르면 설정 창이 열립니다.
  - **공통**: Google API 키, Meta 액세스 토큰(모든 채널 공통), 뉴스 주제, 강조 색상, 음악 폴더, Windows 시작 시 자동 실행
  - **채널별**: 사용 여부, 인스타 비즈니스 계정 ID, 이미지에 넣을 계정명, 자동 업로드 시간(최대 5개), 올릴 것
- 시간 기준: English는 뉴욕시간, 한국어·日本語는 한국시간. 같은 시간에 겹치면 한 채널씩 차례로 올립니다.

## 사용 방법

1. `InstagramAuto.exe`를 실행합니다. 서명되지 않은 앱이라 "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르세요.
2. **Google API 키** ([AI Studio에서 무료 발급](https://aistudio.google.com/apikey)), **인스타 액세스 토큰** ([받는 법](https://chedlab.org/instagram/#token)), **이미지에 넣을 계정명**을 입력하고 **설정 저장** → **인스타 연결 확인**을 누릅니다.
3. **미리보기만 만들기**로 결과물을 확인합니다. 이때는 업로드하지 않습니다.
4. **자동 업로드 시간**에서 하루 최대 5개 시간(뉴욕시간, 30분 단위)을 고르고 **▶ 자동 업로드 시작**을 누르면 매일 그 시간에 올립니다. 화면에 다음 업로드 시간이 뉴욕시간과 한국시간으로 함께 나옵니다 (서머타임 자동 반영).
5. (선택) **Windows 시작할 때 자동 실행**을 체크하면 PC를 켤 때 앱이 자동으로 켜지고 자동 업로드도 시작됩니다.

PC가 켜져 있는 동안만 동작합니다. 창은 최소화해 두면 되고, 닫으면 멈춥니다.

## 동작 순서

1. **뉴스 수집**: 기본은 **자연재해 뉴스만** 모읍니다. 지진·쓰나미, 허리케인·태풍, 산불, 홍수, 토네이도, 화산, 산사태, 폭염·가뭄·폭설을 Google News에서 최근 2일치로 검색하고, 같은 이름의 스포츠 팀이나 증시 기사 같은 것은 걸러 냅니다. 설정의 `뉴스 주제`에서 전체 인기 뉴스(톱뉴스, 연예, 스포츠, 테크, 과학)로 바꿀 수 있습니다.
2. **AI 문구**: Gemini가 가장 바이럴할 기사를 고르고 대문자 헤드라인, 강조 단어, 릴스 문장을 씁니다. 캡션은 기사 본문을 바탕으로 자세하게(4~6문장: 무슨 일인지, 핵심 사실, 왜 중요한지, 댓글 유도 질문) 쓰고, 팔로우 문구·출처·해시태그 5개(이 기사 3개 + 분야 2개)를 붙입니다. 키가 없으면 기사 본문 문장과 다른 언론사 헤드라인으로 만듭니다.
3. **게시물 (3~6장)**: 기사 본문을 읽고 표지 + 내용 슬라이드 2~4장 + 팔로우 슬라이드를 만듭니다. 슬라이드 내용은 기사 본문에 있는 사실만 씁니다. 사진은 슬라이드마다 다르게 씁니다. **표지는 항상 기사 관련 실제 사진**: 기사 대표 사진 → 헤드라인 속 인물·장소의 Wikipedia 사진 → 같은 소식을 다룬 다른 언론사 기사 사진 → Wikimedia Commons 순으로 찾고, 하나도 없으면 그 기사는 건너뛰고 다음 인기 기사를 씁니다. 안쪽 슬라이드는 주제별 Wikipedia/Wikimedia 사진, 없으면 텍스트 카드.
4. **릴스**: 1080×1920, 8초 영상. 문장마다 다른 사진으로 줌인하고 헤드라인과 스토리 문장을 넣습니다. 음악 폴더를 지정하면 그 안의 mp3를 랜덤으로 씁니다.
5. **업로드**: 자동 업로드는 한 번에 1개씩 올립니다. `자동 업로드 때 올릴 것`에서 하나씩 번갈아(릴스 → 게시물 3~6장 → 릴스 …, 기본), 릴스만, 게시물만 중에 고릅니다. **🎬 릴스 올리기**와 **🖼 게시물 올리기** 버튼으로 원하는 것을 바로 올릴 수도 있습니다. 올린 기사는 기록해 두고 다시 올리지 않습니다.
   - **공식 API (기본, 추천)**: 프로페셔널 계정 + Meta 앱 토큰. 토큰 앞글자로 방식을 자동으로 고릅니다.
     - `IG...` (Instagram 로그인): graph.instagram.com, 토큰은 일주일마다 자동 연장
     - `EAA...` (Unified login / 비즈니스용 Facebook 로그인, 시스템 사용자 토큰 등): graph.facebook.com v23.0, 연장 없음. 인스타 비즈니스 계정 ID는 `/me/accounts`로 자동으로 찾고, 못 찾으면 설정에 직접 넣습니다.
     - 영상은 PC에서 바로 올립니다(resumable). 공식 API는 사진과 `video_url`을 공개 URL로만 받기 때문에, 공개 URL(`PUBLIC_MEDIA_BASE_URL`)이 없으면 게시물 이미지는 6초 정지 화면 릴스로 올라갑니다.
     - Meta 오류는 code와 메시지를 그대로 보여 주고, 권한 오류(code 10, 200번대)는 확인할 것을 안내합니다. 토큰은 로그에 앞 4자리만 나옵니다.
   - **아이디/비밀번호 (비공식, instagrapi)**: 인스타가 이 방식을 막는 경우가 있습니다 ("Your version of Instagram is out of date"). 그럴 때는 공식 API를 쓰세요.

## 저장 위치

| 내용 | 위치 |
|---|---|
| 설정 (비밀번호, API 키는 Windows DPAPI로 암호화) | `%APPDATA%\InstagramAuto\settings.json` |
| 만든 이미지, 영상, 캡션 | `%APPDATA%\InstagramAuto\output\` (앱의 **결과 폴더** 버튼) |
| 인스타 로그인 세션, 올린 기사 기록 | `%APPDATA%\InstagramAuto\state\` |

## 자동 업데이트

`instagram_auto/`가 바뀌어 `main`에 머지되면 `.github/workflows/instagram-auto-windows.yml`이 Windows용 `.exe`를 빌드하고, 셀프 테스트(이미지·영상 생성)를 통과하면 `instagram-auto-latest` 릴리스로 올립니다.

앱은 켤 때와 그 뒤 3시간마다 새 버전을 확인합니다. 새 버전이 있으면:

1. 새 `.exe`를 받습니다.
2. 진행 중인 업로드가 끝날 때까지 기다립니다.
3. 자기 자신을 새 파일로 바꾸고 다시 시작합니다. 자동 업로드가 켜져 있었다면 다시 켜진 상태로 시작합니다.

설정과 토큰은 `%APPDATA%`에 있어서 그대로 유지됩니다. 폴더에 쓰기 권한이 없는 등 자동 교체가 안 되면 **새 버전 받기** 버튼이 나타납니다.

## 개발자용 (Python으로 실행)

```bash
cd instagram_auto
pip install -r requirements.txt
python app.py                     # 데스크톱 앱
python main.py --dry-run          # 명령줄: 업로드 없이 output/ 에 생성
python main.py --loop             # 명령줄: 간격마다 계속 업로드 (.env 사용, .env.example 참고)
```

## 파일

| 파일 | 역할 |
|---|---|
| `app.py` | Windows 데스크톱 앱 (tkinter) |
| `main.py` | 한 번의 실행 흐름 (뉴스, 문구, 이미지, 릴스, 업로드) |
| `news.py` | Google News 트렌딩 수집, 기사 사진 찾기 |
| `ai.py` | Gemini로 기사 선택과 문구 작성 |
| `render.py` | Pubity 스타일 이미지와 릴스 오버레이 |
| `reel.py` | ffmpeg로 릴스 영상과 커버 생성 (ffmpeg는 앱에 포함) |
| `poster.py` | 인스타 업로드 (instagrapi, 또는 공식 Graph API) |
| `config.py`, `secure_store.py` | 설정 저장과 암호화 |

## 주의

- 아이디/비밀번호 방식(instagrapi)은 비공식이라 인스타가 막거나 계정을 제한할 수 있습니다. 공식 API를 권장하고, 간격은 4~6시간을 권장합니다.
- 뉴스 사진과 기사의 저작권은 각 언론사에 있습니다. 출처는 캡션에 자동으로 들어갑니다.
- 폰트: Anton, Montserrat, Black Han Sans, Noto Sans KR, Dela Gothic One, Noto Sans JP (모두 SIL Open Font License, `fonts/OFL.txt`, `fonts/OFL-cjk.txt`).
