# 빌드 가이드 — Windows 설치 파일(.exe) 만들기

비전문 사용자도 더블클릭 설치 후 바로 쓰도록, **필요한 것들을 앱이 알아서 설치**하게
패키징합니다. 무거운 CUDA 런타임은 설치 파일에 내장하지 않고 첫 실행 시 (NVIDIA 공식
휠로) 받으며, Python·라이브러리는 사용자 시스템과 **격리된 공간에만** 설치됩니다.

## 빌드 환경
- Windows 10/11
- Node.js LTS (https://nodejs.org)
- 인터넷 연결

## 단계

```bat
:: 1) 프로젝트 의존성
npm install

:: 2) 런타임(독립 Python + ffmpeg) 수집  ← 최초 1회
npm run fetch-runtime

:: 3) 설치 파일 빌드
npm run dist
```

빌드가 끝나면 `dist\SubtitleGenerator-Setup-1.0.0.exe` 가 생깁니다. 이 파일을 배포하면 됩니다.

> 커스텀 아이콘을 쓰려면 `build\icon.ico` 를 두고 `package.json`의 `build.win`에
> `"icon": "build/icon.ico"` 를 추가하세요(선택).

## 사용자 입장에서의 동작
1. `SubtitleGenerator-Setup.exe` 실행 → 일반 설치.
2. **첫 실행 시** 앱이 격리 환경(`%APPDATA%\SubtitleGenerator\runtime\venv`)을 만들고
   필요한 라이브러리를 자동 설치합니다(인터넷 필요, 최초 1회 수 분). 진행 상황이
   화면에 표시됩니다.
3. NVIDIA GPU가 감지되면 GPU 가속 런타임(cuDNN/cuBLAS)도 **NVIDIA 공식 PyPI 휠**로
   자동 설치합니다. 사용자가 CUDA를 시스템에 따로 설치할 필요가 없습니다.
4. 이후 실행부터는 설치 과정 없이 바로 시작됩니다.

## 설계 원칙(요약)
- **자동 의존성 설치**: 첫 실행 부트스트랩(`src/main/bootstrap.js`)이 venv 생성 +
  `python/requirements-app.txt` 설치를 자동 수행.
- **시스템 비침범(격리)**: 모든 Python/라이브러리는 `%APPDATA%`의 전용 venv에만 설치 →
  사용자 PC의 기존 Python/환경과 서로 영향 없음.
- **CUDA 비내장**: 설치 파일에는 GPU 런타임을 넣지 않고, GPU가 있을 때만 공식 휠을
  내려받음. GPU 런타임이 없거나 실패하면 자동으로 CPU로 동작.
- **ffmpeg 동봉**: 작은 실행 파일이라 동봉(시스템 설치 불필요).

## 동봉/생성 구조
```
설치앱 resources/
├─ python/   (동봉 standalone Python — venv 부트스트랩용)
├─ ffmpeg/   (동봉 ffmpeg.exe, ffprobe.exe)
└─ engine/   (engine.py 등 Python 소스 + requirements-app.txt)

%APPDATA%\SubtitleGenerator\runtime\
└─ venv/     (첫 실행 시 생성 — faster-whisper, transformers, torch 등 설치)
```

## 참고 / 문제 해결
- 첫 실행 설치가 실패하면(네트워크 등) 화면의 **다시 시도** 버튼으로 재시도.
- 사내망/프록시 환경은 pip가 PyPI에 접근 가능해야 합니다.
- `npm run fetch-runtime`의 Python 버전을 올리려면 스크립트 상단 URL을
  python-build-standalone 최신 릴리스로 교체하세요.
