# cogs/admin.py — 관리자용 슬래시 명령어

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from database.translation_cache import clear_all as cache_clear, get_stats as cache_stats
from database.dictionary_manager import (
    add_typo_word, remove_typo_word,
    add_abbreviation, remove_abbreviation,
    add_ending, remove_ending,
    get_typo_words, get_abbreviations, get_suspicious_endings,
)
from database.user_settings import (
    set_server_config, set_role_lang, remove_role_lang, get_all_role_langs,
    set_channel_config, remove_channel_config, get_channel_config,
    get_role_lang, set_user_pref,
    get_vision_settings, set_vision_settings, get_all_user_settings,
    get_server_config
)
from utils.usage_tracker import (
    get_global_usage, get_correction_efficiency, get_daily_stats, 
    get_all_user_usage_stats, get_monthly_usage
)
from utils.chart_generator import generate_usage_chart, generate_cost_chart, generate_efficiency_chart
from utils.logger import bot_log
from config import MONTHLY_COST_LIMIT



class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setlang", description="Set translation language for a member or role (Admin)")
    @app_commands.describe(language="Language to set", member="Member to set", role="Role to set")
    async def cmd_set_lang(
        self,
        interaction: discord.Interaction,
        language: str,
        member: discord.Member | None = None,
        role: discord.Role | None = None
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        from config import SUPPORTED_LANGUAGES
        matched = next((l for l in SUPPORTED_LANGUAGES if l.lower() == language.lower()), None)
        if not matched:
            await interaction.response.send_message(f"❌ 지원하지 않는 언어입니다.", ephemeral=True)
            return

        if role:
            await set_role_lang(interaction.guild.id, role.id, matched)
            await interaction.response.send_message(f"✅ 역할 **{role.name}** → **{matched}**로 설정되었습니다.", ephemeral=True)
        elif member:
            await set_user_pref(member.id, lang=matched, auto=True)
            await interaction.response.send_message(f"✅ 멤버 **{member.display_name}** → **{matched}**로 설정되었습니다. (자동번역 켜짐)", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 멤버 또는 역할을 지정해주세요.", ephemeral=True)

    @app_commands.command(name="userlist", description="List all user and role language settings (Admin)")
    async def cmd_user_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        user_settings = get_all_user_settings()
        role_settings = get_all_role_langs()
        
        lines = []
        if role_settings:
            lines.append("👥 **역할 설정**")
            for r_id, lang in role_settings.items():
                r = interaction.guild.get_role(r_id)
                r_name = r.name if r else f"(삭제됨 {r_id})"
                lines.append(f"• {r_name} → {lang}")
            lines.append("")

        if user_settings:
            lines.append("👤 **유저 설정**")
            for u_id, config in user_settings.items():
                # 멤버 객체 가져오기 (캐시 우선)
                m = interaction.guild.get_member(int(u_id))
                m_name = m.display_name if m else f"Unknown({u_id})"
                auto_str = " (자동)" if config.get("auto") else " (수동)"
                lines.append(f"• {m_name} → {config['lang']}{auto_str}")
        
        if not lines:
            await interaction.response.send_message("📋 설정된 데이터가 없습니다.", ephemeral=True)
            return

        # 메시지 길이 제한 (2000자) 대응
        full_text = "\n".join(lines)
        if len(full_text) > 1900:
            full_text = full_text[:1850] + "\n... (중략)"

        embed = discord.Embed(title="📋 서버 언어 설정 목록", description=full_text, color=0x3498DB)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="serverstats", description="View server statistics and usage rankings (Admin)")
    @app_commands.describe(chart="Whether to include visual charts")
    @app_commands.choices(chart=[
        app_commands.Choice(name="None", value="none"),
        app_commands.Choice(name="Usage Chart", value="usage"),
        app_commands.Choice(name="Cost Chart", value="cost"),
        app_commands.Choice(name="All Charts", value="all"),
    ])
    async def cmd_server_stats(self, interaction: discord.Interaction, chart: str = "none"):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        g = await get_global_usage()
        top_users = await get_all_user_usage_stats(limit=10)
        monthly_cost = await get_monthly_usage()
        
        embed = discord.Embed(title="📊 서버 번역 통계 보고서", color=0x2ECC71)
        
        # 1. 요약 정보
        s = g["stats"]
        summary = (
            f"👤 활성 유저: {g['user_count']}명\n"
            f"📞 총 호출: {s['total_calls']:,}회\n"
            f"📦 캐시 히트: {s['cache_hits']:,}회\n"
            f"💰 누적 비용: **${g['total_cost_usd']:.4f}**\n"
            f"📅 이달 사용: **${monthly_cost:.4f}** / **${MONTHLY_COST_LIMIT}**"
        )
        embed.add_field(name="🔹 요약", value=summary, inline=False)

        # 예산 경고 (80% 초과 시)
        if monthly_cost >= MONTHLY_COST_LIMIT * 0.8:
            warning_lvl = "🛑 위험" if monthly_cost >= MONTHLY_COST_LIMIT else "⚠️ 주의"
            embed.add_field(name=f"{warning_lvl} 예산 알림", value=f"설정된 월 예산(${MONTHLY_COST_LIMIT})의 {monthly_cost/MONTHLY_COST_LIMIT*100:.1f}%를 사용 중입니다.", inline=False)
        
        # 2. 유저별 순위 (Top 10)
        if top_users:
            rank_lines = []
            for i, u in enumerate(top_users, 1):
                rank_lines.append(f"`{i:2d}.` **{u['nickname']}**: {u['total_calls']}회 / ${u['total_cost_usd']:.3f}")
            embed.add_field(name="🏆 유저별 사용량 순위 (Top 10)", value="\n".join(rank_lines), inline=False)

        # 3. 차트 생성
        files = []
        if chart != "none":
            stats = await get_daily_stats(14)
            if chart in ("usage", "all"):
                files.append(discord.File(generate_usage_chart(stats), filename="usage.png"))
            if chart in ("cost", "all"):
                files.append(discord.File(generate_cost_chart(stats), filename="cost.png"))
            if files:
                embed.set_image(url=f"attachment://{files[0].filename}")

        await interaction.followup.send(embed=embed, files=files, ephemeral=True)

    # ── 히스토리 관리 그룹 (통합) ──
    history_group = app_commands.Group(name="history", description="번역 캐시 및 채팅 로그 통합 관리 (관리자)")

    @history_group.command(name="stats", description="Check database storage statistics.")
    async def history_stats(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        from database.chat_logger import get_total_log_count
        from database.translation_cache import get_stats as get_cache_stats
        
        cache_stats = await get_cache_stats()
        # 전체 채팅 로그 개수 (서버 전체)
        from database.database import get_history_db
        h_db = get_history_db()
        async with h_db.execute("SELECT COUNT(*) FROM chat_logs") as cursor:
            total_logs = (await cursor.fetchone())[0]

        embed = discord.Embed(title="📜 통합 히스토리 저장 통계", color=0x9B59B6)
        embed.add_field(name="📦 번역 캐시 (bot.db)", value=f"총 `{cache_stats['total_entries']:,}`건", inline=True)
        embed.add_field(name="📝 채팅 로그 (history.db)", value=f"총 `{total_logs:,}`건", inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @history_group.command(name="clear", description="Clear stored data.")
    @app_commands.describe(target="Data to delete")
    @app_commands.choices(target=[
        app_commands.Choice(name="Clear translation cache (bot.db)", value="cache"),
        app_commands.Choice(name="Clear chat logs (history.db)", value="logs"),
        app_commands.Choice(name="Reset everything (DANGER!!)", value="all"),
    ])
    async def history_clear(self, interaction: discord.Interaction, target: str):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        msg = "🗑️ 삭제 완료: "
        if target in ("cache", "all"):
            await cache_clear()
            msg += "[번역 캐시] "
        if target in ("logs", "all"):
            from database.database import get_history_db
            h_db = get_history_db()
            await h_db.execute("DELETE FROM chat_logs")
            await h_db.commit()
            msg += "[채팅 로그] "
            
        await interaction.response.send_message(f"✅ {msg}", ephemeral=True)

    @history_group.command(name="optimize", description="Optimize database storage (VACUUM).")
    async def history_optimize(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        from database.database import get_db, get_history_db
        db = get_db()
        h_db = get_history_db()
        
        await db.execute("VACUUM")
        await h_db.execute("VACUUM")
        
        await interaction.followup.send("✅ 모든 데이터베이스(bot.db, history.db) 최적화가 완료되었습니다.", ephemeral=True)

    @app_commands.command(name="setlog", description="Set translation log channel and level (Admin)")
    @app_commands.describe(channel="Channel for logs", level="Log verbosity level")
    @app_commands.choices(level=[
        app_commands.Choice(name="Minimal (Error only)", value="minimal"),
        app_commands.Choice(name="Normal (Error + Summary)", value="normal"),
        app_commands.Choice(name="Verbose (All records)", value="verbose"),
    ])
    async def cmd_set_log(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        level: str | None = None
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        if not channel and not level:
            config = get_server_config(interaction.guild.id)
            ch_id = config.get("log_channel_id")
            ch_mention = f"<#{ch_id}>" if ch_id else "설정 안 됨"
            await interaction.response.send_message(
                f"📋 현재 로그 설정: 채널={ch_mention}, 레벨=`{config.get('log_level', 'normal')}`",
                ephemeral=True
            )
            return

        update_data = {}
        if channel:
            perms = channel.permissions_for(interaction.guild.me)
            if not perms.send_messages or not perms.embed_links:
                await interaction.response.send_message(
                    f"❌ 봇이 {channel.mention}에 메시지를 보낼 권한이 없습니다.", ephemeral=True)
                return
            update_data["log_channel_id"] = channel.id
        if level:
            update_data["log_level"] = level

        await set_server_config(interaction.guild.id, **update_data)
        
        msg = "✅ 로그 설정이 업데이트되었습니다."
        if channel: msg += f"\n채널: {channel.mention}"
        if level: msg += f"\n레벨: `{level}`"
        
        await interaction.response.send_message(msg, ephemeral=True)
        
        if channel:
            try:
                await channel.send(f"📋 **번역 로그 알림**: {interaction.user.display_name}님이 이 채널을 로그 채널로 지정했습니다.")
            except: pass

    @app_commands.command(name="ignorechannel", description="Disable bot translation in a specific channel (Admin)")
    @app_commands.describe(channel="Channel to ignore", toggle="On/Off")
    @app_commands.choices(toggle=[
        app_commands.Choice(name="Ignore", value="on"),
        app_commands.Choice(name="Unignore", value="off"),
    ])
    async def cmd_ignore_channel(self, interaction: discord.Interaction, channel: discord.TextChannel, toggle: str):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        config = get_server_config(interaction.guild.id)
        ignored = config.get("ignored_channels", [])
        if toggle == "on":
            if channel.id not in ignored:
                ignored.append(channel.id)
            await set_server_config(interaction.guild.id, ignored_channels=ignored)
            await interaction.response.send_message(f"✅ {channel.mention}에서 번역이 비활성화되었습니다.", ephemeral=True)
        else:
            if channel.id in ignored:
                ignored.remove(channel.id)
            await set_server_config(interaction.guild.id, ignored_channels=ignored)
            await interaction.response.send_message(f"✅ {channel.mention}에서 번역이 다시 활성화되었습니다.", ephemeral=True)

    @app_commands.command(name="syncroles", description="Sync language settings by scanning all member roles (Admin)")
    async def cmd_sync_roles(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        count = 0
        async for member in interaction.guild.fetch_members():
            if member.bot:
                continue
            
            target_lang = None
            for role in member.roles:
                # DB 매핑 확인 (ID 기반)
                db_lang = get_role_lang(role.id)
                if db_lang:
                    target_lang = db_lang
                    break
            
            if target_lang:
                await set_user_pref(member.id, lang=target_lang, auto=True)
                count += 1
            else:
                # 역할 매핑이 없는 경우에도 auto_translate는 켬
                await set_user_pref(member.id, auto=True)

        await interaction.followup.send(f"✅ 총 {count}명의 멤버 설정을 역할에 맞춰 업데이트했습니다. (전체 자동번역 활성화 완료)", ephemeral=True)

    @app_commands.command(name="setvision", description="Change image translation settings (Admin)")
    @app_commands.describe(model="Vision model to use", trigger="Prefix for image translation")
    @app_commands.choices(model=[
        app_commands.Choice(name="GPT-5 (Flagship)", value="gpt-5-2025-08-07"),
        app_commands.Choice(name="GPT-4o (High-performance)", value="gpt-4o-2024-08-06"),
        app_commands.Choice(name="GPT-4o-mini (Efficient)", value="gpt-4o-mini"),
    ])
    async def cmd_set_vision(self, interaction: discord.Interaction, model: str | None = None, trigger: str | None = None):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return
        
        if not model and not trigger:
            settings = get_vision_settings(interaction.guild.id)
            await interaction.response.send_message(f"📋 현재 설정: 모델=`{settings['model']}`, 트리거=`{settings['trigger']}`", ephemeral=True)
            return

        await set_vision_settings(interaction.guild.id, model=model, trigger=trigger)
        new = get_vision_settings(interaction.guild.id)
        await interaction.response.send_message(f"✅ 설정 변경 완료: 모델=`{new['model']}`, 트리거=`{new['trigger']}`", ephemeral=True)

    @app_commands.command(name="setchannel", description="Set channel-specific translation rules (Admin)")
    @app_commands.describe(channel="Target channel", action="Action", target_lang="Target language")
    @app_commands.choices(action=[
        app_commands.Choice(name="Set/Update", value="on"),
        app_commands.Choice(name="Disable", value="off"),
        app_commands.Choice(name="List", value="list"),
    ])
    async def cmd_set_channel(self, interaction: discord.Interaction, action: str, channel: discord.TextChannel | None = None, target_lang: str | None = None):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        from database.user_settings import _channel_cache
        if action == "list":
            if not _channel_cache:
                await interaction.response.send_message("📋 설정된 채널 규칙이 없습니다.", ephemeral=True)
                return
            lines = []
            for ch_id, config in _channel_cache.items():
                ch = interaction.guild.get_channel(int(ch_id))
                name = ch.mention if ch else f"(삭제된 채널 {ch_id})"
                status = "✅활성" if config.get("auto") else "❌비활성"
                lines.append(f"{name} → **{config['target_lang']}** ({status})")
            
            embed = discord.Embed(title="📋 채널별 번역 설정", description="\n".join(lines), color=0x3498DB)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not channel:
            await interaction.response.send_message("❌ 채널을 선택해주세요.", ephemeral=True)
            return

        if action == "off":
            success = await remove_channel_config(channel.id)
            if success:
                await interaction.response.send_message(f"✅ {channel.mention}의 채널 전용 번역 규칙이 삭제되었습니다.", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {channel.mention}에 설정된 규칙이 없습니다.", ephemeral=True)
            return

        if action == "on":
            if not target_lang:
                await interaction.response.send_message("❌ 번역 대상 언어를 입력해주세요.", ephemeral=True)
                return
            
            from config import SUPPORTED_LANGUAGES
            matched = next((l for l in SUPPORTED_LANGUAGES if l.lower() == target_lang.lower()), None)
            if not matched:
                await interaction.response.send_message(f"❌ 지원하지 않는 언어입니다.", ephemeral=True)
                return

            await set_channel_config(channel.id, interaction.guild.id, target_lang=matched, auto=True)
            await interaction.response.send_message(
                f"✅ {channel.mention} 채널의 모든 메시지는 이제 **{matched}**(으)로 자동 번역됩니다.\n"
                f"(유저 개인 설정보다 우선 적용됩니다)",
                ephemeral=True
            )

    @app_commands.command(name="reload", description="Reload code modules in real-time (Admin)")
    @app_commands.describe(cog="Module to reload")
    @app_commands.choices(cog=[
        app_commands.Choice(name="Events (Listener)", value="events"),
        app_commands.Choice(name="Commands (Basic)", value="commands"),
        app_commands.Choice(name="Admin (Management)", value="admin"),
        app_commands.Choice(name="Persona (Analysis)", value="persona"),
        app_commands.Choice(name="Mentor (Chat)", value="mentor"),
        app_commands.Choice(name="Routines (Scheduler)", value="routines"),
    ])
    async def cmd_reload(self, interaction: discord.Interaction, cog: str):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.reload_extension(f"cogs.{cog}")
            # 트리 싱크 (새 명령어가 추가되었을 수 있으므로)
            if self.bot.guild_id:
                await self.bot.tree.sync(guild=discord.Object(id=self.bot.guild_id))
            else:
                await self.bot.tree.sync()
            
            await interaction.followup.send(f"✅ `cogs.{cog}` 모듈이 성공적으로 새로고침되었습니다.", ephemeral=True)
            bot_log.info(f"🔄 Reloaded cogs.{cog} by {interaction.user.display_name}")
        except Exception as e:
            await interaction.followup.send(f"❌ 새로고침 중 오류 발생: {e}", ephemeral=True)
            bot_log.error(f"[RELOAD-ERROR] {e}")

    @app_commands.command(name="check_persona", description="Check a member's persona and instructions (Admin)")
    @app_commands.describe(member="Member to check")
    async def cmd_check_persona(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        from database.user_personas import get_user_persona
        persona = await get_user_persona(member.id)
        
        if not persona:
            await interaction.response.send_message(f"❓ **{member.display_name}**님에 대한 저장된 페르소나 정보가 없습니다.", ephemeral=True)
            return
            
        embed = discord.Embed(title=f"👤 페르소나 정보: {member.display_name}", color=0xF1C40F)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        # Persona Summary (Historical/Last)
        summary = persona.get("first_persona") or "정보 없음"
        last = persona.get("last_persona") or "정보 없음"
        
        embed.add_field(name="📜 최초 분석 요약", value=summary[:1024], inline=False)
        if summary != last:
            embed.add_field(name="🔄 최근 분석 요약", value=last[:1024], inline=False)
            
        # Mentor Instructions
        instruction = persona.get("mentor_instruction") or "설정된 지시사항 없음"
        embed.add_field(name="💡 멘토 지시사항 (Prompt)", value=instruction[:1024], inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @cmd_set_lang.autocomplete("language")
    @cmd_set_channel.autocomplete("target_lang")
    async def lang_autocomplete(self, interaction: discord.Interaction, current: str):
        from config import SUPPORTED_LANGUAGES
        return [
            app_commands.Choice(name=l, value=l)
            for l in SUPPORTED_LANGUAGES if current.lower() in l.lower()
        ][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
