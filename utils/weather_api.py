import aiohttp
import logging
import urllib.parse

logger = logging.getLogger("WeatherAPI")

import asyncio

def get_pm10_status(value: float) -> str:
    if value <= 30: return "좋음 🔵"
    elif value <= 80: return "보통 🟢"
    elif value <= 150: return "나쁨 🟡"
    return "매우나쁨 🔴"

def get_pm25_status(value: float) -> str:
    if value <= 15: return "좋음 🔵"
    elif value <= 35: return "보통 🟢"
    elif value <= 75: return "나쁨 🟡"
    return "매우나쁨 🔴"

async def get_air_quality_by_coords(session: aiohttp.ClientSession, lat: str, lon: str) -> str:
    """Open-Meteo API를 통해 미세먼지 정보를 반환."""
    try:
        aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=pm10,pm2_5"
        async with session.get(aqi_url) as resp:
            if resp.status != 200:
                logger.warning(f"AQI API returned status {resp.status} for {lat},{lon}")
                return ""
            aqi_data = await resp.json()
            
            current = aqi_data.get("current", {})
            pm10 = current.get("pm10")
            pm2_5 = current.get("pm2_5")
            
            if pm10 is None or pm2_5 is None:
                logger.warning(f"AQI data missing for {lat},{lon}")
                return ""
            
            return f"\n😷 <b>미세먼지(PM10)</b>: {pm10} ({get_pm10_status(pm10)}) | <b>초미세먼지(PM2.5)</b>: {pm2_5} ({get_pm25_status(pm2_5)})"
    except Exception as e:
        logger.warning(f"Failed to fetch AQI for coords {lat},{lon}: {e}")
        return ""

async def get_weather(location: str) -> str:
    """
    wttr.in API(JSON)로 날씨와 좌표를 구한 뒤, Open-Meteo API로 미세먼지를 연계 조회합니다.
    """
    if not location:
        return "조회할 지역명을 입력해주세요."

    try:
        encoded_location = urllib.parse.quote(location)
        async with aiohttp.ClientSession() as session:
            # 1. wttr.in에서 JSON 데이터를 가져옴 (좌표 포함)
            url = f"https://wttr.in/{encoded_location}?format=j1&lang=ko"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if not data.get("current_condition") or not data.get("nearest_area"):
                        return f"'{location}' 지역의 날씨 정보를 찾을 수 없습니다. 영문 도시명(예: Seoul, Tokyo)으로 정확히 시도해 보세요."
                    
                    current = data["current_condition"][0]
                    area = data["nearest_area"][0]
                    
                    lat = area.get("latitude")
                    lon = area.get("longitude")
                    
                    if not lat or not lon:
                        logger.warning(f"Coordinates missing for {location}")
                        # 좌표가 없어도 날씨 정보는 표시 시도
                        lat, lon = None, None

                    temp = current.get("temp_C", "?")
                    humidity = current.get("humidity", "?")
                    wind = current.get("windspeedKmph", "?")
                    
                    # 한국어 설명 우선, 없으면 영어 설명 사용
                    desc = "알 수 없음"
                    if "lang_ko" in current and current["lang_ko"]:
                        desc = current["lang_ko"][0].get("value", desc)
                    elif "weatherDesc" in current and current["weatherDesc"]:
                        desc = current["weatherDesc"][0].get("value", desc)
                    
                    wttr_str = f"현재 **{location}** 날씨: {desc}   +{temp}°C 습도:{humidity}% 풍속:{wind}km/h"
                    
                    # 2. 얻은 좌표로 미세먼지 조회 (좌표가 있을 때만)
                    aqi_str = ""
                    if lat and lon:
                        aqi_str = await get_air_quality_by_coords(session, lat, lon)
                    
                    return f"{wttr_str}{aqi_str}"
                elif response.status == 500:
                    return f"'{location}' 지역을 조회할 수 없습니다. 지역명을 확인하거나 잠시 후 다시 시도해 주세요. (서버 내부 오류)"
                else:
                    return f"날씨 정보를 가져오는 중 오류가 발생했습니다. (HTTP {response.status})"
                    
    except Exception as e:
        logger.error(f"Weather API Error for {location}: {e}", exc_info=True)
        return f"날씨 검색 중 기술적 내부 오류가 발생했습니다: {str(e)}"
