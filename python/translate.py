"""번역 백엔드.

Whisper는 한국어 등 임의 언어로의 번역을 지원하지 않으므로(영어 출력만),
전사 결과를 별도 번역 단계로 목표 언어로 옮긴다.

백엔드:
- nllb    : 로컬 NLLB-200 (transformers). 완전 오프라인. 기본값.
- online  : 온라인 API(DeepL/Google). 인터넷 + API 키 필요.

공통 인터페이스:
    t = make_translator(backend, model_key=..., device=..., api_key=...)
    out = t.translate(texts, src_code, tgt_code, on_log=..., on_progress=..., should_cancel=...)
src_code/tgt_code 는 Whisper 언어 코드(ko/en/ja/...)이며, 내부에서
NLLB FLORES-200 코드로 변환한다.
"""
from __future__ import annotations

import os
import re
from typing import Callable, List, Optional

# 일부 네트워크에서 무한 대기/실패를 일으키는 hf-xet 비활성 (NLLB 다운로드 안정화)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class TranslationError(Exception):
    pass


# Whisper 언어코드 → NLLB FLORES-200 코드
NLLB_CODES = {
    "ko": "kor_Hang", "en": "eng_Latn", "ja": "jpn_Jpan",
    "zh": "zho_Hans", "zh-tw": "zho_Hant",
    "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn",
    "ru": "rus_Cyrl", "vi": "vie_Latn", "th": "tha_Thai",
    "id": "ind_Latn", "it": "ita_Latn", "pt": "por_Latn",
    "ar": "arb_Arab", "hi": "hin_Deva", "tr": "tur_Latn",
    "pl": "pol_Latn", "nl": "nld_Latn", "uk": "ukr_Cyrl",
}

# 선택 가능한 NLLB 모델
NLLB_MODELS = {
    "nllb-600m": "facebook/nllb-200-distilled-600M",
    "nllb-1.3b": "facebook/nllb-200-distilled-1.3B",
}


def to_nllb(whisper_code: str | None) -> Optional[str]:
    if not whisper_code:
        return None
    return NLLB_CODES.get(whisper_code.lower())


def supported_pair(src: str | None, tgt: str | None) -> bool:
    return bool(to_nllb(src) and to_nllb(tgt) and src != tgt)


class NllbTranslator:
    """로컬 NLLB-200 (transformers + torch)."""

    def __init__(self, model_key: str = "nllb-600m",
                 device: Optional[str] = None, model_dir: Optional[str] = None):
        self.model_id = NLLB_MODELS.get(model_key, NLLB_MODELS["nllb-600m"])
        self.device = device
        self.model_dir = model_dir
        self._tok = None
        self._model = None
        self._torch = None
        self._dev = None

    def load(self, on_log: Optional[Callable[[str], None]] = None):
        if self._model is not None:
            return
        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
            import torch
        except Exception:
            raise TranslationError(
                "번역 라이브러리가 없습니다. 설치: "
                "pip install transformers sentencepiece torch")
        if on_log:
            on_log(f"(최초 1회) 번역 모델 다운로드/로드 중: {self.model_id} "
                   f"— 큰 모델은 수 분 소요, 한 번만 받습니다")
        self._tok = AutoTokenizer.from_pretrained(
            self.model_id, cache_dir=self.model_dir)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(
            self.model_id, cache_dir=self.model_dir)
        dev = self.device
        if dev in (None, "auto"):
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        self._model.to(dev)
        self._torch = torch
        self._dev = dev
        if on_log:
            on_log(f"번역 디바이스: {dev}"
                   + ("" if dev == "cuda"
                      else " (CPU — GPU 가속을 원하면 CUDA용 torch 설치 권장)"))

    def _bos_id(self, tgt_nllb: str) -> int:
        tok = self._tok
        try:
            tid = tok.convert_tokens_to_ids(tgt_nllb)
            if tid is not None and tid >= 0:
                return tid
        except Exception:
            pass
        # 구버전 호환
        return tok.lang_code_to_id[tgt_nllb]

    def translate(self, texts: List[str], src_code: str, tgt_code: str,
                  on_log=None, on_progress=None, should_cancel=None,
                  batch_size: int = 16) -> List[str]:
        src = to_nllb(src_code)
        tgt = to_nllb(tgt_code)
        if not src or not tgt:
            raise TranslationError(f"지원하지 않는 언어쌍: {src_code}→{tgt_code}")
        self.load(on_log)
        tok, model, torch = self._tok, self._model, self._torch
        tok.src_lang = src
        bos = self._bos_id(tgt)
        out: List[str] = []
        total = max(len(texts), 1)
        for i in range(0, len(texts), batch_size):
            if should_cancel and should_cancel():
                from transcribe import CancelledError
                raise CancelledError()
            chunk = texts[i:i + batch_size]
            enc = tok(chunk, return_tensors="pt", padding=True,
                      truncation=True, max_length=512).to(self._dev)
            with torch.no_grad():
                # num_beams=1(그리디)로 속도 우선. 품질을 더 원하면 2 이상으로.
                gen = model.generate(**enc, forced_bos_token_id=bos,
                                     max_length=512, num_beams=1)
            out.extend(tok.batch_decode(gen, skip_special_tokens=True))
            if on_progress:
                on_progress(min(1.0, (i + len(chunk)) / total))
        return out


