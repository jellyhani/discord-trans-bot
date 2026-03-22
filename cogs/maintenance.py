import discord
from discord.ext import commands, tasks
import shutil
import os
from datetime import datetime
from utils.logger import bot_log

class MaintenanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.backup_loop.start()

    def cog_unload(self):
        self.backup_loop.cancel()

    @tasks.loop(hours=12)
    async def backup_loop(self):
        """매 12시간마다 데이터베이스 백업을 수행합니다."""
        await self.perform_backup()

    async def perform_backup(self):
        """실제 백업 로직"""
        try:
            from database.database import DB_FILE, HISTORY_DB_FILE
            
            backup_dir = os.path.join(os.path.dirname(os.path.dirname(DB_FILE)), "backups")
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            for db_path in [DB_FILE, HISTORY_DB_FILE]:
                if os.path.exists(db_path):
                    filename = os.path.basename(db_path)
                    backup_path = os.path.join(backup_dir, f"{timestamp}_{filename}")
                    shutil.copy2(db_path, backup_path)
                    bot_log.info(f"[BACKUP] Successfully backed up {filename} to {backup_path}")
            
            return True
        except Exception as e:
            bot_log.error(f"[BACKUP-ERROR] {e}")
            return False

    @discord.app_commands.command(name="backup", description="Manually trigger a database backup (Admin only).")
    async def manual_backup(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Administrator permissions are required.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        success = await self.perform_backup()
        
        if success:
            await interaction.followup.send("✅ Database backup completed successfully!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Backup failed. Check logs for details.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MaintenanceCog(bot))
