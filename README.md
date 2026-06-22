# 자막 생성기 (Subtitle Generator)

Whisper 기반으로 영상 폴더의 자막(.srt/.smi)을 백그라운드에서 일괄·병렬 생성하는 Windows 데스크톱 앱.

```
subtitle-generator/
├─ package.json          # Electron 앱 정의
├─ src/
│  ├─ main/              # Electron 메인 프로세스(Node)
│  │  ├─ main.js         #  - 창 생성 + engine.py 스폰 + JSON stdio 브리지
│  │  └─ preload.js      #  - 렌더러에 안전한 api 노출
│  └─ renderer/          # UI
│     ├─ index.html
│     ├─ styles.css
│     └─ app.js          #  - 폴더 스캔/드래그 선택/큐/설정
└─ python/               # 백엔드 코어 (M1·M2)
   ├─ engine.py          #  - 사이드카(JSON stdin/stdout)
   ├─ jobqueue.py        #  - 큐: 순차/병렬·취소·재시도
   ├─ transcribe.py · subtitle.py · scanner.py · device.py · jobs.py
   ├─ cli.py · batch.py  #  - 터미널 단독 실행
   └─ requirements.txt
```

## 사전 준비 (최초 1회)

1. **Python 의존성** (이미 했다면 생략):
   ```
   cd python
   pip install -r requirements.txt
   ```
2. **Node.js** 설치 확인: 터미널에서 `node -v` 가 버전을 출력하면 OK.
   없으면 https://nodejs.org 에서 LTS 설치.
3. **ffmpeg** 가 PATH에 있어야 합니다 (`ffmpeg -version` 확인). 이미 설치됨.

## 앱 실행

프로젝트 루트(`subtitle-generator`)에서:

```
npm install      # 최초 1회 — Electron 다운로드
npm start        # 앱 실행
```

## 사용법

1. **📁 폴더 열기** → 영상이 있는 폴더 선택. 목록이 뜹니다.
2. 목록에서 **드래그**로 여러 개를 한 번에 선택 (Shift=범위, Ctrl=개별 토글, 상단 "전체" 체크).
3. 하단에서 **모델 / 원본 언어 / 포맷 / 동시 실행 수** 지정.
4. **▶ 선택 항목 자막 생성** 클릭 → 오른쪽 큐에서 진행률·상태 확인.
5. 각 작업은 **취소 / 재시도 / 위치 열기** 가능. 자막은 영상과 같은 폴더에 저장됩니다.
6. **⚙ 설정**: 기본 모델·언어·포맷·동시 실행 수·콘텐츠 튜닝 프롬프트(고유명사 주입) 저장.

## 동작 구조

```
[렌더러 UI] ──IPC──> [Electron main] ──JSON stdin/stdout──> [python/engine.py]
     ▲                                                            │
     └───────────── 이벤트(progress/job_state/...) ◀─────────────┘
```

UI는 명령(JSON)을 main을 통해 engine.py로 보내고, engine은 작업 큐를 돌리며
이벤트를 stdout으로 흘려보냅니다. main이 이를 렌더러로 중계해 화면을 갱신합니다.

## 참고 / 문제 해결

- **python을 못 찾는 경우**: 환경변수 `SUBGEN_PYTHON`에 python.exe 전체 경로를 지정하면 됩니다.
- **모델 최초 다운로드가 느릴 때**: `transcribe.py`에 `HF_HUB_DISABLE_XET=1`을 넣어 두어
  일반 HTTPS로 받습니다. 그래도 막히면 브라우저로 받아 `python/` 사용법(python/README.md) 참고.
- **번역(한국어 등) 자막**: 로컬 NLLB-200 기반. 사용하려면 번역 의존성 설치 필요:
  ```
  cd python
  pip install -r requirements-translate.txt
  ```
  (GPU 가속 torch는 https://pytorch.org 안내대로 CUDA 빌드 설치). 설치돼 있지 않으면
  작업은 정상 완료되되 **원어 자막**으로 저장되고 로그에 안내가 표시됩니다.
  설정에서 번역 백엔드(NLLB 600M/1.3B/온라인 DeepL)를 고를 수 있습니다.
  첫 번역 시 모델(600M ≈ 2.5GB)을 1회 다운로드합니다.
- **번역 용어집(번역 프로필)**: NLLB는 프롬프트를 못 받으므로, 고유명사 표기를
  강제하려면 용어집을 씁니다. 설정 → "번역 프로필(용어집) 편집"에서
  `원문 => 번역`(오른쪽 비우면 원문 유지) 형식으로 입력해 프로필로 저장하고,
  메인 화면의 **번역 프로필** 드롭다운에서 선택해 적용합니다. (placeholder
  보호 방식으로 NLLB·DeepL 양쪽에 적용)
- **메인 화면 컨트롤**: 모델·번역 모델(백엔드)·원본/대상 언어·튜닝 프로필·번역
  프로필을 하단 바에서 바로 바꿀 수 있고, 각 작업 카드에 어떤 프로필·번역
  설정으로 처리되는지 표시됩니다(작업별 독립 적용).
- 터미널만으로 쓰고 싶으면 `python/batch.py` (일괄) 또는 `python/cli.py` (단일) 사용.

## 모델 선택

기본 모델(tiny ~ large-v3-turbo)은 바로 사용 가능합니다. 추가로 한국어/일본어 특화
파인튜닝 모델을 메인 화면 "모델" 드롭다운에서 고를 수 있습니다:

- **한국어 · turbo** — ghost613/whisper-large-v3-turbo-korean
- **한국어 · medium komix v2** — seastar105/whisper-medium-komixv2
- **한국어 · small** — SungBeom/whisper-small-ko
- **일본 애니/겜 · anime-whisper** — litagin/anime-whisper (kotoba-whisper 기반)

이 모델들은 표준 HuggingFace 체크포인트라, **처음 선택 시 1회 CTranslate2로 자동 변환**
(다운로드 + 변환에 수 분 소요, 이후 캐시되어 빠름)됩니다. 변환에는 `transformers`·`torch`가
필요합니다(`pip install -r requirements-translate.txt`). 변환 진행 중에는 상단 바에
"커스텀 모델 변환 중 (N초 경과)"가 표시됩니다. 한국어 모델은 원본 언어를 `ko` 또는
`auto`, anime-whisper는 `ja`로 두면 좋습니다.

## 진행 상황
- ✅ M1 코어 파이프라인 (추출→전사→SRT/SMI)
- ✅ M2 작업 큐 (순차/병렬·취소·재시도·이벤트)
- ✅ M3 Electron UI (폴더/리스트/드래그 선택/큐/설정)
- ✅ M4 번역(NLLB-200) · 튜닝 프로필 (대상 언어·번역 백엔드·프로필 선택)
- ✅ M5 패키징(설치형 .exe) — 첫 실행 자동 의존성 설치(격리 venv) + 조건부 GPU 런타임.
  빌드 방법은 `BUILD.md` 참고.

> 개발 중 실행(`npm start`)은 그대로 동작합니다. 패키지 빌드 시에만 `npm run fetch-runtime`
> 으로 동봉 런타임을 준비한 뒤 `npm run dist` 로 설치 파일을 만듭니다.