class OnlineTranslator:
    """온라인 번역 API (DeepL). API 키 필요."""

    def __init__(self, api_key: Optional[str] = None, provider: str = "deepl"):
        self.api_key = api_key
        self.provider = provider

    # DeepL 언어 코드(대문자). NLLB와 별개.
    _DEEPL = {"ko": "KO", "en": "EN", "ja": "JA", "zh": "ZH", "es": "ES",
              "fr": "FR", "de": "DE", "ru": "RU", "it": "IT", "pt": "PT",
              "nl": "NL", "pl": "PL", "uk": "UK", "tr": "TR", "id": "ID"}

    def translate(self, texts, src_code, tgt_code, on_log=None,
                  on_progress=None, should_cancel=None, batch_size=40):
        if not self.api_key:
            raise TranslationError("온라인 번역 API 키가 설정되지 않았습니다.")
        try:
            import requests
        except Exception:
            raise TranslationError("requests 라이브러리가 필요합니다: pip install requests")
        tgt = self._DEEPL.get((tgt_code or "").lower())
        if not tgt:
            raise TranslationError(f"DeepL 미지원 대상 언어: {tgt_code}")
        src = self._DEEPL.get((src_code or "").lower())
        url = "https://api-free.deepl.com/v2/translate"
        out = []
        total = max(len(texts), 1)
        for i in range(0, len(texts), batch_size):
            if should_cancel and should_cancel():
                from transcribe import CancelledError
                raise CancelledError()
            chunk = texts[i:i + batch_size]
            data = [("text", t) for t in chunk]
            data.append(("target_lang", tgt))
            if src:
                data.append(("source_lang", src))
            r = requests.post(url, data=data,
                              headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
                              timeout=30)
            if r.status_code != 200:
                raise TranslationError(f"DeepL 오류 {r.status_code}: {r.text[:200]}")
            out.extend([x["text"] for x in r.json().get("translations", [])])
            if on_progress:
                on_progress(min(1.0, (i + len(chunk)) / total))
        return out


# ---------- 번역 용어집(glossary) ----------
# NLLB는 프롬프트/용어집을 지원하지 않으므로, 번역 전후로 플레이스홀더 보호 기법을
# 적용해 고유명사를 원하는 표기로 강제한다.
#   glossary 항목: {"src": "Faker", "dst": "페이커"}  또는  {"src":"Worlds","keep":True}

def normalize_glossary(glossary) -> list[tuple]:
    """[(src, dst)] 리스트로 정규화. keep=True 이거나 dst 비면 원문 유지."""
    out = []
    for e in glossary or []:
        src = (e.get("src") or "").strip()
        if not src:
            continue
        if e.get("keep"):
            dst = src
        else:
            dst = (e.get("dst") or "").strip() or src
        out.append((src, dst))
    return out


def _ph(i: int) -> str:
    return f"⟦{i}⟧"


def protect_text(text: str, terms: list[tuple]) -> str:
    for i, (src, _dst) in enumerate(terms):
        text = re.sub(re.escape(src), _ph(i), text, flags=re.IGNORECASE)
    return text


def restore_text(text: str, terms: list[tuple]) -> str:
    # 번역 과정에서 플레이스홀더에 공백이 끼어들 수 있어 느슨하게 매칭
    for i, (_src, dst) in enumerate(terms):
        text = re.sub(r"⟦\s*" + str(i) + r"\s*⟧", lambda m, d=dst: d, text)
    return text


