from dotenv import load_dotenv
import os

# .env 파일의 정확한 경로 지정 및 로드 (임포트 전에 수행)
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(root_dir, ".env")
load_dotenv(env_path)

import asyncio
import aiohttp
import sys

# 프로젝트 루트 경로 추가 (utils 임포트용)
sys.path.append(root_dir)

from utils.game_api import get_vrc_profile

async def test_vrc():
    print(f"Loading .env from: {env_path}")
    print("VRChat API 연동 테스트 시작...")
    
    # 본인 닉네임이나 검색할 닉네임
    test_user = "하늘이양" # 리퍼러에서 확인된 검색어
    
    result = await get_vrc_profile(test_user)
    
    if result.get("error"):
        print(f"FAILED: {result['error']}")
    else:
        print("SUCCESS!")
        print(f"  - User ID: {result.get('user_id')}")
        print(f"  - Display Name: {result.get('display_name')}")
        print(f"  - Status: {result.get('status')}")
        print(f"  - Platform: {result.get('last_platform')}")
        print(f"  - Joined: {result.get('date_joined')}")
        print(f"  - World: {result.get('world_name')}")
        print(f"  - Bio: {result.get('bio')[:50]}...")
        print(f"  - Tags: {result.get('tags')[:5]}")

if __name__ == "__main__":
    asyncio.run(test_vrc())
