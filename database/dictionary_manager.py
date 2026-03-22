# dictionary_manager.py — 오타/축약어/어미 사전 관리 (DB + 메모리 캐시)

from database.database import get_db

# 메모리 캐시 (봇 시작 시 DB에서 로드, 변경 시 즉시 반영)
_typo_words: set[str] = set()
_abbreviations: set[str] = set()
_suspicious_endings: list[str] = []


async def load_all() -> None:
    """봇 시작 시 DB에서 메모리로 로드."""
    global _typo_words, _abbreviations, _suspicious_endings
    db = get_db()

    _typo_words = set()
    async with db.execute("SELECT word FROM typo_words") as cursor:
        async for row in cursor:
            _typo_words.add(row[0])

    _abbreviations = set()
    async with db.execute("SELECT word FROM abbreviations") as cursor:
        async for row in cursor:
            _abbreviations.add(row[0])

    _suspicious_endings = []
    async with db.execute("SELECT pattern FROM suspicious_endings") as cursor:
        async for row in cursor:
            _suspicious_endings.append(row[0])


async def seed_defaults() -> None:
    """DB가 비어있으면 기본값 삽입. 마이그레이션 시 1회만 실행."""
    db = get_db()

    # 이미 데이터가 있으면 스킵
    async with db.execute("SELECT COUNT(*) FROM typo_words") as cursor:
        count = (await cursor.fetchone())[0]
    if count > 0:
        return

    default_typo_words = [
        "뱌보", "뱌봐", "기엽", "명쳥", "멍쳥",
        "냐는", "냐가", "냐도", "냐랑", "냐한테",
        "졍말", "쩡말", "졍짜",
        "슙니다", "읍니다", "슴니다", "습니댜",
        "하겟", "하겟슴", "하겟습",
        "갈으", "갈은", "간으", "간은",
        "모르겟", "모르겟슴",
        "안녀", "안녕하새요", "안녕하삼",
        "감삼", "감사함다", "감사합니댜",
        "네넹", "넹", "넵", "욥", "앙녕",
        "고맙숩", "고맙슴",
        "사랑행", "사랑햄",
        "미안햄", "미안행",
        "뭐햄", "뭐행",
        "재밌겟", "재밋", "재밌슴",
        "먹겟", "먹겟슴", "했늠", "했는뎅",
        "없늠", "있늠", "했슴", "했읍",
        "ㄱㅅ", "ㄴㄴ", "ㅈㄹ", "ㅁㄹ", "ㅎㅇ", "반갑노",
    ]

    default_abbreviations = [
        "ㄱㄱ", "ㄱㄷ", "ㄱㅊ", "ㄱㅅ",
        "ㄴㄴ", "ㄴㅇ",
        "ㄷㄷ",
        "ㄹㅇ",
        "ㅁㄹ", "ㅁㅊ",
        "ㅂㅂ", "ㅂㅇ",
        "ㅅㄱ", "ㅅㅂ", "ㅅㅍ",
        "ㅇㅇ", "ㅇㅈ", "ㅇㅋ", "ㅇㅎ",
        "ㅈㄹ", "ㅈㅅ", "ㅈㄱ", "ㄹㅈㄷ",
        "ㅊㅋ",
        "ㅌㅌ",
        "ㅍㅍ",
        "ㅎㄹ",
    ]

    default_endings = [
        r'겟[^다]?$', r'겟슴', r'겟습',
        r'했늠', r'있늠', r'없늠', r'했슴', r'했읍',
        r'습니댜', r'합니댜', r'됩니댜',
        r'하새요', r'하삼$', r'함다$',
        r'해용$', r'해행$', r'해햄$',
        r'인뎅', r'는뎅', r'한뎅',
        r'[가-힣]+노[?!.]*$', r'[가-힣]+나[?!.]*$',  # Dialect endings
        r'ㅎㅇ', r'ㅂㅇ', r'ㅃㅇ',                # short slang
    ]

    for word in default_typo_words:
        await db.execute("INSERT OR IGNORE INTO typo_words (word) VALUES (?)", (word,))
    for word in default_abbreviations:
        await db.execute("INSERT OR IGNORE INTO abbreviations (word) VALUES (?)", (word,))
    for pattern in default_endings:
        await db.execute("INSERT OR IGNORE INTO suspicious_endings (pattern) VALUES (?)", (pattern,))

    await db.commit()
    await load_all()


