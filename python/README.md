# M1 코어 파이프라인 (프로토타입)

영상 → **오디오 추출(ffmpeg) → faster-whisper 전사 → SRT/SMI 저장**까지의 핵심 파이프라인.
이후 마일스톤(큐, Electron UI, 번역)의 토대가 되는 백엔드 코어다.

## 구성

| 파일 | 역할 |
|---|---|
| `device.py` | GPU/CPU 자동 감지 (CUDA 있으면 float16, 없으면 int8 폴백) |
| `transcribe.py` | ffmpeg 오디오 추출 + faster-whisper 전사, 진행률 콜백 |
| `subtitle.py` | 타임스탬프 포매팅, SRT/SMI 생성, 줄바꿈 후처리 |
| `cli.py` | 위 모듈을 묶은 명령줄 진입점 |
| `test_subtitle.py` | 자막 포맷 단위 테스트 (무의존성) |

## 사전 준비 (Windows)

1. **Python 3.10+** 설치
2. **ffmpeg** 설치 후 PATH 등록 (또는 환경변수 `FFMPEG_PATH`로 ffmpeg.exe 지정)
3. 의존성 설치:
   ```
   pip install -r requirements.txt
   ```
   - **GPU 사용 시**: NVIDIA 드라이버 + CUDA 12 / cuDNN 9 런타임 필요. 없으면 자동으로 CPU로 폴백됩니다.
   - **CPU만**: 추가 런타임 없이 바로 동작.

## 실행

```bash
# 가장 단순 (auto 언어 감지, small 모델, SRT, 영상과 같은 폴더에 저장)
python cli.py "C:\videos\match1.mp4"

# 모델/언어/포맷 지정
python cli.py match1.mp4 --model medium --language ko --format srt

# CPU 강제 + 콘텐츠 튜닝 프롬프트(LoL 대회 예시)
python cli.py match1.mkv --device cpu --initial-prompt "페이커, 제우스, 바론, 한타, 갱킹, 미드, 정글"

# 영어로 번역(Whisper translate, 영어 출력만 지원)
python cli.py clip.mp4 --task translate
```

### 주요 옵션
- `--model` : tiny / base / small / medium / large-v3 / large-v3-turbo (기본 small). 로컬에 없으면 자동 다운로드.
- `--device` : auto(기본) / cuda / cpu
- `--language` : 원본 언어 코드 또는 auto(기본)
- `--task` : transcribe(원어 전사) / translate(영어 번역)
- `--format` : srt(기본) / smi
- `--initial-prompt` : 도메인 용어 주입(콘텐츠 튜닝)
- `--max-line-chars` : 한 줄 최대 글자수
- `--no-vad` : 무음 구간 감지(VAD) 끄기

## 테스트

```bash
python test_subtitle.py      # 자막 포맷 로직 (5/5 통과 확인됨)
```

## 검증 현황 (이 프로토타입)

샌드박스(Linux, GPU 없음, PyPI 차단)에서 모델 추론을 제외한 전 구간을 검증 완료:
- ✅ ffmpeg 오디오 추출 → 16kHz mono PCM WAV 정상 생성
- ✅ device 자동 감지 및 CPU 폴백 로직
- ✅ 진행률 콜백 / 언어감지 / 세그먼트 수집 통합 흐름
- ✅ SRT · SMI 파일 출력 (모킹된 세그먼트로 end-to-end)
- ✅ 자막 포맷 단위 테스트 5/5

남은 검증(사용자 Windows 환경에서 수행 권장):
- ⏳ 실제 faster-whisper 모델 다운로드 + 추론 (GPU/CPU 실제 성능·정확도)

## M2 — 작업 큐 (완료)

여러 파일을 순차/병렬로 처리하는 백엔드 큐. Electron UI(M3)가 그대로 구동할 엔진.

추가 파일:

| 파일 | 역할 |
|---|---|
| `jobs.py` | Job / JobOptions / JobStatus 데이터 모델 |
| `scanner.py` | 디렉토리 스캔(지원 확장자 필터), ffprobe 길이(옵션) |
| `jobqueue.py` | 워커 풀 기반 큐: 동시성·취소·재시도·이벤트, 워커별 모델 1회 로드 재사용 |
| `batch.py` | 명령줄 배치 실행(터미널에서 바로 사용) |
| `engine.py` | JSON-lines stdin/stdout 사이드카 (Electron 연동용) |

### 배치 실행 (터미널)

```bash
# 폴더 내 영상 전부, 순차
python batch.py "C:\videos"

# 2개 병렬, medium 모델
python batch.py "C:\videos" --concurrency 2 --model medium

# 파일 여러 개 직접 지정 + 일본어 고정
python batch.py a.mp4 b.mkv --language ja --format srt
```

병렬(`--concurrency N`)은 워커마다 모델을 따로 로드합니다. GPU VRAM을 고려해
large 계열은 1~2를 권장합니다.

### 사이드카 프로토콜 (engine.py) — M3 연동용

stdin으로 명령(JSON 한 줄), stdout으로 이벤트(JSON 한 줄):

```
→ {"cmd":"scan","dir":"C:/videos"}
← {"type":"scan_result","items":[{"path":..,"name":..,"size":..}]}
→ {"cmd":"set_concurrency","value":2}
→ {"cmd":"add","paths":["C:/videos/a.mp4"],"options":{"model":"medium","fmt":"srt"}}
→ {"cmd":"start"}
← {"type":"progress","job_id":1,"ratio":0.42,"message":"..."}
← {"type":"job_state","id":1,"status":"done","output":"...a.srt"}
→ {"cmd":"cancel","job_id":1}   /   {"cmd":"retry","job_id":1}
→ {"cmd":"shutdown"}            ← {"type":"bye"}
```

### M2 검증 현황 (모킹 엔진으로 로직 검증 완료)
- ✅ 순차(1.56s) 대비 병렬 concurrency=3(0.55s) — 동시성 정상
- ✅ 실행 중 작업 협조적 취소 → cancelled
- ✅ 취소/실패 작업 재시도 → done
- ✅ 이벤트 스트림(job_added/progress/job_state/log) 정상
- ✅ scanner: 영상 확장자만 필터(txt 제외)
- ✅ engine.py JSON stdio: ready→scan→add→병렬 done→bye, SRT 생성 확인

## 다음 단계 (M3)
Electron UI — 폴더 열기/리스트업, 드래그 다중 선택, 큐 시각화(진행률 바),
설정 화면. main 프로세스가 `engine.py`를 자식 프로세스로 띄워 위 프로토콜로 통신.
