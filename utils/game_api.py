# game_api.py — Steam / VRChat 프로필 조회 모듈

import asyncio
import aiohttp
import os
import xml.etree.ElementTree as ET
from utils.logger import bot_log

# ──────────────────────────────────────────────
# Steam 프로필 조회 (API 키 불필요)
# ──────────────────────────────────────────────

async def get_steam_profile(profile_url: str) -> dict:
    """
    Steam 커뮤니티 프로필을 XML로 파싱합니다.
    
    Args:
        profile_url: 다음 형식 중 하나:
            - "https://steamcommunity.com/profiles/76561198xxxxxxxxx"
            - "username" (vanity URL로 자동 변환)
            - "76561198xxxxxxxxx" (SteamID64로 자동 변환)
    
    Returns:
        {
            "nickname": str,
            "steam_id": str,
            "status": str,           # Online, Offline, In-Game 등
            "current_game": str | None,
            "summary": str,          # 프로필 요약 (자기소개)
            "avatar_url": str,
            "member_since": str,
            "profile_url": str,
            "error": str | None,
        }
    """
    # URL 정규화
    url = _normalize_steam_url(profile_url)
    xml_url = url.rstrip("/") + "/?xml=1"

    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; TransBot/1.0)"}
            async with session.get(xml_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return {"error": f"Steam 프로필을 가져올 수 없습니다 (HTTP {resp.status})"}
                
                text = await resp.text()
        
        root = ET.fromstring(text)
        
        # 비공개 프로필 체크
        privacy = root.findtext("privacyState", "")
        if privacy and privacy != "public":
            return {
                "nickname": root.findtext("steamID", "Unknown"),
                "steam_id": root.findtext("steamID64", ""),
                "status": "비공개 프로필",
                "current_game": None,
                "summary": "(이 유저의 프로필은 비공개입니다)",
                "avatar_url": root.findtext("avatarFull", ""),
                "member_since": "",
                "profile_url": url,
                "error": None,
            }
        
        # 온라인 상태 파싱
        state_msg = root.findtext("stateMessage", "")
        online_state = root.findtext("onlineState", "offline")
        current_game = root.findtext("inGameInfo/gameName") if root.find("inGameInfo") else None
        
        if current_game:
            status = f"🎮 플레이 중: {current_game}"
        elif online_state == "online":
            status = "🟢 온라인"
        elif online_state == "in-game":
            status = "🎮 게임 중"
        else:
            status = "⚫ 오프라인"
        
        # 요약 텍스트 (HTML 태그 제거)
        import re
        summary_raw = root.findtext("summary", "")
        summary = re.sub(r"<[^>]+>", "", summary_raw).strip()
        summary = summary.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        if not summary or summary == "No information given.":
            summary = "(자기소개 없음)"
        
        # 최근 게임 목록
        recent_games = []
        most_played = root.find("mostPlayedGames")
        if most_played:
            for game in most_played.findall("mostPlayedGame")[:5]:
                name = game.findtext("gameName", "")
                hours = game.findtext("hoursPlayed", "0")
                if name:
                    recent_games.append(f"{name} ({hours}시간)")

        return {
            "nickname": root.findtext("steamID", "Unknown"),
            "steam_id": root.findtext("steamID64", ""),
            "status": status,
            "current_game": current_game,
            "summary": summary,
            "avatar_url": root.findtext("avatarFull", ""),
            "member_since": root.findtext("memberSince", ""),
            "profile_url": url,
            "recent_games": recent_games,
            "error": None,
        }

    except ET.ParseError:
        return {"error": "Steam 프로필 XML 파싱에 실패했습니다. URL을 확인해 주세요."}
    except asyncio.TimeoutError:
        return {"error": "Steam 서버 응답 시간 초과 (10초)"}
    except Exception as e:
        bot_log.error(f"[STEAM] Error: {e}")
        return {"error": f"Steam 프로필 조회 중 오류: {str(e)}"}


def _normalize_steam_url(input_str: str) -> str:
    """다양한 형식의 Steam 입력을 정규 URL로 변환."""
    s = input_str.strip()
    
    # 이미 완전한 URL인 경우
    if s.startswith("https://steamcommunity.com/"):
        return s
    if s.startswith("http://steamcommunity.com/"):
        return s.replace("http://", "https://")
    
    # SteamID64인 경우 (17자리 숫자)
    if s.isdigit() and len(s) == 17:
        return f"https://steamcommunity.com/profiles/{s}"
    
    # Vanity URL (영문/숫자 닉네임)
    return f"https://steamcommunity.com/id/{s}"


# ──────────────────────────────────────────────
# VRChat 프로필 조회 (인증 쿠키 사용)
# ──────────────────────────────────────────────

_VRC_AUTH = os.getenv("VRCHAT_AUTH_COOKIE", "")
_VRC_2FA = os.getenv("VRCHAT_2FA_COOKIE", "")
_VRC_UA = os.getenv("VRCHAT_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
_VRC_BASE = "https://api.vrchat.cloud/api/1"

async def get_vrc_profile(username: str) -> dict:
    """
    VRChat 유저의 상세 정보를 인증된 세션으로 조회합니다.
    """
    if not _VRC_AUTH:
        return {"error": "VRChat 인증 쿠키가 설정되지 않았습니다."}

    cookies = {"auth": _VRC_AUTH, "twoFactorAuth": _VRC_2FA}
    headers = {"User-Agent": _VRC_UA}

    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            # 1. 유저 검색 (userId 획득)
            search_url = f"{_VRC_BASE}/users?search={username}&n=1"
            async with session.get(search_url, headers=headers) as resp:
                if resp.status != 200:
                    return {"error": f"VRChat 검색 실패 (HTTP {resp.status})"}
                
                search_results = await resp.json()
                if not search_results:
                    return {"error": f"'{username}' 이름을 가진 유저를 찾을 수 없습니다."}
                
                target_user = search_results[0]
                user_id = target_user.get("id")

            # 2. 상세 프로필 조회
            profile_url = f"{_VRC_BASE}/users/{user_id}"
            async with session.get(profile_url, headers=headers) as resp:
                if resp.status != 200:
                    return {"error": f"VRChat 상세 조회 실패 (HTTP {resp.status})"}
                
                data = await resp.json()
                
                # 기본 정보
                display_name = data.get("displayName", "Unknown")
                status_desc = data.get("statusDescription", "")
                status = data.get("status", "offline")
                bio = data.get("bio", "")
                
                # 이미지 (우선순위: profilePicOverride > currentAvatarThumbnailImageUrl)
                avatar_url = data.get("profilePicOverride") or data.get("currentAvatarThumbnailImageUrl")
                user_icon = data.get("userIcon")
                
                # 타임라인 및 플랫폼
                last_login = data.get("last_login", "Unknown")
                date_joined = data.get("date_joined", "Unknown")
                last_platform = data.get("last_platform", "standalonewindows")
                tags = data.get("tags", [])
                
                # 위치 정보 분석
                location = data.get("location", "")
                world_id = data.get("worldId")
                instance_id = data.get("instanceId")
                
                world_name = "Private or Offline"
                world_image = None
                
                if world_id and world_id not in ["offline", "private"]:
                    world_data = await get_vrc_world_info(session, world_id)
                    if world_data:
                        world_name = world_data.get("name", "Unknown World")
                        world_image = world_data.get("thumbnailImageUrl")

                return {
                    "user_id": user_id,
                    "display_name": display_name,
                    "status": status.upper(),
                    "status_description": status_desc,
                    "bio": bio,
                    "avatar_url": avatar_url,
                    "user_icon": user_icon,
                    "last_login": last_login,
                    "date_joined": date_joined,
                    "last_platform": last_platform,
                    "tags": tags,
                    "world_name": world_name,
                    "world_image": world_image,
                    "profile_url": f"https://vrchat.com/home/user/{user_id}",
                    "error": None,
                }

    except Exception as e:
        bot_log.error(f"[VRC] API Error: {e}")
        return {"error": f"VRChat 조회 중 오류 발생: {str(e)}"}

async def get_vrc_world_info(session, world_id: str) -> dict:
    """월드 ID로 월드 상세 정보를 조회합니다."""
    url = f"{_VRC_BASE}/worlds/{world_id}"
    headers = {"User-Agent": _VRC_UA}
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.json()
    except:
        pass
    return None
