# user_settings.py — SQLite 기반 유저/서버/역할 설정 (메모리 캐시)

import json
from database.database import get_db


# ──────────────────────────────────────────────
# 메모리 캐시
# ──────────────────────────────────────────────
_user_cache: dict = {}          # str(user_id) → {"lang": str, "auto": bool}
_server_cache: dict = {}        # str(guild_id) → {"log_channel_id": int, "log_level": str, "ignored_channels": list}
_role_lang_cache: dict = {}     # int(role_id) → str(target_lang)
_channel_cache: dict[int, dict] = {} # int(channel_id) → {"source_lang": str, "target_lang": str, "auto": bool}
_server_vision_cache: dict[int, dict] = {} # {guild_id: {"model": str, "trigger": str}}


# ──────────────────────────────────────────────
# 초기 로드 (봇 시작 시 호출)
# ──────────────────────────────────────────────
async def load_all_settings():
    """봇 시작 시 DB에서 메모리로 전부 로드."""
    global _user_cache, _server_cache, _channel_cache, _server_vision_cache
    db = get_db()

    _user_cache = {}
    async with db.execute("SELECT user_id, lang, auto_translate FROM user_settings") as cursor:
        async for row in cursor:
            _user_cache[row[0]] = {"lang": row[1], "auto": bool(row[2])}

    _server_cache = {}
    async with db.execute("SELECT guild_id, log_channel_id, log_level, ignored_channels FROM server_settings") as cursor:
        async for row in cursor:
            ignored = []
            if row[3]:
                try:
                    ignored = json.loads(row[3])
                except (json.JSONDecodeError, TypeError):
                    ignored = []
            _server_cache[row[0]] = {
                "log_channel_id": row[1],
                "log_level": row[2],
                "ignored_channels": ignored,
            }

    _channel_cache = {}
    async with db.execute("SELECT channel_id, source_lang, target_lang, auto_translate FROM channel_settings") as cursor:
        async for row in cursor:
            _channel_cache[int(row[0])] = { # Assuming row[0] is channel_id, row[1] is source_lang, row[2] is target_lang, row[3] is auto_translate
                "source_lang": row[1],
                "target_lang": row[2],
                "auto": bool(row[3])
            }

    # Vision 캐시 로드
    # Assuming db.execute returns a cursor that can be iterated or fetched as dicts if row_factory is set
    # For consistency with other loads, let's assume row[0], row[1], row[2] for guild_id, vision_model, vision_trigger
    _server_vision_cache = {}
    async with db.execute("SELECT guild_id, vision_model, vision_trigger FROM server_settings") as cursor:
        async for row in cursor:
            _server_vision_cache[int(row[0])] = {
                "model": row[1],
                "trigger": row[2] or "-i"
            }


async def load_role_lang_map():
    """봇 시작 시 역할-언어 매핑을 DB에서 메모리로 로드."""
    global _role_lang_cache
    db = get_db()
    _role_lang_cache = {}
    async with db.execute("SELECT role_id, target_lang FROM role_lang_map") as cursor:
        async for row in cursor:
            _role_lang_cache[row[0]] = row[1]


# ──────────────────────────────────────────────
# 유저 설정
# ──────────────────────────────────────────────
def get_user_lang(user_id: int) -> str:
    return _user_cache.get(str(user_id), {}).get("lang", "Korean")


def get_auto_translate(user_id: int) -> bool:
    return _user_cache.get(str(user_id), {}).get("auto", True)


async def set_user_pref(user_id: int, lang: str = None, auto: bool = None):
    uid = str(user_id)
    current = _user_cache.get(uid, {"lang": "Korean", "auto": True})

    if lang is not None:
        current["lang"] = lang
    if auto is not None:
        current["auto"] = auto

    _user_cache[uid] = current

    db = get_db()
    await db.execute(
        """INSERT OR REPLACE INTO user_settings (user_id, lang, auto_translate)
           VALUES (?, ?, ?)""",
        (uid, current["lang"], int(current["auto"]))
    )
    await db.commit()


async def set_user_lang(user_id: int, language: str):
    await set_user_pref(user_id, lang=language)


async def remove_user_lang(user_id: int) -> bool:
    uid = str(user_id)
    if uid in _user_cache:
        del _user_cache[uid]
        db = get_db()
        await db.execute("DELETE FROM user_settings WHERE user_id = ?", (uid,))
        await db.commit()
        return True
    return False


async def migrate_users_auto_translate():
    """기존 모든 유저의 자동 번역 설정을 '켜짐'으로 업데이트 (이미 꺼둔 사람 제외하고 싶다면 조건 추가 가능하나, 여기선 일괄적으로 켬)"""
    db = get_db()
    await db.execute("UPDATE user_settings SET auto_translate = 1")
    await db.commit()
    # 메모리 캐시도 동기화
    for uid in _user_cache:
        _user_cache[uid]["auto"] = True


