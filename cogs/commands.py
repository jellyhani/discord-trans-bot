# cogs/commands.py — 유저용 슬래시 명령어

import discord
from discord import app_commands
from discord.ext import commands

from config import SUPPORTED_LANGUAGES
from core.translator import detect_and_translate
from database.user_settings import get_user_lang, set_user_pref, get_auto_translate
from utils.usage_tracker import record_cache_hit, get_user_usage


class CommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="translate", description="Translate text to your preferred language.")
    async def cmd_translate(self, interaction: discord.Interaction, text: str, language: str | None = None):
        target_lang = language or get_user_lang(interaction.user.id)
        await interaction.response.defer()
        try:
            result = await detect_and_translate(
                text, target_lang,
                user_id=interaction.user.id, nickname=interaction.user.display_name,
            )
            if result.get("cache_hit"):
                await record_cache_hit(interaction.user.id, interaction.user.display_name)

            cache_tag = " · 📦캐시" if result.get("cache_hit") else ""
            embed = discord.Embed(color=0x5865F2)
            embed.add_field(name=f"📝 원문 ({result['source_lang']})", value=text[:1000], inline=False)
            embed.add_field(name=f"🌐 번역 ({target_lang})", value=result["translated"][:1000], inline=False)
            embed.set_footer(
                text=f"요청: {interaction.user.display_name}{cache_tag}",
                icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            )
            await interaction.followup.send(embed=embed)
        except Exception:
            await interaction.followup.send(
                embed=discord.Embed(description="⚠️ 번역 중 오류가 발생했습니다.", color=discord.Color.orange()),
                ephemeral=False,
            )

    @app_commands.command(name="status", description="Check your current settings and translation usage.")
    async def cmd_status(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        lang = get_user_lang(user_id)
        auto = "켜짐" if get_auto_translate(user_id) else "꺼짐"
        
        data = await get_user_usage(user_id)
        
        embed = discord.Embed(title=f"🙋‍♂️ {interaction.user.display_name} 상태 보고서", color=0x5865F2)
        embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        
        # 설정 정보
        embed.add_field(name="📍 설정 언어", value=f"**{lang}**", inline=True)
        embed.add_field(name="🔄 자동 번역", value=auto, inline=True)
        
        # 사용량 정보
        if data:
            s = data["stats"]
            embed.add_field(name="📊 총 호출", value=f"{s['total_calls']}회", inline=True)
            embed.add_field(name="📦 캐시 히트", value=f"{s['cache_hits']}회", inline=True)
            embed.add_field(name="💰 누적 비용", value=f"${data['total_cost_usd']:.4f}", inline=True)
            
            # 토큰 상세 (In/Out 합산)
            tot_mini = s['mini_input_tokens'] + s['mini_output_tokens']
            tot_smart = s['smart_input_tokens'] + s['smart_output_tokens']
            embed.add_field(name="📝 사용 토큰", value=f"번역: {tot_mini:,} / 교정: {tot_smart:,}", inline=False)
        else:
            embed.add_field(name="📊 사용량", value="사용 기록이 없습니다.", inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="languages", description="View the list of supported translation languages.")
    async def cmd_languages(self, interaction: discord.Interaction):
        langs = ", ".join(SUPPORTED_LANGUAGES)
        await interaction.response.send_message(f"🌐 **지원 언어 안내**\n```{langs}```", ephemeral=True)

    @cmd_translate.autocomplete("language")
    async def lang_auto(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=l, value=l)
            for l in SUPPORTED_LANGUAGES if current.lower() in l.lower()
        ][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(CommandsCog(bot))
