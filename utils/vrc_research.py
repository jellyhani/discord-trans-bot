import asyncio
import aiohttp
import os
import json
from dotenv import load_dotenv

async def get_full_vrc_info():
    load_dotenv()
    auth = os.getenv("VRCHAT_AUTH_COOKIE")
    two_fa = os.getenv("VRCHAT_2FA_COOKIE")
    ua = os.getenv("VRCHAT_USER_AGENT")
    
    if not auth:
        print("No auth cookie found in .env")
        return

    cookies = {'auth': auth, 'twoFactorAuth': two_fa}
    headers = {'User-Agent': ua}
    
    async with aiohttp.ClientSession(cookies=cookies) as session:
        # 1. Get Self Info to see all available fields
        async with session.get('https://api.vrchat.cloud/api/1/auth/user', headers=headers) as resp:
            data = await resp.json()
            print("\n" + "="*50)
            print("FULL USER DATA SCHEMA (Self):")
            print("="*50)
            print(json.dumps(data, indent=2))
            
            # If in a world, try to get world info
            world_id = data.get('worldId')
            if world_id and world_id != 'offline':
                print(f"\nFetching World Info for: {world_id}")
                async with session.get(f'https://api.vrchat.cloud/api/1/worlds/{world_id}', headers=headers) as w_resp:
                    w_data = await w_resp.json()
                    print("\n" + "="*50)
                    print("FULL WORLD DATA SCHEMA:")
                    print("="*50)
                    print(json.dumps(w_data, indent=2))

if __name__ == "__main__":
    asyncio.run(get_full_vrc_info())