def translate_with_glossary(translator, texts: List[str], src_code: str,
                            tgt_code: str, glossary=None, **cb) -> List[str]:
    """용어집을 적용해 번역. 용어집이 없으면 일반 번역."""
    terms = normalize_glossary(glossary)
    if not terms:
        return translator.translate(texts, src_code, tgt_code, **cb)
    protected = [protect_text(t, terms) for t in texts]
    out = translator.translate(protected, src_code, tgt_code, **cb)
    return [restore_text(o, terms) for o in out]


class NllbCt2Translator:
    """NLLB-200을 CTranslate2로 구동(추론에 torch 불필요, GPU 가속).

    최초 1회 HF 체크포인트를 CT2로 변환(이때만 transformers·torch 필요)하고,
    이후 ctranslate2.Translator로 추론한다. 변환/로드 실패 시 transformers 기반
    NllbTranslator로 자동 폴백한다.
    """

    def __init__(self, model_key: str = "nllb-600m",
                 device: Optional[str] = None, model_dir: Optional[str] = None):
        self.model_id = NLLB_MODELS.get(model_key, NLLB_MODELS["nllb-600m"])
        self.model_key = model_key
        self.device = device
        self.model_dir = model_dir
        self._translator = None
        self._tok = None
        self._dev = None
        self._fallback = None

    def _ct2_dir(self) -> str:
        root = self.model_dir or os.path.join(
            os.path.expanduser("~"), ".cache", "subgen", "ct2-nllb")
        return os.path.join(root, self.model_id.replace("/", "__"))

    def _ensure_ct2(self, on_log=None) -> str:
        out_dir = self._ct2_dir()
        if os.path.isdir(out_dir) and os.path.exists(os.path.join(out_dir, "model.bin")):
            return out_dir
        from ctranslate2.converters import TransformersConverter
        try:
            import transformers  # noqa: F401
            import torch  # noqa: F401
        except Exception:
            raise TranslationError(
                "NLLB CT2 변환에는 transformers·torch가 한 번 필요합니다. "
                "python 폴더에서: pip install -r requirements-translate.txt")
        os.makedirs(os.path.dirname(out_dir), exist_ok=True)
        if on_log:
            on_log(f"(최초 1회) 번역 모델 CT2 변환 중: {self.model_id} (수 분 소요)")
        conv = TransformersConverter(self.model_id)
        conv.convert(out_dir, quantization="int8", force=True)
        return out_dir

    def load(self, on_log=None):
        if self._translator is not None:
            return
        import ctranslate2
        from transformers import AutoTokenizer
        out_dir = self._ensure_ct2(on_log)
        dev = self.device
        if dev in (None, "auto"):
            dev = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        compute = "int8_float16" if dev == "cuda" else "int8"
        if on_log:
            on_log(f"번역 디바이스: {dev} (CT2)")
        self._translator = ctranslate2.Translator(out_dir, device=dev,
                                                  compute_type=compute)
        self._tok = AutoTokenizer.from_pretrained(self.model_id,
                                                  cache_dir=self.model_dir)
        self._dev = dev

    def _torch_fallback(self):
        if self._fallback is None:
            self._fallback = NllbTranslator(model_key=self.model_key,
                                            device=self.device, model_dir=self.model_dir)
        return self._fallback

    def translate(self, texts: List[str], src_code: str, tgt_code: str,
                  on_log=None, on_progress=None, should_cancel=None,
                  batch_size: int = 32) -> List[str]:
        src = to_nllb(src_code)
        tgt = to_nllb(tgt_code)
        if not src or not tgt:
            raise TranslationError(f"지원하지 않는 언어쌍: {src_code}→{tgt_code}")
        try:
            self.load(on_log)
        except Exception as e:
            if on_log:
                on_log(f"CT2 번역 불가 → transformers로 폴백: {e}")
            return self._torch_fallback().translate(
                texts, src_code, tgt_code, on_log=on_log,
                on_progress=on_progress, should_cancel=should_cancel)

        tok = self._tok
        tok.src_lang = src
        out: List[str] = []
        total = max(len(texts), 1)
        for i in range(0, len(texts), batch_size):
            if should_cancel and should_cancel():
                from transcribe import CancelledError
                raise CancelledError()
            chunk = texts[i:i + batch_size]
            src_tokens = [tok.convert_ids_to_tokens(tok.encode(t)) for t in chunk]
            tgt_prefix = [[tgt]] * len(chunk)
            results = self._translator.translate_batch(
                src_tokens, target_prefix=tgt_prefix, beam_size=1,
                max_decoding_length=512)
            for r in results:
                hyp = list(r.hypotheses[0])
                if hyp and hyp[0] == tgt:
                    hyp = hyp[1:]
                out.append(tok.decode(tok.convert_tokens_to_ids(hyp)))
            if on_progress:
                on_progress(min(1.0, (i + len(chunk)) / total))
        return out


