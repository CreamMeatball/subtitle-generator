"""GPU VRAM 가드 — 병렬 실행 시 메모리 초과를 막기 위한 추정 유틸.

nvidia-smi로 여유 VRAM을 읽고, 모델별 대략 사용량으로 안전한 동시 실행 수를
계산한다. nvidia-smi가 없거나 CPU면 제한하지 않는다.
"""
from __future__ import annotations

import shutil
import subprocess

# 모델별 대략 VRAM 사용량(GB, float16 1 인스턴스 기준, 여유분 포함 보수적 추정)
_MODEL_VRAM_GB = {
    "tiny": 1.0, "base": 1.0, "small": 2.0, "medium": 5.0,
    "large-v3-turbo": 6.0, "large-v3": 6.0, "large": 6.0, "turbo": 6.0,
}
_DEFAULT_VRAM_GB = 6.0  # 커스텀/대형 모델 가정


def model_vram_gb(model: str) -> float:
    key = str(model or "").lower()
    for k, v in _MODEL_VRAM_GB.items():
        if k in key:
            return v
    if "small" in key:
        return 2.0
    if "medium" in key:
        return 5.0
    if "large" in key or "turbo" in key:
        return 6.0
    return _DEFAULT_VRAM_GB


def gpu_free_total_gb():
    """(free_gb, total_gb) 반환. nvidia-smi 없거나 실패 시 None."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=memory.free,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8)
        line = (out.stdout or "").strip().splitlines()[0]
        free_mb, total_mb = [float(x.strip()) for x in line.split(",")][:2]
        return (free_mb / 1024.0, total_mb / 1024.0)
    except Exception:
        return None


def safe_concurrency(model: str, requested: int, device: str):
    """GPU면 VRAM 기준 안전 동시 실행 수를 계산.

    반환: (safe_n, message|None). message가 있으면 제한이 적용된 것.
    """
    requested = max(1, int(requested))
    if device != "cuda":
        return requested, None
    ft = gpu_free_total_gb()
    if not ft:
        return requested, None
    free, _total = ft
    per = model_vram_gb(model)
    safe = max(1, int(free // per))
    if requested > safe:
        msg = (f"GPU 여유 VRAM {free:.1f}GB, 모델 약 {per:.0f}GB/개 → "
               f"동시 실행을 {requested}→{safe}로 제한했습니다(메모리 부족 방지).")
        return safe, msg
    return requested, None
