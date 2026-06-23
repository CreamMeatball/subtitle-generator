"""사이드카 엔진: JSON-lines stdin/stdout 프로토콜.

Electron(M3) main 프로세스가 이 스크립트를 자식 프로세스로 띄우고,
명령은 stdin에 JSON 한 줄씩, 이벤트는 stdout에 JSON 한 줄씩 주고받는다.

--- 명령 (stdin) ---
{"cmd":"scan","dir":"C:/videos","recursive":false,"with_duration":true}
{"cmd":"add","paths":["C:/videos/a.mp4"],"options":{"model":"medium","fmt":"srt"}}
{"cmd":"set_concurrency","value":2}
{"cmd":"start"}
{"cmd":"cancel","job_id":3}
{"cmd":"retry","job_id":3}
{"cmd":"list"}
{"cmd":"shutdown"}

--- 이벤트 (stdout) ---
{"type":"ready"}
{"type":"scan_result","items":[...]}
{"type":"job_added","job":{...}}
{"type":"job_state","id":..,"status":"running|done|failed|cancelled",...}
{"type":"progress","job_id":..,"ratio":0.42,"message":"..."}
{"type":"log","job_id":..,"message":"..."}
{"type":"error","message":"..."}
{"type":"bye"}
"""
from __future__ import annotations

import json
import os
import sys
import threading

# Windows 기본 stdout 인코딩(cp949 등)으로 인한 한글·일본어 깨짐(????) 방지 → UTF-8 강제
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 명령 입력 채널을 stdin(fd0)에서 분리한다.
# fd0을 복제해 명령 읽기용(cmd_in)으로 쓰고, 실제 fd0은 NUL로 교체.
# → 워커가 쓰는 라이브러리(faster-whisper/ffmpeg 등)가 stdin을 읽어도 빈 파이프에서
#   블로킹되지 않음. (GUI에서 '첫 작업만 무한 멈춤'의 근본 원인 차단)
try:
    _cmd_fd = os.dup(0)
    _nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(_nul, 0)
    os.close(_nul)
    cmd_in = os.fdopen(_cmd_fd, "r", encoding="utf-8", errors="replace")
except Exception:
    cmd_in = sys.stdin

def _register_cuda_dlls():
    """격리 venv에 설치된 NVIDIA 휠(cuDNN/cuBLAS)의 DLL 경로를 등록.

    ctranslate2가 GPU 라이브러리를 찾도록 돕는다(Windows). 없으면 자동 CPU 폴백.
    """
    import glob
    add = getattr(os, "add_dll_directory", None)
    if not add:
        return
    for base in list(sys.path):
        try:
            for d in glob.glob(os.path.join(base, "nvidia", "*", "bin")):
                try:
                    add(d)
                except Exception:
                    pass
        except Exception:
            pass


_register_cuda_dlls()

from jobs import JobOptions
from jobqueue import JobQueue
from scanner import list_media

_out_lock = threading.Lock()


def emit(ev: dict):
    with _out_lock:
        sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _make_options(raw: dict | None) -> JobOptions:
    raw = raw or {}
    # 튜닝/번역 프로필은 렌더러가 관리하며, 최종 initial_prompt와 표시명을 직접 보낸다.
    allowed = {
        "model", "device", "compute_type", "language", "task", "initial_prompt",
        "fmt", "vad_filter", "beam_size", "word_timestamps",
        "condition_on_previous_text", "hallucination_silence_threshold",
        "temperature", "no_repeat_ngram_size", "vad_min_silence_ms",
        "overwrite_policy", "mode", "subtitle_backup",
        "max_line_chars", "max_subtitle_dur", "output_dir", "model_dir",
        "translate", "target_lang", "translate_backend", "api_key",
        "glossary", "tprofile_name", "profile_name", "custom_prompt",
    }
    kwargs = {k: v for k, v in raw.items() if k in allowed}
    return JobOptions(**kwargs)


def _guard_vram(q):
    """병렬 실행 전 VRAM을 점검해 동시 실행 수를 안전하게 제한."""
    try:
        from device import detect_device
        from vram import safe_concurrency
        queued = [j["model"] for j in q.list_jobs() if j["status"] == "queued"]
        if not queued:
            return
        cfg = detect_device(None, None)
        safe, message = safe_concurrency(queued[0], q._concurrency, cfg.device)
        if message:
            q.set_concurrency(safe)
            emit({"type": "vram_warning", "message": message, "concurrency": safe})
    except Exception:
        pass


def main() -> int:
    q = JobQueue(concurrency=1, emit=emit)
    try:
        from profiles import list_profiles
        emit({"type": "ready", "profiles": list_profiles()})
    except Exception:
        emit({"type": "ready", "profiles": []})

    for line in cmd_in:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            emit({"type": "error", "message": f"JSON 파싱 실패: {e}"})
            continue

        cmd = msg.get("cmd")
        try:
            if cmd == "scan":
                items = list_media(
                    msg["dir"], recursive=bool(msg.get("recursive", False)),
                    with_duration=bool(msg.get("with_duration", False)))
                emit({"type": "scan_result", "items": items})
            elif cmd == "add":
                opts = _make_options(msg.get("options"))
                for pth in msg.get("paths", []):
                    q.add(pth, opts)
            elif cmd == "set_concurrency":
                q.set_concurrency(int(msg.get("value", 1)))
            elif cmd == "start":
                _guard_vram(q)
                q.start()
            elif cmd == "cancel":
                q.cancel(int(msg["job_id"]))
            elif cmd == "retry":
                q.retry(int(msg["job_id"]))
            elif cmd == "list":
                emit({"type": "job_list", "jobs": q.list_jobs()})
            elif cmd == "shutdown":
                q.shutdown(wait=False)
                emit({"type": "bye"})
                break
            else:
                emit({"type": "error", "message": f"알 수 없는 명령: {cmd}"})
        except Exception as e:
            emit({"type": "error", "message": f"{cmd} 처리 실패: {e}"})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
