# translator.py — OpenAI API 번역 엔진 (부호 최적화 + 언어 감지 고도화)

import re
import asyncio
import logging
import os
from utils.logger import tlog
from typing import Optional, List
from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
from dotenv import load_dotenv

from config import (
    OPENAI_MODEL,
    OPENAI_REASONING_MODEL,
    OPENAI_MODEL_SMART,
    TRANSLATION_SYSTEM_PROMPT,
    CONTEXT_TRANSLATION_SYSTEM_PROMPT,
    OPENAI_VISION_MODEL,
    VISION_SYSTEM_PROMPT,
    API_MAX_RETRIES,
    API_RETRY_DELAY,
    QUEUE_MAX_CONCURRENT,
    CONTEXT_MESSAGE_COUNT
)
from database.translation_cache import get_cached, set_cached
from utils.usage_tracker import record_usage, record_daily_stats
from core.typo_detector import looks_like_typo
from core.punctuation_handler import analyze_punctuation, build_ai_input, restore_punctuation





# ──────────────────────────────────────────────
# OpenAI 클라이언트
# ──────────────────────────────────────────────
_client: AsyncOpenAI | None = None
_api_semaphore: asyncio.Semaphore | None = None


def configure_openai(api_key: str):
    global _client, _api_semaphore
    _client = AsyncOpenAI(api_key=api_key)
    # Semaphore는 호출 시점에 루프가 있어야 하므로, 여기서 생성하거나 실행 시점에 확인
    try:
        asyncio.get_running_loop()
        _api_semaphore = asyncio.Semaphore(QUEUE_MAX_CONCURRENT)
    except RuntimeError:
        _api_semaphore = None


def _get_semaphore() -> asyncio.Semaphore:
    global _api_semaphore
    if _api_semaphore is None:
        _api_semaphore = asyncio.Semaphore(QUEUE_MAX_CONCURRENT)
    return _api_semaphore


def _get_client() -> AsyncOpenAI:
    if _client is None:
        raise RuntimeError("OpenAI API가 초기화되지 않았습니다.")
    return _client


