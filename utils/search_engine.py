import asyncio
from duckduckgo_search import DDGS
from utils.logger import bot_log

async def search_web(query: str, max_results: int = 10, region: str = "wt-wt") -> str:
    """
    DuckDuckGo를 사용하여 웹 검색을 수행합니다.
    region: 'kr-kr', 'us-en', 'jp-jp', 'wt-wt' 등 (기본값 wt-wt)
    """
    try:
        loop = asyncio.get_event_loop()
        
        # 지역 코드 보정 (간단한 매핑)
        region_map = {
            "kr": "kr-kr", "ko": "kr-kr",
            "us": "us-en", "en": "us-en",
            "jp": "jp-jp", "ja": "jp-jp",
            "cn": "cn-zh", "zh": "cn-zh",
            "tw": "tw-tzh",
        }
        r_code = region_map.get(region.lower(), region)

        def _sync_search():
            with DDGS() as ddgs:
                results = list(ddgs.text(query, region=r_code, max_results=max_results))
                return results
                
        results = await loop.run_in_executor(None, _sync_search)
        
        if not results:
            return "검색 결과가 없습니다."
            
        formatted_results = []
        for i, res in enumerate(results, 1):
            title = res.get('title', 'No Title')
            snippet = res.get('body', 'No Snippet')
            link = res.get('href', '#')
            formatted_results.append(f"[{i}] {title}\nURL: {link}\nSnippet: {snippet}\n")
            
        return "\n".join(formatted_results)
        
    except Exception as e:
        bot_log.error(f"[SEARCH-ERROR] {e}")
        return f"검색 중 오류가 발생했습니다: {str(e)}"

# 간단한 테스트를 위한 메인
if __name__ == "__main__":
    async def main():
        res = await search_web("오늘 서울 날씨")
        print(res)
    asyncio.run(main())
