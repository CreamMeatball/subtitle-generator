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
        compute_type = _best_compute_type(device)

    return DeviceConfig(device=device, compute_type=compute_type, cuda_count=cuda_count)


def _cuda_device_count() -> int:
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def supported_compute_types(device: str) -> set:
    """해당 디바이스에서 '효율적으로' 지원되는 compute_type 집합.

    CTranslate2는 GPU의 compute capability가 낮으면(예: GTX 10 시리즈 Pascal,
    cc 6.1) float16을 '효율 지원' 목록에서 제외한다. 이 목록을 그대로 쓰면
    'Requested float16 ... do not support efficient float16' 오류를 피할 수 있다.
    """
    try:
        import ctranslate2
        return set(ctranslate2.get_supported_compute_types(device))
    except Exception:
        return set()


def _best_compute_type(device: str) -> str:
    """디바이스가 실제로 지원하는 것 중 가장 빠르고 정확한 compute_type 선택."""
    if device != "cuda":
        # CPU: int8이 지원되면 빠르고 가벼움, 아니면 float32.
        sup = supported_compute_types("cpu")
        return "int8" if (not sup or "int8" in sup) else "float32"

    sup = supported_compute_types("cuda")
    # 선호 순서: float16(최신 GPU) → int8_float16 → int8 → float32
    for ct in ("float16", "int8_float16", "int8", "float32"):
        if not sup or ct in sup:
            # sup 조회가 실패(빈 집합)하면 float16을 우선 시도하되,
            # 로드 단계(transcribe.load_model)에서 폴백이 한 번 더 보호한다.
            if not sup:
                return "float16"
            return ct
    return "float32"


if __name__ == "__main__":
    cfg = detect_device()
    print(cfg.describe())
