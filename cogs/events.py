# cogs/events.py — 메시지/리액션/삭제 이벤트

import re
import discord
from discord.ext import commands, tasks
from collections import OrderedDict
from datetime import datetime

from config import FLAG_TO_LANG, CONTEXT_MESSAGE_COUNT, LOG_LEVELS, LOG_BUFFER_INTERVAL, VISION_TRIGGER_PREFIX
from core.translator import detect_and_translate, translate_image
from database.user_settings import (
    get_user_lang, get_auto_translate, get_log_channel_id, get_log_level,
    get_ignored_channels, get_channel_config, get_role_lang, set_user_pref,
    get_vision_settings
)

from utils.usage_tracker import record_cache_hit, record_usage
from utils.logger import bot_log

# ──────────────────────────────────────────────
# 메시지 필터링
# ──────────────────────────────────────────────
_URL_PATTERN = re.compile(
    r'https?://\S+|discord\.gg/\S+|www\.\S+|<https?://[^>]+>'
)
_DISCORD_PATTERN = re.compile(
    r'<@!?\d+>|<@&\d+>|<#\d+>|<t:\d+(:[tTdDfFR])?>|<a?:\w+:\d+>'
)
_UNICODE_EMOJI_PATTERN = re.compile(
    r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
    r'\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F'
    r'\U0000200D\U00002600-\U000026FF\U0001F900-\U0001F9FF'
    r'\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002B50'
    r'\U000023F0-\U000023FF\U0000203C\U00002049]+',
    re.UNICODE
)
_REPEAT_PATTERN = re.compile(r'^(.)\1{1,}$')


def _strip_all_non_text(text: str) -> str:
    result = _URL_PATTERN.sub('', text)
    result = _DISCORD_PATTERN.sub('', result)
    result = _UNICODE_EMOJI_PATTERN.sub('', result)
    return result.strip()


def _should_skip_translation(text: str) -> bool:
    stripped = text.strip()
    pure_text = _strip_all_non_text(stripped)
    if len(pure_text) < 2:
        return True
    if re.fullmatch(r'[\d\s.,!?;:~\-+=%#*@(){}[\]<>/\\\'\"]+', pure_text):
        return True
    no_space = pure_text.replace(' ', '')
    if _REPEAT_PATTERN.match(no_space):
        return True
    if re.fullmatch(r'[ㅋㅎㅠㅜwWzZ\s]+', pure_text):
        return True
    return False


def _clean_context_message(text: str) -> str | None:
    cleaned = _strip_all_non_text(text)
    if len(cleaned) < 2:
        return None
    return cleaned


# ──────────────────────────────────────────────
# 국기 이모지 매칭
# ──────────────────────────────────────────────
def _normalize_emoji(emoji_str: str) -> str:
    cleaned = ""
    for ch in emoji_str:
        cp = ord(ch)
        if 0x1F1E6 <= cp <= 0x1F1FF:
            cleaned += ch
        elif cp > 0x2600 and ch.isprintable():
            cleaned += ch
    return cleaned


def _match_flag_lang(emoji_str: str) -> str | None:
    normalized = _normalize_emoji(emoji_str)
    if normalized in FLAG_TO_LANG:
        return FLAG_TO_LANG[normalized]
    if emoji_str in FLAG_TO_LANG:
        return FLAG_TO_LANG[emoji_str]
    return None


