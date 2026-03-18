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
from config import MONTHLY_COST_LIMIT



class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setlang", description="멤버 또는 역할의 번역 언어를 설정합니다 (관리자)")
    @app_commands.describe(language="설정할 언어", member="설정할 멤버", role="설정할 역할")
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

    @app_commands.command(name="userlist", description="설정된 모든 유저 및 역할의 언어 목록을 확인합니다 (관리자)")
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

    @app_commands.command(name="serverstats", description="서버 전체 통계 및 사용량 순위를 확인합니다 (관리자)")
    @app_commands.describe(chart="차트 포함 여부")
    @app_commands.choices(chart=[
        app_commands.Choice(name="안 함", value="none"),
        app_commands.Choice(name="요청량 차트", value="usage"),
        app_commands.Choice(name="비용 차트", value="cost"),
        app_commands.Choice(name="모든 차트", value="all"),
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
            embed.add_field(name=f"{warning_lvl} 예산 알림", value=f"설정된 월 예산(${MONTHLY_COST_LIMIT})의 {monthly_cost/MONTHLY_COST_LIMIT*100:.1;f}%를 사용 중입니다.", inline=False)
        
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

    @app_commands.command(name="clearcache", description="번역 캐시를 전체 삭제합니다 (관리자)")
    async def cmd_clear_cache(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return
        count = await cache_clear()
        await interaction.response.send_message(f"🗑️ 캐시 {count}개 항목이 삭제되었습니다.", ephemeral=True)

    @app_commands.command(name="optimize", description="데이터베이스 용량을 최적화합니다 (관리자)")
    async def cmd_optimize(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        from database.database import get_db
        db = get_db()
        await db.execute("VACUUM")
        await interaction.followup.send("✅ 데이터베이스 최적화(VACUUM)가 완료되었습니다.", ephemeral=True)

    @app_commands.command(name="setlog", description="번역 로그 채널 및 레벨을 설정합니다 (관리자)")
    @app_commands.describe(channel="로그를 전송할 채널", level="로그 레벨")
    @app_commands.choices(level=[
        app_commands.Choice(name="Minimal (에러만)", value="minimal"),
        app_commands.Choice(name="Normal (에러 + 요약)", value="normal"),
        app_commands.Choice(name="Verbose (모든 번역 기록)", value="verbose"),
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

    @app_commands.command(name="dict", description="오타/축약어 사전을 관리합니다 (관리자)")
    @app_commands.describe(
        action="추가/삭제/목록",
        category="사전 종류",
        word="단어 또는 패턴 (목록 조회 시 불필요)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="추가", value="add"),
            app_commands.Choice(name="삭제", value="remove"),
            app_commands.Choice(name="목록", value="list"),
        ],
        category=[
            app_commands.Choice(name="오타 단어", value="typo"),
            app_commands.Choice(name="축약어", value="abbr"),
            app_commands.Choice(name="비표준 어미", value="ending"),
        ],
    )
    async def cmd_dict(
        self,
        interaction: discord.Interaction,
        action: str,
        category: str,
        word: str | None = None,
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ '서버 관리' 권한이 필요합니다.", ephemeral=True)
            return

        if action == "list":
            if category == "typo":
                items = sorted(get_typo_words())
                title = "📖 오타 단어 사전"
            elif category == "abbr":
                items = sorted(get_abbreviations())
                title = "📖 축약어 사전"
            else:
                items = get_suspicious_endings()
                title = "📖 비표준 어미 패턴"

            if not items:
                await interaction.response.send_message(f"{title}: (비어있음)", ephemeral=True)
                return

            text = ", ".join(items)
            if len(text) > 1900:
                text = text[:1900] + "..."

            embed = discord.Embed(title=title, description=f"```{text}```", color=0x9B59B6)
            embed.set_footer(text=f"총 {len(items)}개")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not word:
            await interaction.response.send_message("❌ 단어를 입력해주세요.", ephemeral=True)
            return

        if action == "add":
            if category == "typo":
                success = await add_typo_word(word)
            elif category == "abbr":
                success = await add_abbreviation(word)
            else:
                success = await add_ending(word)

            if success:
                await interaction.response.send_message(f"✅ `{word}` 추가 완료.", ephemeral=True)
            else:
                await interaction.response.send_message(f"ℹ️ `{word}`은(는) 이미 존재합니다.", ephemeral=True)

        elif action == "remove":
            if category == "typo":
                success = await remove_typo_word(word)
            elif category == "abbr":
                success = await remove_abbreviation(word)
            else:
                success = await remove_ending(word)

            if success:
                await interaction.response.send_message(f"✅ `{word}` 삭제 완료.", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ `{word}`을(를) 찾을 수 없습니다.", ephemeral=True)

    @app_commands.command(name="ignorechannel", description="특정 채널에서 봇 번역을 비활성화합니다 (관리자)")
    @app_commands.describe(channel="무시할 채널", toggle="On/Off")
    @app_commands.choices(toggle=[
        app_commands.Choice(name="무시", value="on"),
        app_commands.Choice(name="해제", value="off"),
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

    @app_commands.command(name="syncroles", description="모든 멤버의 역할을 스캔하여 언어 설정을 동기화합니다 (관리자)")
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

    @app_commands.command(name="setvision", description="이미지 번역 설정을 변경합니다 (관리자)")
    @app_commands.describe(model="사용할 비전 모델", trigger="이미지 번역 트리거 접두사")
    @app_commands.choices(model=[
        app_commands.Choice(name="GPT-5 (최상위 플래그십)", value="gpt-5-2025-08-07"),
        app_commands.Choice(name="GPT-4o (고성능)", value="gpt-4o-2024-08-06"),
        app_commands.Choice(name="GPT-4o-mini (효율성)", value="gpt-4o-mini"),
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

    @app_commands.command(name="setchannel", description="채널 전용 번역 규칙을 설정합니다 (관리자)")
    @app_commands.describe(channel="대상 채널", action="동작", target_lang="목표 언어")
    @app_commands.choices(action=[
        app_commands.Choice(name="설정/수정", value="on"),
        app_commands.Choice(name="해제", value="off"),
        app_commands.Choice(name="목록", value="list"),
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
