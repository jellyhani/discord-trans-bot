# usage_tracker.py — SQLite 기반 사용량 추적 (호출별 누적)

from config import COST_PER_1M, OPENAI_MODEL_SMART, MONTHLY_COST_LIMIT
from database.database import get_db
from datetime import date


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = COST_PER_1M.get(model, {"input": 0, "output": 0})
    cost = (input_tokens / 1_000_000) * rates["input"] + (output_tokens / 1_000_000) * rates["output"]
    return round(cost, 8)


def _is_smart_model(model: str) -> bool:
    return model == OPENAI_MODEL_SMART


async def _ensure_user(uid: str, nickname: str):
    db = get_db()
    await db.execute(
        """INSERT OR IGNORE INTO usage (user_id, last_nickname) VALUES (?, ?)""",
        (uid, nickname)
    )


async def record_usage(
    user_id: int,
    nickname: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    was_correction: bool = False,
):
    db = get_db()
    uid = str(user_id)
    await _ensure_user(uid, nickname)

    this_cost = _calc_cost(model, input_tokens, output_tokens)

    if _is_smart_model(model):
        await db.execute(
            """UPDATE usage SET
                last_nickname = ?,
                smart_input_tokens = smart_input_tokens + ?,
                smart_output_tokens = smart_output_tokens + ?,
                smart_total_calls = smart_total_calls + 1,
                smart_corrections = smart_corrections + ?,
                total_calls = total_calls + 1,
                total_cost_usd = total_cost_usd + ?
            WHERE user_id = ?""",
            (nickname, input_tokens, output_tokens, int(was_correction), this_cost, uid)
        )
    else:
        await db.execute(
            """UPDATE usage SET
                last_nickname = ?,
                mini_input_tokens = mini_input_tokens + ?,
                mini_output_tokens = mini_output_tokens + ?,
                total_calls = total_calls + 1,
                total_cost_usd = total_cost_usd + ?
            WHERE user_id = ?""",
            (nickname, input_tokens, output_tokens, this_cost, uid)
        )

    await db.commit()
    # 일별 통계 통합 기록
    await record_daily_stats(model, input_tokens, output_tokens, is_typo_correction=was_correction)


async def record_cache_hit(user_id: int, nickname: str):
    db = get_db()
    uid = str(user_id)
    await _ensure_user(uid, nickname)
    await db.execute(
        """UPDATE usage SET last_nickname = ?, cache_hits = cache_hits + 1
           WHERE user_id = ?""",
        (nickname, uid)
    )
    await db.commit()
    # 일별 통계 통합 기록
    from config import OPENAI_MODEL
    await record_daily_stats(OPENAI_MODEL, 0, 0, is_cache_hit=True)



async def get_user_usage(user_id: int) -> dict | None:
    db = get_db()
    async with db.execute("SELECT * FROM usage WHERE user_id = ?", (str(user_id),)) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "last_nickname": row[1],
            "stats": {
                "mini_input_tokens": row[2],
                "mini_output_tokens": row[3],
                "smart_input_tokens": row[4],
                "smart_output_tokens": row[5],
                "total_calls": row[6],
                "cache_hits": row[7],
                "smart_corrections": row[8],
                "smart_total_calls": row[9],
            },
            "total_cost_usd": row[10],
        }


