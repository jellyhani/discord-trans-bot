from database.database import get_db, get_history_db
from datetime import datetime

async def record_chat_log(user_id: int, nickname: str, content: str, channel_id: int):
    """
    모든 채팅 메시지를 역사 DB(history.db)에 기록합니다.
    """
    db = get_history_db()
    await db.execute(
        """INSERT INTO chat_logs (user_id, nickname, content, channel_id, timestamp)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (str(user_id), nickname, content, str(channel_id))
    )
    await db.commit()

async def get_chat_logs(user_id: int, limit: int = None) -> list:
    """
    특정 유저의 대화 기록을 역사 DB(history.db)에서 가져옵니다.
    """
    db = get_history_db()
    query = "SELECT nickname, content, timestamp FROM chat_logs WHERE user_id = ? ORDER BY timestamp DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    async with db.execute(query, (str(user_id),)) as cursor:
        rows = await cursor.fetchall()
        return [{"nickname": r[0], "content": r[1], "timestamp": r[2]} for r in reversed(rows)]

async def get_total_log_count(user_id: int) -> int:
    """역사 DB에 저장된 특정 유저의 메시지 총 개수를 확인합니다."""
    db = get_history_db()
    async with db.execute("SELECT COUNT(*) FROM chat_logs WHERE user_id = ?", (str(user_id),)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0

# ──────────────────────────────────────────────
# [NEW] Mentor Session Management
# ──────────────────────────────────────────────

async def create_session(user_id: int, title: str) -> int:
    """새로운 대화 세션을 생성하고 활성화합니다."""
    db = get_history_db()
    uid = str(user_id)
    
    # 기존 활성 세션 비활성화
    await db.execute("UPDATE mentor_sessions SET is_active = 0 WHERE user_id = ?", (uid,))
    
    # 새 세션 생성
    cursor = await db.execute(
        "INSERT INTO mentor_sessions (user_id, title, is_active) VALUES (?, ?, 1)",
        (uid, title)
    )
    session_id = cursor.lastrowid
    await db.commit()
    return session_id

async def get_sessions(user_id: int, include_deleted: bool = False) -> list[dict]:
    """유저의 모든 세션 목록을 가져옵니다. 기본적으로 삭제되지 않은 것만 반환합니다."""
    db = get_history_db()
    
    query = "SELECT id, title, is_active, created_at, is_deleted FROM mentor_sessions WHERE user_id = ?"
    if not include_deleted:
        query += " AND is_deleted = 0"
    query += " ORDER BY created_at DESC"
    
    async with db.execute(query, (str(user_id),)) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_active_session_id(user_id: int) -> int | None:
    """유저의 현재 활성화된 세션 ID를 가져옵니다. 없으면 첫 세션을 자동 생성합니다."""
    db = get_history_db()
    uid = str(user_id)
    async with db.execute(
        "SELECT id FROM mentor_sessions WHERE user_id = ? AND is_active = 1 AND is_deleted = 0",
        (uid,)
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return row[0]
        
    # 만약 활성 세션이 없으면 하나 만들어줌 (또는 기존 꺼 중 하나 활성화)
    sessions = await get_sessions(user_id)
    if not sessions:
        return await create_session(user_id, "New Conversation")
    
    # 마지막(최신) 세션을 활성화
    session_id = sessions[0]["id"]
    await switch_session(user_id, session_id)
    return session_id

async def archive_session(user_id: int, session_id: int) -> bool:
    """세션을 '소프트 삭제(아카이브)' 처리합니다."""
    db = get_history_db()
    uid = str(user_id)
    
    # 해당 세션이 유저의 것인지 확인
    async with db.execute(
        "SELECT id FROM mentor_sessions WHERE id = ? AND user_id = ?",
        (session_id, uid)
    ) as cursor:
        if not await cursor.fetchone():
            return False
            
    await db.execute("UPDATE mentor_sessions SET is_deleted = 1, is_active = 0 WHERE id = ?", (session_id,))
    await db.commit()
    return True

async def restore_session(user_id: int, session_id: int) -> bool:
    """삭제된 세션을 복구합니다."""
    db = get_history_db()
    uid = str(user_id)
    
    # 해당 세션이 유저의 것인지 확인
    async with db.execute(
        "SELECT id FROM mentor_sessions WHERE id = ? AND user_id = ?",
        (session_id, uid)
    ) as cursor:
        if not await cursor.fetchone():
            return False
            
    await db.execute("UPDATE mentor_sessions SET is_deleted = 0 WHERE id = ?", (session_id,))
    await db.commit()
    return True

async def switch_session(user_id: int, session_id: int) -> bool:
    """활성 세션을 변경합니다."""
    db = get_history_db()
    uid = str(user_id)
    
    # 해당 세션이 유저의 것인지 확인
    async with db.execute(
        "SELECT id FROM mentor_sessions WHERE id = ? AND user_id = ?",
        (session_id, uid)
    ) as cursor:
        if not await cursor.fetchone():
            return False
            
    await db.execute("UPDATE mentor_sessions SET is_active = 0 WHERE user_id = ?", (uid,))
    await db.execute("UPDATE mentor_sessions SET is_active = 1 WHERE id = ?", (session_id,))
    await db.commit()
    return True

async def record_mentor_log(user_id: int, question: str, answer: str):
    """멘토와 나눈 대화를 현재 활성 세션에 기록합니다."""
    db = get_history_db()
    session_id = await get_active_session_id(user_id)
    
    await db.execute(
        "INSERT INTO mentor_logs (user_id, session_id, question, answer, timestamp) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (str(user_id), session_id, question, answer)
    )
    await db.commit()

async def get_mentor_logs(user_id: int, limit: int = None) -> list:
    """현재 활성 세션의 멘토 대화 기록만 가져옵니다."""
    db = get_history_db()
    session_id = await get_active_session_id(user_id)
    
    query = "SELECT question, answer, timestamp FROM mentor_logs WHERE user_id = ? AND session_id = ? ORDER BY timestamp DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    async with db.execute(query, (str(user_id), session_id)) as cursor:
        rows = await cursor.fetchall()
        return [{"question": r[0], "answer": r[1], "timestamp": r[2]} for r in reversed(rows)]

async def delete_mentor_logs(user_id: int):
    """특정 유저의 모든 멘토 대화 기록을 삭제합니다."""
    db = get_history_db()
    await db.execute("DELETE FROM mentor_logs WHERE user_id = ?", (str(user_id),))
    await db.commit()

async def get_all_cache_texts(user_id: int = None, limit: int = None) -> list:
    """
    [PERSONALIZED] 캐시 테이블(bot.db)에서 특정 유저의 원문만 가져옵니다.
    """
    db = get_db()
    if user_id is None:
        # 공용 데이터 배제 원칙에 따라, ID가 없으면 빈 리스트 반환 (또는 필요시 전체)
        return []
        
    query = "SELECT original FROM cache WHERE user_id = ? ORDER BY ROWID DESC"
    if limit:
        query += f" LIMIT {limit}"
        
    async with db.execute(query, (str(user_id),)) as cursor:
        rows = await cursor.fetchall()
        return [r[0] for r in reversed(rows)]

async def get_user_total_history(user_id: int, max_chars: int = 100000) -> str:
    """
    [UNIFIED ENGINE] 공용 데이터를 제외하고 오직 해당 유저의 개인 로그, 개인 캐시, 멘토 로그를 합쳐서 반환합니다.
    [NEW] 삭제되지 않은 세션의 멘토 로그만 포함합니다.
    """
    # 1. 개인 채팅 로그 수집
    user_logs = await get_chat_logs(user_id)
    
    # 2. 멘토 로그 수집 (모든 비삭제 세션)
    db = get_history_db()
    mentor_logs = []
    async with db.execute("""
        SELECT question, answer, timestamp 
        FROM mentor_logs 
        WHERE user_id = ? AND session_id IN (SELECT id FROM mentor_sessions WHERE user_id = ? AND is_deleted = 0)
        ORDER BY timestamp DESC
    """, (str(user_id), str(user_id))) as cursor:
        rows = await cursor.fetchall()
        mentor_logs = [{"question": r[0], "answer": r[1], "timestamp": r[2]} for r in reversed(rows)]
    
    # 3. 개인용 캐시 수집 (번역 기록)
    user_cache = await get_all_cache_texts(user_id=user_id)
    
    combined = []
    
    # 개인 채팅 로그 추가 (시간 정보 포함)
    for log in user_logs:
        # timestamp format: 2024-03-19 11:10:33
        time_str = log['timestamp']
        hour = time_str.split(" ")[1].split(":")[0] if " " in time_str else "??"
        combined.append(f"[{hour}h] Chat: {log['content']}")
        
    # 멘토 로그 추가
    for log in mentor_logs:
        time_str = log['timestamp']
        hour = time_str.split(" ")[1].split(":")[0] if " " in time_str else "??"
        combined.append(f"[{hour}h] Mentor Question: {log['question']}")
        combined.append(f"[{hour}h] Mentor Answer: {log['answer']}")
        
    # 개인 번역 로그 추가
    for text in user_cache:
        combined.append(f"[??h] Translation: {text}")
        
    full_text = "\n".join(combined)
    
    if len(full_text) > max_chars:
        return full_text[:max_chars]
    
    return full_text
