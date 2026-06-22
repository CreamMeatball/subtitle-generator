"""자막 생성: 타임스탬프 포매팅, SRT / SMI 출력, 간단한 후처리.

faster-whisper의 segment 객체(start, end, text 속성)나 동일 형태의 dict를
입력으로 받는다. 외부 의존성 없이 순수 파이썬으로 동작하므로 단독 테스트 가능.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence
import html


@dataclass
class Cue:
    index: int
    start: float  # seconds
    end: float    # seconds
    text: str


def format_timestamp(seconds: float, decimal_sep: str = ",") -> str:
    """초 단위를 HH:MM:SS,mmm (SRT) 형식으로 변환."""
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000.0))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal_sep}{millis:03d}"


def _normalize(segments: Iterable) -> list[Cue]:
    """segment 객체/딕셔너리 혼용을 Cue 리스트로 정규화."""
    cues: list[Cue] = []
    for i, seg in enumerate(segments, start=1):
        if isinstance(seg, dict):
            start, end, text = seg["start"], seg["end"], seg["text"]
        else:
            start, end, text = seg.start, seg.end, seg.text
        text = (text or "").strip()
        if not text:
            continue
        cues.append(Cue(index=len(cues) + 1, start=float(start),
                        end=float(end), text=text))
    return cues


def clamp_segments(segments, max_dur: float | None = 7.0,
                   min_dur: float = 0.4) -> list:
    """자막 표시 시간 정리.

    - 다음 자막 시작을 침범하지 않게 끝 시간을 자른다(겹침 방지).
    - max_dur(초)보다 오래 떠 있는 자막은 잘라낸다 → 침묵 구간에 자막이
      계속 떠 있는 문제(예: 앞 대사가 1분간 잔존)를 방지(꼬리 침묵 트림).
    - 너무 짧은 자막은 min_dur까지 늘리되 다음 자막은 침범하지 않는다.
    반환: [{"start","end","text"}] dict 리스트.
    """
    cues = _normalize(segments)
    starts = [c.start for c in cues]
    n = len(cues)
    out = []
    for i, c in enumerate(cues):
        start, end = c.start, c.end
        next_start = starts[i + 1] if i + 1 < n else None
        if next_start is not None and end > next_start:
            end = next_start
        if max_dur and max_dur > 0 and (end - start) > max_dur:
            end = start + max_dur
        if end - start < min_dur:
            end = start + min_dur
            if next_start is not None and end > next_start:
                end = next_start
        if end <= start:
            end = start + 0.1
        out.append({"start": start, "end": end, "text": c.text})
    return out


def wrap_text(text: str, max_chars: int | None) -> str:
    """한 줄 최대 글자수 제한(간단 후처리). 단어 경계 기준 2줄까지 줄바꿈."""
    if not max_chars or len(text) <= max_chars:
        return text
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def build_srt(segments: Iterable, max_line_chars: int | None = None) -> str:
    cues = _normalize(segments)
    blocks = []
    for cue in cues:
        text = wrap_text(cue.text, max_line_chars)
        blocks.append(
            f"{cue.index}\n"
            f"{format_timestamp(cue.start, ',')} --> {format_timestamp(cue.end, ',')}\n"
            f"{text}\n"
        )
    return "\n".join(blocks)


def build_smi(segments: Iterable, lang_class: str = "KRCC",
              max_line_chars: int | None = None) -> str:
    """SAMI(.smi) 형식. SYNC Start는 밀리초 단위 정수."""
    cues = _normalize(segments)
    header = (
        "<SAMI>\n<HEAD>\n<TITLE></TITLE>\n"
        "<STYLE TYPE=\"text/css\">\n<!--\n"
        "P { margin:0; font-family:Arial; font-size:18pt; text-align:center; }\n"
        f".{lang_class} {{ Name:Korean; lang:ko-KR; SAMIType:CC; }}\n"
        "-->\n</STYLE>\n</HEAD>\n<BODY>\n"
    )
    body = []
    for cue in cues:
        text = wrap_text(cue.text, max_line_chars)
        text_html = html.escape(text).replace("\n", "<br>")
        start_ms = int(round(cue.start * 1000))
        end_ms = int(round(cue.end * 1000))
        body.append(f"<SYNC Start={start_ms}><P Class={lang_class}>{text_html}")
        # 빈 자막으로 종료 (다음 자막 전까지 표시)
        body.append(f"<SYNC Start={end_ms}><P Class={lang_class}>&nbsp;")
    footer = "\n</BODY>\n</SAMI>\n"
    return header + "\n".join(body) + footer


def write_subtitle(segments: Sequence, out_path: str, fmt: str = "srt",
                   max_line_chars: int | None = None) -> str:
    fmt = fmt.lower()
    if fmt == "srt":
        content = build_srt(segments, max_line_chars)
    elif fmt == "smi":
        content = build_smi(segments, max_line_chars=max_line_chars)
    else:
        raise ValueError(f"지원하지 않는 자막 포맷: {fmt}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path


# ---------- 기존 자막 읽기(번역 전용용) ----------

def _read_text(path: str) -> str:
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def parse_srt(text: str) -> list:
    blocks = re.split(r"\n\s*\n", text.strip())
    segs = []
    tc = re.compile(
        r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
    for b in blocks:
        lines = [l for l in b.strip().splitlines() if l.strip() != ""]
        if not lines:
            continue
        idx = 0
        if not tc.search(lines[0]) and len(lines) > 1 and tc.search(lines[1]):
            idx = 1
        m = tc.search(lines[idx]) if idx < len(lines) else None
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        txt = " ".join(lines[idx + 1:]).strip()
        if txt:
            segs.append({"start": start, "end": end, "text": txt})
    return segs


def parse_smi(text: str) -> list:
    import html as _html
    items = re.findall(r"<SYNC\s+Start\s*=\s*(\d+)[^>]*>(.*?)(?=<SYNC|</BODY|\Z)",
                       text, re.IGNORECASE | re.DOTALL)
    segs = []
    prev = None  # (start_sec, text)
    for start_ms, content in items:
        t = re.sub(r"<[^>]+>", "", content)
        t = _html.unescape(t).replace(" ", " ").replace("\n", " ").strip()
        start = int(start_ms) / 1000.0
        if prev is not None:
            ps, pt = prev
            if pt:
                segs.append({"start": ps, "end": start, "text": pt})
        prev = (start, t)
    if prev is not None and prev[1]:
        segs.append({"start": prev[0], "end": prev[0] + 3.0, "text": prev[1]})
    return segs


def read_subtitle(path: str, fmt: str = "srt") -> list:
    text = _read_text(path)
    return parse_smi(text) if fmt.lower() == "smi" else parse_srt(text)


def detect_lang_simple(text: str) -> str:
    """자막 텍스트에서 대략적 언어 추정(번역 src용)."""
    if re.search(r"[가-힣]", text):
        return "ko"
    if re.search(r"[぀-ヿ]", text):
        return "ja"
    if re.search(r"[一-鿿]", text):
        return "zh"
    return "en"
