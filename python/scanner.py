"""디렉토리 내 영상/오디오 파일 스캔."""
from __future__ import annotations

import json
import os
import subprocess
from typing import List

from transcribe import VIDEO_EXTS, find_ffmpeg


def _ffprobe_path() -> str | None:
    """ffmpeg 위치에서 ffprobe를 추정."""
    try:
        ff = find_ffmpeg()
    except Exception:
        return None
    d = os.path.dirname(ff)
    for name in ("ffprobe.exe", "ffprobe"):
        cand = os.path.join(d, name)
        if os.path.exists(cand):
            return cand
    # PATH 폴백
    import shutil
    return shutil.which("ffprobe")


def probe_duration(path: str) -> float:
    """영상 길이(초). 실패 시 0.0 (best-effort)."""
    probe = _ffprobe_path()
    if not probe:
        return 0.0
    try:
        out = subprocess.run(
            [probe, "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout or "{}")
        return float(data.get("format", {}).get("duration", 0.0) or 0.0)
    except Exception:
        return 0.0


def list_media(directory: str, recursive: bool = False,
               with_duration: bool = False) -> List[dict]:
    """디렉토리에서 지원 확장자 파일 목록을 반환.

    각 항목: {path, name, size, ext, duration(옵션)}
    """
    results: List[dict] = []
    if not os.path.isdir(directory):
        return results

    def handle(fp: str):
        ext = os.path.splitext(fp)[1].lower()
        if ext not in VIDEO_EXTS:
            return
        try:
            size = os.path.getsize(fp)
        except OSError:
            size = 0
        item = {"path": fp, "name": os.path.basename(fp),
                "size": size, "ext": ext}
        if with_duration:
            item["duration"] = probe_duration(fp)
        results.append(item)

    if recursive:
        for root, _dirs, files in os.walk(directory):
            for f in files:
                handle(os.path.join(root, f))
    else:
        for f in os.listdir(directory):
            handle(os.path.join(directory, f))

    results.sort(key=lambda x: x["name"].lower())
    return results
