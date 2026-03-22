import json
from config import MENTOR_REASONING_MODEL, MENTOR_ANSWER_MODEL, OPENAI_MODEL_SMART

async def get_model_route(client, prompt: str):
    """
    Classifies the prompt and returns (reasoner, answerer).
    """
    classifier_prompt = f"""Task: Route the following user request to either 'flagship' or 'mini'.
Request: "{prompt}"

Use 'flagship' if:
- Requires searching for multiple sources or complex news/stock analysis.
- Involves complex logic, math, or deep reasoning.
- Specifically asks for 'high intelligence' or deep research.
- Request for a scheduled routine execution.
Otherwise, use 'mini'.
Output only 'flagship' or 'mini'."""

    try:
        route_resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": classifier_prompt}],
            max_tokens=10
        )
        route_decision = route_resp.choices[0].message.content.strip().lower()
        
        if "flagship" in route_decision:
            return OPENAI_MODEL_SMART, OPENAI_MODEL_SMART, True
        else:
            return MENTOR_REASONING_MODEL, MENTOR_ANSWER_MODEL, False
    except Exception:
        # Fallback to defaults
        return MENTOR_REASONING_MODEL, MENTOR_ANSWER_MODEL, False
