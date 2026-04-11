import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from core.prompt_manager import prompt_manager
from utils.logger import bot_log
from database.chat_logger import record_chat_log, get_chat_logs, get_all_cache_texts

# 디스코드 Locale -> 언어 이름 매핑
LOCALE_TO_LANG = {
    "ko": "Korean",
    "en-US": "English",
    "en-GB": "English",
    "ja": "Japanese",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Traditional Chinese (Taiwan)",
    "fr": "French",
    "de": "German",
    "es-ES": "Spanish",
    "it": "Italian",
    "pt-BR": "Portuguese",
    "ru": "Russian",
    "vi": "Vietnamese",
    "th": "Thai",
    "tr": "Turkish",
}

class PersonaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="draw-me", description="Analyze chat history to visualize your persona and explain the reasoning.")
    async def cmd_draw_me(self, interaction: discord.Interaction):
        """
        [고급 분석 모드] 모든 데이터를 분석하여 유저의 '페르소나'를 요약하고 이미지를 생성합니다.
        """
        await interaction.response.defer(thinking=True)
        
        try:
            user_id = interaction.user.id
            nickname = interaction.user.display_name
            
            # 1. DB에서 해당 유저의 모든 개인 데이터 수집
            from database.chat_logger import get_user_total_history, get_total_log_count
            from database.user_personas import get_user_persona, save_user_persona
            
            context_text = await get_user_total_history(user_id, max_chars=200000)
            log_count = await get_total_log_count(user_id)
            # 2. 페르소나 및 지시사항 데이터 가져오기 (문맥 파악 및 아바타 적용)
            persona_data = await get_user_persona(user_id)
            first_persona_val = persona_data["first_persona"] if persona_data else None
            user_specific_instruction = persona_data["mentor_instruction"] if persona_data else None
            
            # 3. 유저 언어 판단 (디스코드 로컬 언어 기반)
            user_locale = str(interaction.locale)
            user_lang = LOCALE_TO_LANG.get(user_locale, "Korean")
            
            # API 클라이언트 및 설정 로드
            from core.translator import _get_client
            from config import OPENAI_MODEL_SMART, OPENAI_MODEL # 하단 푸터용 추가 임포트
            client = _get_client()
            
            # --- [DYNAMISM UPGRADE] ---
            import random
            lenses = ["Emotional Tone & Mood", "Social Proactivity & Networking", "Intellectual Curiosity & Interests", "Unique Linguistic Habits", "Creative Metaphors & Humor"]
            chosen_lens = random.choice(lenses)
            
            # 2. 최근 채팅 하이라이트 (일반 채팅만 포함)
            from database.chat_logger import get_chat_logs
            recent_logs = await get_chat_logs(user_id, limit=50)
            recent_context = "\n".join([f"- {l['content']}" for l in recent_logs])
            
            # [수정] 파이썬 3.11 호환성을 위해 f-string 내부 백슬래시 제거
            avatar_rules = f"## MANDATORY USER CHARACTERIZATION (AVATAR RULES):\n{user_specific_instruction}\n" if user_specific_instruction else ""
            
            # [OPTIMIZE] 10만 자는 토큰 한계(약 3만+)에 근접하여 에러 가능성 있음 -> 4만 자(약 1만 토큰)로 조정
            full_context_text = context_text[:40000]
            
            base_analysis_prompt = prompt_manager.get_prompt("persona", "analysis_prompt")
            analysis_prompt = base_analysis_prompt.format(
                user_lang=user_lang,
                historical_persona=first_persona_val if first_persona_val else "None (Initial Analysis)",
                recent_context=recent_context,
                full_context=full_context_text,
                avatar_rules=avatar_rules,
                focus_lens=chosen_lens
            )
            # DALL-E 규칙 주입
            analysis_prompt += f"\n\n{avatar_rules}\nStated Avatar Rule: {user_specific_instruction if user_specific_instruction else 'Purely artistic'}"
            
            # [FIX] 추론 모델의 경우 response_format 지원 여부가 불투명하므로 수동 파싱 강화
            is_reasoning = any(x in OPENAI_MODEL_SMART for x in ["gpt-5", "o1", "o3"])
            api_kwargs = {
                "model": OPENAI_MODEL_SMART,
                "messages": [{"role": "user", "content": analysis_prompt}],
                **({"max_completion_tokens": 8000} if is_reasoning else {"max_tokens": 4000}), # 추론 토큰 확보를 위해 8천으로 상향
                **({"temperature": 0.85} if not is_reasoning else {})
            }
            if not is_reasoning:
                api_kwargs["response_format"] = {"type": "json_object"}

            bot_log.info(f"[PERSONA-TRACE] Prompt Length: {len(analysis_prompt)} chars | reasoning: {is_reasoning}")
            
            analysis_resp = await client.chat.completions.create(**api_kwargs)
            choice = analysis_resp.choices[0]
            raw_content = choice.message.content.strip() if choice.message.content else ""
            finish_reason = getattr(choice, 'finish_reason', 'unknown')
            
            bot_log.info(f"[PERSONA-TRACE] Finish Reason: {finish_reason} | Content empty: {not raw_content}")

            if not raw_content:
                raise ValueError(f"AI가 빈 응답을 반환했습니다. (사유: {finish_reason})")
            
            try:
                # JSON 블록 추출 시도
                import re
                json_match = re.search(r"(\{.*\})", raw_content, re.DOTALL)
                if json_match:
                    clean_json = json_match.group(1)
                    analysis_data = json.loads(clean_json)
                else:
                    analysis_data = json.loads(raw_content)
            except Exception as json_err:
                bot_log.error(f"[PERSONA-JSON-ERROR] Failed to parse: {repr(raw_content[:500])}")
                raise ValueError(f"JSON 파싱 실패 (사유: {finish_reason}, 내용 일부: {raw_content[:50]}...)") from json_err
            
            # 4. 분석 결과 저장 (DB)
            await save_user_persona(user_id, analysis_data.get('persona_summary', 'Analysis failed.'))
            bot_log.info(f"[PERSONA-DRAW] Analysis success for {user_id}")

            # 5. 이미지 생성 (DALL-E 3)
            dalle_prompt = analysis_data.get("dalle_prompt")
            if not dalle_prompt:
                raise ValueError("DALL-E 프롬프트가 생성되지 않았습니다.")

            bot_log.info(f"[PERSONA-DALLE] Generated Prompt: {dalle_prompt}")

            image_resp = await client.images.generate(
                model="dall-e-3",
                prompt=dalle_prompt,
                size="1024x1024",
                quality="hd"
            )
            
            image_url = image_resp.data[0].url
            
            # 5. 결과 전송 (분석 내용 포함)
            embed = discord.Embed(
                title=f"🌌 {analysis_data.get('title', 'Persona Report')}",
                description=(
                    f"**{analysis_data.get('persona_label', 'Persona')}**\n> {analysis_data['persona_summary']}\n\n"
                    f"**{analysis_data.get('growth_label', 'Growth')}**\n> {analysis_data['growth_report']}\n\n"
                    f"**{analysis_data.get('interest_label', 'Interests')}**\n> {analysis_data['intellectual_curiosity']}"
                ),
                color=0x6C5CE7 # 세련된 보라색
            )
            embed.set_image(url=image_url)
            embed.set_footer(text=f"{analysis_data.get('footer', f'Data: {log_count}')} | Power: {OPENAI_MODEL_SMART} & DALL-E 3")
            
            # 6. 결과 전송 (AI가 생성한 언어별 안내문 사용)
            response_msg = f"🎨 {analysis_data.get('status_message', 'Your transformation is complete.')}"
            await interaction.followup.send(content=response_msg, embed=embed)
            
        except Exception as e:
            bot_log.error(f"[PERSONA-DRAW-ERROR] {e}")
            try:
                await interaction.followup.send(f"⚠️ 정밀 분석 중 오류가 발생했습니다: {str(e)}")
            except:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(PersonaCog(bot))
