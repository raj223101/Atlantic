import random

class ExecutionModel:
    def __init__(self, delay_ms_min=100, delay_ms_max=500, spread_bps=1.0, slippage_bps=0.5):
        self.delay_ms_min = delay_ms_min
        self.delay_ms_max = delay_ms_max
        self.spread_bps = spread_bps
        self.slippage_bps = slippage_bps

    def sample_delay_ms(self) -> int:
        return random.randint(self.delay_ms_min, self.delay_ms_max)

    def apply_execution_costs(self, mid_price: float, side: str = "buy") -> float:
        """
        side: 'buy' or 'sell'
        spread + slippage approximation in bps.
        """
        spread = mid_price * (self.spread_bps / 10000.0)
        slip = mid_price * (self.slippage_bps / 10000.0)

        if side.lower() == "buy":
            return mid_price + spread / 2 + slip
        return mid_price - spread / 2 - slip