# ──────────────────────────────────────────────
# Cog 클래스
# ──────────────────────────────────────────────
class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._processed_ids: OrderedDict = OrderedDict()
        self.translation_replies: dict[int, dict] = {}
        self.reply_to_original: dict[int, dict] = {}
        self.log_buffer: dict[int, list[str]] = {}
        self.flush_logs_task.start()

    def cog_unload(self):
        self.flush_logs_task.cancel()

    # ── 유틸리티 ──
    def _is_duplicate(self, event_id) -> bool:
        if event_id in self._processed_ids:
            return True
        self._processed_ids[event_id] = None
        if len(self._processed_ids) > 500:
            self._processed_ids.popitem(last=False)
        return False

    def _trim_dict(self, d: dict, max_size: int = 1000):
        while len(d) > max_size:
            oldest = next(iter(d))
            del d[oldest]

    def _log_event(self, event_type: str, user, content: str = "", extra: str = ""):
        now = datetime.now().strftime("%H:%M:%S")
        if hasattr(user, 'display_name'):
            user_str = f"{user.display_name}({user.id})"
        else:
            user_str = str(user)
        bot_log.info(f"[{event_type}] {user_str} | {content} | {extra}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Carl-bot 등이 역할 부여 → 자동 언어 설정."""
        if before.roles == after.roles:
            return
        added_roles = set(after.roles) - set(before.roles)

        for role in added_roles:
            target_lang = get_role_lang(role.id)
            if target_lang:
                await set_user_pref(after.id, lang=target_lang, auto=True)
                self._log_event("ROLE-LANG", after, f"역할 '{role.name}' → {target_lang} 자동 설정")
                break

    # ── 로깅 ──
    async def _send_log(self, guild_id: int, level: int, message: str):
        server_level = LOG_LEVELS.get(get_log_level(guild_id), 2)
        if level > server_level:
            return
        if guild_id not in self.log_buffer:
            self.log_buffer[guild_id] = []
        now = datetime.now().strftime("%H:%M:%S")
        self.log_buffer[guild_id].append(f"[{now}] {message}")
        if level == 1:
            await self._flush_guild_logs(guild_id)

    async def _send_error_log(self, guild_id: int, error_msg: str):
        channel_id = get_log_channel_id(guild_id)
        if not channel_id:
            return
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not channel:
                bot_log.warning(f"Could not find log channel {channel_id} for guild {guild_id}")
                return
            
            # 권한 체크
            perms = channel.permissions_for(channel.guild.me)
            if not perms.send_messages or not perms.embed_links:
                bot_log.warning(f"Missing permissions in log channel {channel_id}")
                return

            embed = discord.Embed(
                title="⚠️ 번역 오류", description=error_msg[:2000],
                color=discord.Color.red(), timestamp=datetime.now(),
            )
            await channel.send(embed=embed)
        except Exception as e:
            bot_log.error(f"Failed to send error log to channel: {e}")

    async def _flush_guild_logs(self, guild_id: int):
        logs = self.log_buffer.pop(guild_id, [])
        if not logs:
            return
        channel_id = get_log_channel_id(guild_id)
        if not channel_id:
            return
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            chunk = ""
            for line in logs:
                if len(chunk) + len(line) + 1 > 1900:
                    embed = discord.Embed(description=f"```\n{chunk}\n```", color=0x95A5A6)
                    embed.set_footer(text=f"번역 로그 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                    await channel.send(embed=embed)
                    chunk = ""
                chunk += line + "\n"
            if chunk.strip():
                embed = discord.Embed(description=f"```\n{chunk}\n```", color=0x95A5A6)
                embed.set_footer(text=f"번역 로그 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                await channel.send(embed=embed)
        except Exception as e:
            bot_log.error(f"LOG-FLUSH-ERR: {e}")

    @tasks.loop(seconds=LOG_BUFFER_INTERVAL)
    async def flush_logs_task(self):
        for guild_id in list(self.log_buffer.keys()):
            await self._flush_guild_logs(guild_id)

    @flush_logs_task.before_loop
    async def before_flush_logs(self):
        await self.bot.wait_until_ready()

    # ── 문맥 수집 ──
    async def _fetch_context(self, channel, before_message, count: int) -> list[str]:
        context = []
        try:
            async for msg in channel.history(limit=count + 5, before=before_message):
                if msg.id == before_message.id or msg.author.bot:
                    continue
                if not msg.content or not msg.content.strip():
                    continue
                cleaned = _clean_context_message(msg.content)
                if cleaned:
                    context.append(f"{msg.author.display_name}: {cleaned}")
                if len(context) >= count:
                    break
            context.reverse()
        except Exception:
            pass
        return context[-count:]

    # ── 번역 실행 ──
    async def _do_translate(self, message, target_lang, use_cache=True, footer_suffix=""):
        content = message.content.strip()
        user_id = message.author.id
        nickname = message.author.display_name
        context_messages = await self._fetch_context(message.channel, message, CONTEXT_MESSAGE_COUNT)

        result = await detect_and_translate(
            content, target_lang, user_id=user_id, nickname=nickname,
            use_cache=use_cache, context_messages=context_messages,
        )

        if result.get("cache_hit"):
            await record_cache_hit(user_id, nickname)

        if result["source_lang"].lower() == target_lang.lower():
            self._log_event("SKIP-SAME", message.author, "same lang")
            return None

        cache_tag = " · 📦캐시" if result.get("cache_hit") else ""
        correction_tag = " · ✏️교정됨" if result.get("was_correction") else ""
        footer = f"🌐 {result['source_lang']} → {target_lang}{cache_tag}{correction_tag}"
        if footer_suffix:
            footer += f" · {footer_suffix}"

        embed = discord.Embed(description=result["translated"], color=discord.Color.blue())
        embed.set_footer(text=footer)
        reply_msg = await message.reply(embed=embed, mention_author=False)

        # ── 캐시 저장 (삭제 연동용) ──
        self.translation_replies[message.id] = {
            "reply_id": reply_msg.id, "channel_id": message.channel.id,
        }
        self.reply_to_original[reply_msg.id] = {
            "original_text": content, "target_lang": target_lang,
            "channel_id": message.channel.id, "original_msg_id": message.id,
        }
        self._trim_dict(self.translation_replies, 1000)
        self._trim_dict(self.reply_to_original, 1000)

        if message.guild:
            cache_str = "캐시" if result.get("cache_hit") else "API"
            model_info = result.get("model", "Cache")
            self._log_event("TRANS-DONE", message.author, f"{result['source_lang']}→{target_lang}", f"model={model_info}")
            await self._send_log(
                message.guild.id, 3,
                f"[번역] {nickname} | {result['source_lang']}→{target_lang} | {cache_str} | \"{content}\"",
            )

        return reply_msg
    
    async def _do_vision_translate(self, message, target_lang, model=None, instruction=None):
        """이미지 번역 실행"""
        for attachment in message.attachments:
            if not (attachment.content_type and attachment.content_type.startswith('image/')):
                continue
            
            self._log_event("VISION-START", message.author, f"attachment={attachment.filename}", f"instruction='{instruction}'" if instruction else "")
            
            try:
                result = await translate_image(
                    attachment.url, target_lang,
                    user_id=message.author.id, nickname=message.author.display_name,
                    model_override=model, instruction=instruction
                )
                
                embed = discord.Embed(color=0xA2C2E1) # 밝은 파랑
                embed.add_field(name=f"🖼️ 이미지 텍스트 ({result['source_lang']})", value=result["original_text"][:1000], inline=False)
                embed.add_field(name=f"🌐 번역 ({target_lang})", value=result["translated"][:1000], inline=False)
                embed.set_footer(text=f"Vision · {result['model']}")
                
                reply_msg = await message.reply(embed=embed, mention_author=False)
                self._log_event("VISION-DONE", message.author, "success")
                
                # ── 캐시 저장 (삭제 연동용) ──
                self.translation_replies[message.id] = {
                    "reply_id": reply_msg.id, "channel_id": message.channel.id,
                }
                self.reply_to_original[reply_msg.id] = {
                    "original_text": f"(Image) {instruction or ''}", 
                    "target_lang": target_lang,
                    "channel_id": message.channel.id, "original_msg_id": message.id,
                }
                self._trim_dict(self.translation_replies, 1000)
                self._trim_dict(self.reply_to_original, 1000)
                
                if message.guild:
                    await self._send_log(
                        message.guild.id, 3,
                        f"[이미지 번역] {message.author.display_name} | {result['source_lang']}→{target_lang} | \"{result['original_text'][:30]}...\""
                    )
            except Exception as e:
                bot_log.error(f"Vision Error: {e}")
                self._log_event("VISION-ERROR", message.author, str(e))
                # 일반 에러와 마찬가지로 로그 전송
                if message.guild:
                    await self._send_error_log(message.guild.id, f"이미지 번역 오류\n```{str(e)[:500]}```")

    # ── 봇 reply 역추적 ──
    async def _find_bot_reply(self, channel, original_msg_id: int):
        try:
            async for msg in channel.history(limit=30, after=discord.Object(id=original_msg_id)):
                if msg.author.id != self.bot.user.id:
                    continue
                if msg.reference and msg.reference.message_id == original_msg_id:
                    return msg
        except Exception:
            pass
        return None

    # ──────────────────────────────────────────
    # 이벤트 리스너
    # ──────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # 무시 채널 체크
        if message.guild:
            ignored = get_ignored_channels(message.guild.id)
            if message.channel.id in ignored:
                return

        self._log_event("MSG", message.author, message.content or "(empty)")

        if self._is_duplicate(f"msg:{message.id}"):
            return

        content = message.content.strip() if message.content else ""
        
        # ── 0. 이미지 번역 체크 ──
        # 서버별 Vision 설정(트리거, 모델) 가져오기
        vision_settings = get_vision_settings(message.guild.id) if message.guild else {"trigger": VISION_TRIGGER_PREFIX, "model": OPENAI_VISION_MODEL}
        trigger = vision_settings["trigger"]
        
        is_vision_trigger = content.startswith(trigger)
        has_image = any(a.content_type and a.content_type.startswith('image/') for a in message.attachments)
        
        if is_vision_trigger and has_image:
            # 트리거가 있는 경우 이미지 번역 대상으로 간주
            pass
        elif len(content) < 2 or _should_skip_translation(content):
            if len(content) >= 2:
                self._log_event("SKIP-FILTER", message.author, content)
            return
        user_id = message.author.id
        # ── 1. 채널 설정 체크 (우선순위 높음) ──
        channel_config = get_channel_config(message.channel.id)
        if channel_config.get("auto"):
            target_lang = channel_config["target_lang"]
            footer_suffix = "채널 고정"
            # channel_config["source_lang"] 도 필요시 translator에 넘길 수 있음
            # 일단은 detect_and_translate가 감지하도록 둠
        else:
            # ── 2. 유저 설정 체크 ──
            if not get_auto_translate(user_id):
                self._log_event("SKIP-USER-OFF", message.author, "auto-trans off")
                return
            target_lang = get_user_lang(user_id)
            footer_suffix = "자동"

        try:
            if is_vision_trigger and has_image:
                # 트리거를 뺀 나머지 텍스트를 AI 지시어로 전달
                pure_instruction = content[len(trigger):].strip()
                await self._do_vision_translate(message, target_lang, model=vision_settings["model"], instruction=pure_instruction)
                # 이미지 번역이 수행된 경우 일반 텍스트 번역은 건너뜀 (중복 답변 방지)
                return
            
            # 텍스트가 있는 경우에만 일반 번역 수행
            if len(content) >= 2 and not _should_skip_translation(content):
                await self._do_translate(message, target_lang, use_cache=True, footer_suffix=footer_suffix)
        except Exception as e:
            self._log_event("ERROR", message.author, str(e))
            if message.guild:
                await self._send_error_log(message.guild.id, f"번역 오류: {message.author.display_name}\n```{str(e)[:500]}```")
            try:
                err_embed = discord.Embed(
                    description="⚠️ 번역 중 오류가 발생했습니다.", color=discord.Color.orange(),
                )
                await message.reply(embed=err_embed, mention_author=False, delete_after=10)
            except:
                pass

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.author.bot:
            return

        content = after.content.strip() if after.content else ""
        if len(content) < 2 or _should_skip_translation(content):
            return

        user_id = after.author.id
        if not get_auto_translate(user_id):
            return

        target_lang = get_user_lang(user_id)

        try:
            context_messages = await self._fetch_context(after.channel, after, CONTEXT_MESSAGE_COUNT)
            result = await detect_and_translate(
                content, target_lang, user_id=user_id, nickname=after.author.display_name,
                use_cache=False, context_messages=context_messages,
            )

            if result["source_lang"].lower() == target_lang.lower():
                return

            correction_tag = " · ✏️교정됨" if result.get("was_correction") else ""
            footer = f"🌐 {result['source_lang']} → {target_lang}{correction_tag} · 수정됨"
            embed = discord.Embed(description=result["translated"], color=discord.Color.blue())
            embed.set_footer(text=footer)

            info = self.translation_replies.get(after.id)
            if info:
                try:
                    ch = self.bot.get_channel(info["channel_id"]) or await self.bot.fetch_channel(info["channel_id"])
                    reply_msg = await ch.fetch_message(info["reply_id"])
                    await reply_msg.edit(embed=embed)
                    self._log_event("EDIT-UPDATE", after.author, content[:20])
                    return
                except discord.NotFound:
                    pass

            reply_msg = await after.reply(embed=embed, mention_author=False)
            self.translation_replies[after.id] = {
                "reply_id": reply_msg.id, "channel_id": after.channel.id,
            }
            self.reply_to_original[reply_msg.id] = {
                "original_text": content, "target_lang": target_lang,
                "channel_id": after.channel.id, "original_msg_id": after.id,
            }
            self._log_event("EDIT-NEW", after.author, content[:20])
        except Exception as e:
            self._log_event("EDIT-ERROR", after.author, str(e))

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        info = self.translation_replies.pop(message.id, None)
        if info:
            try:
                ch = self.bot.get_channel(info["channel_id"]) or await self.bot.fetch_channel(info["channel_id"])
                reply_msg = await ch.fetch_message(info["reply_id"])
                await reply_msg.delete()
                self.reply_to_original.pop(info["reply_id"], None)
                self._log_event("AUTO-DEL", message.author if message.author else "Unknown", f"reply {info['reply_id']}")
                return
            except (discord.NotFound, discord.Forbidden):
                pass
            except Exception as e:
                self._log_event("AUTO-DEL-FAIL", "System", str(e))
                return

        try:
            bot_reply = await self._find_bot_reply(message.channel, message.id)
            if bot_reply:
                await bot_reply.delete()
                self.reply_to_original.pop(bot_reply.id, None)
                self._log_event("AUTO-DEL-TRACE", message.author if message.author else "Unknown", f"reply {bot_reply.id}")
        except (discord.NotFound, discord.Forbidden):
            pass
        except Exception as e:
            self._log_event("AUTO-DEL-TRACE-FAIL", "System", str(e))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        # 무시 채널 체크
        if payload.guild_id:
            ignored = get_ignored_channels(payload.guild_id)
            if payload.channel_id in ignored:
                return

        emoji_str = str(payload.emoji)
        self._log_event("REACT-RAW", payload.user_id, f"emoji='{emoji_str}' hex={[hex(ord(c)) for c in emoji_str]}")

        # ── 🔄 재번역 ──
        if emoji_str == "🔄":
            if self._is_duplicate(f"refresh:{payload.message_id}:{payload.user_id}"):
                return

            try:
                ch = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
                bot_reply_msg = await ch.fetch_message(payload.message_id)

                if bot_reply_msg.author.id != self.bot.user.id:
                    return

                user = payload.member or await self.bot.fetch_user(payload.user_id)
                info = self.reply_to_original.get(payload.message_id)

                if not info:
                    if not bot_reply_msg.reference or not bot_reply_msg.reference.message_id:
                        return
                    original_msg_id = bot_reply_msg.reference.message_id
                    try:
                        original_msg = await ch.fetch_message(original_msg_id)
                    except discord.NotFound:
                        return
                    if not original_msg.content or not original_msg.content.strip():
                        return
                    target_lang = get_user_lang(payload.user_id)
                    info = {
                        "original_text": original_msg.content.strip(), "target_lang": target_lang,
                        "channel_id": ch.id, "original_msg_id": original_msg_id,
                    }

                context_messages = await self._fetch_context(ch, await ch.fetch_message(info["original_msg_id"]), CONTEXT_MESSAGE_COUNT)
                result = await detect_and_translate(
                    info["original_text"], info["target_lang"],
                    user_id=payload.user_id, nickname=user.display_name,
                    use_cache=False, context_messages=context_messages,
                )

                if result["source_lang"].lower() == info["target_lang"].lower():
                    return

                correction_tag = " · ✏️교정됨" if result.get("was_correction") else ""
                footer = f"🌐 {result['source_lang']} → {info['target_lang']}{correction_tag} · 🔄재번역"
                embed = discord.Embed(description=result["translated"], color=discord.Color.green())
                embed.set_footer(text=footer)
                await bot_reply_msg.edit(embed=embed)

                self.reply_to_original[payload.message_id] = info
                self._log_event("REFRESH", user, info["original_text"][:20])
            except Exception as e:
                self._log_event("REFRESH-ERR", "System", str(e))
            return

        # ── 국기 리액션 번역 ──
        target_lang = _match_flag_lang(emoji_str)
        if not target_lang:
            return

        if self._is_duplicate(f"react:{payload.message_id}:{emoji_str}:{payload.user_id}"):
            return

        try:
            channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            if not message.content or _should_skip_translation(message.content):
                return

            user = payload.member or await self.bot.fetch_user(payload.user_id)
            self._log_event("REACT", user, message.content[:20], f"→ {target_lang}")

            context_messages = await self._fetch_context(channel, message, CONTEXT_MESSAGE_COUNT)
            result = await detect_and_translate(
                message.content, target_lang,
                user_id=payload.user_id, nickname=user.display_name,
                use_cache=True, context_messages=context_messages,
            )

            if result.get("cache_hit"):
                await record_cache_hit(payload.user_id, user.display_name)

            cache_tag = " · 📦캐시" if result.get("cache_hit") else ""
            embed = discord.Embed(color=0x5865F2)
            embed.add_field(name=f"📝 원문 ({result['source_lang']})", value=message.content[:1000], inline=False)
            embed.add_field(name=f"🌐 번역 ({target_lang})", value=result["translated"][:1000], inline=False)
            embed.set_footer(
                text=f"요청: {user.display_name}{cache_tag}",
                icon_url=user.display_avatar.url if user.display_avatar else None,
            )
            await channel.send(embed=embed)

            if payload.guild_id:
                await self._send_log(
                    payload.guild_id, 3,
                    f"[리액션 번역] {user.display_name} | {result['source_lang']}→{target_lang} | \"{message.content}\"",
                )
        except Exception as e:
            bot_log.error(f"Reaction Error: {e}")
            if payload.guild_id:
                await self._send_error_log(payload.guild_id, f"리액션 번역 오류\n```{str(e)[:500]}```")


async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
