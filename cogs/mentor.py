import discord
from discord.ext import commands
from core.translator import _get_client
from utils.logger import bot_log, mentor_log
from database.database import add_pending_inquiry, get_pending_inquiry, remove_pending_inquiry
import re
from core.mentor_engine import MentorEngine

class MentorCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = MentorEngine(bot)
        
    @discord.app_commands.command(name="reset", description="Archive the current session and start a new one.")
    async def reset_persona(self, interaction: discord.Interaction):
        """현재 세션을 아카이브(소프트 삭제)하고 새 세션을 시작합니다."""
        from database.chat_logger import get_active_session_id, archive_session, create_session
        
        user_id = interaction.user.id
        active_sid = await get_active_session_id(user_id)
        
        await archive_session(user_id, active_sid)
        await create_session(user_id, "New Conversation (After Reset)")
        
        await interaction.response.send_message("✅ Current session archived and a new one started!", ephemeral=True)

    @discord.app_commands.command(name="archive", description="Archive a specific conversation session.")
    @discord.app_commands.describe(session_id="The ID of the session to archive")
    async def archive_chat(self, interaction: discord.Interaction, session_id: int):
        from database.chat_logger import archive_session
        success = await archive_session(interaction.user.id, session_id)
        if success:
            await interaction.response.send_message(f"📁 Archived session ID: `{session_id}`", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Could not find that session.", ephemeral=True)

    @discord.app_commands.command(name="archived", description="List my archived conversation sessions.")
    async def list_archived(self, interaction: discord.Interaction):
        from database.chat_logger import get_sessions
        sessions = await get_sessions(interaction.user.id, include_deleted=True)
        archived = [s for s in sessions if s["is_deleted"]]
        
        if not archived:
            await interaction.response.send_message("You don't have any archived conversations.", ephemeral=True)
            return
            
        msg = "**Your Archived Conversations:**\n"
        for s in archived:
            msg += f"- ID: `{s['id']}` | **{s['title']}** (Archived)\n"
        
        msg += "\nUse `/restore <id>` to bring them back."
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.app_commands.command(name="restore", description="Restore an archived conversation session.")
    @discord.app_commands.describe(session_id="The ID of the session to restore")
    async def restore_chat(self, interaction: discord.Interaction, session_id: int):
        from database.chat_logger import restore_session
        success = await restore_session(interaction.user.id, session_id)
        if success:
            await interaction.response.send_message(f"✅ Restored session ID: `{session_id}`. You can now see it in `/chats`.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Could not find that archived session.", ephemeral=True)

    @discord.app_commands.command(name="new_chat", description="Start a new conversation session.")
    @discord.app_commands.describe(title="Title of the new conversation")
    async def new_chat(self, interaction: discord.Interaction, title: str = "New Conversation"):
        from database.chat_logger import create_session
        await create_session(interaction.user.id, title)
        await interaction.response.send_message(f"🚀 Started a new conversation: **{title}**", ephemeral=True)

    @discord.app_commands.command(name="chats", description="List my conversation sessions.")
    async def list_chats(self, interaction: discord.Interaction):
        from database.chat_logger import get_sessions
        sessions = await get_sessions(interaction.user.id)
        if not sessions:
            await interaction.response.send_message("You don't have any saved conversations yet.", ephemeral=True)
            return
            
        msg = "**Your Conversations:**\n"
        for s in sessions:
            active_tag = " ✨(Active)" if s["is_active"] else ""
            msg += f"- ID: `{s['id']}` | **{s['title']}** {active_tag}\n"
        
        msg += "\nUse `/switch <id>` to change sessions."
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.app_commands.command(name="switch", description="Switch to a different conversation session.")
    @discord.app_commands.describe(session_id="The ID of the session to switch to")
    async def switch_chat(self, interaction: discord.Interaction, session_id: int):
        from database.chat_logger import switch_session
        success = await switch_session(interaction.user.id, session_id)
        if success:
            await interaction.response.send_message(f"✅ Switched to session ID: `{session_id}`", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Could not find that session. Please check `/chats`.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        is_mentioned = self.bot.user in message.mentions
        is_reply_to_bot = (
            message.reference and 
            message.reference.resolved and 
            isinstance(message.reference.resolved, discord.Message) and
            message.reference.resolved.author.id == self.bot.user.id
        )

        if is_mentioned or is_reply_to_bot:
            await self.handle_mentor_chat(message)

    async def handle_mentor_chat(self, message: discord.Message):
        """
        AI 엔진을 사용하여 답변을 생성하고 유저에게 전달합니다.
        가성비를 위해 모델 라우팅 및 지능형 프롬프트를 사용합니다.
        """
        user_id = message.author.id
        nickname = message.author.display_name
        
        # 1. 입력 정제 가공
        clean_content = message.content.replace(f'<@{self.bot.user.id}>', '').replace(f'<@!{self.bot.user.id}>', '').strip()
        has_images = any(a.content_type and a.content_type.startswith('image/') for a in message.attachments)
        
        # 텍스트 설명이 없으면 이미지 분석을 수행하지 않음 (단순 멘션+이미지 스킵)
        if not clean_content:
            return

        mentor_log.debug(f"===== [MENTOR-START] User: {nickname}({user_id}) =====")
        mentor_log.debug(f"Content: {clean_content}")

        async with message.channel.typing():
            try:
                # 2. 이미지 및 레퍼런스 메시지 파악
                image_urls = [a.url for a in message.attachments if a.content_type and a.content_type.startswith('image/')]
                
                reference_content = None
                if message.reference and message.reference.resolved:
                    reference_content = message.reference.resolved.content

                # 3. AI 엔진 호출 (핵심 로직 분리)
                result = await self.engine.generate_response(
                    user_id=user_id,
                    nickname=nickname,
                    content=clean_content,
                    reference_content=reference_content,
                    original_message=message,
                    image_urls=image_urls
                )
                
                answer = result["answer"]
                needs_relay = result.get("needs_relay", False)
                relay_question = result.get("relay_question", "")

                # 4. 제작자 릴레이 처리 (Cog 레벨에서 UI 처리)
                if needs_relay:
                    req_id = await add_pending_inquiry(str(user_id), str(message.channel.id), str(message.id), relay_question)
                    from os import getenv
                    dev_uid_str = getenv("DEVELOPER_UID")
                    dev_id = int(dev_uid_str) if dev_uid_str and dev_uid_str.isdigit() else 0
                    
                    dev_user = self.bot.get_user(dev_id) or await self.bot.fetch_user(dev_id)
                    if dev_user:
                        await dev_user.send(
                            f"🔔 **신상정보 문의 알림 (Req ID: {req_id})**\n유저: {nickname} ({user_id})\n질문: {relay_question}\n"
                            f"응답은 `{req_id} 답변` 형식으로 보내주세요."
                        )
                        answer += "\n\n*(제작자님께 해당 내용을 물어보았습니다. 답변이 오면 바로 알려드릴게요!)*"
                    else:
                        answer += "\n\n*(제작자님께 연락을 시도했으나 실패했습니다.)*"

                if not answer or not answer.strip():
                    answer = "죄송합니다. 답변을 생성하는 중에 문제가 발생했습니다."

                mentor_log.debug(f"[ANSWER] {answer[:100]}...")
                
                # 5. 결과 전송
                from utils.discord_utils import split_send
                await split_send(message.channel, f"<@{user_id}> {answer}" if not message.reference else answer) 
                
                bot_log.info(f"[MENTOR] Success via MentorEngine")

            except Exception as e:
                bot_log.error(f"[MENTOR-ERROR] {e}")
                mentor_log.error(f"[CRITICAL-ERROR] {e}", exc_info=True)
                # 에러 발생 시에도 빈 메시지 방지
                await message.reply("⚠️ 정보를 가져오거나 답변을 생성하는 중에 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
            finally:
                mentor_log.debug("===== [MENTOR-END] =====\n")

    @commands.Cog.listener("on_message")
    async def on_dm_relay(self, message: discord.Message):
        """제작자의 DM 답변을 원래 유저에게 전달합니다."""
        if not isinstance(message.channel, discord.DMChannel) or message.author.bot:
            return

        from os import getenv
        dev_uid_str = getenv("DEVELOPER_UID")
        dev_id = int(dev_uid_str) if dev_uid_str and dev_uid_str.isdigit() else 0
        
        if message.author.id != dev_id:
            return

        # 패턴: <req_id> <답변>
        match = re.match(r'^(\d+)\s+(.+)$', message.content.strip(), re.DOTALL)
        if not match:
            # 패턴에 맞지 않으면 일반 대화로 처리하거나 무시
            return

        req_id = int(match.group(1))
        answer_text = match.group(2).strip()

        inquiry = await get_pending_inquiry(req_id)
        if not inquiry:
            await message.reply(f"❌ 해당 ID({req_id})의 대기 중인 질문을 찾을 수 없습니다.")
            return

        try:
            target_channel = self.bot.get_channel(int(inquiry["channel_id"]))
            if target_channel:
                requester_mention = f"<@{inquiry['user_id']}>"
                relay_msg = (
                     f"📢 {requester_mention}님, 제작자님으로부터 답변이 도착했습니다!\n\n"
                     f"**질문**: {inquiry['question']}\n"
                     f"**답변**: {answer_text}"
                )
                await target_channel.send(relay_msg)
                
                # [NEW] Save to Developer Knowledge Base
                from database.database import save_developer_knowledge
                await save_developer_knowledge(inquiry["question"], answer_text)
                
                await remove_pending_inquiry(req_id)
                await message.reply(f"✅ 유저(<@{inquiry['user_id']}>)에게 답변을 성공적으로 전달하고, 해당 정보를 학습했습니다!")
            else:
                await message.reply("❌ 채널을 찾을 수 없어 답변 전달에 실패했습니다.")
        except Exception as e:
            bot_log.error(f"[MENTOR-RELAY-ERROR] {e}")
            await message.reply(f"❌ 오류가 발생했습니다: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(MentorCog(bot))