# ──────────────────────────────────────────────
# 조회 (메모리에서, typo_detector가 사용)
# ──────────────────────────────────────────────
def get_typo_words() -> set[str]:
    return _typo_words


def get_abbreviations() -> set[str]:
    return _abbreviations


def get_suspicious_endings() -> list[str]:
    return _suspicious_endings


# ──────────────────────────────────────────────
# 추가/삭제 (DB + 메모리 동시 반영)
# ──────────────────────────────────────────────
async def add_typo_word(word: str) -> bool:
    if word in _typo_words:
        return False
    db = get_db()
    await db.execute("INSERT OR IGNORE INTO typo_words (word) VALUES (?)", (word,))
    await db.commit()
    _typo_words.add(word)
    return True


async def remove_typo_word(word: str) -> bool:
    if word not in _typo_words:
        return False
    db = get_db()
    await db.execute("DELETE FROM typo_words WHERE word = ?", (word,))
    await db.commit()
    _typo_words.discard(word)
    return True


async def add_abbreviation(word: str) -> bool:
    if word in _abbreviations:
        return False
    db = get_db()
    await db.execute("INSERT OR IGNORE INTO abbreviations (word) VALUES (?)", (word,))
    await db.commit()
    _abbreviations.add(word)
    return True


async def remove_abbreviation(word: str) -> bool:
    if word not in _abbreviations:
        return False
    db = get_db()
    await db.execute("DELETE FROM abbreviations WHERE word = ?", (word,))
    await db.commit()
    _abbreviations.discard(word)
    return True


async def add_ending(pattern: str) -> bool:
    if pattern in _suspicious_endings:
        return False
    db = get_db()
    await db.execute("INSERT OR IGNORE INTO suspicious_endings (pattern) VALUES (?)", (pattern,))
    await db.commit()
    _suspicious_endings.append(pattern)
    return True


async def remove_ending(pattern: str) -> bool:
    if pattern not in _suspicious_endings:
        return False
    db = get_db()
    await db.execute("DELETE FROM suspicious_endings WHERE pattern = ?", (pattern,))
    await db.commit()
    _suspicious_endings.remove(pattern)
    return True


# ──────────────────────────────────────────────
# [NEW] Custom Slang (Guild-specific)
# ──────────────────────────────────────────────
async def get_custom_slang(guild_id: str) -> dict[str, str]:
    """해당 서버의 커스텀 줄임말 사전 가져오기."""
    db = get_db()
    slang_dict = {}
    async with db.execute("SELECT short_form, full_meaning FROM custom_slang WHERE guild_id = ?", (str(guild_id),)) as cursor:
        async for row in cursor:
            slang_dict[row[0]] = row[1]
    return slang_dict


async def add_custom_slang(guild_id: str, short_form: str, full_meaning: str) -> None:
    db = get_db()
    await db.execute(
        "INSERT OR REPLACE INTO custom_slang (guild_id, short_form, full_meaning) VALUES (?, ?, ?)",
        (str(guild_id), short_form, full_meaning)
    )
    await db.commit()


async def remove_custom_slang(guild_id: str, short_form: str) -> bool:
    db = get_db()
    async with db.execute("SELECT 1 FROM custom_slang WHERE guild_id = ? AND short_form = ?", (str(guild_id), short_form)) as cursor:
        if not await cursor.fetchone():
            return False
    
    await db.execute("DELETE FROM custom_slang WHERE guild_id = ? AND short_form = ?", (str(guild_id), short_form))
    await db.commit()
    return True
