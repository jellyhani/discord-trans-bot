# typo_detector.py — 한국어 오타 감지 (DB 사전 기반)

import re
from database.dictionary_manager import get_typo_words, get_abbreviations, get_suspicious_endings

# ──────────────────────────────────────────────
# 한글 자모 분해
# ──────────────────────────────────────────────
CHOSUNG = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
JUNGSUNG = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
JONGSUNG = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")


def decompose(char: str):
    code = ord(char) - 0xAC00
    if code < 0 or code > 11171:
        return None
    cho = code // (21 * 28)
    jung = (code % (21 * 28)) // 28
    jong = code % 28
    return CHOSUNG[cho], JUNGSUNG[jung], JONGSUNG[jong]


# ──────────────────────────────────────────────
# 비정상 초성+중성 조합 (이건 언어학적 규칙이라 코드에 유지)
# ──────────────────────────────────────────────
RARE_COMBOS = {
    ("ㅃ", "ㅑ"), ("ㅃ", "ㅕ"), ("ㅃ", "ㅛ"), ("ㅃ", "ㅠ"),
    ("ㅉ", "ㅑ"), ("ㅉ", "ㅕ"), ("ㅉ", "ㅛ"), ("ㅉ", "ㅠ"),
    ("ㄸ", "ㅑ"), ("ㄸ", "ㅕ"), ("ㄸ", "ㅛ"), ("ㄸ", "ㅠ"),
    ("ㅋ", "ㅑ"), ("ㅋ", "ㅕ"), ("ㅋ", "ㅛ"), ("ㅋ", "ㅠ"),
    ("ㅌ", "ㅑ"), ("ㅌ", "ㅕ"), ("ㅌ", "ㅛ"),
    ("ㅍ", "ㅑ"), ("ㅍ", "ㅕ"), ("ㅍ", "ㅛ"), ("ㅍ", "ㅠ"),
}

# ──────────────────────────────────────────────
# 감탄사/의성어 허용 목록 (언어학적 규칙, 코드에 유지)
# ──────────────────────────────────────────────
EXCLAMATION_PATTERNS = re.compile(
    r'^[우와오아으어허후으흐야여유이]{1,10}[~!.]*$|'
    r'^[에엥잉읭]{1,5}[~?!.]*$|'
    r'^[흠음엄]{1,5}[~.]*$'
)

# 문장 내 자음 축약 감지 패턴
_ABBREVIATION_IN_SENTENCE = re.compile(r'(?:^|\s)([ㄱ-ㅎ]{2,})(?:\s|$)')


# ──────────────────────────────────────────────
# 메인 판단 함수
# ──────────────────────────────────────────────
def looks_like_typo(text: str) -> bool:
    korean_syllables = [c for c in text if '\uAC00' <= c <= '\uD7A3']
    korean_jamo = [c for c in text if '\u3131' <= c <= '\u3163']

    if not korean_syllables and not korean_jamo:
        return False

    stripped = text.strip()

    # ── 감탄사/의성어 예외 ──
    if EXCLAMATION_PATTERNS.match(stripped):
        return False

    # ── 0. 구어체 축약 감지 (DB에서 로드) ──
    abbreviations = get_abbreviations()
    words = stripped.split()
    for word in words:
        clean_word = re.sub(r'[.,!?~]+', '', word)
        if clean_word in abbreviations:
            if not re.fullmatch(r'[ㅋㅎㅠㅜ]+', clean_word):
                return True

    if _ABBREVIATION_IN_SENTENCE.search(stripped):
        match = _ABBREVIATION_IN_SENTENCE.search(stripped)
        found = match.group(1)
        if not re.fullmatch(r'[ㅋㅎㅠㅜ]+', found):
            return True

    # ── 1. 알려진 오타 단어 사전 매칭 (DB에서 로드) ──
    typo_words = get_typo_words()
    for typo in typo_words:
        if typo in stripped:
            return True

    # ── 2. 자모만 나열 (ㅋㅎㅠㅜ 반복 제외) ──
    jamo_only = re.sub(r'[ㅋㅎㅠㅜ]+', '', ''.join(korean_jamo))
    if len(jamo_only) >= 2:
        return True

    # ── 3. 비정상 음절 조합 (한글 4자 이상일 때만) ──
    if len(korean_syllables) >= 4:
        rare_count = 0
        vowel_shift_count = 0

        for char in korean_syllables:
            decomposed = decompose(char)
            if not decomposed:
                continue
            cho, jung, jong = decomposed

            if (cho, jung) in RARE_COMBOS:
                rare_count += 1

            if jung in ("ㅑ", "ㅕ", "ㅛ", "ㅠ", "ㅒ", "ㅖ"):
                vowel_shift_count += 1

        if rare_count >= 2:
            return True

        if vowel_shift_count / len(korean_syllables) > 0.4:
            return True

    # ── 4. 감정 표현 제외 연속 자음 반복 ──
    consonant_repeat = re.search(r'([ㄱ-ㅎ])\1{2,}', text)
    if consonant_repeat:
        char = consonant_repeat.group(1)
        if char not in ('ㅋ', 'ㅎ', 'ㅠ', 'ㅜ'):
            return True

    # ── 5. 비표준 어미 패턴 (DB에서 로드) ──
    suspicious_endings = get_suspicious_endings()
    for pattern in suspicious_endings:
        if re.search(pattern, text):
            return True

    return False
