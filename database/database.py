# database.py — SQLite 공통 DB 레이어

import os
import aiosqlite

DB_FILE = os.path.join(os.path.dirname(__file__), "bot.db")

_db: aiosqlite.Connection | None = None


async def init() -> None:
    global _db
    _db = await aiosqlite.connect(DB_FILE)
    _db.row_factory = aiosqlite.Row

    await _db.executescript("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            original TEXT,
            target_lang TEXT,
            source_lang TEXT,
            translated TEXT
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            lang TEXT DEFAULT 'Korean',
            auto_translate INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS server_settings (
            guild_id TEXT PRIMARY KEY,
            log_channel_id INTEGER,
            log_level TEXT DEFAULT 'normal',
            ignored_channels TEXT DEFAULT '[]',
            vision_model TEXT,
            vision_trigger TEXT DEFAULT '-i'
        );

        CREATE TABLE IF NOT EXISTS usage (
            user_id TEXT PRIMARY KEY,
            last_nickname TEXT DEFAULT '',
            mini_input_tokens INTEGER DEFAULT 0,
            mini_output_tokens INTEGER DEFAULT 0,
            smart_input_tokens INTEGER DEFAULT 0,
            smart_output_tokens INTEGER DEFAULT 0,
            total_calls INTEGER DEFAULT 0,
            cache_hits INTEGER DEFAULT 0,
            smart_corrections INTEGER DEFAULT 0,
            smart_total_calls INTEGER DEFAULT 0,
            total_cost_usd REAL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS typo_words (
            word TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS abbreviations (
            word TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS suspicious_endings (
            pattern TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            total_calls INTEGER DEFAULT 0,
            cache_hits INTEGER DEFAULT 0,
            typo_corrections INTEGER DEFAULT 0,
            mini_input_tokens INTEGER DEFAULT 0,
            mini_output_tokens INTEGER DEFAULT 0,
            smart_input_tokens INTEGER DEFAULT 0,
            smart_output_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS role_lang_map (
            role_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            target_lang TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS channel_settings (
            channel_id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            source_lang TEXT,
            target_lang TEXT,
            auto_translate INTEGER DEFAULT 0
        );
    """)
    await _db.commit()

    # ──────────────────────────────────────────────
    # [Migration] 신규 컬럼 소급 적용
    # ──────────────────────────────────────────────
    # server_settings 테이블에 vision_model, vision_trigger 컬럼이 없으면 추가
    async with _db.execute("PRAGMA table_info(server_settings)") as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
        
        if "vision_model" not in columns:
            await _db.execute("ALTER TABLE server_settings ADD COLUMN vision_model TEXT")
            print("[DB-MIGRATE] Added 'vision_model' column to server_settings")
            
        if "vision_trigger" not in columns:
            await _db.execute("ALTER TABLE server_settings ADD COLUMN vision_trigger TEXT DEFAULT '-i'")
            print("[DB-MIGRATE] Added 'vision_trigger' column to server_settings")
            
    await _db.commit()


async def close() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("DB가 초기화되지 않았습니다. database.init()을 먼저 호출하세요.")
    return _db
