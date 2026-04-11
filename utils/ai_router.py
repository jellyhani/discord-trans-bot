from config import MENTOR_REASONING_MODEL, MENTOR_ANSWER_MODEL, OPENAI_MODEL_SMART, OPENAI_MODEL
from core.prompt_manager import prompt_manager

async def get_model_route(client, prompt: str, has_image: bool = False):
    """
    Classifies the prompt and returns (reasoner, answerer, is_smart).
    """
    # [NEW] 이미지가 포함된 경우 최소 Standard(5-mini) 이상으로 라우팅 유도
    # 이미지 분석은 단순 채팅보다 복잡하므로 mini(4.1)보다는 5세대를 권장

    system_prompt = prompt_manager.get_prompt("router", "system")

    try:
        # [FIX] 추후 모델 변경 대비 호환성 유지
        is_reasoning = "gpt-5" in "gpt-4o-mini" or "o1" in "gpt-4o-mini"
        route_resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Request: {prompt}"}
            ],
            **( {"max_completion_tokens": 20} if is_reasoning else {"max_tokens": 20} )
        )
        raw_decision = route_resp.choices[0].message.content.strip()
        
        # 형식: route|lang
        if "|" in raw_decision:
            route_decision, lang_code = raw_decision.split("|", 1)
            route_decision = route_decision.lower().strip()
            lang_code = lang_code.strip().lower()
        else:
            route_decision = raw_decision.lower().strip()
            lang_code = "ko" # 기본값

        if "flagship" in route_decision:
            return OPENAI_MODEL_SMART, OPENAI_MODEL_SMART, True, lang_code
        elif "standard" in route_decision or has_image: # [FIX] Image always needs standard or above
            return MENTOR_REASONING_MODEL, MENTOR_ANSWER_MODEL, True, lang_code
        else:
            # Baseline (4.1-mini)
            return OPENAI_MODEL, OPENAI_MODEL, False, lang_code
    except Exception:
        # Fallback to defaults
        return MENTOR_REASONING_MODEL, MENTOR_ANSWER_MODEL, False, "ko"
