# ghost_client.py — 디스코드 유저 프로필(Bio) 비공식 조회 모듈
# [경고] 이 모듈은 Discord TOS 회색 영역에서 작동합니다.
# 반드시 더미 계정 토큰만 사용하세요.

import os
import time
import asyncio
import aiohttp
import random
from utils.logger import bot_log

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
_USER_TOKEN = os.getenv("DISCORD_USER_TOKEN", "")
_API_BASE = "https://discord.com/api/v9"

# 브라우저 위장 헤더
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
    "X-Discord-Locale": "ko",
    "X-Discord-Timezone": "Asia/Seoul",
    "X-Super-Properties": (
        "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiRmlyZWZveCIsImRldmljZSI6IiIs"
        "InN5c3RlbV9sb2NhbGUiOiJrby1LUiIsImhhc19jbGllbnRfbW9kcyI6ZmFsc2Us"
        "ImJyb3dzZXJfdXNlcl9hZ2VudCI6Ik1vemlsbGEvNS4wIChXaW5kb3dzIE5UIDEw"
        "LjA7IFdpbjY0OyB4NjQ7IHJ2OjE0OS4wKSBHZWNrby8yMDEwMDEwMSBGaXJlZm94"
        "LzE0OS4wIiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTQ5LjAiLCJvc192ZXJzaW9uIjoi"
        "MTAiLCJyZWZlcnJlciI6IiIsInJlZmVycmluZ19kb21haW4iOiIiLCJyZWZlcnJl"
        "cl9jdXJyZW50IjoiIiwicmVmZXJyaW5nX2RvbWFpbl9jdXJyZW50IjoiIiwicmVs"
        "ZWFzZV9jaGFubmVsIjoic3RhYmxlIiwiY2xpZW50X2J1aWxkX251bWJlciI6NTIz"
        "MDYxLCJjbGllbnRfZXZlbnRfc291cmNlIjpudWxsfQ=="
    ),
}

# ──────────────────────────────────────────────
# 캐시 (TTL 1시간)
# ──────────────────────────────────────────────
_CACHE: dict[str, dict] = {}
_CACHE_TTL = 3600  # 1시간


def _get_cached(user_id: str) -> dict | None:
    entry = _CACHE.get(user_id)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    _CACHE.pop(user_id, None)
    return None


def _set_cached(user_id: str, data: dict):
    _CACHE[user_id] = {"data": data, "ts": time.time()}


# ──────────────────────────────────────────────
# API 호출
# ──────────────────────────────────────────────
async def fetch_discord_profile(user_id: int | str, force: bool = False) -> dict:
    """
    디스코드 Internal API를 통해 유저의 상세 프로필을 조회합니다.
    """
    uid = str(user_id)

    # 캐시 확인 (force가 True면 무시)
    if not force:
        cached = _get_cached(uid)
        if cached:
            bot_log.info(f"[GHOST] Cache hit for {uid}")
            return cached
    else:
        bot_log.info(f"[GHOST] Force refresh for {uid}")

    if not _USER_TOKEN:
        return {"error": "DISCORD_USER_TOKEN이 .env에 설정되지 않았습니다."}

    # 봇 감지 회피를 위한 랜덤 딜레이
    await asyncio.sleep(random.uniform(0.5, 1.5))

    headers = {**_HEADERS, "Authorization": _USER_TOKEN}

    try:
        async with aiohttp.ClientSession() as session:
            url = f"{_API_BASE}/users/{uid}/profile?with_mutual_guilds=true&with_mutual_friends_count=true"
            async with session.get(url, headers=headers) as resp:
                bot_log.info(f"[GHOST] GET {uid} → {resp.status}")

                if resp.status == 200:
                    data = await resp.json()
                    result = _parse_profile(data)
                    _set_cached(uid, result)
                    return result

                elif resp.status == 401:
                    return {"error": "❌ 유저 토큰이 만료되었습니다. .env의 DISCORD_USER_TOKEN을 갱신해 주세요."}
                elif resp.status == 403:
                    return {"error": "❌ 이 유저의 프로필에 접근할 수 없습니다. (서버 미참가 또는 차단됨)"}
                elif resp.status == 404:
                    return {"error": "❌ 존재하지 않는 유저 ID입니다."}
                elif resp.status == 429:
                    retry_after = (await resp.json()).get("retry_after", 60)
                    return {"error": f"⏳ 요청 제한에 걸렸습니다. {retry_after}초 후 다시 시도해 주세요."}
                else:
                    body = await resp.text()
                    return {"error": f"❌ 알 수 없는 오류 (HTTP {resp.status}): {body[:200]}"}

    except aiohttp.ClientError as e:
        bot_log.error(f"[GHOST] Network error: {e}")
        return {"error": f"네트워크 오류: {str(e)}"}
    except Exception as e:
        bot_log.error(f"[GHOST] Unexpected error: {e}")
        return {"error": f"예상치 못한 오류: {str(e)}"}


def _parse_profile(data: dict) -> dict:
    """Internal API 응답을 깔끔한 딕셔너리로 변환."""
    user = data.get("user", {})
    profile = data.get("user_profile", {})

    # 아바타 URL 조립
    avatar_hash = user.get("avatar")
    avatar_url = None
    if avatar_hash:
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        avatar_url = f"https://cdn.discordapp.com/avatars/{user.get('id')}/{avatar_hash}.{ext}?size=256"

    # 연동된 계정 (Steam, Twitch 등)
    connected = []
    for acc in data.get("connected_accounts", []):
        acc_type = acc.get("type", "unknown")
        acc_name = acc.get("name", "")
        acc_id = acc.get("id", "")
        
        # 서비스별 URL 조립
        url = None
        if acc_type == "steam":
            url = f"https://steamcommunity.com/profiles/{acc_id}"
        elif acc_type == "twitch":
            url = f"https://www.twitch.tv/{acc_name}"
        elif acc_type == "youtube":
            url = f"https://www.youtube.com/channel/{acc_id}"
        elif acc_type == "github":
            url = f"https://github.com/{acc_name}"
        elif acc_type == "spotify":
            url = f"https://open.spotify.com/user/{acc_id}"
        elif acc_type == "twitter":
            url = f"https://twitter.com/i/user/{acc_id}"
        elif acc_type == "reddit":
            url = f"https://www.reddit.com/u/{acc_name}"
        elif acc_type == "xbox":
            url = f"https://account.xbox.com/en-us/profile?gamerTag={acc_name}"

        connected.append({
            "type": acc_type,
            "name": acc_name,
            "id": acc_id,
            "url": url,
        })

    return {
        "username": user.get("username", ""),
        "global_name": user.get("global_name"),
        "bio": profile.get("bio", ""),
        "banner_color": profile.get("accent_color") or user.get("accent_color"),
        "avatar_url": avatar_url,
        "mutual_guilds": [g.get("id") for g in data.get("mutual_guilds", [])],
        "connected_accounts": connected,
        "error": None,
    }
