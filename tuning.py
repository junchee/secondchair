"""Values that decide how Anne listens, cleans and translates, changeable while it runs (Settings > Developer).

Each value has a group (what it is for), a range, a short explanation and the default that was tuned by hand
on 2026-10-22/23. Changes apply from the next line and are kept in user_settings.json (only the changed ones).
Code asks for a value with get("key"); nothing else in the program holds these numbers.
"""

GROUPS = [
    ("cut", "1. 말 구간 자르기", "소리에서 말이 시작하고 끝나는 곳을 찾는 기준입니다. 줄 길이와 쉬는 틈은 Settings의 Lines에 있습니다."),
    ("noise", "2. 소음 걸러내기", "기침, 키보드, 조용한 방 소리가 글자로 나오는 것을 막는 기준입니다. 걸러진 것은 터미널에 dropped로 나옵니다."),
    ("whisper", "3. 받아 적기 (Whisper)", "소리를 글로 바꾸는 단계의 조절 값입니다. 초안은 말하는 도중 영어가 자라는 기능입니다."),
    ("bubble", "4. 말풍선 묶기", "문장 중간에서 끊긴 줄을 한 말풍선에 이어 붙이는 기준입니다."),
    ("translate", "5. 번역", "번역 요청의 제한 시간, 백업, 문맥에 관한 값입니다. 번역 모델은 위의 Translation model에서 고릅니다."),
]

# key, group, label, kind, default, low, high, step, help
_ROWS = [
    ("min_speech_seconds", "cut", "말로 인정하는 최소 길이 (초)", "number", 0.3, 0.1, 1.5, 0.05,
     "이보다 짧은 소리(딸깍, 기침)는 줄로 만들지 않습니다. 올리면 짧은 대답('네')이 사라질 수 있습니다."),
    ("preroll_seconds", "cut", "말 시작 앞부분 여유 (초)", "number", 0.3, 0.0, 1.0, 0.05,
     "말이 시작되기 직전 소리를 이만큼 함께 넣어 첫 단어가 잘리지 않게 합니다."),
    ("speech_ratio", "cut", "말소리 배율", "number", 3.0, 1.5, 8.0, 0.5,
     "주변 소음보다 이 배수만큼 커야 말로 봅니다. 올리면 조용한 말을 놓치고, 내리면 소음이 말로 들어옵니다."),
    ("min_speech_rms", "cut", "말소리 최소 크기", "number", 0.003, 0.0005, 0.02, 0.0005,
     "아무리 조용한 방이어도 이보다 작은 소리는 말로 보지 않습니다."),

    ("no_speech_prob", "noise", "무음일 확률 한계", "number", 0.5, 0.1, 1.0, 0.05,
     "Whisper가 '말이 아닌 것 같다'고 보는 확률이 이보다 크고 단어 확신도 낮으면 버립니다. 내리면 더 많이 버립니다."),
    ("min_avg_logprob", "noise", "단어 확신 한계", "number", -0.8, -2.0, 0.0, 0.05,
     "단어에 대한 Whisper의 확신이 이보다 낮으면(더 음수) 버립니다. 올리면(0에 가깝게) 더 많이 버립니다."),
    ("min_language_share", "noise", "영어·한국어 비율 한계", "number", 0.5, 0.0, 1.0, 0.05,
     "언어 추측에서 영어와 한국어의 합이 이보다 작으면 소음으로 보고 버립니다. 다른 언어를 쓰는 회의면 내립니다."),
    ("noise_phrases", "noise", "지어낸 문구 목록", "text", "thanks for watching, thank you for watching, please subscribe, subscribe, bye, bye bye, 시청해주셔서 감사합니다, 구독과 좋아요, MBC news, 字幕", None, None, None,
     "소리가 없을 때 Whisper가 만들어 내는 문구입니다. 쉼표로 구분합니다. 이것과 똑같은 줄은 버립니다."),

    ("use_hint", "whisper", "배경지식 힌트 사용", "bool", True, None, None, None,
     "배경지식의 주제와 용어를 Whisper에게 힌트로 줍니다. 엉뚱한 용어가 끼어들면 꺼 보세요."),
    ("draft_seconds", "whisper", "초안 간격 (초, 0 = 끔)", "number", 1.0, 0.0, 5.0, 0.25,
     "말하는 도중 이 간격으로 영어 초안을 만듭니다. 느린 Mac에서는 올리거나 끄면 최종 전사가 빨라집니다."),
    ("draft_min_seconds", "whisper", "초안을 시작하는 길이 (초)", "number", 0.8, 0.3, 3.0, 0.1,
     "이보다 짧은 줄은 초안을 만들지 않습니다."),
    ("max_tokens", "whisper", "글자 수 상한 (토큰, 최대)", "number", 160, 40, 448, 8,
     "한 줄에서 Whisper가 쓸 수 있는 최대 토큰입니다. 같은 말이 반복되는 오류를 막는 안전장치입니다."),
    ("en_tokens_base", "whisper", "영어 상한: 기본", "number", 16, 0, 100, 4, "영어 줄의 글자 수 상한 = 기본 + 초당 값 x 길이."),
    ("en_tokens_per_second", "whisper", "영어 상한: 초당", "number", 12, 4, 40, 1, "영어는 초당 약 3~4단어입니다."),
    ("ko_tokens_base", "whisper", "한국어 상한: 기본", "number", 48, 0, 150, 4, "한국어 줄의 글자 수 상한 = 기본 + 초당 값 x 길이."),
    ("ko_tokens_per_second", "whisper", "한국어 상한: 초당", "number", 30, 8, 80, 2, "한국어는 영어보다 토큰이 훨씬 많이 필요합니다."),

    ("max_bubble_chars", "bubble", "한 말풍선의 최대 글자 수", "number", 500, 100, 2000, 50,
     "이보다 길어지면 다음 줄은 새 말풍선이 됩니다."),
    ("small_letter_continues", "bubble", "소문자로 시작하면 이어 붙임", "bool", True, None, None, None,
     "Whisper가 쉬는 곳에 마침표를 찍어도, 다음 줄이 소문자로 시작하면 같은 문장으로 봅니다."),

    ("stream_deadline_seconds", "translate", "번역 제한 시간 (초)", "number", 8, 3, 30, 1,
     "번역이 이 시간 안에 끝나지 않으면 끊고 백업을 씁니다."),
    ("backup_seconds", "translate", "백업 유지 시간 (초)", "number", 60, 0, 600, 10,
     "번역이 실패한 뒤 이 시간 동안 백업 모델(Qwen)을 씁니다."),
    ("context_lines", "translate", "앞 문맥 (말풍선 수)", "number", 2, 0, 6, 1,
     "번역할 때 함께 보내는 앞선 말풍선 수입니다. 늘리면 문맥이 좋아지고 요청이 커집니다."),
    ("use_previous", "translate", "앞 번역을 참고로 보냄", "bool", True, None, None, None,
     "말풍선이 자랄 때 이미 나온 한국어를 그대로 두고 이어 번역합니다. 끄면 매번 새로 번역합니다."),
    ("use_notes", "translate", "배경지식 주제·용어를 보냄", "bool", True, None, None, None,
     "번역 요청에 회의 주제와, 그 문장에 나온 용어를 붙입니다."),
]

