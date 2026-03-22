import aiohttp
import logging

logger = logging.getLogger("WeatherAPI")

async def get_weather(location: str) -> str:
    """
    wttr.in API를 사용하여 특정 지역의 날씨 정보를 가져옵니다.
    """
    try:
        # wttr.in은 URL에 도시 이름을 넣으면 해당 지역 날씨를 반환합니다.
        # format=v2 또는 format=j1(JSON) 가능. 여기서는 읽기 쉬운 v2 형식을 한글로 요청합니다.
        url = f"https://wttr.in/{location}?lang=ko&format=%C+%t+습도:%h+풍속:%w"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.text()
                    if "Unknown location" in data:
                        return f"'{location}' 지역을 찾을 수 없습니다. 영문 도시명(예: Taipei, Seoul)으로 시도해 보세요."
                    return f"현재 {location} 날씨: {data}"
                else:
                    return f"날씨 정보를 가져오는 중 오류가 발생했습니다. (HTTP {response.status})"
    except Exception as e:
        logger.error(f"Weather API Error: {e}")
        return f"날씨 검색 중 기술적 내부 오류가 발생했습니다: {str(e)}"
