import discord
from discord.ext import commands
from discord import app_commands
from database import dictionary_manager

class Slang(commands.Cog):
    """서버별 커스텀 줄임말/신조어 관리 명령어"""
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="slang", description="Manage server-specific slang and abbreviations.")
    @app_commands.describe(
        action="Select action (set: add/update, remove: delete, list: view all)",
        short="Abbreviation (e.g., nc, ncnc, ㄱㄱ)",
        meaning="Full meaning (e.g., nice, go go)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Add/Update (set)", value="set"),
        app_commands.Choice(name="Delete (remove)", value="remove"),
        app_commands.Choice(name="List (list)", value="list")
    ])
    async def slang_command(self, interaction: discord.Interaction, action: str, short: str = None, meaning: str = None):
        guild_id = str(interaction.guild_id)
        
        if action == "list":
            slang_dict = await dictionary_manager.get_custom_slang(guild_id)
            if not slang_dict:
                return await interaction.response.send_message("이 서버에 등록된 줄임말이 없습니다.", ephemeral=False)
            
            embed = discord.Embed(title=f"📌 {interaction.guild.name} 커스텀 줄임말 목록", color=discord.Color.blue())
            content = "\n".join([f"`{s}`: {m}" for s, m in slang_dict.items()])
            embed.description = content
            return await interaction.response.send_message(embed=embed, ephemeral=False)

        if not short:
            return await interaction.response.send_message("줄임말(short)을 입력해주세요.", ephemeral=False)

        if action == "set":
            if not meaning:
                return await interaction.response.send_message("원래 의미(meaning)를 입력해주세요.", ephemeral=False)
            
            await dictionary_manager.add_custom_slang(guild_id, short, meaning)
            await interaction.response.send_message(f"✅ 줄임말 등록 완료: `{short}` -> `{meaning}`", ephemeral=False)

        elif action == "remove":
            success = await dictionary_manager.remove_custom_slang(guild_id, short)
            if success:
                await interaction.response.send_message(f"🗑️ 줄임말 삭제 완료: `{short}`", ephemeral=False)
            else:
                await interaction.response.send_message(f"❓ 등록되지 않은 줄임말입니다: `{short}`", ephemeral=False)

async def setup(bot):
    await bot.add_cog(Slang(bot))
