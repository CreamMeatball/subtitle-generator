"""subtitle.py 단위 테스트 (무의존성). 실행: python test_subtitle.py"""
from subtitle import format_timestamp, build_srt, build_smi, wrap_text


def test_timestamp():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(1.5) == "00:00:01,500"
    assert format_timestamp(61.234) == "00:01:01,234"
    assert format_timestamp(3661.001) == "01:01:01,001"
    assert format_timestamp(-5) == "00:00:00,000"
    # 반올림 확인
    assert format_timestamp(0.0006) == "00:00:00,001"


def test_srt_basic():
    segs = [
        {"start": 0.0, "end": 1.2, "text": " 안녕하세요 "},
        {"start": 1.2, "end": 2.5, "text": "테스트입니다"},
        {"start": 2.5, "end": 3.0, "text": "   "},  # 빈 텍스트 → 스킵
    ]
    out = build_srt(segs)
    assert "1\n00:00:00,000 --> 00:00:01,200\n안녕하세요" in out
    assert "2\n00:00:01,200 --> 00:00:02,500\n테스트입니다" in out
    # 빈 세그먼트는 제외되어 인덱스가 3개가 아닌 2개
    assert "3\n" not in out


def test_wrap():
    text = "this is a fairly long subtitle line that should wrap"
    wrapped = wrap_text(text, 20)
    assert "\n" in wrapped
    for line in wrapped.split("\n"):
        # 단어 경계 기준이므로 약간 초과 가능하지만 대략 제한 근처
        assert len(line) <= 25
    # 짧으면 그대로
    assert wrap_text("short", 20) == "short"
    assert wrap_text("anything", None) == "anything"


def test_smi_basic():
    segs = [{"start": 0.0, "end": 1.0, "text": "안녕 <태그>"}]
    out = build_smi(segs)
    assert "<SAMI>" in out and "</SAMI>" in out
    assert "<SYNC Start=0>" in out
    assert "<SYNC Start=1000>" in out
    # HTML 이스케이프 확인
    assert "&lt;태그&gt;" in out


def test_object_segments():
    class Seg:
        def __init__(self, s, e, t):
            self.start, self.end, self.text = s, e, t
    out = build_srt([Seg(0, 1, "객체 세그먼트")])
    assert "객체 세그먼트" in out


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} 테스트 통과")
