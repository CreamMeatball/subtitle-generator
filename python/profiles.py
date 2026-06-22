"""콘텐츠 튜닝 프로필.

각 프로필은 Whisper의 initial_prompt에 주입할 도메인 텍스트(고유명사·용어)를
제공한다. 모델 재학습 없이 인식 정확도와 맥락 적합성을 높이는 방식.
사용자 커스텀 프롬프트와 합쳐서 사용할 수 있다.
"""
from __future__ import annotations

# 순서 유지를 위해 리스트(id, 표시명, 프롬프트)
PROFILES = [
    ("general", "일반", ""),
    ("esports_lol", "LoL e스포츠",
     "리그 오브 레전드 프로 대회 중계 해설입니다. "
     "페이커, 제우스, 오너, 구마유시, 케리아, 쇼메이커, 카나비, 룰러, "
     "탑, 미드, 정글, 원딜, 서포터, 봇, 한타, 갱킹, 백도어, 로밍, "
     "바론, 드래곤, 내셔 남작, 장로 드래곤, 억제기, 포탑, 미니언, "
     "와드, 블루, 레드, 협곡, 라인전, 다이브, 슈퍼플레이."),
    ("esports_general", "e스포츠(일반)",
     "프로 게임 대회 중계입니다. 세트, 매치, 경기, 선수, 팀, 우승, "
     "결승, 플레이오프, 한타, 교전, 빌드, 전략을 다룹니다."),
    ("lecture", "강의/세미나",
     "전문 강의 녹화입니다. 개념, 정의, 예시, 증명, 정리, 요약, "
     "질문, 과제, 참고문헌을 포함한 학술적 발표입니다."),
    ("meeting", "회의",
     "업무 회의 녹음입니다. 안건, 일정, 액션 아이템, 담당자, 마감일, "
     "예산, 우선순위, 결정 사항을 논의합니다."),
    ("interview", "인터뷰/팟캐스트",
     "대담·인터뷰입니다. 진행자와 게스트가 번갈아 대화하는 구어체입니다."),
    ("drama", "드라마/영화",
     "드라마·영화 대사입니다. 자연스러운 구어체와 감정 표현, "
     "인물 간 대화를 포함합니다."),
    ("news", "뉴스/시사",
     "뉴스 보도입니다. 앵커, 기자, 인터뷰, 정치, 경제, 사회, 국제 "
     "분야의 공식적인 문어체 표현을 사용합니다."),
]

_BY_ID = {pid: prompt for pid, _name, prompt in PROFILES}


def list_profiles() -> list[dict]:
    return [{"id": pid, "name": name} for pid, name, _p in PROFILES]


def build_prompt(profile_id: str | None, custom: str | None = "") -> str:
    """프로필 기본 프롬프트와 사용자 커스텀을 합쳐 initial_prompt 생성."""
    base = _BY_ID.get(profile_id or "general", "")
    custom = (custom or "").strip()
    if base and custom:
        return f"{base} {custom}"
    return base or custom
