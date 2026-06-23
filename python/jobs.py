"""작업(Job) 데이터 모델."""
from __future__ import annotations

import itertools
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from transcribe import TranscribeOptions


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass
class JobOptions:
    """작업별 옵션. 전역 설정에서 복사해 만든 뒤 개별 조정 가능."""
    model: str = "small"
    device: Optional[str] = None
    compute_type: Optional[str] = None
    language: Optional[str] = None       # None/"auto" => 자동 감지
    task: str = "transcribe"
    initial_prompt: Optional[str] = None
    fmt: str = "srt"                     # "srt" | "smi"
    vad_filter: bool = True
    beam_size: int = 5
    word_timestamps: bool = False
    condition_on_previous_text: bool = True
    hallucination_silence_threshold: Optional[float] = None
    # 고급 옵션
    temperature: Optional[float] = None
    no_repeat_ngram_size: int = 0
    vad_min_silence_ms: Optional[int] = None
    overwrite_policy: str = "overwrite"  # "overwrite" | "skip" | "rename"
    mode: str = "transcribe"             # "transcribe" | "translate_only"
    subtitle_backup: str = "backup"      # 번역전용: "backup"(원본 백업) | "overwrite"
    max_line_chars: Optional[int] = None
    max_subtitle_dur: Optional[float] = 7.0  # 자막 최대 표시 시간(초). 0/None=무제한
    output_dir: Optional[str] = None     # None => 영상과 같은 폴더
    model_dir: Optional[str] = None
    # 번역(M4)
    translate: bool = False              # True면 전사 후 target_lang으로 번역
    target_lang: Optional[str] = None    # "ko" 등 (Whisper 코드)
    translate_backend: str = "nllb"      # "nllb" | "nllb-1.3b" | "online"
    api_key: Optional[str] = None        # 온라인 백엔드용
    glossary: Optional[list] = None      # [{"src","dst"} | {"src","keep":True}]
    # 표시/추적용 (전사·번역 동작에는 영향 없음)
    profile: str = ""                    # (구) 튜닝 프로필 id
    profile_name: str = ""               # 튜닝 프로필 표시 이름
    custom_prompt: str = ""              # 사용자 커스텀 프롬프트(원문)
    tprofile_name: str = ""              # 번역(용어집) 프로필 이름

    def to_transcribe_options(self) -> TranscribeOptions:
        return TranscribeOptions(
            model=self.model, device=self.device, compute_type=self.compute_type,
            language=self.language, task=self.task, initial_prompt=self.initial_prompt,
            vad_filter=self.vad_filter, beam_size=self.beam_size,
            word_timestamps=self.word_timestamps,
            condition_on_previous_text=self.condition_on_previous_text,
            hallucination_silence_threshold=self.hallucination_silence_threshold,
            temperature=self.temperature,
            no_repeat_ngram_size=self.no_repeat_ngram_size,
            vad_min_silence_ms=self.vad_min_silence_ms,
            model_dir=self.model_dir,
        )


_counter = itertools.count(1)


@dataclass
class Job:
    path: str
    options: JobOptions
    id: int = field(default_factory=lambda: next(_counter))
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    message: str = ""
    error: str = ""
    output: str = ""
    duration: float = 0.0
    language: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "status": self.status.value,
            "progress": round(self.progress, 4),
            "message": self.message,
            "error": self.error,
            "output": self.output,
            "duration": self.duration,
            "language": self.language,
            "model": self.options.model,
            "fmt": self.options.fmt,
            # 적용 설정 표시용
            "profile": self.options.profile or "",
            "profile_name": self.options.profile_name or "",
            "custom_prompt": self.options.custom_prompt or "",
            "translate": bool(self.options.translate),
            "target_lang": self.options.target_lang or "",
            "translate_backend": self.options.translate_backend or "",
            "tprofile_name": self.options.tprofile_name or "",
        }
