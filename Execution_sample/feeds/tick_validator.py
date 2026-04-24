import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, time as dtime
from config import INSTRUMENTS

_MARKET_START = dtime(9, 15)
_MARKET_END   = dtime(15, 30)

def _market() -> bool:
    return _MARKET_START <= datetime.now().time() <= _MARKET_END


class TickValidator:

    _last_price : dict = {}
    _last_ts    : dict = {}

    @staticmethod
    def validate(symbol: str, ltp: float, ts: datetime, source: str) -> bool:
        if ltp <= 0:
            return False

        prev_price = TickValidator._last_price.get(symbol)
        if prev_price:
            limit = INSTRUMENTS.get(symbol, {}).get("price_limit", 5000)
            if abs(ltp - prev_price) > limit:
                return False

        prev_ts = TickValidator._last_ts.get(symbol)
        if prev_ts and ts < prev_ts:
            return False

        TickValidator._last_price[symbol] = ltp
        TickValidator._last_ts[symbol]    = ts
        return True

    @staticmethod
    def reset(symbol: str):
        TickValidator._last_price.pop(symbol, None)
        TickValidator._last_ts.pop(symbol, None)