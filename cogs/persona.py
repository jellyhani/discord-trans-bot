import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
from core.translator import _get_client
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
            
            # 1. DB에서 해당 유저의 모든 개인 데이터 수집
            from database.chat_logger import get_user_total_history, get_total_log_count
            from database.user_personas import get_user_persona, save_user_persona
            
            context_text = await get_user_total_history(user_id, max_chars=100000)
            log_count = await get_total_log_count(user_id)
            persona_data = await get_user_persona(user_id)
            
            if not context_text.strip():
                await interaction.followup.send("💬 분석할 개인 데이터가 아직 없습니다! 대화를 나눈 뒤 시도해 주세요.")
                return
            
            first_persona_val = persona_data["first_persona"] if persona_data else None
            
            # 2. 유저 언어 판단 (Locale 기반)
            user_locale = str(interaction.locale)
            user_lang = LOCALE_TO_LANG.get(user_locale, "Korean")
            
            client = _get_client()
            
            # 3. 인공지능 스타일 분석 (GPT-4.1 mini 활용)
            analysis_prompt = f"""
            # Role: Master Psychologist & Surrealist Digital Artist
            # Task: Deep Persona Analysis & Visualization (Growth & Soul)
            
            Analyze the user's essence based on context and respond in {user_lang}.
            IMPORTANT: For Traditional Chinese (Taiwan), treat it as a distinct cultural entity with its own nuances.
            
            ## Analysis Context
            - **Historical Persona**: {first_persona_val if first_persona_val else "First analysis. Create a foundation."}
            - **Recent Interaction Data**: {context_text}
            
            ## Objectives
            1. **Inner Self**: Identify emotional core, intellectual curiosity, and communicative style.
            2. **Growth Trajectory**: Contrast historical patterns with recent ones.
            3. **Aesthetic Translation**: Create a high-concept DALL-E 3 prompt that represents their soul as an abstract masterpiece.
            
            ## Response Format (Strict JSON)
            {{
                "title": "Poetic/Abstract title ({user_lang})",
                "persona_label": "Label for 'Persona' ({user_lang})",
                "persona_summary": "2-3 profound sentences analyzing their identity and tone ({user_lang})",
                "growth_label": "Label for 'Evolution' ({user_lang})",
                "growth_report": "How they have evolved or stayed consistent ({user_lang})",
                "interest_label": "Label for 'Core Sparks' ({user_lang})",
                "intellectual_curiosity": "Their recent intellectual/emotional fascinations ({user_lang})",
                "footer": "Meaningful footer referencing {log_count} data points ({user_lang})",
                "dalle_prompt": "Sophisticated English description for DALL-E 3. Focus on artistic styles (e.g., Cybernetic Surrealism, Ethereal Impressionism, Bio-mechanical Abstract). DO NOT use text in the image. Use complex lighting and metaphorical objects."
            }}
            """
            
            from config import OPENAI_MODEL
            analysis_resp = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": analysis_prompt}],
                response_format={"type": "json_object"},
                max_tokens=1000
            )
            
            analysis_data = json.loads(analysis_resp.choices[0].message.content)
            
            # 4. 분석 결과 저장 (DB)
            await save_user_persona(user_id, analysis_data['persona_summary'])
            bot_log.info(f"[PERSONA-DRAW] Analysis: {analysis_data}")

            # 4. 이미지 생성 (DALL-E 3)
            image_resp = await client.images.generate(
                model="dall-e-3",
                prompt=analysis_data["dalle_prompt"],
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
            embed.set_footer(text=f"{analysis_data.get('footer', f'Data: {log_count}')} | Model: GPT-4.1 & DALL-E 3")
            
            response_msg = "🎨 Your personalized persona visualization is ready." if user_lang != "Korean" else f"🎨 **{interaction.user.display_name}**님, 당신의 진화된 존재감을 시각화한 결과입니다."
            await interaction.followup.send(content=response_msg, embed=embed)
            
        except Exception as e:
            bot_log.error(f"[PERSONA-DRAW-ERROR] {e}")
            try:
                await interaction.followup.send(f"⚠️ 정밀 분석 중 오류가 발생했습니다: {str(e)}")
            except:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(PersonaCog(bot))
