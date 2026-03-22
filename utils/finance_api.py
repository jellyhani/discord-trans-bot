import yfinance as yf
import asyncio
import logging

logger = logging.getLogger("FinanceAPI")

async def get_finance_data(symbol: str) -> str:
    """
    yfinance를 사용하여 주식 시세 또는 환율 정보를 가져옵니다.
    """
    try:
        loop = asyncio.get_event_loop()
        
        def _fetch():
            ticker = yf.Ticker(symbol)
            # fast_info 또는 history(period='1d') 사용
            hist = ticker.history(period='1d')
            if hist.empty:
                return None
            
            latest = hist.iloc[-1]
            current_price = latest['Close']
            prev_close = hist['Open'].iloc[-1] # 단순화를 위해 시가 대비
            change = current_price - prev_close
            change_pct = (change / prev_close) * 100
            
            # 종목 이름 (정식 명칭)
            info = ticker.info
            name = info.get('longName', symbol)
            currency = info.get('currency', '단위미상')
            
            return {
                "name": name,
                "price": f"{current_price:,.2f} {currency}",
                "change": f"{change:+.2f} ({change_pct:+.2f}%)",
                "time": latest.name.strftime('%Y-%m-%d %H:%M:%S')
            }

        data = await loop.run_in_executor(None, _fetch)
        
        if not data:
            return f"'{symbol}'에 대한 금융 데이터를 찾을 수 없습니다. (예: 삼성전자는 005930.KS, 애플은 AAPL)"
            
        return (
            f"📈 {data['name']} 실시간 정보\n"
            f"현재가: {data['price']}\n"
            f"변동: {data['change']}\n"
            f"기준 시간: {data['time']}"
        )

    except Exception as e:
        logger.error(f"Finance API Error: {e}")
        return f"금융 데이터 조회 중 오류가 발생했습니다: {str(e)}"

async def get_exchange_rate(pair: str = "USDKRW=X") -> str:
    """
    환율 정보를 가져옵니다. (기본값: 원/달러)
    """
    return await get_finance_data(pair)