class GoogleTranslator:
    """Google Cloud Translation API v2 (API 키 방식)."""
    _MAP = {"zh": "zh-CN", "zh-tw": "zh-TW"}

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def _code(self, c):
        c = (c or "").lower()
        return self._MAP.get(c, c)

    def translate(self, texts, src_code, tgt_code, on_log=None,
                  on_progress=None, should_cancel=None, batch_size=64):
        if not self.api_key:
            raise TranslationError("Google 번역 API 키가 필요합니다(설정 → 온라인 API 키).")
        import html as _h
        import requests
        url = "https://translation.googleapis.com/language/translate/v2"
        out = []
        total = max(len(texts), 1)
        for i in range(0, len(texts), batch_size):
            if should_cancel and should_cancel():
                from transcribe import CancelledError
                raise CancelledError()
            chunk = texts[i:i + batch_size]
            data = [("q", t) for t in chunk]
            data.append(("target", self._code(tgt_code)))
            if src_code and src_code not in ("auto", "", None):
                data.append(("source", self._code(src_code)))
            data.append(("format", "text"))
            r = requests.post(url, params={"key": self.api_key}, data=data, timeout=30)
            if r.status_code != 200:
                raise TranslationError(f"Google 오류 {r.status_code}: {r.text[:200]}")
            trs = r.json().get("data", {}).get("translations", [])
            out.extend(_h.unescape(t.get("translatedText", "")) for t in trs)
            if on_progress:
                on_progress(min(1.0, (i + len(chunk)) / total))
        return out


class KakaoTranslator:
    """카카오 번역 REST API (REST API 키 방식)."""
    _MAP = {"ko": "kr", "en": "en", "ja": "jp", "zh": "cn"}

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def _code(self, c):
        return self._MAP.get((c or "").lower(), (c or "").lower())

    def translate(self, texts, src_code, tgt_code, on_log=None,
                  on_progress=None, should_cancel=None, batch_size=1):
        if not self.api_key:
            raise TranslationError("카카오 번역 REST API 키가 필요합니다(설정 → 온라인 API 키).")
        import requests
        url = "https://dapi.kakao.com/v2/translation/translate"
        headers = {"Authorization": f"KakaoAK {self.api_key}"}
        src = self._code(src_code) if src_code not in ("auto", "", None) else "kr"
        tgt = self._code(tgt_code)
        out = []
        total = max(len(texts), 1)
        for i, t in enumerate(texts):
            if should_cancel and should_cancel():
                from transcribe import CancelledError
                raise CancelledError()
            r = requests.get(url, headers=headers,
                             params={"src_lang": src, "target_lang": tgt, "query": t},
                             timeout=30)
            if r.status_code != 200:
                raise TranslationError(f"카카오 오류 {r.status_code}: {r.text[:200]}")
            sents = r.json().get("translated_text", [])
            out.append(" ".join(" ".join(s) for s in sents) if sents else "")
            if on_progress and (i % 5 == 0 or i == len(texts) - 1):
                on_progress(min(1.0, (i + 1) / total))
        return out


def make_translator(backend: str = "nllb", model_key: str = "nllb-600m",
                    device: Optional[str] = None, model_dir: Optional[str] = None,
                    api_key: Optional[str] = None):
    backend = (backend or "nllb").lower()
    if backend in ("nllb", "nllb-600m", "nllb-1.3b"):
        key = backend if backend in NLLB_MODELS else model_key
        # CT2 기반(추론 torch 불필요·GPU). 실패 시 내부에서 transformers로 폴백.
        return NllbCt2Translator(model_key=key, device=device, model_dir=model_dir)
    if backend == "google":
        return GoogleTranslator(api_key=api_key)
    if backend in ("kakao", "kakaotranslate"):
        return KakaoTranslator(api_key=api_key)
    if backend in ("online", "deepl"):
        return OnlineTranslator(api_key=api_key)
    raise TranslationError(f"알 수 없는 번역 백엔드: {backend}")
