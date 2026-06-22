"""GPU/CPU 자동 감지 모듈.

faster-whisper는 CTranslate2 위에서 동작하므로, CTranslate2의 CUDA 디바이스
카운트를 이용해 GPU 사용 가능 여부를 가볍게 판별한다. (torch 의존성 불필요)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeviceConfig:
    device: str        # "cuda" | "cpu"
    compute_type: str  # "float16" | "int8" | ...
    cuda_count: int

    def describe(self) -> str:
        if self.device == "cuda":
            return f"GPU (CUDA x{self.cuda_count}, {self.compute_type})"
        return f"CPU ({self.compute_type})"


def detect_device(override: str | None = None,
                  compute_type: str | None = None) -> DeviceConfig:
    """사용할 디바이스와 compute_type을 결정한다.

    override: "cuda" | "cpu" | "auto"(또는 None) — 사용자가 강제 지정 가능.
    compute_type: 지정 시 우선 사용. None이면 디바이스에 맞는 기본값.
    """
    cuda_count = _cuda_device_count()

    if override in (None, "auto"):
        device = "cuda" if cuda_count > 0 else "cpu"
    else:
        device = override
        if device == "cuda" and cuda_count == 0:
            # 사용자가 cuda를 강제했지만 사용 불가 → 안전하게 CPU 폴백
            device = "cpu"

    if compute_type is None:
        compute_type = "float16" if device == "cuda" else "int8"

    return DeviceConfig(device=device, compute_type=compute_type, cuda_count=cuda_count)


def _cuda_device_count() -> int:
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


if __name__ == "__main__":
    cfg = detect_device()
    print(cfg.describe())