# ──────────────────────────────────────────────
# API 호출 재시도 + 큐잉 래퍼
# ──────────────────────────────────────────────
async def _api_call_with_retry(coro_factory, max_retries: int = API_MAX_RETRIES):
    sem = _get_semaphore()
    async with sem:
        last_error = None
        for attempt in range(max_retries):
            try:
                return await coro_factory()
            except (APITimeoutError, APIError, RateLimitError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = API_RETRY_DELAY * (2 ** attempt)
                    await asyncio.sleep(wait)
        raise last_error



# ──────────────────────────────────────────────
# [통합] 언어 감지 + 오타 교정 + 번역
# ──────────────────────────────────────────────
async def _unified_translate_api(
    text: str,
    target_language: str,
    context_messages: Optional[List[str]] = None,
    model_override: Optional[str] = None
) -> tuple[str, str, str, bool, any]:
    """
    언어 감지, 오타 교정, 번역을 한 번의 API 호출로 수행.
    """
    client = _get_client()
    use_context = context_messages and len(context_messages) > 0
    system_prompt = CONTEXT_TRANSLATION_SYSTEM_PROMPT if use_context else TRANSLATION_SYSTEM_PROMPT

    # 모델 선택: 오버라이드가 있으면 사용, 없으면 기본 모델
    target_model = model_override or OPENAI_MODEL

    # 추론 모델(gpt-5)인 경우 더 높은 토큰 한도 필요 (생각하는 토큰 포함)
    is_reasoning = "gpt-5" in target_model
    max_tokens_val = 4000 if is_reasoning else 800

    if use_context:
        context_block = "### Recent conversation (for context):\n"
        for i, msg in enumerate(context_messages, 1):
            context_block += f"{i}. {msg}\n"
        prompt = f"{context_block}\n### Task: Translate the following to {target_language}\n### Content:\n{text}"
    else:
        prompt = f"### Task: Translate the following to {target_language}\n### Content:\n{text}"

    response = await _api_call_with_retry(lambda: client.chat.completions.create(
        model=target_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        **( {"max_completion_tokens": max_tokens_val} if is_reasoning else {"max_tokens": max_tokens_val} ),
        **({"temperature": 0.3} if not is_reasoning else {})
    ))

    usage = response.usage
    choice = response.choices[0]
    content = choice.message.content.strip() if choice.message.content else ""
    # 로그Snippet을 500자로 늘려 전체 파싱 결과 확인
    tlog.info(f"[UNIFIED-API] model={response.model} | in={usage.prompt_tokens} out={usage.completion_tokens} | result={repr(content[:500])}")

    # 응답 파싱 (3개 라인: DETECTED, CORRECTED, TRANSLATED)
    # 정규표현식을 사용하여 더 유연하게 파싱 (볼드체나 공백 대응)
    def extract_field(label, text_block):
        pattern = rf"(?i)(?:\*\*|__)?{label}(?:\*\*|__)?\s*:\s*(.*)"
        match = re.search(pattern, text_block)
        return match.group(1).strip() if match else None

    source_lang = extract_field("DETECTED", content) or "Unknown"
    corrected_text = extract_field("CORRECTED", content) or text
    translated_text = extract_field("TRANSLATED", content) or ""

    # 만약 파싱에 실패했다면 (라인 형식이 완전히 틀린 경우) 줄 단위로 시도
    if not translated_text:
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        if len(lines) >= 3:
            translated_text = lines[2].split(":", 1)[-1].strip() if ":" in lines[2] else lines[2]
        elif len(lines) >= 1:
            translated_text = lines[-1].split(":", 1)[-1].strip() if ":" in lines[-1] else lines[-1]

    # 최종 안전장치: 빈 결과 방지 (원문을 번역문으로 사용)
    if not translated_text:
        translated_text = text
        tlog.warning(f"[UNIFIED-PARSER-FAIL] Parsing failed for content: {repr(content)}")

    was_correction = _is_meaningful_correction(text, corrected_text)

    return source_lang, corrected_text, translated_text, was_correction, usage



# ──────────────────────────────────────────────
# 오타 교정
# ──────────────────────────────────────────────
def _is_meaningful_correction(original: str, corrected: str) -> bool:
    if original == corrected:
        return False

    def normalize(s: str) -> str:
        s = re.sub(r'[\s.,!?;:~…·\-_\'\"(){}[\]<>@#$%^&*+=|/\\]', '', s)
        return s.lower()

    return normalize(original) != normalize(corrected)


# Redundant functions removed: _correct_typos_smart is now part of _unified_translate_api.


# ──────────────────────────────────────────────
# 번역
# ──────────────────────────────────────────────
# translate and translate_with_context are now integrated into _unified_translate_api.



# ──────────────────────────────────────────────
# 문맥 필요 여부
# ──────────────────────────────────────────────
def _needs_context(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) <= 15:
        return True
    words = stripped.split()
    if len(words) <= 3:
        return True
    return False


def _is_complex_text(text: str) -> bool:
    """말장난이나 복잡한 구조를 가진 텍스트인지 판단."""
    if len(text) < 5:
        return False
        
    # 1. 단어 반복 체크
    words = text.split()
    if len(words) > 2:
        unique_words = set(words)
        if len(unique_words) / len(words) < 0.7:
            return True
            
    # 2. 글자 반복 체크 (간장공장공장장 등 공백 없는 경우 대비)
    char_counts = {}
    for c in text:
        if c.strip():
            char_counts[c] = char_counts.get(c, 0) + 1
    
    if char_counts:
        max_freq = max(char_counts.values())
        # 글자 수 대비 특정 글자가 20% 이상 (강력한 말장난 패턴)
        if max_freq >= 4 and max_freq / len(text) > 0.2:
            return True
            
    # 3. 고성능 모델 명시적 필요 키워드
    high_performance_hints = ['초월번역', '의역', '말장난', '고난도', '발음', '현지화']
    if any(hint in text for hint in high_performance_hints):
        return True
        
    return False


# ──────────────────────────────────────────────
# 메인 파이프라인
# ──────────────────────────────────────────────
async def detect_and_translate(
    text: str,
    target_language: str,
    user_id: int = 0,
    nickname: str = "",
    use_cache: bool = True,
    context_messages: list[str] | None = None,
) -> dict:
    """
    전처리(부호 분리) → 캐시 → 오타 → 감지 → 번역 → 후처리(부호 복원)
    """
    # ── 1. 전처리: 부호 분리 ──
    clean_text, semantic_mark, emphasis_raw = analyze_punctuation(text)
    ai_input_text = build_ai_input(clean_text, semantic_mark)

    # ── 2. 캐시 확인 ──
    if use_cache:
        cached = await get_cached(ai_input_text, target_language)
        if cached:
            restored = restore_punctuation(cached["translated"], semantic_mark, emphasis_raw)
            tlog.info(f"[CACHE-HIT] \"{clean_text[:30]}\" → {target_language}")
            return {
                "source_lang": cached["source_lang"],
                "translated": restored,
                "model": "Cache",
                "cache_hit": True,
                "was_correction": False,
            }

    # ── 3. 하이브리드 모델 선택 ──
    # 기본적으로 비용이 저렴하고 빠른 gpt-4.1-mini를 사용합니다.
    # 문맥 파악이 매우 중요한 경우에만 gpt-5-mini(추론형)를 선택합니다.
    
    use_reasoning_model = False
    reason = "simple"
    
    if context_messages and _needs_context(clean_text):
        use_reasoning_model = True
        reason = "context"
    elif _is_complex_text(clean_text):
        use_reasoning_model = True
        reason = "complexity"
        
    # 기본 성능이 충분하므로 슬랭/오타/긴 문장도 4.1-mini가 처리
    # 말장난이나 고난도 텍스트는 플래그십 gpt-5(smart)를 사용하여 품질 극대화
    if reason == "complexity":
        target_model = OPENAI_MODEL_SMART
    elif reason == "context":
        target_model = OPENAI_REASONING_MODEL
    else:
        target_model = OPENAI_MODEL

    tlog.info(f"[MODEL-SELECT] choice={target_model} | reason={reason} | text={repr(clean_text[:60])}")

    # 통합 API 호출
    source_lang, corrected_text, translated, was_correction, usage = await _unified_translate_api(
        ai_input_text,
        target_language,
        context_messages=context_messages if use_reasoning_model else None,
        model_override=target_model
    )

    # ── 4. 사용량 기록 ──
    if usage and user_id:
        await record_usage(
            user_id, nickname, target_model,
            usage.prompt_tokens, usage.completion_tokens,
            was_correction=was_correction
        )

    # ── 5. 후처리: 강조 부호 복원 ──
    final_translated = restore_punctuation(translated, semantic_mark, emphasis_raw)

    # ── 6. 캐시 저장 ──
    if use_cache:
        await set_cached(ai_input_text, target_language, source_lang, translated)
    return {
        "source_lang": source_lang,
        "translated": final_translated,
        "model": target_model,
        "cache_hit": False,
        "was_correction": was_correction,
    }


async def translate_image(
    image_url: str,
    target_language: str,
    user_id: int = 0,
    nickname: str = "",
    model_override: str = None,
    instruction: str = None
) -> dict:
    """
    이미지 내 텍스트를 인식하고 번역.
    """
    client = _get_client()
    target_model = model_override or OPENAI_VISION_MODEL

    prompt = f"### Task: Extract and translate image text to {target_language}"
    if instruction:
        prompt += f"\n### User Special Instruction: {instruction}"

    # 추론형 모델(gpt-5) 대응
    is_reasoning = "gpt-5" in target_model
    max_tokens_val = 4000 if is_reasoning else 1000

    response = await _api_call_with_retry(lambda: client.chat.completions.create(
        model=target_model,
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    }
                ]
            },
        ],
        **( {"max_completion_tokens": max_tokens_val} if is_reasoning else {"max_tokens": max_tokens_val} ),
        **({"temperature": 0.3} if not is_reasoning else {})
    ))

    usage = response.usage
    content = response.choices[0].message.content.strip()
    tlog.info(f"[VISION-API] model={response.model} | in={usage.prompt_tokens} out={usage.completion_tokens}")

    # 응답 파싱
    def extract_field(label, text_block):
        pattern = rf"(?i)(?:\*\*|__)?{label}(?:\*\*|__)?\s*:\s*(.*)"
        match = re.search(pattern, text_block)
        return match.group(1).strip() if match else None

    source_lang = extract_field("DETECTED", content) or "Unknown"
    original_text = extract_field("TEXT", content) or "(No text extracted)"
    translated = extract_field("TRANSLATED", content) or ""

    if not translated:
        # 줄 단위 파싱 시도
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        if len(lines) >= 3:
            translated = lines[2].split(":", 1)[-1].strip() if ":" in lines[2] else lines[2]
        elif len(lines) >= 1:
            translated = lines[-1].split(":", 1)[-1].strip() if ":" in lines[-1] else lines[-1]

    # 사용량 기록
    if usage and user_id:
        await record_usage(
            user_id, nickname, target_model,
            usage.prompt_tokens, usage.completion_tokens
        )

    return {
        "source_lang": source_lang,
        "original_text": original_text,
        "translated": translated or "(Translation failed)",
        "model": target_model
    }

