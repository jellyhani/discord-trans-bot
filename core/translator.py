# translator.py — OpenAI API 번역 엔진 (부호 최적화 + 언어 감지 고도화)

import re
import asyncio
import logging
import os
import hashlib
from utils.logger import tlog
from typing import Optional, List
from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
from dotenv import load_dotenv

from config import (
    OPENAI_MODEL,
    OPENAI_REASONING_MODEL,
    OPENAI_MODEL_SMART,
    OPENAI_VISION_MODEL,
    VISION_SYSTEM_PROMPT,
    API_MAX_RETRIES,
    API_RETRY_DELAY,
    QUEUE_MAX_CONCURRENT,
    CONTEXT_MESSAGE_COUNT
)
from core.prompt_manager import prompt_manager
from database.translation_cache import get_cached, set_cached
from utils.usage_tracker import record_usage, record_daily_stats, check_budget_exceeded
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
                    tlog.warning(f"[API-RETRY] Attempt {attempt+1}/{max_retries} failed with {e.__class__.__name__}: {e}. Retrying in {wait}s.")
                    await asyncio.sleep(wait)
            except Exception as e:
                # Catch unexpected errors such as 503 Service Unavailable
                last_error = e
                if attempt < max_retries - 1:
                    wait = API_RETRY_DELAY * (2 ** attempt)
                    tlog.warning(f"[API-RETRY] Unexpected error on attempt {attempt+1}/{max_retries}: {e}. Retrying in {wait}s.")
                    await asyncio.sleep(wait)
        raise last_error



