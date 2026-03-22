# database.py — SQLite 공통 DB 레이어 (설정 및 역사 분리)

import os
import aiosqlite

# ──────────────────────────────────────────────
# DB 파일 경로 설정
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
DB_FILE = os.path.join(BASE_DIR, "bot.db")
HISTORY_DB_FILE = os.path.join(BASE_DIR, "history.db")

_db: aiosqlite.Connection | None = None
_history_db: aiosqlite.Connection | None = None


async def init() -> None:
    """봇 시작 시 모든 DB 연결 초기화."""
    global _db, _history_db
    
    # 1. 메인 설정 DB (Settings, Cache, Stats)
    _db = await aiosqlite.connect(DB_FILE)
    _db.row_factory = aiosqlite.Row

    await _db.executescript("""
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            original TEXT,
            target_lang TEXT,
            source_lang TEXT,
            translated TEXT,
            user_id TEXT -- [NEW] 누가 요청했는지 기록
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

        CREATE TABLE IF NOT EXISTS user_personas (
            user_id TEXT PRIMARY KEY,
            first_persona TEXT,
            last_persona TEXT,
            mentor_instruction TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS custom_slang (
            guild_id TEXT,
            short_form TEXT,
            full_meaning TEXT,
            PRIMARY KEY (guild_id, short_form)
        );

        CREATE TABLE IF NOT EXISTS bot_traits (
            trait_key TEXT PRIMARY KEY,
            trait_value TEXT
        );

        CREATE TABLE IF NOT EXISTS pending_inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            channel_id TEXT,
            message_id TEXT,
            question TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            channel_id TEXT,
            task_type TEXT, -- 'search', 'weather', 'news'
            query TEXT,
            schedule_time TEXT, -- 'HH:MM' format (24h)
            last_run_date TEXT, -- 'YYYY-MM-DD'
            destination TEXT DEFAULT 'channel' -- 'channel' or 'dm'
        );

        CREATE TABLE IF NOT EXISTS developer_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT UNIQUE,
            answer TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await _db.commit()

    # 2. 대화 역사 DB (Chat History) - 분리된 대규모 로그
    _history_db = await aiosqlite.connect(HISTORY_DB_FILE)
    _history_db.row_factory = aiosqlite.Row
    
    await _history_db.executescript("""
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            nickname TEXT,
            content TEXT,
            channel_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mentor_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            session_id INTEGER, -- [NEW]
            question TEXT,
            answer TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mentor_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            title TEXT,
            is_active INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0, -- [NEW]
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- [INDEX] 검색 성능 최적화
        CREATE INDEX IF NOT EXISTS idx_chat_logs_user ON chat_logs(user_id);
        CREATE INDEX IF NOT EXISTS idx_mentor_logs_lookup ON mentor_logs(user_id, session_id);
        CREATE INDEX IF NOT EXISTS idx_mentor_sessions_user ON mentor_sessions(user_id);
    """)
    await _history_db.commit()

    # ──────────────────────────────────────────────
    # [Migration] 신규 컬럼 소급 적용
    # ──────────────────────────────────────────────
    await _db.commit()

    # [Migration] 신규 컬럼 소급 적용
    async with _db.execute("PRAGMA table_info(server_settings)") as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
        if "vision_model" not in columns:
            await _db.execute("ALTER TABLE server_settings ADD COLUMN vision_model TEXT")
        if "vision_trigger" not in columns:
            await _db.execute("ALTER TABLE server_settings ADD COLUMN vision_trigger TEXT DEFAULT '-i'")
    await _db.commit()

    # [Migration] history.db - mentor_logs session_id 추가
    async with _history_db.execute("PRAGMA table_info(mentor_logs)") as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
        if "session_id" not in columns:
            await _history_db.execute("ALTER TABLE mentor_logs ADD COLUMN session_id INTEGER")
    
    # [Migration] history.db - mentor_sessions is_deleted 추가
    async with _history_db.execute("PRAGMA table_info(mentor_sessions)") as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
        if "is_deleted" not in columns:
            await _history_db.execute("ALTER TABLE mentor_sessions ADD COLUMN is_deleted INTEGER DEFAULT 0")
    
    await _history_db.commit()


async def close() -> None:
    """모든 DB 연결 종료."""
    global _db, _history_db
    if _db:
        await _db.close()
        _db = None
    if _history_db:
        await _history_db.close()
        _history_db = None


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("메인 DB가 초기화되지 않았습니다.")
    return _db

def get_history_db() -> aiosqlite.Connection:
    if _history_db is None:
        raise RuntimeError("역사 DB가 초기화되지 않았습니다.")
    return _history_db


# ──────────────────────────────────────────────
# [NEW] Bot Traits & Inquiries Helper Functions
# ──────────────────────────────────────────────

async def get_bot_trait(key: str) -> str | None:
    db = get_db()
    async with db.execute("SELECT trait_value FROM bot_traits WHERE trait_key = ?", (key,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else None

async def set_bot_trait(key: str, value: str) -> None:
    db = get_db()
    await db.execute(
        "INSERT OR REPLACE INTO bot_traits (trait_key, trait_value) VALUES (?, ?)",
        (key, value)
    )
    await db.commit()

async def add_pending_inquiry(user_id: str, channel_id: str, message_id: str, question: str) -> int:
    db = get_db()
    async with db.execute(
        "INSERT INTO pending_inquiries (user_id, channel_id, message_id, question) VALUES (?, ?, ?, ?)",
        (user_id, channel_id, message_id, question)
    ) as cursor:
        req_id = cursor.lastrowid
    await db.commit()
    return req_id

async def get_pending_inquiry(inquiry_id: int) -> dict | None:
    db = get_db()
    async with db.execute("SELECT * FROM pending_inquiries WHERE id = ?", (inquiry_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None

async def remove_pending_inquiry(inquiry_id: int) -> None:
    db = get_db()
    await db.execute("DELETE FROM pending_inquiries WHERE id = ?", (inquiry_id,))
    await db.commit()

# ──────────────────────────────────────────────
# [NEW] Routines Helper Functions
# ──────────────────────────────────────────────

async def add_routine(user_id: str, channel_id: str, t_type: str, query: str, s_time: str, destination: str = "channel") -> None:
    db = get_db()
    await db.execute(
        "INSERT INTO routines (user_id, channel_id, task_type, query, schedule_time, destination) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, channel_id, t_type, query, s_time, destination)
    )
    await db.commit()

async def get_due_routines(current_time: str, current_date: str) -> list[dict]:
    db = get_db()
    # Only pick routines scheduled for the EXACT current minute.
    async with db.execute(
        "SELECT * FROM routines WHERE schedule_time = ? AND (last_run_date IS NULL OR last_run_date != ?)",
        (current_time, current_date)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def update_routine_last_run(r_id: int, date: str) -> None:
    db = get_db()
    await db.execute("UPDATE routines SET last_run_date = ? WHERE id = ?", (date, r_id))
    await db.commit()

async def get_user_routines(user_id: str) -> list[dict]:
    db = get_db()
    async with db.execute("SELECT * FROM routines WHERE user_id = ?", (user_id,)) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def delete_routine(r_id: int, user_id: str) -> bool:
    db = get_db()
    async with db.execute("DELETE FROM routines WHERE id = ? AND user_id = ?", (r_id, user_id)) as cursor:
        affected = cursor.rowcount
    await db.commit()
    return affected > 0

# ──────────────────────────────────────────────
# [NEW] Developer Knowledge Base Helper Functions
# ──────────────────────────────────────────────

async def save_developer_knowledge(question: str, answer: str) -> None:
    db = get_db()
    await db.execute(
        "INSERT OR REPLACE INTO developer_knowledge (question, answer, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (question, answer)
    )
    await db.commit()

async def get_all_developer_knowledge() -> list[dict]:
    db = get_db()
    async with db.execute("SELECT question, answer FROM developer_knowledge ORDER BY updated_at ASC") as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
