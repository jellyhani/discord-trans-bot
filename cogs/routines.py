import discord
from discord.ext import commands, tasks
from datetime import datetime
from database.database import (
    get_due_routines, update_routine_last_run, add_routine, 
    get_user_routines, delete_routine, get_routine_history, 
    save_routine_history
)
from discord import app_commands
import asyncio

class RoutineCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        from core.mentor_engine import MentorEngine
        self.engine = MentorEngine(bot)
        self.routine_loop.start()

    def cog_unload(self):
        self.routine_loop.cancel()

    @tasks.loop(minutes=1)
    async def routine_loop(self):
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")

        due_tasks = await get_due_routines(current_time, current_date)
        if not due_tasks:
            return

        for task in due_tasks:
            await self.execute_routine(task, current_date)

    async def execute_routine(self, task: dict, current_date: str):
        # 0. Prevent Loop: Mark as run immediately
        await update_routine_last_run(task["id"], current_date)
        
        user_id = int(task["user_id"])
        destination = task.get("destination", "channel")
        
        target = None
        from utils.logger import bot_log
        if destination == "dm":
            target = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        else:
            target = self.bot.get_channel(int(task["channel_id"]))
            
        if not target:
            bot_log.warning(f"[ROUTINE-FAIL] Could not find target(Dest: {destination}) for user {user_id}")
            return

        t_type = task["task_type"]
        query = task["query"]
        nickname = target.display_name if hasattr(target, 'display_name') else target.name if hasattr(target, 'name') else "User"

        try:
            # [NEW] 루틴 메모리(이력) 조회 및 프롬프트 주입
            history = await get_routine_history(task["id"], limit=5)
            prompt = f"System: Generate {t_type} result for '{query}'."
            if history:
                history_context = "\n- ".join(history)
                prompt += f"\n\n### Previous outputs for this routine (Avoid Duplicates):\n- {history_context}"
                prompt += "\n\nCRITICAL: Do NOT repeat the items mentioned above. Provide new, different, or more advanced content."

            result = await self.engine.generate_response(
                user_id=user_id,
                nickname=nickname,
                content=prompt,
                original_message=None # Proactive task
            )
            
            answer = result["answer"]
            
            # [NEW] 실행 결과 저장
            await save_routine_history(task["id"], answer)
            
            from utils.discord_utils import split_send
            mention = f"<@{user_id}>" if destination != "dm" else ""
            await split_send(target, f"📅 **[정기 루틴 알림]** {mention}님, 요청하신 {t_type} 결과입니다:\n\n{answer}")
            bot_log.info(f"[ROUTINE-SUCCESS] Executed {t_type} for {user_id}")
            
        except Exception as e:
            bot_log.error(f"Routine Execution Error: {e}")

    @app_commands.command(name="routine", description="Describe your routine in natural language (e.g., 'every day 7am dm me Seoul weather')")
    @app_commands.describe(prompt="Your routine request in plain language")
    async def natural_routine_cmd(self, interaction: discord.Interaction, prompt: str):
        """
        AI-powered natural language routine setup.
        """
        await interaction.response.defer(thinking=True, ephemeral=False)
        
        from core.translator import _get_client
        import json
        
        now_time = datetime.now().strftime("%H:%M")
        
        client = _get_client()
        extract_prompt = f"""
        Extract routine scheduling details from the following user prompt.
        If any information (task_type, query, time) is missing, identify it.
        Default destination is 'channel' if not mentioned.
        Output MUST be a valid JSON object.
        
        User Prompt: "{prompt}"
        Current Time: {now_time}
        
        Roles:
        - task_type: [search, weather, news]
        - destination: [channel, dm]
        - time: HH:MM (24-hour)
        - query: String (e.g., 'Seoul', 'GPT-4o news', 'AAPL stock')
        
        Example Output (Complete):
        {{ "success": true, "task_type": "weather", "query": "Seoul", "time": "08:00", "destination": "dm" }}
        
        Example Output (Partial):
        {{ "success": false, "missing": ["time"], "reason": "Please provide a specific time (e.g., 09:00)." }}
        """
        
        try:
            # [FIX] 추후 gpt-5 등으로 모델 변경 시 호환성 유지
            is_reasoning = "gpt-5" in "gpt-4o-mini" or "o1" in "gpt-4o-mini"
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": extract_prompt}],
                response_format={"type": "json_object"},
                **( {"max_completion_tokens": 250} if is_reasoning else {"max_tokens": 250} )
            )
            data = json.loads(resp.choices[0].message.content)
            
            if not data.get("success", False):
                missing_fields = ", ".join(data.get("missing", []))
                reason = data.get("reason", "Please provide more details.")
                await interaction.followup.send(
                    f"🤔 **Almost there!** I need a bit more info to set up your routine.\n"
                    f"> **Missing**: `{missing_fields}`\n"
                    f"> **Tip**: {reason}\n\n"
                    f"*Example: '/routine every day 8am dm me Seoul weather'*"
                )
                return

            t_type = data["task_type"]
            q = data["query"]
            t = data["time"]
            d = data.get("destination", "channel")
            
            # Simple validation
            if t_type not in ['search', 'weather', 'news']: t_type = 'search'
            if d not in ['channel', 'dm']: d = 'channel'
            
            await add_routine(str(interaction.user.id), str(interaction.channel_id), t_type, q, t, destination=d)
            
            emoji = "🔍" if t_type == "search" else "☀️" if t_type == "weather" else "📰"
            dest_str = "DM" if d == "dm" else "this channel"
            await interaction.followup.send(
                f"✅ **Routine Scheduled!**\n> {emoji} **{t_type.capitalize()}**: `{q}`\n> ⏰ **Time**: `{t}`\n> 📍 **To**: `{dest_str}`"
            )
            
        except Exception as e:
            from utils.logger import bot_log
            bot_log.error(f"[NATURAL-ROUTINE-ERROR] {e}")
            await interaction.followup.send("❌ 루틴 분석 중 오류가 발생했습니다. 더 명확하게 다시 말씀해 주시거나, 멘토봇(@멘토봇)에게 직접 루틴 등록을 부탁해 보세요.")


    @app_commands.command(name="routine-list", description="List all your active daily routines.")
    async def list_routines_cmd(self, interaction: discord.Interaction):
        routines = await get_user_routines(str(interaction.user.id))
        if not routines:
            await interaction.response.send_message("No active routines found.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 My Daily Routines", color=discord.Color.blue())
        for r in routines:
            embed.add_field(
                name=f"ID: {r['id']} | {r['schedule_time']}",
                value=f"Type: {r['task_type']}\nQuery: {r['query']}\nDest: {r['destination']}",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="routine-delete", description="Delete a specific routine by ID.")
    async def delete_routine_cmd(self, interaction: discord.Interaction, id: int):
        success = await delete_routine(id, str(interaction.user.id))
        if success:
            await interaction.response.send_message(f"✅ Deleted routine (ID: {id}).", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Could not find an active routine with ID {id}.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RoutineCog(bot))
