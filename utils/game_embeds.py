import discord
from datetime import datetime

def create_vrc_profile_embed(data: dict) -> discord.Embed:
    """
    VRChat 프로필 데이터를 바탕으로 화려한 디스코드 임베드 카드를 생성합니다.
    """
    if data.get("error"):
        return discord.Embed(title="VRChat 조회 오류", description=data["error"], color=discord.Color.red())

    status = data.get("status", "OFFLINE").lower()
    
    # 1. 상태별 색상 및 이모지 설정
    color_map = {
        "active": discord.Color.green(),
        "join me": discord.Color.green(),
        "ask me": discord.Color.gold(),
        "busy": discord.Color.red(),
        "offline": discord.Color.light_grey()
    }
    emoji_map = {
        "active": "🟢",
        "join me": "🔵",
        "ask me": "🟡",
        "busy": "🔴",
        "offline": "⚫"
    }
    
    embed_color = color_map.get(status, discord.Color.light_grey())
    status_emoji = emoji_map.get(status, "⚪")
    
    # 2. 임베드 기본 설정
    embed = discord.Embed(
        title=f"{status_emoji} {data['display_name']}",
        description=data.get("status_description", "No status message"),
        url=data.get("profile_url", ""),
        color=embed_color,
        timestamp=datetime.now()
    )
    
    # 3. 이미지 설정
    if data.get("avatar_url"):
        embed.set_thumbnail(url=data["avatar_url"])
    
    if data.get("world_image"):
        embed.set_image(url=data["world_image"])
        
    # 4. 필드 구성
    # 플랫폼 아이콘
    platform = data.get("last_platform", "standalonewindows").lower()
    platform_str = "💻 PC"
    if "android" in platform or "quest" in platform:
        platform_str = "📱 Mobile/Quest"
    elif "ios" in platform:
        platform_str = "🍎 iOS"
        
    embed.add_field(name="Platform", value=platform_str, inline=True)
    
    # 가입일 계산
    try:
        joined_date = data.get("date_joined", "Unknown")
        if joined_date != "Unknown":
            dt = datetime.fromisoformat(joined_date.replace("Z", "+00:00"))
            joined_str = dt.strftime("%Y-%m-%d")
            embed.add_field(name="Joined Date", value=joined_str, inline=True)
    except:
        pass

    # VRC+ 여부 (태그 분석)
    is_vrc_plus = any("system_supporter" in t for t in data.get("tags", []))
    if is_vrc_plus:
        embed.add_field(name="VRC+", value="💎 Supporter", inline=True)

    # 현재 위치한 월드
    world_name = data.get("world_name", "Private or Offline")
    if world_name != "Private or Offline":
        embed.add_field(name="Current Location", value=f"📍 {world_name}", inline=False)

    # 자기소개 (Bio) - 최대 1024자 제한
    bio = data.get("bio", "No bio provided.")
    if len(bio) > 300:
        bio = bio[:300] + "..."
    embed.add_field(name="Bio", value=f"```\n{bio}\n```", inline=False)
    
    embed.set_footer(text="VRChat Profile Card • Real-time Data")
    
    return embed
