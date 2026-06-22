# 배포 가이드 — GitHub 공개 + 자동 업데이트

무료 배포: 소스는 GitHub 저장소에, 설치 파일(.exe)은 **GitHub Releases**에 올립니다.
자동 업데이트는 electron-updater가 Releases의 `latest.yml` 을 읽어 동작합니다.

## 0. 저장소 이름
`package.json`의 publish 설정이 **owner: `CreamMeatball`, repo: `subtitle-generator`** 로
되어 있습니다. GitHub 저장소를 **이 이름으로** 만들거나, 다른 이름이면 package.json의
`build.publish.repo` 값을 그 이름으로 바꿔주세요.

## 1. 저장소 만들고 소스 올리기
```bat
cd C:\SubtitleGenerator\subtitle-generator
git init
git add .
git commit -m "Initial release v1.0.0"
git branch -M main
git remote add origin https://github.com/CreamMeatball/subtitle-generator.git
git push -u origin main
```
(`.gitignore` 가 node_modules/dist/runtime 등 무거운 산출물을 제외합니다. 소스·아이콘만 올라갑니다.)

## 2. 설치 파일 빌드 + 릴리스에 올리기 (자동 업데이트 핵심)
자동 업데이트가 되려면 릴리스에 **3개 파일**이 함께 있어야 합니다:
`SubtitleGenerator-Setup-1.0.0.exe`, `...exe.blockmap`, `latest.yml`.

### 방법 A — 자동 게시(권장)
1. GitHub Personal Access Token 발급(스코프: `repo`).
2. 토큰을 환경변수로 두고 게시 빌드:
   ```bat
   set GH_TOKEN=ghp_여기에토큰
   npm run dist -- --publish always
   ```
   → 빌드 후 GitHub에 **Draft Release**로 3개 파일이 자동 업로드됩니다.
3. GitHub의 Releases에서 그 draft를 **Publish** 하면 끝.

### 방법 B — 수동 업로드
1. `npm run dist` (관리자 cmd 권장)
2. GitHub → Releases → **Draft a new release** → 태그 `v1.0.0` 생성.
3. `dist\` 의 **세 파일**(exe, exe.blockmap, latest.yml)을 에셋으로 업로드 → Publish.

## 3. 새 버전 낼 때
1. `package.json`의 `version` 을 올림(예: 1.0.1).
2. (코드 수정) → 방법 A 또는 B로 다시 빌드·게시.
3. 사용자 앱이 시작 시 새 버전을 감지 → 설정의 ‘자동/수동’에 따라 다운로드 후
   "지금 재시작"으로 적용됩니다. (격리 런타임은 유지되어 라이브러리 재설치 없음)

## 참고
- 앱이 **서명되지 않아** 설치/업데이트 시 SmartScreen 경고가 날 수 있습니다(무료 배포에선 일반적).
  추후 코드서명 인증서를 넣으면 경고가 사라집니다.
- 사용자별 무거운 ML 라이브러리는 첫 실행 때 PyPI에서 받으므로, 릴리스에는 작은 설치 파일만 올리면 됩니다.
- README에 다운로드 링크(Releases)·스크린샷·사용법을 적어두면 좋습니다.