# ──────────────────────────────────────────────
# [통합] 언어 감지 + 오타 교정 + 번역
# ──────────────────────────────────────────────
async def _unified_translate_api(
    text: str,
    target_language: str,
    context_messages: Optional[List[str]] = None,
    model_override: Optional[str] = None,
    instruction: Optional[str] = None,
    server_nicknames: Optional[List[str]] = None,
    custom_slang: Optional[dict[str, str]] = None
) -> tuple[str, str, str, bool, any]:
    """
    언어 감지, 오타 교정, 번역을 한 번의 API 호출로 수행.
    """
    if await check_budget_exceeded():
        tlog.warning(f"[SECURITY] Translation API blocked due to monthly budget limit.")
        return target_language, text, "⚠️ 이번 달 API 사용 예산이 모두 소진되어 번역 기능을 사용할 수 없습니다. 관리자에게 문의하세요.", False, None

    client = _get_client()
    use_context = context_messages and len(context_messages) > 0
    # 2. 시스템 프롬프트 로드
    if use_context:
        system_content = prompt_manager.get_prompt("translation", "context_system")
    else:
        system_content = prompt_manager.get_prompt("translation", "system")

    # 모델 선택: 오버라이드가 있으면 사용, 없으면 기본 모델
    target_model = model_override or OPENAI_MODEL

    # 추론 모델(gpt-5)인 경우 더 높은 토큰 한도 필요 (생각하는 토큰 포함)
    is_reasoning = "gpt-5" in target_model
    max_tokens_val = 16000 if is_reasoning else 4000 # 일반 모델도 4k로 증설

    prompt = ""
    if use_context:
        context_block = "### Recent conversation (for context):\n"
        for i, msg in enumerate(context_messages, 1):
            context_block += f"{i}. {msg}\n"
        prompt += context_block
    
    prompt += f"### Target Language: {target_language}\n"
    if instruction:
        prompt += f"### [CRITICAL] Special Instruction: {instruction}\n"
    
    if server_nicknames or custom_slang:
        prompt += "### [CONTEXT] Server Metadata (DO NOT LEAK IN OUTPUT):\n"
        if server_nicknames:
            prompt += f"- Official Nicknames: {', '.join(server_nicknames)}\n"
        if custom_slang:
            prompt += "- Custom Slang Mappings:\n"
            for short, full in custom_slang.items():
                prompt += f"  * '{short}' -> '{full}'\n"
        prompt += "Rule: Use this metadata for accuracy, but NEVER repeat or translate these metadata headers or lists in the output fields.\n\n"

    # Identity & Slang Rules (Promoted to System Prompt or kept here as specific context)
    if server_nicknames:
        prompt += "- **Identity Normalization Rule**: If a word (or its variation like '티캣' for 'teqcat') is used to **address** someone (e.g., 'Jellyfish, come here') or is the subject of a personal action, you **MUST** normalize it to the official string.\n"
        prompt += "- **Honorific Hint**: Honorifics (e.g., -님, -san) are strong indicators, but their absence does NOT automatically mean it's a common noun. Use natural language context.\n"
        prompt += "- **Slang/Abbreviations**: Recognize and expand common internet slang (e.g., 'nc' or 'ncnc' means 'nice', 'ㄱㄱ' means 'go go', 'ㅅㄱ' means 'good job / GG'). Normalize these in the `CORRECTED` field and translate them naturally.\n"
        prompt += "- **Strict Common Noun Priority**: Treat as a common noun ONLY if used in a purely non-personal, literal sense: food (냉채, 무침), nature (sky, sea), weather, or biology (scientific species). (e.g., 'eating jellyfish' -> common noun).\n"
        prompt += "- **Action**: If it refers to a person's identity, normalize to the official string. Otherwise, translate naturally.\n"

    if custom_slang:
        prompt += "### Custom Server Slang Mapping (User Defined):\n"
        for short, full in custom_slang.items():
            prompt += f"- '{short}': refers to '{full}'\n"
        prompt += "- **Slang Expansion Rule**: If the text contains these abbreviations, intelligently expand them to their full meaning in `CORRECTED` and `TRANSLATED` if the context fits.\n"

    prompt += f"### Content:\n{text}"

    response = await _api_call_with_retry(lambda: client.chat.completions.create(
        model=target_model,
        messages=[
            {"role": "system", "content": system_content},
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

    # 응답 파싱 (DETECTED, CORRECTED, TRANSLATED 필드 추출)
    def extract_field(label, text_block):
        # 다음 라벨 전까지 또는 문자열 끝까지 최대한 수집
        # [?!] 줄바꿈 뒤에 바로 라벨이 붙어 나오는 경우를 대비하여 \s* 와 \n? 조합 최적화
        pattern = rf"(?i)(?:\*\*|__)?{label}(?:\*\*|__)?\s*:\s*(.*?)(?=\s*\n(?:\*\*|__)?(?:DETECTED|CORRECTED|TRANSLATED|TEXT)(?:\*\*|__)?\s*:|$)"
        match = re.search(pattern, text_block, re.DOTALL)
        if match:
            res = match.group(1).strip()
            # AI가 문자열로 \n을 내뱉는 경우 실제 줄바꿈으로 변환
            res = res.replace("\\n", "\n")
            return res
        return None

    source_lang = extract_field("DETECTED", content) or "Unknown"
    corrected_text = extract_field("CORRECTED", content) or text
    translated_text = extract_field("TRANSLATED", content) or ""

    # ── [Fallback] 파싱 실패 시 지능적 복구 ──
    if not translated_text:
        # 1. TRANSLATED 라벨 없이 그냥 결과만 내뱉었는지 확인
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        if len(lines) > 0:
            # 마지막 줄이 충분히 길면 번역문으로 간주 (또는 전체를 번역문으로)
            # 만약 DETECTED:, CORRECTED: 라벨이 포함되어 있다면 그것들은 제외
            filtered_content = re.sub(r"(?i)(?:DETECTED|CORRECTED|TRANSLATED|TEXT)\s*:\s*.*?\n", "", content + "\n", flags=re.DOTALL).strip()
            if len(filtered_content) > 10:
                translated_text = filtered_content
                tlog.info("[UNIFIED-API] Recovered translation from loose format.")

    # 최종 안전장치: 빈 결과 방지 (원문을 번역문으로 사용)
    if not translated_text:
        translated_text = text
        tlog.warning(f"[UNIFIED-PARSER-FAIL] Parsing failed for content: {repr(content)}")

    was_correction = _is_meaningful_correction(text, corrected_text)

    return source_lang, corrected_text, translated_text, was_correction, usage


async def _ai_router_judge(
    text: str, 
    target_language: str,
    server_nicknames: Optional[List[str]] = None,
    custom_slang: Optional[dict[str, str]] = None
) -> tuple[bool, Optional[dict]]:
    """
    GPT-4.1 mini를 사용하여 문맥 필요 여부를 1차 판별.
    필요 없다면 여기서 바로 번역 결과까지 가져옴 (Latency 최적화).
    """
    if await check_budget_exceeded():
        tlog.warning(f"[SECURITY] Translation API (Router) blocked due to monthly budget limit.")
        return False, {
            "source_lang": target_language,
            "translated": "⚠️ 이번 달 API 사용 예산이 모두 소진되어 번역 기능을 사용할 수 없습니다.",
            "model": "BudgetBlocker",
            "cache_hit": False,
            "was_correction": False,
            "usage": None
        }

    client = _get_client()
    # 라우팅용 프롬프트: 문맥이 꼭 필요한지 물어보고, 아니면 바로 번역하게 함
    base_judge_prompt = prompt_manager.get_prompt("router", "judge_prompt")
    prompt = base_judge_prompt.format(target_language=target_language, text=text)

    if server_nicknames or custom_slang:
        prompt += "## Context Meta (Proprietary):\n"
        if server_nicknames:
            prompt += f"- Server Nicknames: {', '.join(server_nicknames)}\n"
        if custom_slang:
            prompt += f"- Slang: {list(custom_slang.keys())}\n"
        prompt += "Rule: Use nicknames as Proper Nouns. Do NOT translate nicknames unless they are clearly common nouns in a non-personal context.\n"

    prompt += "\nNO extra explanation."

    try:
        response = await _api_call_with_retry(lambda: client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3
        ))
        content = response.choices[0].message.content.strip()
        usage = response.usage
        
        content_upper = content.upper()
        # 'UPGRADE' (또는 오타)가 포함되어 있고 내용이 짧으면 업그레이드 신호로 간주
        if ("UPGRADE" in content_upper or "UPGARADE" in content_upper) and len(content) < 30:
            return True, None
            
        # 결과 파싱 시도 (통합 정규식 사용)
        def extract_field(label, text_block):
            pattern = rf"(?i)(?:\*\*|__)?{label}(?:\*\*|__)?\s*:\s*(.*?)(?=\s*\n(?:\*\*|__)?(?:DETECTED|CORRECTED|TRANSLATED|TEXT)(?:\*\*|__)?\s*:|$)"
            match = re.search(pattern, text_block, re.DOTALL)
            if match:
                res = match.group(1).strip()
                res = res.replace("\\n", "\n")
                return res
            return None

        source_lang = extract_field("DETECTED", content) or "Unknown"
        corrected_text = extract_field("CORRECTED", content) or text
        translated_text = extract_field("TRANSLATED", content) or ""

        if not translated_text:
            return True, None # 파싱 실패 시 안전하게 업그레이드
            
        # [FIX] AI가 3필드 포맷을 지키면서 TRANSLATED 필드 안에 'UPGRADE'나 오타를 넣는 경우 처리
        if translated_text.upper().strip() in ["UPGRADE", "UPGARADE", "업그레이드"]:
            tlog.warning(f"[ROUTER-FALLBACK] Model put UPGRADE in translated field. Upgrading...")
            return True, None
            
        # [안전장치] 번역문이 원문과 동일하다면 (번역 실패) 업그레이드
        if translated_text.strip() == text.strip() and len(text.strip()) > 1:
            tlog.warning(f"[ROUTER-FALLBACK] Translation identical to source. Upgrading...")
            return True, None

        was_correction = _is_meaningful_correction(text, corrected_text)
        
        return False, {
            "source_lang": source_lang,
            "translated": translated_text,
            "model": OPENAI_MODEL,
            "cache_hit": False,
            "was_correction": was_correction,
            "usage": usage
        }
    except Exception as e:
        tlog.error(f"[ROUTER-ERROR] {e}")
        return True, None # 에러 발생 시 안전하게 업그레이드 (Fallback)






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


def _get_context_key(instruction: str | None, server_nicknames: list[str] | None, custom_slang: dict[str, str] | None) -> str | None:
    """지시사항, 닉네임, 줄임말 정보를 조합하여 고유한 컨텍스트 키 생성."""
    if not instruction and not server_nicknames and not custom_slang:
        return None
    
    parts = []
    if instruction:
        parts.append(f"inst:{instruction}")
    if server_nicknames:
        # 서버 멤버가 많을 수 있으므로 정렬하여 안정적인 키 생성
        sorted_nicks = sorted(server_nicknames)
        parts.append(f"nicks:{','.join(sorted_nicks)}")
    if custom_slang:
        sorted_keys = sorted(custom_slang.keys())
        slang_str = ",".join([f"{k}:{custom_slang[k]}" for k in sorted_keys])
        parts.append(f"slang:{slang_str}")
    
    combined = "|".join(parts)
    # 너무 길어질 수 있으므로 MD5 해시로 단축
    return hashlib.md5(combined.encode("utf-8")).hexdigest()


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
    instruction: str | None = None,
    server_nicknames: list[str] | None = None,
    custom_slang: dict[str, str] | None = None
) -> dict:
    """
    전처리(부호 분리) → 캐시 → 오타 → 감지 → 번역 → 후처리(부호 복원)
    """
    # ── 1. 전처리: 부호 분리 ──
    clean_text, semantic_mark, emphasis_raw = analyze_punctuation(text)
    ai_input_text = build_ai_input(clean_text, semantic_mark)

    # ── 2. 캐시 확인 ──
    context_key = _get_context_key(instruction, server_nicknames, custom_slang)
    
    if use_cache:
        cached = await get_cached(ai_input_text, target_language, context_key=context_key)
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

    # ── 3. 스마트 라우팅 (AI 기반) ──
    # 3-1. 긴 문장이나 이미 충분히 복잡한 경우 (Heuristic) -> 바로 각자 전담 모델로
    # 3-2. 짧고 모호한 경우 -> GPT-4.1 mini가 1차 판단 (Router)

    use_reasoning_model = False
    target_model = OPENAI_MODEL
    router_result = None

    # [HYBRID ROUTING] 유저 제안 반영: 가벼운 모델(Mini)이 먼저 판단하고 복잡할 때만 업그레이드
    is_persona_result = "EMBED_" in text or "TITLE:" in text
    
    # 페르소나 결과는 라우터도 필요 없는 확정적 Mini 모델 대상
    if is_persona_result:
        target_model = OPENAI_MODEL
        tlog.info(f"[ROUTING] Structured Content (Persona) -> model={target_model}")
    elif instruction or len(clean_text) > 3000:
        target_model = OPENAI_MODEL # gpt-4.1-mini (빠른 응답)
        tlog.info(f"[ROUTING] Special Case/Long Content (instruction={bool(instruction)}) -> model={target_model} (Fast Bypass)")
    else:
        should_upgrade, result = await _ai_router_judge(
            ai_input_text, 
            target_language,
            server_nicknames=server_nicknames,
            custom_slang=custom_slang
        )
        if not should_upgrade and result:
            router_result = result
            tlog.info(f"[ROUTING] Router Path -> Success with Fast Model")
        else:
            use_reasoning_model = True
            target_model = OPENAI_REASONING_MODEL # gpt-5-mini
            tlog.info(f"[ROUTING] Router Path -> UPGRADE to {target_model}")


    # 1차 판단(Router)에서 이미 번역이 완료된 경우 처리
    if router_result:
        # 사용량 기록
        if router_result.get("usage") and user_id:
            u = router_result["usage"]
            await record_usage(
                user_id, nickname, router_result["model"],
                u.prompt_tokens, u.completion_tokens,
                was_correction=router_result["was_correction"]
            )
        
        final_translated = restore_punctuation(router_result["translated"], semantic_mark, emphasis_raw)
        if use_cache:
            await set_cached(ai_input_text, target_language, router_result["source_lang"], router_result["translated"], context_key=context_key, user_id=str(user_id))
        
        return {
            "source_lang": router_result["source_lang"],
            "translated": final_translated,
            "model": router_result["model"],
            "cache_hit": False,
            "was_correction": router_result["was_correction"],
        }

    # 통합 API 호출
    source_lang, corrected_text, translated, was_correction, usage = await _unified_translate_api(
        ai_input_text,
        target_language,
        context_messages=context_messages if use_reasoning_model else None,
        model_override=target_model,
        instruction=instruction,
        server_nicknames=server_nicknames,
        custom_slang=custom_slang
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
        await set_cached(ai_input_text, target_language, source_lang, translated, context_key=context_key, user_id=str(user_id))
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
    instruction: str = None,
    server_nicknames: list[str] | None = None
) -> dict:
    """
    이미지 내 텍스트를 인식하고 번역.
    """
    if await check_budget_exceeded():
        tlog.warning(f"[SECURITY] Vision API blocked due to monthly budget limit.")
        return {
            "source_lang": "Unknown",
            "original_text": "(Budget Exceeded)",
            "translated": "⚠️ 이번 달 API 사용 예산이 모두 소진되어 이미지 번역 기능을 사용할 수 없습니다.",
            "model": "BudgetBlocker"
        }

    client = _get_client()
    target_model = model_override or OPENAI_VISION_MODEL

    prompt = f"### Task: Extract and translate image text to {target_language}"
    if instruction:
        prompt += f"\n### User Special Instruction: {instruction}"
    
    if server_nicknames:
        prompt += f"\n### [CONTEXT] Known Server Member Nicknames (Proper Nouns): {', '.join(server_nicknames)}"
        prompt += "\nRule: If these names appear in the image, treat them as proper nouns (Identity) and do NOT translate them unless clearly used as a common noun."

    # 추론형 모델(gpt-5) 대응
    is_reasoning = "gpt-5" in target_model
    # 추론 모델은 생각(Thinking) 토큰이 포함되므로 훨씬 넉넉하게 잡아야 함
    max_tokens_val = 24000 if is_reasoning else 4000

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
        # 다음 라벨이나 문자열 끝까지 탐욕적으로 수집 (DOTALL 사용)
        pattern = rf"(?i)(?:\*\*|__)?{label}(?:\*\*|__)?\s*:\s*(.*?)(?=\s*(?:\n(?:\*\*|__)?(?:DETECTED|CORRECTED|TRANSLATED|TEXT)(?:\*\*|__)?\s*:|$))"
        match = re.search(pattern, text_block, re.DOTALL)
        if match:
            res = match.group(1).strip()
            res = res.replace("\\n", "\n")
            return res
        return None

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