SCHEMA = [
    {"key": k, "group": g, "label": label, "kind": kind, "default": d, "low": lo, "high": hi, "step": st, "help": h}
    for k, g, label, kind, d, lo, hi, st, h in _ROWS
]
_BY_KEY = {row["key"]: row for row in SCHEMA}
_values = {row["key"]: row["default"] for row in SCHEMA}


def get(key):
    return _values[key]


def values():
    return dict(_values)


def changed():
    """Only the values that differ from the defaults (what is saved)."""
    return {k: v for k, v in _values.items() if v != _BY_KEY[k]["default"]}


def apply(change):
    """Take over values from a dict; unknown keys and bad values are ignored, numbers are kept in their range."""
    for key, value in (change or {}).items():
        row = _BY_KEY.get(key)
        if not row:
            continue
        try:
            if row["kind"] == "bool":
                if isinstance(value, bool):
                    _values[key] = value
            elif row["kind"] == "text":
                _values[key] = str(value)[:2000]
            else:
                number = min(row["high"], max(row["low"], float(value)))
                _values[key] = int(number) if isinstance(row["default"], int) else number
        except (TypeError, ValueError):
            pass


def reset(group=None):
    """Back to the defaults: one group, or everything (group = None or "all")."""
    for row in SCHEMA:
        if group in (None, "all") or row["group"] == group:
            _values[row["key"]] = row["default"]


def noise_phrases():
    """The made-up phrases as a set of letters only, lower case (how a line is compared)."""
    import re
    return {re.sub(r"[\W_]+", "", p).lower() for p in _values["noise_phrases"].split(",") if p.strip()}
