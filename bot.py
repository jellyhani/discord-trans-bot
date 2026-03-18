# bot.py — 봇 초기화 및 실행

import os
import sys
import discord
from discord.ext import commands
from dotenv import load_dotenv



if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8', line_buffering=True)

from database import database
from core.translator import configure_openai
from database.user_settings import load_all_settings
from utils.logger import bot_log

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GUILD_ID_STR = os.getenv("DISCORD_GUILD_ID")

if not DISCORD_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ 환경 변수(TOKEN/API_KEY)가 누락되었습니다.")

GUILD_ID = int(GUILD_ID_STR) if GUILD_ID_STR and GUILD_ID_STR.isdigit() else None


# configure_openai(OPENAI_API_KEY)  # setup_hook으로 이동

# Intents 설정
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True


class TranslateBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.guild_id = GUILD_ID

    async def setup_hook(self):
        await database.init()
        
        # 마이그레이션 및 초기 설정 로드
        from database.user_settings import migrate_users_auto_translate
        await migrate_users_auto_translate()
        
        await load_all_settings()
        configure_openai(OPENAI_API_KEY)

        # 사전 초기화 (DB 비어있으면 기본값 삽입)
        from database.dictionary_manager import seed_defaults, load_all as load_dictionary
        await seed_defaults()
        await load_dictionary()

        from database.user_settings import load_role_lang_map
        await load_role_lang_map()

        await self.load_extension("cogs.events")
        await self.load_extension("cogs.commands")
        await self.load_extension("cogs.admin")

        if self.guild_id:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            bot_log.info(f"DEBUG: {self.guild_id} 서버에 명령어 동기화 완료")
        else:
            await self.tree.sync()
            bot_log.info("DEBUG: 모든 서버(Global)에 명령어 동기화 완료")

    async def close(self):
        await database.close()
        await super().close()


bot = TranslateBot()


@bot.event
async def on_ready():
    bot_log.info(f"✅ 봇 온라인 | PID: {os.getpid()} | 유저: {bot.user}")
    bot_log.info(f"📡 {len(bot.guilds)}개 서버에서 작동 중")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
