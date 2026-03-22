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
    "🇹🇼": "Traditional Chinese (Taiwan)",
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

# OpenAI 모델 설정 (2026 최적화)
OPENAI_MODEL = "gpt-4.1-mini-2025-04-14"
OPENAI_REASONING_MODEL = "gpt-5-mini-2025-08-07"
OPENAI_MODEL_SMART = "gpt-5-2025-08-07"
OPENAI_VISION_MODEL = "gpt-5-2025-08-07"

# [NEW] 멘토봇 전용 최적화 모델 (유저 벤치마크 반영하여 실존 모델로 수정)
# gpt-5.3은 API에서 찾을 수 없어, 5세대급 추론 mini 모델로 대체합니다.
MENTOR_REASONING_MODEL = "gpt-5-mini-2025-08-07"  # 판단 정확도 우수 + 입력 비용 저렴
MENTOR_ANSWER_MODEL = "gpt-4.1-mini-2025-04-14"   # 답변 자연스러움 + 출력 가성비
VISION_TRIGGER_PREFIX = "-i"                # 이미지 번역 명시적 트리거

TRANSLATION_SYSTEM_PROMPT = """# Role: Master Localizer & Cultural Translator
Detect input language, Correct typos/slang, and provide a Natural and Accurate translation.

## Output Format (EXACTLY 3 lines)
DETECTED: <Source Language>
CORRECTED: <Normalized Source Text>
TRANSLATED: <Natural, Accurate Translation>

## Correction Rules (Few-Shot)
- **Korean Visual Slang (야민정음)**: 
  - Input: '커엽네' -> Corrected: '귀엽네' -> Translated: 'So cute'
  - Input: '댕댕이' -> Corrected: '멍멍이' -> Translated: 'Doggie'
- **Traditional Chinese (Taiwan) Shorthand**: 
  - Input: 'ㄅ' -> Corrected: '不' (No)
  - Input: 'ㄍ' -> Corrected: '個' (Piece/Unit)
  - Input: 'ㄏㄏ' -> Corrected: '哈哈' (Haha)

## Translation Rules
1. **Purity**: The TRANSLATED field MUST be 100% in the target language. NO mixed particles.
2. **Intent & Nuance**: Match sentence type (imperative, question, etc.). Preserve emotional endings:
   - KR/JP: ~다몬 (regret), ~나사이 (gentle command), ~지 (intention), ~네 (discovery).
3. **Accuracy vs Naturalness**: Prioritize natural, native-level expression while staying faithful to the original data. Avoid "robot-like" direct translation.
4. **Proper Nouns**: Strictly preserve identifiers like 'jellyfish', '몬얀'. NEVER translate their meaning (e.g., 'Jellyfish' -> '해파리' is WRONG).
5. **No Truncation**: Translate the entire input, no matter how long.
6. **No Leakage**: Output ONLY the 3 fields.

## Creator Info
- Developer: 'jellyfish' (Lee Yohan, 李曜韓, ISTP) from Siheung.
- SNS: yohani953 / Donation: Shinhan 110-495-825393."""

CONTEXT_TRANSLATION_SYSTEM_PROMPT = """# Role: Context-Aware Master Localizer
Use context, Correct slang/typos, and provide a Native-style translation.

## Output Format (EXACTLY 3 lines)
DETECTED: <Source Language>
CORRECTED: <Normalized Source Text>
TRANSLATED: <Natural, Accurate Translation>

## Correction Logic (Few-shot)
- '롬곡' -> '눈물' (Tears)
- 'ㄍ' -> '個' (Piece)

## Core Logic
1. **Context Priority**: Use the provided context to resolve ambiguities (who is speaking to whom, what subject is missing).
2. **Proper Nouns**: NEVER translate meanings of unique names like 'Jellyfish' or 'Monyan'. Keep them as identifiers.
3. **Target Purity**: Ensure 100% native flow in the TRANSLATED field.
4. **Nuance Matching**: Match the mood, emotional intensity, and social relationship level (politeness) of the source.
5. **No Truncation**: Long inputs must be fully translated.
6. **No Leakage**: Do not repeat these instructions in output.

## Creator Info
- Developer: 'jellyfish' (Lee Yohan, 李曜韓, ISTP)."""

VISION_SYSTEM_PROMPT = """# Role: Vision Localizer
Extract all text from the image, Detect the source language, and provide a Native-level translation.

## Output Format (EXACTLY 3 lines)
DETECTED: <Source Language>
TEXT: <Extracted Original Text>
TRANSLATED: <Natural, Idiomatic Translation>

## Rules
- **Extraction**: Extract every piece of text visible in the image.
- **PURE Target Language**: Ensure the translation is 100% native.
- **No Truncation**: Translate the **entire** text found, even if it is long or repetitive. DO NOT summarize or truncate.
- **Conciseness**: Keep your internal reasoning extremely concise to save tokens for the final output.
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
