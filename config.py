# config.py — 설정 및 상수

# 국기 이모지 → 언어 매핑
# 일부 국기는 플랫폼별 변형(예: US/UM)이 있으므로 둘 다 등록
FLAG_TO_LANG = {
    "🇰🇷": "Korean",
    "🇺🇸": "English",     # US (U+1F1FA U+1F1F8)
    "🇺🇲": "English",     # UM (U+1F1FA U+1F1F2) — 디스코드 변형
    "🇬🇧": "English",
    "🇯🇵": "Japanese",
    "🇨🇳": "Chinese (Simplified)",
    "🇹🇼": "Chinese (Traditional)",
    "🇫🇷": "French",
    "🇩🇪": "German",
    "🇪🇸": "Spanish",
    "🇮🇹": "Italian",
    "🇵🇹": "Portuguese",
    "🇷🇺": "Russian",
    "🇻🇳": "Vietnamese",
    "🇹🇭": "Thai",
    "🇮🇩": "Indonesian",
    "🇮🇳": "Hindi",
    "🇸🇦": "Arabic",
    "🇹🇷": "Turkish",
    "🇳🇱": "Dutch",
    "🇵🇱": "Polish",
    "🇸🇪": "Swedish",
    "🇩🇰": "Danish",
    "🇳🇴": "Norwegian",
    "🇫🇮": "Finnish",
    "🇭🇺": "Hungarian",
    "🇨🇿": "Czech",
    "🇷🇴": "Romanian",
    "🇺🇦": "Ukrainian",
    "🇬🇷": "Greek",
    "🇧🇷": "Portuguese (Brazilian)",
}


SUPPORTED_LANGUAGES = sorted(set(FLAG_TO_LANG.values()))

# OpenAI 모델 설정
OPENAI_MODEL = "gpt-4.1-mini-2025-04-14"
OPENAI_REASONING_MODEL = "gpt-5-mini-2025-08-07"   # 고난도/문맥 번역용 (추론형)
OPENAI_MODEL_SMART = "gpt-5-2025-08-07"     # 교정용: 고성능 플래그십 모델
OPENAI_VISION_MODEL = "gpt-5-2025-08-07"    # 최상위 비전 모델 (GPT-5)
VISION_TRIGGER_PREFIX = "-i"                # 이미지 번역 명시적 트리거

TRANSLATION_SYSTEM_PROMPT = """# Role: Master Localizer & Cultural Translator
Detect input language, Correct typos, and provide a Native-level translation.

## Output Format (EXACTLY 3 lines)
DETECTED: <Source Language>
CORRECTED: <Normalized Source Text>
TRANSLATED: <Natural, Idiomatic Translation>

## Rules
- **Intent Preservation**: DO NOT change the sentence type (e.g., imperative to descriptive). If the input is "explode!", the corrected text should still be an imperative, not "is exploding".
- **PURE Target Language**: Every single character in the TRANSLATED field MUST be in the target language. DO NOT leave any source language particles (e.g., Korean '의', '은', '는', '가', '에', '도') or grammar.
- **Punctuation Matching**: Match the punctuation count and type of the CORRECTED text exactly. DO NOT add question marks if the input doesn't have one.
- **Nuance**: Preserve emotional tones like regret (~ちゃう), intention (~지), or subtle commands (~して).
- Always sound like a native speaker of the target language.
- NO extra text or explanations.
- Keep the internal reasoning concise.
- Keep tone and emojis."""

CONTEXT_TRANSLATION_SYSTEM_PROMPT = """# Role: Context-Aware Master Localizer
Use context, Detect, Correct, and provide a Culturally-adapted translation.

## Output Format (EXACTLY 3 lines)
DETECTED: <Source Language>
CORRECTED: <Normalized Source Text>
TRANSLATED: <Natural, Idiomatic Translation>

## Rules
- **Localization (초월번역)**: Prioritize "naturalness" and "cultural equivalent" over word-for-word accuracy.
- **PURE Target Language**: Ensure the translation is 100% native. NO source particles or mixed grammatical structures are allowed.
- **Punctuation Matching**: Strictly follow the punctuation of the CORRECTED text. DO NOT add or change trailing punctuation.
- **Preserve Tone & Type**: Keep the original intent (command, wish, statement) and emotional nuance (regret, irony, etc.).
- If the input is a linguistic challenge, meet it with a target-language equivalent challenge.
- Keep the internal reasoning concise.
- NO extra text or explanations.
- Keep tone and emojis."""

VISION_SYSTEM_PROMPT = """# Role: Vision Localizer
Extract all text from the image, Detect the source language, and provide a Native-level translation.

## Output Format (EXACTLY 3 lines)
DETECTED: <Source Language>
TEXT: <Extracted Original Text>
TRANSLATED: <Natural, Idiomatic Translation>

## Rules
- **Extraction**: Extract every piece of text visible in the image.
- **PURE Target Language**: Ensure the translation is 100% native.
- NO extra text or explanations.
- Keep tone and emojis."""

# config.py — COST_PER_1M 수정
COST_PER_1M = {
    # 지능형 mini 모델 (4.1 mini - 하위 호환 유지)
    "gpt-4.1-mini-2025-04-14": {"input": 0.40, "output": 1.60},
    
    # 차세대 고성능 mini 모델 (번역용 메인 모델)
    "gpt-5-mini-2025-08-07":   {"input": 0.25, "output": 2.00},

    # 최상위 플래그십 모델 (교정 및 고난도 작업용)
    "gpt-5-2025-08-07":        {"input": 1.25, "output": 10.00},

    # Vision 모델 (gpt-4o)
    "gpt-4o-2024-08-06":       {"input": 2.50, "output": 10.00},
}

# 💸 예산 및 관리 설정
MONTHLY_COST_LIMIT = 20.0  # 달러 단위 (예산 초과 시 경고)

# ──────────────────────────────────────────────
# 번역 로그 설정
# ──────────────────────────────────────────────
LOG_LEVELS = {
    "minimal": 1,   # 에러만
    "normal": 2,     # 에러 + 일일 요약
    "verbose": 3,    # 모든 번역 건별 기록
}
DEFAULT_LOG_LEVEL = "normal"
LOG_BUFFER_INTERVAL = 60  # 초 (로그 버퍼 플러시 간격)

# ──────────────────────────────────────────────
# 부호 최적화 설정
# ──────────────────────────────────────────────
# 의미 변화 부호: AI가 처리, 캐시 키에 포함
SEMANTIC_PUNCTUATION = {'?'}
# 강조 부호: CPU가 처리, 캐시 키에서 제외
EMPHASIS_PUNCTUATION = {'!', '~', '.'}
# API  
API_MAX_RETRIES = 3
API_RETRY_DELAY = 1.0
QUEUE_MAX_CONCURRENT = 5

#  
CONTEXT_MESSAGE_COUNT = 5