async def get_global_usage() -> dict:
    db = get_db()
    async with db.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(mini_input_tokens), 0),
            COALESCE(SUM(mini_output_tokens), 0),
            COALESCE(SUM(smart_input_tokens), 0),
            COALESCE(SUM(smart_output_tokens), 0),
            COALESCE(SUM(total_calls), 0),
            COALESCE(SUM(cache_hits), 0),
            COALESCE(SUM(smart_corrections), 0),
            COALESCE(SUM(smart_total_calls), 0),
            COALESCE(SUM(total_cost_usd), 0)
        FROM usage
    """) as cursor:
        row = await cursor.fetchone()

    return {
        "user_count": row[0],
        "stats": {
            "mini_input_tokens": row[1],
            "mini_output_tokens": row[2],
            "smart_input_tokens": row[3],
            "smart_output_tokens": row[4],
            "total_calls": row[5],
            "cache_hits": row[6],
            "smart_corrections": row[7],
            "smart_total_calls": row[8],
        },
        "total_cost_usd": round(row[9], 6),
    }


async def get_correction_efficiency() -> dict:
    db = get_db()
    async with db.execute("""
        SELECT
            COALESCE(SUM(smart_total_calls), 0),
            COALESCE(SUM(smart_corrections), 0)
        FROM usage
    """) as cursor:
        row = await cursor.fetchone()

    total_smart = row[0]
    total_corrections = row[1]

    if total_smart == 0:
        efficiency = 0.0
    else:
        efficiency = round((total_corrections / total_smart) * 100, 2)

    return {
        "smart_total_calls": total_smart,
        "smart_corrections": total_corrections,
        "efficiency_pct": efficiency,
    }


async def record_daily_stats(
    model: str,
    input_tokens: int,
    output_tokens: int,
    is_cache_hit: bool = False,
    is_typo_correction: bool = False,
):
    """매 번역/캐시히트마다 호출. 일별 통계 누적."""
    db = get_db()
    today = date.today().isoformat()  # "2026-03-14"

    cost = _calc_cost(model, input_tokens, output_tokens) if not is_cache_hit else 0.0

    if _is_smart_model(model):
        await db.execute(
            """INSERT INTO daily_stats (date, total_calls, cache_hits, typo_corrections,
                smart_input_tokens, smart_output_tokens, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_calls = total_calls + excluded.total_calls,
                cache_hits = cache_hits + excluded.cache_hits,
                typo_corrections = typo_corrections + excluded.typo_corrections,
                smart_input_tokens = smart_input_tokens + excluded.smart_input_tokens,
                smart_output_tokens = smart_output_tokens + excluded.smart_output_tokens,
                cost_usd = cost_usd + excluded.cost_usd""",
            (today,
             0 if is_cache_hit else 1,
             1 if is_cache_hit else 0,
             1 if is_typo_correction else 0,
             input_tokens, output_tokens, cost)
        )
    else:
        await db.execute(
            """INSERT INTO daily_stats (date, total_calls, cache_hits,
                mini_input_tokens, mini_output_tokens, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_calls = total_calls + excluded.total_calls,
                cache_hits = cache_hits + excluded.cache_hits,
                mini_input_tokens = mini_input_tokens + excluded.mini_input_tokens,
                mini_output_tokens = mini_output_tokens + excluded.mini_output_tokens,
                cost_usd = cost_usd + excluded.cost_usd""",
            (today,
             0 if is_cache_hit else 1,
             1 if is_cache_hit else 0,
             input_tokens, output_tokens, cost)
        )

    await db.commit()


async def get_daily_stats(days: int = 14) -> list[dict]:
    """최근 N일간 일별 통계 반환."""
    db = get_db()
    async with db.execute(
        """SELECT date, total_calls, cache_hits, typo_corrections,
                mini_input_tokens, mini_output_tokens,
                smart_input_tokens, smart_output_tokens, cost_usd
        FROM daily_stats
        ORDER BY date DESC
        LIMIT ?""",
        (days,)
    ) as cursor:
        rows = await cursor.fetchall()

    result = []
    for row in reversed(rows):  # 오래된 순으로 정렬
        result.append({
            "date": row[0],
            "total_calls": row[1],
            "cache_hits": row[2],
            "typo_corrections": row[3],
            "mini_input_tokens": row[4],
            "mini_output_tokens": row[5],
            "smart_input_tokens": row[6],
            "smart_output_tokens": row[7],
            "cost_usd": row[8],
        })

    return result


async def get_all_user_usage_stats(limit: int = 20) -> list[dict]:
    """모든 유저의 사용량 통계를 가져옴 (비용 순 정렬)."""
    db = get_db()
    async with db.execute("""
        SELECT user_id, last_nickname, total_calls, cache_hits, total_cost_usd
        FROM usage
        ORDER BY total_cost_usd DESC
        LIMIT ?
    """, (limit,)) as cursor:
        rows = await cursor.fetchall()
        
    return [
        {
            "user_id": row[0],
            "nickname": row[1],
            "total_calls": row[2],
            "cache_hits": row[3],
            "total_cost_usd": row[4],
        } for row in rows
    ]


async def get_monthly_usage() -> float:
    """이번 달의 총 사용 비용(USD)을 가져옴."""
    db = get_db()
    today = date.today().isoformat()
    this_month = today[:7]  # "2026-03"
    
    async with db.execute("""
        SELECT SUM(cost_usd) FROM daily_stats
        WHERE date LIKE ?
    """, (f"{this_month}%",)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row and row[0] is not None else 0.0

async def check_budget_exceeded() -> bool:
    """월 예산이 초과되었는지 확인합니다."""
    current_cost = await get_monthly_usage()
    return current_cost >= MONTHLY_COST_LIMIT

