"""배치 CLI: 디렉토리/파일들을 큐에 넣어 순차·병렬로 자막 생성.

사용 예:
  python batch.py "C:\\videos"                      # 폴더 내 영상 전부, 순차
  python batch.py "C:\\videos" --concurrency 2       # 2개 병렬
  python batch.py a.mp4 b.mkv --model medium --format srt
  python batch.py "C:\\videos" --recursive --language ja

병렬 처리 시 각 워커가 모델을 별도로 로드합니다. GPU VRAM/RAM을 고려해
동시 실행 수를 정하세요(large 계열은 1~2 권장).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from jobs import JobOptions, JobStatus
from jobqueue import JobQueue
from scanner import list_media


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="자막 배치 생성 (M2 큐)")
    p.add_argument("inputs", nargs="+", help="폴더 또는 영상 파일들")
    p.add_argument("--concurrency", type=int, default=1, help="동시 실행 수(기본 1=순차)")
    p.add_argument("--recursive", action="store_true", help="폴더 하위까지 스캔")
    p.add_argument("--model", default="small")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--language", default="auto")
    p.add_argument("--task", default="transcribe", choices=["transcribe", "translate"])
    p.add_argument("--format", default="srt", choices=["srt", "smi"])
    p.add_argument("--initial-prompt", default=None)
    p.add_argument("--max-line-chars", type=int, default=None)
    p.add_argument("--no-vad", action="store_true")
    p.add_argument("--output-dir", default=None)
    p.add_argument("--model-dir", default=None)
    args = p.parse_args(argv)

    # 입력 → 파일 목록
    paths: list[str] = []
    for inp in args.inputs:
        if os.path.isdir(inp):
            paths += [m["path"] for m in list_media(inp, recursive=args.recursive)]
        elif os.path.isfile(inp):
            paths.append(inp)
        else:
            print(f"[경고] 찾을 수 없음: {inp}", file=sys.stderr)
    if not paths:
        print("[오류] 처리할 파일이 없습니다.", file=sys.stderr)
        return 2

    opts = JobOptions(
        model=args.model, device=args.device, language=args.language,
        task=args.task, fmt=args.format, initial_prompt=args.initial_prompt,
        vad_filter=not args.no_vad, max_line_chars=args.max_line_chars,
        output_dir=args.output_dir, model_dir=args.model_dir,
    )

    bars: dict[int, float] = {}

    def emit(ev: dict):
        t = ev.get("type")
        if t == "job_added":
            j = ev["job"]
            print(f"+ 추가 #{j['id']}: {j['name']}")
        elif t == "log":
            print(f"  · #{ev['job_id']} {ev['message']}")
        elif t == "progress":
            jid = ev["job_id"]
            r = ev["ratio"]
            if r - bars.get(jid, -1) >= 0.05 or r >= 1.0:
                bars[jid] = r
                print(f"  #{jid} {r*100:5.1f}%  {ev['message'][:40]}")
        elif t == "job_state":
            st = ev["status"]
            mark = {"running": "▶", "done": "✓", "failed": "✗",
                    "cancelled": "⊘", "queued": "…"}.get(st, "?")
            extra = ""
            if st == "done":
                extra = f" → {ev['output']} (언어 {ev['language']})"
            elif st == "failed":
                extra = f" : {ev['error']}"
            print(f"{mark} #{ev['id']} {ev['name']} [{st}]{extra}")

    q = JobQueue(concurrency=args.concurrency, emit=emit)
    for pth in paths:
        q.add(pth, opts)

    start = time.time()
    print(f"\n총 {len(paths)}개 / 동시 실행 {args.concurrency} / 모델 {args.model}\n")
    q.start()
    q.join()
    q.shutdown(wait=True)

    jobs = q.list_jobs()
    done = sum(1 for j in jobs if j["status"] == JobStatus.DONE.value)
    failed = sum(1 for j in jobs if j["status"] == JobStatus.FAILED.value)
    cancelled = sum(1 for j in jobs if j["status"] == JobStatus.CANCELLED.value)
    print(f"\n완료 {done} / 실패 {failed} / 취소 {cancelled} "
          f"/ 총 {len(jobs)} / {time.time()-start:.1f}s")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
