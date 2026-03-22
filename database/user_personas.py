from database.database import get_db
from datetime import datetime

async def get_user_persona(user_id: int) -> dict:
    """유저의 페르소나 및 멘토 지시사항을 가져옵니다."""
    db = get_db()
    async with db.execute(
        "SELECT first_persona, last_persona, mentor_instruction FROM user_personas WHERE user_id = ?",
        (str(user_id),)
    ) as cursor:
        row = await cursor.fetchone()
        if row:
            return {
                "first_persona": row[0],
                "last_persona": row[1],
                "mentor_instruction": row[2]
            }
        return None

async def save_user_persona(user_id: int, persona: str):
    """유저의 페르소나 분석 결과를 저장합니다. 최초인 경우 first_persona로도 저장합니다."""
    db = get_db()
    existing = await get_user_persona(user_id)
    
    if not existing:
        await db.execute(
            "INSERT INTO user_personas (user_id, first_persona, last_persona) VALUES (?, ?, ?)",
            (str(user_id), persona, persona)
        )
    else:
        await db.execute(
            "UPDATE user_personas SET last_persona = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (persona, str(user_id))
        )
    await db.commit()

async def save_mentor_instruction(user_id: int, instruction: str):
    """유저가 멘토에게 내린 지시사항(말투 등)을 저장합니다."""
    db = get_db()
    existing = await get_user_persona(user_id)
    
    if not existing:
        await db.execute(
            "INSERT INTO user_personas (user_id, mentor_instruction) VALUES (?, ?)",
            (str(user_id), instruction)
        )
    else:
        await db.execute(
            "UPDATE user_personas SET mentor_instruction = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (instruction, str(user_id))
        )
    await db.commit()

async def delete_user_persona(user_id: int):
    """유저의 페르소나 및 지시사항을 완전히 삭제합니다."""
    db = get_db()
    await db.execute("DELETE FROM user_personas WHERE user_id = ?", (str(user_id),))
    await db.commit()
