"""오디오 추출(ffmpeg) + faster-whisper 전사.

- 다양한 영상 컨테이너 호환을 위해 ffmpeg로 16kHz mono WAV를 먼저 추출한다.
- 진행률은 콜백(on_progress)으로 전달한다. ratio<0 은 단계/로그 라인을 의미한다.
- M2: 모델 로드와 전사를 분리(load_model / run_transcription)하여 워커가
  모델을 한 번만 로드해 여러 작업에 재사용할 수 있게 한다. 취소(should_cancel)도 지원.
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
import tempfile
import threading
import time

# Windows에서 무해한 HF 캐시 symlink 경고 숨김 (다운로드 동작에는 영향 없음)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# hf-xet 프로토콜이 일부 네트워크에서 무한 대기에 걸리는 문제 회피 (일반 HTTPS 사용)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
from dataclasses import dataclass, field
from typing import Callable, Optional

from device import detect_device, DeviceConfig, supported_compute_types


VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts",
    ".m4v", ".mpg", ".mpeg", ".m2ts", ".mts", ".vob", ".ogv", ".3gp",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".opus",  # 오디오도 허용
}


class CancelledError(Exception):
    """작업이 사용자 요청으로 취소되었음을 나타낸다."""


@dataclass
class TranscribeOptions:
    model: str = "small"
    device: Optional[str] = None        # None/"auto" | "cuda" | "cpu"
    compute_type: Optional[str] = None
    language: Optional[str] = None       # None => 자동 감지(auto)
    task: str = "transcribe"             # "transcribe" | "translate"(영어)
    initial_prompt: Optional[str] = None  # 콘텐츠 튜닝 프롬프트
    vad_filter: bool = True
    beam_size: int = 5
    word_timestamps: bool = False  # 단어 단위 정렬(시작/끝 정확↑, 속도↓). 기본 off
    # 환각(hallucination) 억제
    condition_on_previous_text: bool = True   # False면 무음/배경음 환각·반복 드리프트 감소
    hallucination_silence_threshold: Optional[float] = None  # word_timestamps와 함께일 때 효과
    model_dir: Optional[str] = None       # 모델 캐시 경로


@dataclass
class TranscribeResult:
    segments: list = field(default_factory=list)
    language: str = ""
    language_probability: float = 0.0
    duration: float = 0.0
    device: DeviceConfig = None


def _ensure_cuda_dll_path() -> None:
    """Windows: pip로 설치된 NVIDIA cuBLAS/cuDNN 휠의 bin 폴더를 DLL 검색 경로에 추가.

    CTranslate2(파이썬 휠)는 cublas64_12.dll·cudnn*.dll 을 런타임에 동적 로드하지만,
    pip 휠이 깐 DLL 폴더(site-packages/nvidia/*/bin)는 기본 DLL 검색 경로에 없다.
    이를 추가하지 않으면 다음 오류가 난다:
      - "Library cublas64_12.dll is not found or cannot be loaded"
      - "[WinError 1114] DLL 초기화 루틴을 실행할 수 없습니다"
    이 함수 덕분에 CUDA Toolkit/cuDNN을 시스템에 따로 설치하지 않아도 GPU가 동작한다.
    """
    if os.name != "nt":
        return
    import glob
    seen = set()
    for base in list(sys.path):
        if not base or not os.path.isdir(base):
            continue
        nv = os.path.join(base, "nvidia")
        if not os.path.isdir(nv):
            continue
        for bindir in glob.glob(os.path.join(nv, "*", "bin")):
            if not os.path.isdir(bindir):
                continue
            real = os.path.normcase(os.path.abspath(bindir))
            if real in seen:
                continue
            seen.add(real)
            try:
                os.add_dll_directory(bindir)   # Python 3.8+ Windows DLL 검색 경로
            except Exception:
                pass
            # 일부 환경(자식 프로세스/구버전 로더) 대비 PATH에도 선행 추가
            os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")


def find_ffmpeg() -> str:
    """동봉된 ffmpeg 우선, 없으면 PATH의 ffmpeg 사용."""
    env = os.environ.get("FFMPEG_PATH")
    if env and os.path.exists(env):
        return env
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError(
            "ffmpeg를 찾을 수 없습니다. 동봉 ffmpeg 또는 PATH 설정이 필요합니다.")
    return found


def extract_audio(video_path: str, ffmpeg: Optional[str] = None) -> str:
    """영상에서 16kHz mono WAV 추출. 임시 파일 경로 반환(호출자가 삭제)."""
    ffmpeg = ffmpeg or find_ffmpeg()
    fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="subgen_")
    os.close(fd)
    # -nostdin + stdin=DEVNULL: ffmpeg가 부모(engine.py)의 stdin 파이프를
    # 물려받아 읽으며 멈추는 문제 방지 (GUI에서 '오디오 추출 중' 무한 멈춤의 원인)
    cmd = [
        ffmpeg, "-nostdin", "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000",
        "-acodec", "pcm_s16le", wav_path,
    ]
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        try:
            os.remove(wav_path)
        except OSError:
            pass
        raise RuntimeError(
            f"오디오 추출 실패: {proc.stderr.decode('utf-8', 'ignore')[-500:]}")
    return wav_path


class _Heartbeat:
    """블로킹 구간(모델 다운로드/로드 등) 동안 경과 시간을 주기적으로 알린다.

    on_progress 콜백을 ratio=-1.0(=로그 라인)으로 호출한다.
    """

    def __init__(self, msg, on_progress, interval=3.0):
        self.msg = msg
        self.cb = on_progress
        self.interval = interval
        self._stop = threading.Event()
        self._t = None
        self._start = 0.0

    def __enter__(self):
        self._start = time.time()
        if self.cb:
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()
        return self

    def _run(self):
        while not self._stop.wait(self.interval):
            elapsed = int(time.time() - self._start)
            self.cb(-1.0, f"{self.msg} ({elapsed}s 경과)")

    def __exit__(self, *exc):
        self._stop.set()
        if self._t:
            self._t.join(timeout=0.2)


def is_model_cached(model: str, model_dir: Optional[str] = None) -> bool:
    """faster-whisper 모델이 로컬 캐시에 이미 있는지 추정."""
    # 사용자 지정 경로 또는 디렉토리 형태로 직접 준 경우
    if os.path.isdir(model):
        return True
    try:
        from huggingface_hub import try_to_load_from_cache
        repo = model if "/" in model else f"Systran/faster-whisper-{model}"
        hit = try_to_load_from_cache(repo, "model.bin", cache_dir=model_dir)
        return isinstance(hit, str) and os.path.exists(hit)
    except Exception:
        return False


def _is_custom_repo(model: str) -> bool:
    """HuggingFace repo id(예: 'ghost613/whisper-...')인지. 로컬 폴더/사이즈명은 제외."""
    return isinstance(model, str) and "/" in model and not os.path.isdir(model)


def _ct2_cache_root(model_dir: Optional[str]) -> str:
    if model_dir:
        return os.path.join(model_dir, "ct2-custom")
    return os.path.join(os.path.expanduser("~"), ".cache", "subgen", "ct2-custom")


def _fetch_tokenizer_files(repo: str, out_dir: str):
    """변환된 CT2 폴더에 faster-whisper가 필요로 하는 토크나이저/전처리 파일 보강."""
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return
    for fn in ("tokenizer.json", "preprocessor_config.json", "vocabulary.json",
               "vocab.json", "tokenizer_config.json", "special_tokens_map.json"):
        try:
            p = hf_hub_download(repo, fn)
            shutil.copy(p, os.path.join(out_dir, fn))
        except Exception:
            pass


def _ensure_ct2(repo: str, cfg: DeviceConfig, model_dir: Optional[str] = None,
                on_progress: Optional[Callable[[float, str], None]] = None) -> str:
    """표준 HF Whisper 체크포인트를 CT2 형식으로 변환(최초 1회)하고 경로 반환."""
    root = _ct2_cache_root(model_dir)
    out_dir = os.path.join(root, repo.replace("/", "__"))
    if os.path.isdir(out_dir) and os.path.exists(os.path.join(out_dir, "model.bin")):
        return out_dir
    try:
        from ctranslate2.converters import TransformersConverter
    except Exception as e:
        raise RuntimeError(f"CT2 변환기를 불러올 수 없습니다: {e}")
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
    except Exception:
        raise RuntimeError(
            "커스텀 HuggingFace 모델 변환에는 transformers·torch 설치가 필요합니다. "
            "python 폴더에서: pip install -r requirements-translate.txt")

    quant = "float16" if cfg.device == "cuda" else "int8"
    os.makedirs(root, exist_ok=True)
    if on_progress:
        on_progress(-1.0, f"(최초 1회) 커스텀 모델 변환 중 (다운로드+변환, 수 분 소요): {repo}")
    with _Heartbeat("(최초 1회) 커스텀 모델 변환 중", on_progress):
        conv = TransformersConverter(repo, load_as_float16=(quant == "float16"))
        conv.convert(out_dir, quantization=quant, force=True)
    _fetch_tokenizer_files(repo, out_dir)
    return out_dir


def load_model(opts: TranscribeOptions,
               on_progress: Optional[Callable[[float, str], None]] = None):
    """WhisperModel을 로드(필요 시 다운로드)하고 (model, DeviceConfig) 반환.

    워커가 한 번만 호출해 모델 인스턴스를 재사용하도록 분리했다.
    """
    if on_progress:
        on_progress(-1.0, "[1/4] 라이브러리 로드 중...")
    _ensure_cuda_dll_path()   # GPU용 cuBLAS/cuDNN DLL 경로 보강 (로드 실패 방지)
    from faster_whisper import WhisperModel

    if on_progress:
        on_progress(-1.0, "[2/4] 장치(GPU/CPU) 확인 중...")
    cfg = detect_device(opts.device, opts.compute_type)
    if on_progress:
        on_progress(-1.0, f"[3/4] 디바이스: {cfg.describe()}")

    # 커스텀 HF 모델(repo id)은 CT2로 변환한 뒤 그 경로를 사용
    model_arg = opts.model
    if _is_custom_repo(opts.model):
        model_arg = _ensure_ct2(opts.model, cfg, opts.model_dir, on_progress)

    cached = is_model_cached(model_arg, opts.model_dir)
    if on_progress:
        if cached:
            on_progress(-1.0, f"[4/4] 모델 로드 중: {opts.model}")
        else:
            on_progress(-1.0,
                        f"[4/4] (최초 1회) 모델 다운로드 중: {opts.model} "
                        f"(수백 MB~수 GB, 한 번만 받습니다)...")

    hb_msg = ("(최초 1회) 모델 다운로드 중" if not cached else "모델 로드 중")
    with _Heartbeat(hb_msg, on_progress):
        # 캐시/변환된 모델은 local_files_only=True 로 온라인 확인을 건너뛴다.
        model, cfg = _load_with_fallback(
            WhisperModel, model_arg, cfg, opts.model_dir, cached, on_progress)
    return model, cfg


def _compute_type_attempts(device: str, preferred: str) -> list:
    """이 디바이스에서 시도할 compute_type 우선순위 목록(중복 제거)."""
    if device == "cuda":
        order = [preferred, "int8_float16", "int8", "float32"]
    else:
        order = [preferred, "int8", "float32"]
    sup = supported_compute_types(device)
    out = []
    for ct in order:
        if ct in out:
            continue
        if sup and ct not in sup:
            continue  # 지원 안 하는 타입은 건너뜀
        out.append(ct)
    if not out:  # sup 조회 실패 등으로 비면 안전한 기본값
        out = [preferred] if device == "cuda" else ["int8", "float32"]
    return out


def _load_with_fallback(WhisperModel, model_arg, cfg, model_dir, cached, on_progress):
    """compute_type → (필요 시) GPU→CPU 순으로 단계적 폴백하며 모델을 로드한다.

    - GTX 10 시리즈 등에서 float16 미지원 시 int8/float32로 자동 전환.
    - cuDNN/cuBLAS 로드 실패, VRAM 부족(OOM) 등 GPU 로드 자체가 실패하면 CPU로 폴백.
    """
    # (device, [compute_types]) 시도 순서
    plans = [(cfg.device, _compute_type_attempts(cfg.device, cfg.compute_type))]
    if cfg.device == "cuda":
        plans.append(("cpu", _compute_type_attempts("cpu", "int8")))

    last_err = None
    for device, ctypes in plans:
        for ct in ctypes:
            try:
                model = WhisperModel(
                    model_arg, device=device, compute_type=ct,
                    download_root=model_dir, local_files_only=cached,
                )
                used = DeviceConfig(device=device, compute_type=ct,
                                    cuda_count=cfg.cuda_count)
                if on_progress:
                    if device != cfg.device:
                        on_progress(-1.0,
                                    f"[!] GPU 로드 실패 → CPU로 전환합니다 ({ct}).")
                    elif ct != cfg.compute_type:
                        on_progress(-1.0,
                                    f"[!] {cfg.compute_type} 미지원 GPU → {ct}(으)로 전환합니다.")
                return model, used
            except Exception as e:  # noqa: BLE001
                last_err = e
                msg = str(e)
                if on_progress:
                    on_progress(-1.0, f"[재시도] {device}/{ct} 로드 실패: {msg[:120]}")
                continue
    # 모든 시도 실패
    raise RuntimeError(
        "모델 로드에 실패했습니다. GPU 드라이버/메모리 문제이거나 설치가 손상되었을 수 "
        "있습니다. 설정 > '의존성 재설치'를 시도하거나 더 작은 모델을 선택해 주세요.\n"
        f"마지막 오류: {last_err}")


def run_transcription(
    model,
    cfg: DeviceConfig,
    video_path: str,
    opts: TranscribeOptions,
    on_progress: Optional[Callable[[float, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> TranscribeResult:
    """이미 로드된 model로 한 영상을 전사한다. should_cancel()이 True면 중단."""
    if on_progress:
        on_progress(-1.0, "오디오 추출 중...")
    wav_path = extract_audio(video_path)

    try:
        language = None if (opts.language in (None, "auto", "")) else opts.language
        if on_progress:
            on_progress(-1.0, "전사 시작 (첫 구간 분석에 시간이 걸릴 수 있음)...")

        # 특징 추출/언어감지/VAD~첫 구간까지의 공백 동안 "음성 분석 중 (Ns)" 하트비트
        hb = _Heartbeat("음성 분석 중", on_progress)
        hb.__enter__()
        analyzing = True
        try:
            seg_iter, info = model.transcribe(
                wav_path,
                language=language,
                task=opts.task,
                initial_prompt=opts.initial_prompt,
                vad_filter=opts.vad_filter,
                beam_size=opts.beam_size,
                word_timestamps=opts.word_timestamps,
                condition_on_previous_text=opts.condition_on_previous_text,
                hallucination_silence_threshold=opts.hallucination_silence_threshold,
            )

            duration = float(getattr(info, "duration", 0.0)) or 0.0
            segments = []
            for seg in seg_iter:
                if analyzing:
                    hb.__exit__()       # 첫 세그먼트 도착 → 하트비트 종료
                    analyzing = False
                if should_cancel and should_cancel():
                    raise CancelledError()
                segments.append(seg)
                if on_progress and duration > 0:
                    ratio = 0.1 + 0.9 * min(seg.end / duration, 1.0)
                    on_progress(ratio, seg.text.strip()[:60])
        finally:
            if analyzing:
                hb.__exit__()

        result = TranscribeResult(
            segments=segments,
            language=getattr(info, "language", "") or "",
            language_probability=float(getattr(info, "language_probability", 0.0) or 0.0),
            duration=duration,
            device=cfg,
        )
        if on_progress:
            on_progress(1.0, "완료")
        return result
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


def transcribe(
    video_path: str,
    opts: TranscribeOptions,
    on_progress: Optional[Callable[[float, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> TranscribeResult:
    """편의 함수: 모델 로드 + 단일 전사 (cli.py 용)."""
    model, cfg = load_model(opts, on_progress)
    return run_transcription(model, cfg, video_path, opts, on_progress, should_cancel)
