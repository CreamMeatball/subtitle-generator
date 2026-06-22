"""작업 큐: 순차/병렬 동시성, 취소, 재시도, 이벤트 스트리밍.

설계
- N개의 워커 스레드가 대기열에서 작업을 꺼내 처리한다(동시성 = N).
- 각 워커는 (model, device, compute_type) 조합별로 WhisperModel을 한 번만
  로드해 재사용한다(스레드 로컬 캐시).
- 취소: 실행 중 작업은 협조적 취소(세그먼트 루프에서 should_cancel 확인),
  대기 중 작업은 즉시 취소 처리.
- 모든 상태 변화는 emit 콜백으로 이벤트(dict)를 내보낸다. Electron(M3)은
  이 이벤트를 그대로 받아 UI를 갱신한다.

주의: 모듈명을 'jobqueue'로 둔 이유는 표준 라이브러리 'queue'와의 충돌을 피하기 위함.
"""
from __future__ import annotations

import os
import queue as pyqueue
import threading
from typing import Callable, Dict, List, Optional

from jobs import Job, JobOptions, JobStatus
from transcribe import (CancelledError, load_model, run_transcription, _Heartbeat)
from subtitle import write_subtitle

EventCb = Callable[[dict], None]


class JobQueue:
    def __init__(self, concurrency: int = 1, emit: Optional[EventCb] = None):
        self._jobs: Dict[int, Job] = {}
        self._order: List[int] = []
        self._pending: "pyqueue.Queue[int]" = pyqueue.Queue()
        self._emit_cb = emit or (lambda e: None)
        self._lock = threading.Lock()
        self._cancelled: set[int] = set()
        self._concurrency = max(1, int(concurrency))
        self._workers: List[threading.Thread] = []
        self._stop = threading.Event()
        self._tls = threading.local()  # 워커별 모델 캐시
        self._started = False

    # ---------- 이벤트 ----------
    def _emit(self, etype: str, **kw):
        try:
            self._emit_cb({"type": etype, **kw})
        except Exception:
            pass

    # ---------- 큐 조작 ----------
    def add(self, path: str, options: JobOptions) -> Job:
        job = Job(path=path, options=options)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
        self._pending.put(job.id)
        self._emit("job_added", job=job.to_dict())
        if self._started:
            self._ensure_workers()
        return job

    def add_many(self, paths: List[str], options: JobOptions) -> List[Job]:
        return [self.add(p, options) for p in paths]

    def set_concurrency(self, n: int):
        self._concurrency = max(1, int(n))
        self._emit("concurrency", value=self._concurrency)
        if self._started:
            self._ensure_workers()

    def start(self):
        self._started = True
        self._ensure_workers()

    def cancel(self, job_id: int):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                snapshot = job.to_dict()
            elif job.status == JobStatus.RUNNING:
                self._cancelled.add(job_id)
                return
            else:
                return
        self._emit("job_state", **snapshot)

    def retry(self, job_id: int):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
                return
            job.status = JobStatus.QUEUED
            job.error = ""
            job.progress = 0.0
            job.message = ""
            self._cancelled.discard(job_id)
            snapshot = job.to_dict()
        self._pending.put(job_id)
        self._emit("job_state", **snapshot)
        if self._started:
            self._ensure_workers()

    def list_jobs(self) -> List[dict]:
        with self._lock:
            return [self._jobs[i].to_dict() for i in self._order]

    def join(self):
        """모든 대기 작업이 처리될 때까지 블록(배치 모드용)."""
        self._pending.join()

    def shutdown(self, wait: bool = True):
        self._stop.set()
        if wait:
            for t in self._workers:
                t.join(timeout=2.0)

    # ---------- 워커 ----------
    def _ensure_workers(self):
        while len(self._workers) < self._concurrency:
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def _worker_loop(self):
        while not self._stop.is_set():
            try:
                job_id = self._pending.get(timeout=0.5)
            except pyqueue.Empty:
                continue
            try:
                with self._lock:
                    job = self._jobs.get(job_id)
                    proceed = bool(job) and job.status == JobStatus.QUEUED
                    if proceed:
                        job.status = JobStatus.RUNNING
                        snapshot = job.to_dict()
                if proceed:
                    self._emit("job_state", **snapshot)
                    self._process(job)
            finally:
                self._pending.task_done()

    def _process(self, job: Job):
        try:
            self._run_job(job)
        except CancelledError:
            with self._lock:
                job.status = JobStatus.CANCELLED
                self._cancelled.discard(job.id)
                snap = job.to_dict()
            self._emit("job_state", **snap)
        except Exception as e:
            with self._lock:
                job.status = JobStatus.FAILED
                job.error = str(e)
                snap = job.to_dict()
            self._emit("job_state", **snap)

    def _get_model(self, topts, job: Job):
        cache = getattr(self._tls, "models", None)
        if cache is None:
            cache = {}
            self._tls.models = cache
        key = (topts.model, topts.device, topts.compute_type)
        if key not in cache:
            def on_log(ratio, msg):
                if ratio < 0:
                    self._emit("log", job_id=job.id, message=msg)
            cache[key] = load_model(topts, on_log)
        return cache[key]

    def _run_job(self, job: Job):
        if job.options.mode == "translate_only":
            self._run_translate_only(job)
            return

        # 기존 자막 건너뛰기 정책: 전사 전에 검사해 연산을 절약
        if job.options.overwrite_policy == "skip":
            existing = self._default_output_path(job)
            if os.path.exists(existing):
                with self._lock:
                    job.status = JobStatus.SKIPPED
                    job.output = existing
                    job.message = "이미 자막이 있어 건너뜀"
                    job.progress = 1.0
                    snap = job.to_dict()
                self._emit("job_state", **snap)
                return

        topts = job.options.to_transcribe_options()
        model, cfg = self._get_model(topts, job)

        # 번역이 뒤따르면 전사는 0~85%, 번역이 85~100% 구간을 쓰도록 스케일
        will_translate = bool(job.options.translate and job.options.target_lang)

        def on_prog(ratio: float, msg: str):
            if ratio < 0:
                self._emit("log", job_id=job.id, message=msg)
                return
            r = ratio * 0.85 if will_translate else ratio
            job.progress = r
            job.message = msg
            self._emit("progress", job_id=job.id,
                       ratio=round(r, 4), message=msg)

        def should_cancel():
            return job.id in self._cancelled

        result = run_transcription(model, cfg, job.path, topts,
                                   on_prog, should_cancel)

        segments = self._maybe_translate(job, result, should_cancel)

        # 자막 표시 시간 정리(겹침/꼬리 침묵 트림)
        from subtitle import clamp_segments
        segments = clamp_segments(segments, max_dur=job.options.max_subtitle_dur)

        out_path = self._output_path(job)
        write_subtitle(segments, out_path, fmt=job.options.fmt,
                       max_line_chars=job.options.max_line_chars)

        with self._lock:
            job.status = JobStatus.DONE
            job.output = out_path
            job.duration = result.duration
            job.language = result.language
            job.progress = 1.0
            snap = job.to_dict()
        self._emit("job_state", **snap)

    def _find_subtitle(self, video_path: str):
        base = os.path.splitext(video_path)[0]
        for fmt in ("srt", "smi"):
            p = base + "." + fmt
            if os.path.exists(p):
                return p, fmt
        return None, None

    def _backup_file(self, path: str):
        base, ext = os.path.splitext(path)
        bak = f"{base}.원본{ext}"
        i = 1
        while os.path.exists(bak):
            bak = f"{base}.원본.{i}{ext}"
            i += 1
        try:
            os.rename(path, bak)
        except OSError:
            pass

    def _run_translate_only(self, job: Job):
        """전사 없이 기존 자막 파일을 읽어 번역만 수행."""
        o = job.options
        sub_path, fmt = self._find_subtitle(job.path)
        if not sub_path:
            with self._lock:
                job.status = JobStatus.FAILED
                job.error = "기존 자막(.srt/.smi)을 찾을 수 없습니다"
                snap = job.to_dict()
            self._emit("job_state", **snap)
            return
        try:
            from subtitle import read_subtitle, detect_lang_simple, write_subtitle
            self._emit("log", job_id=job.id,
                       message=f"기존 자막 읽는 중: {os.path.basename(sub_path)}")
            segs = read_subtitle(sub_path, fmt)
            if not segs:
                raise RuntimeError("자막을 파싱하지 못했습니다")

            src = o.language if o.language not in (None, "auto", "") else \
                detect_lang_simple(" ".join(s["text"] for s in segs[:40]))

            class _R:
                pass
            result = _R()
            result.segments = segs
            result.language = src
            result.duration = segs[-1]["end"] if segs else 0.0

            def should_cancel():
                return job.id in self._cancelled

            translated = self._maybe_translate(job, result, should_cancel)
            if translated is segs:
                raise RuntimeError(
                    f"번역이 수행되지 않았습니다 (원본 {src or '?'}→{o.target_lang})")

            if o.subtitle_backup == "backup":
                self._backup_file(sub_path)
            write_subtitle(translated, sub_path, fmt=fmt,
                           max_line_chars=o.max_line_chars)
            with self._lock:
                job.status = JobStatus.DONE
                job.output = sub_path
                job.language = src
                job.progress = 1.0
                snap = job.to_dict()
            self._emit("job_state", **snap)
        except CancelledError:
            with self._lock:
                job.status = JobStatus.CANCELLED
                self._cancelled.discard(job.id)
                snap = job.to_dict()
            self._emit("job_state", **snap)
        except Exception as e:
            with self._lock:
                job.status = JobStatus.FAILED
                job.error = str(e)
                snap = job.to_dict()
            self._emit("job_state", **snap)

    def _get_translator(self, job: Job):
        cache = getattr(self._tls, "translators", None)
        if cache is None:
            cache = {}
            self._tls.translators = cache
        o = job.options
        key = o.translate_backend
        if key not in cache:
            from translate import make_translator
            cache[key] = make_translator(
                o.translate_backend, device=o.device,
                model_dir=o.model_dir, api_key=o.api_key)
        return cache[key]

    def _maybe_translate(self, job: Job, result, should_cancel):
        """전사 결과를 target_lang으로 번역(요청 시). 실패하면 원어 유지."""
        o = job.options
        segments = result.segments
        if not o.translate or not o.target_lang:
            return segments

        from translate import to_nllb
        src = result.language or (o.language if o.language not in (None, "auto", "") else "")
        if src and src == o.target_lang:
            self._emit("log", job_id=job.id, message="원본과 대상 언어가 같아 번역을 생략합니다.")
            return segments
        if o.translate_backend != "online" and not (to_nllb(src) and to_nllb(o.target_lang)):
            self._emit("log", job_id=job.id,
                       message=f"번역 미지원 언어쌍({src or '?'}→{o.target_lang}) — 원어로 저장합니다.")
            return segments

        try:
            self._emit("log", job_id=job.id,
                       message=f"번역 준비 중: {src or '자동'}→{o.target_lang}")
            translator = self._get_translator(job)
            texts = [(s["text"] if isinstance(s, dict) else s.text).strip()
                     for s in segments]

            base = 0.0 if o.mode == "translate_only" else 0.85
            span = 1.0 if o.mode == "translate_only" else 0.15

            def on_tprog(r):
                self._emit("progress", job_id=job.id,
                           ratio=round(base + span * r, 4),
                           message=f"번역 중... {int(r * 100)}%")

            def on_tlog(m):
                self._emit("log", job_id=job.id, message=m)

            from translate import translate_with_glossary
            with _Heartbeat("번역 중",
                            lambda r, m: self._emit("log", job_id=job.id, message=m)):
                translated = translate_with_glossary(
                    translator, texts, src, o.target_lang, o.glossary,
                    on_log=on_tlog, on_progress=on_tprog, should_cancel=should_cancel)

            new_segs = []
            for i, s in enumerate(segments):
                start = s["start"] if isinstance(s, dict) else s.start
                end = s["end"] if isinstance(s, dict) else s.end
                txt = translated[i] if i < len(translated) else ""
                new_segs.append({"start": start, "end": end, "text": txt})
            self._emit("log", job_id=job.id, message="번역 완료")
            return new_segs
        except CancelledError:
            raise
        except Exception as e:
            import traceback
            detail = f"{type(e).__name__}: {e}"
            self._emit("log", job_id=job.id,
                       message=f"⚠ 번역 실패 — 원어로 저장합니다. 원인: {detail}")
            self._emit("translate_error", job_id=job.id, message=detail,
                       trace=traceback.format_exc()[-800:])
            return segments

    def _default_output_path(self, job: Job) -> str:
        base, _ext = os.path.splitext(job.path)
        if job.options.output_dir:
            os.makedirs(job.options.output_dir, exist_ok=True)
            return os.path.join(job.options.output_dir,
                                os.path.basename(base) + "." + job.options.fmt)
        return base + "." + job.options.fmt

    def _output_path(self, job: Job) -> str:
        path = self._default_output_path(job)
        # rename 정책: 기존 파일이 있으면 .1, .2 … 로 충돌 회피
        if job.options.overwrite_policy == "rename" and os.path.exists(path):
            root, ext = os.path.splitext(path)
            i = 1
            while os.path.exists(f"{root}.{i}{ext}"):
                i += 1
            path = f"{root}.{i}{ext}"
        return path