def get_all_user_settings() -> dict:
    """모든 유저 설정을 반환 (관리자용 리스트 출력)."""
    return dict(_user_cache)


# ──────────────────────────────────────────────
# 서버 설정
# ──────────────────────────────────────────────
def get_server_config(guild_id: int) -> dict:
    return _server_cache.get(str(guild_id), {})


async def set_server_config(guild_id: int, **kwargs):
    gid = str(guild_id)
    current = _server_cache.get(gid, {
        "log_channel_id": None,
        "log_level": "normal",
        "ignored_channels": [],
    })
    current.update(kwargs)
    _server_cache[gid] = current

    db = get_db()
    ignored_json = json.dumps(current.get("ignored_channels", []))
    await db.execute(
        """INSERT OR REPLACE INTO server_settings (guild_id, log_channel_id, log_level, ignored_channels)
           VALUES (?, ?, ?, ?)""",
        (gid, current.get("log_channel_id"), current.get("log_level", "normal"), ignored_json)
    )
    await db.commit()


def get_log_channel_id(guild_id: int) -> int | None:
    return get_server_config(guild_id).get("log_channel_id")


def get_log_level(guild_id: int) -> str:
    return get_server_config(guild_id).get("log_level", "normal")


def get_ignored_channels(guild_id: int) -> list[int]:
    config = get_server_config(guild_id)
    ignored = config.get("ignored_channels", [])
    if isinstance(ignored, list):
        return ignored
    if isinstance(ignored, str):
        try:
            return json.loads(ignored)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


# ──────────────────────────────────────────────
# 역할-언어 매핑
# ──────────────────────────────────────────────
def get_role_lang(role_id: int) -> str | None:
    return _role_lang_cache.get(role_id)


def get_all_role_langs(guild_id: int = None) -> dict[int, str]:
    return dict(_role_lang_cache)


async def set_role_lang(guild_id: int, role_id: int, target_lang: str):
    db = get_db()
    await db.execute(
        "INSERT OR REPLACE INTO role_lang_map (role_id, guild_id, target_lang) VALUES (?, ?, ?)",
        (role_id, guild_id, target_lang)
    )
    await db.commit()
    _role_lang_cache[role_id] = target_lang


async def remove_role_lang(role_id: int) -> bool:
    if role_id not in _role_lang_cache:
        return False
    db = get_db()
    await db.execute("DELETE FROM role_lang_map WHERE role_id = ?", (role_id,))
    await db.commit()
    del _role_lang_cache[role_id]
    return True


# ──────────────────────────────────────────────
# 채널 설정
# ──────────────────────────────────────────────
def get_channel_config(channel_id: int) -> dict:
    return _channel_cache.get(str(channel_id), {})


async def set_channel_config(channel_id: int, guild_id: int, **kwargs):
    cid = str(channel_id)
    current = _channel_cache.get(cid, {
        "source_lang": None,
        "target_lang": None,
        "auto": False,
    })
    current.update(kwargs)
    _channel_cache[cid] = current

    db = get_db()
    await db.execute(
        """INSERT OR REPLACE INTO channel_settings (channel_id, guild_id, source_lang, target_lang, auto_translate)
           VALUES (?, ?, ?, ?, ?)""",
        (cid, str(guild_id), current.get("source_lang"), current.get("target_lang"), int(current.get("auto")))
    )
    await db.commit()


async def remove_channel_config(channel_id: int) -> bool:
    cid = str(channel_id)
    if cid in _channel_cache:
        del _channel_cache[cid]
        db = get_db()
        await db.execute("DELETE FROM channel_settings WHERE channel_id = ?", (cid,))
        await db.commit()
        return True
    return False


# ── Vision 설정 ──
def get_vision_settings(guild_id: int) -> dict:
    from config import OPENAI_VISION_MODEL, VISION_TRIGGER_PREFIX
    settings = _server_vision_cache.get(guild_id, {})
    return {
        "model": settings.get("model") or OPENAI_VISION_MODEL,
        "trigger": settings.get("trigger") or VISION_TRIGGER_PREFIX
    }

async def set_vision_settings(guild_id: int, model: str = None, trigger: str = None):
    db = get_db()
    settings = get_vision_settings(guild_id)
    new_model = model or settings["model"]
    new_trigger = trigger or settings["trigger"]
    
    await db.execute("""
        INSERT INTO server_settings (guild_id, vision_model, vision_trigger)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            vision_model = excluded.vision_model,
            vision_trigger = excluded.vision_trigger
    """, (str(guild_id), new_model, new_trigger))
    await db.commit()
    
    _server_vision_cache[guild_id] = {"model": new_model, "trigger": new_trigger}
