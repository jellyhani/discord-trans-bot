# translation_cache.py — SQLite 기반 번역 캐시 (유저 식별자 포함)

import re
import hashlib
from database.database import get_db


def _normalize_text(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r'[!~.]+\s*$', '', s).rstrip()
    s = re.sub(r'\?+\s*$', '?', s)
    s = re.sub(r'([,;:])\1+', r'\1', s)
    s = re.sub(r'\s+', ' ', s)
    return s


def _make_key(text: str, target_lang: str, context_key: str = None) -> str:
    normalized = _normalize_text(text)
    raw = f"{normalized}|{target_lang.strip().lower()}"
    if context_key:
        raw += f"|ctx:{context_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_cached(text: str, target_lang: str, context_key: str = None) -> dict | None:
    """캐시된 번역 결과를 가져옵니다."""
    key = _make_key(text, target_lang, context_key)
    db = get_db()
    async with db.execute(
        "SELECT source_lang, translated FROM cache WHERE key = ?", (key,)
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return {"source_lang": row[0], "translated": row[1]}
        return None


async def set_cached(text: str, target_lang: str, source_lang: str, translated: str, context_key: str = None, user_id: str = None):
    """번역 결과를 캐시에 저장합니다. (유저 ID 포함)"""
    key = _make_key(text, target_lang, context_key)
    db = get_db()
    await db.execute(
        """INSERT OR REPLACE INTO cache (key, original, target_lang, source_lang, translated, user_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (key, text, target_lang, source_lang, translated, user_id)
    )
    await db.commit()


async def invalidate(text: str, target_lang: str) -> bool:
    key = _make_key(text, target_lang)
    db = get_db()
    cursor = await db.execute("DELETE FROM cache WHERE key = ?", (key,))
    await db.commit()
    return cursor.rowcount > 0


async def clear_all() -> int:
    db = get_db()
    async with db.execute("SELECT COUNT(*) FROM cache") as cursor:
        count = (await cursor.fetchone())[0]
    await db.execute("DELETE FROM cache")
    await db.commit()
    return count


async def get_stats() -> dict:
    db = get_db()
    async with db.execute("SELECT COUNT(*) FROM cache") as cursor:
        count = (await cursor.fetchone())[0]
    return {"total_entries": count}
