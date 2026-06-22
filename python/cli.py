"""M1 코어 파이프라인 CLI.

사용 예:
  python cli.py "C:\\videos\\match1.mp4"
  python cli.py match1.mp4 --model medium --language ko --format srt
  python cli.py match1.mp4 --device cpu --initial-prompt "페이커, 제우스, 바론, 한타"

영상에서 오디오 추출 → faster-whisper 전사 → SRT/SMI 저장까지 수행한다.
번역(NLLB) 단계는 M4에서 추가 예정.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from transcribe import transcribe, TranscribeOptions, VIDEO_EXTS
from subtitle import write_subtitle


def human_eta(start_ts: float, ratio: float) -> str:
    if ratio <= 0.01:
        return "--:--"
    elapsed = time.time() - start_ts
    total = elapsed / ratio
    remain = max(total - elapsed, 0)
    m, s = divmod(int(remain), 60)
    return f"{m:02d}:{s:02d}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="자막 자동 생성기 — M1 코어 파이프라인")
    p.add_argument("input", help="영상 파일 경로")
    p.add_argument("--model", default="small",
                   help="tiny/base/small/medium/large-v3/large-v3-turbo (기본 small)")
    p.add_argument("--device", default="auto",
                   choices=["auto", "cuda", "cpu"], help="기본 auto(자동 감지)")
    p.add_argument("--compute-type", default=None,
                   help="float16/int8/int8_float16 등 (미지정 시 자동)")
    p.add_argument("--language", default="auto",
                   help="원본 언어 코드(ko/en/ja...) 또는 auto(기본)")
    p.add_argument("--task", default="transcribe",
                   choices=["transcribe", "translate"],
                   help="transcribe=원어 전사, translate=영어 번역")
    p.add_argument("--format", default="srt", choices=["srt", "smi"],
                   help="자막 포맷 (기본 srt)")
    p.add_argument("--initial-prompt", default=None,
                   help="콘텐츠 튜닝용 용어 프롬프트")
    p.add_argument("--max-line-chars", type=int, default=None,
                   help="한 줄 최대 글자수(후처리 줄바꿈)")
    p.add_argument("--no-vad", action="store_true", help="VAD 필터 비활성화")
    p.add_argument("--output", default=None,
                   help="출력 경로(미지정 시 영상과 동일 폴더/이름)")
    p.add_argument("--model-dir", default=None, help="모델 캐시 디렉토리")
    args = p.parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"[오류] 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        return 2

    ext = os.path.splitext(args.input)[1].lower()
    if ext not in VIDEO_EXTS:
        print(f"[경고] 알 수 없는 확장자({ext}) — 그래도 시도합니다.",
              file=sys.stderr)

    if args.output:
        out_path = args.output
    else:
        base = os.path.splitext(args.input)[0]
        out_path = f"{base}.{args.format}"

    opts = TranscribeOptions(
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        task=args.task,
        initial_prompt=args.initial_prompt,
        vad_filter=not args.no_vad,
        model_dir=args.model_dir,
    )

    start_ts = time.time()
    state = {"v": 0.0, "bar_active": False}

    def on_progress(ratio: float, msg: str):
        # ratio < 0 : 단계/하트비트 로그 라인 (자체 줄에 출력)
        if ratio < 0:
            if state["bar_active"]:
                print()  # 진행률 바 줄 마무리
                state["bar_active"] = False
            ts = time.strftime("%H:%M:%S")
            print(f"  [{ts}] {msg}", flush=True)
            return
        # 진행률 바 (전사 단계)
        if ratio - state["v"] >= 0.01 or ratio in (0.0, 1.0):
            state["v"] = ratio
            state["bar_active"] = True
            eta = human_eta(start_ts, ratio)
            bar = "#" * int(ratio * 30)
            print(f"\r[{bar:<30}] {ratio*100:5.1f}% ETA {eta}  {msg[:50]:<50}",
                  end="", flush=True)

    print(f"입력: {args.input}")
    try:
        result = transcribe(args.input, opts, on_progress)
    except Exception as e:
        print(f"\n[오류] 전사 실패: {e}", file=sys.stderr)
        return 1

    print()  # 진행률 줄 종료
    write_subtitle(result.segments, out_path, fmt=args.format,
                   max_line_chars=args.max_line_chars)

    elapsed = time.time() - start_ts
    print(f"감지 언어: {result.language} "
          f"(확률 {result.language_probability:.2f})")
    print(f"세그먼트: {len(result.segments)}개 / 길이 {result.duration:.1f}s "
          f"/ 처리 {elapsed:.1f}s / {result.device.describe()}")
    print(f"저장 완료: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
