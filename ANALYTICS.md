# 익명 사용 통계 (설치/실행 수) 설정 가이드

앱이 **첫 실행 시 1회(install)** 와 **실행마다(launch)** 익명 신호를 보내,
배포처(GitHub·구글 드라이브·USB 등)와 무관하게 실제 설치·사용 수를 셉니다.
**개인정보·영상·자막 내용은 전혀 전송하지 않습니다.** 사용자는 설정에서 끌 수 있습니다.

집계 서버는 무료인 **Cloudflare Worker + KV**로 직접 운영합니다(외부 서비스 의존 없음).

## 1. Cloudflare 가입
https://dash.cloudflare.com 에서 무료 계정 생성.

## 2. KV 네임스페이스 만들기
- 대시보드 → **Storage & Databases → KV → Create namespace**
- 이름 예: `subgen-counter` → 생성.

## 3. Worker 만들기
- **Workers & Pages → Create → Workers → Create Worker** → 이름 예: `subgen-counter` → Deploy.
- 생성된 워커 → **Edit code** → `cloudflare/worker.js` 내용을 붙여넣고 **Deploy**.

## 4. KV 바인딩 연결  ⚠ ('Variables and secrets'가 아니라 'Bindings' 탭)
- 워커 상단 탭에서 **Bindings → Add** 클릭.
  - 종류: **KV namespace** 선택
  - Variable name: **`COUNTER`** (반드시 이 대문자 이름)
  - KV namespace: 2단계에서 만든 것(예: `subgen-counter`) 선택 → **Deploy/Save**.
- 참고: 'Variables and secrets' 패널(Type/Variable name/Value)은 일반 환경변수용이라
  KV 연결에는 사용하지 않습니다.

## 5. 워커 URL을 앱에 넣기
- 워커 주소(예: `https://subgen-counter.<your-subdomain>.workers.dev`)를 복사.
- `src/renderer/app.js` 상단의 `const ANALYTICS_URL = '';` 에 그 주소를 채웁니다:
  ```js
  const ANALYTICS_URL = 'https://subgen-counter.<your-subdomain>.workers.dev';
  ```
- 다시 빌드·배포(`npm run dist -- --publish always`)하면 적용됩니다.
  (비워 두면 앱은 아무 신호도 보내지 않습니다.)

## 6. 숫자 확인
브라우저에서:
```
https://subgen-counter.<your-subdomain>.workers.dev/?view=1
```
→ `{"install": 설치수, "launch": 실행수}` 가 보입니다.

## 참고
- `install` = 기기당 최초 1회(대략 설치 수), `launch` = 앱 실행 횟수(활성 사용 추정).
- KV 무료 한도: 읽기 10만/일, 쓰기 1천/일 수준. 초기 인디 규모엔 충분하며,
  사용량이 커지면 D1(SQL) 등으로 바꾸면 됩니다.
- 동시 접속이 매우 많을 때 카운트가 미세하게 누락될 수 있으나(근사치), 추세 파악엔 무리 없습니다.
