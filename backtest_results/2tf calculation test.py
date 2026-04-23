import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import sys
from datetime import datetime
from collections import deque

# ================= USER CONFIG =================
MT5_LOGIN = 52621105
MT5_PASSWORD = "m5llC@@6De1yaJ"
MT5_SERVER = "ICMarketsSC-Demo"

SYMBOL = "BTCUSD"

HTF = mt5.TIMEFRAME_M5
LTF = mt5.TIMEFRAME_M1

DI_LEN = 7
ADX_LEN = 7
SLOPE_SMOOTH = 1
# ===============================================

# ============ MT5 INIT ==========================
if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
    print("MT5 init failed")
    sys.exit()

mt5.symbol_select(SYMBOL, True)
print("✅ REALTIME DUAL-TF ENGINE STARTED")

# ============ ADX + DI ==========================
def calculate_adx_di(df, di_len, adx_len):
    high, low, close = df['high'], df['low'], df['close']

    up = high.diff()
    down = -low.diff()

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    tr_rma = tr.ewm(alpha=1/di_len, adjust=False).mean()

    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    plusDI  = 100 * pd.Series(plus_dm).ewm(alpha=1/di_len, adjust=False).mean() / tr_rma
    minusDI = 100 * pd.Series(minus_dm).ewm(alpha=1/di_len, adjust=False).mean() / tr_rma

    dx  = 100 * (plusDI - minusDI).abs() / (plusDI + minusDI).replace(0, np.nan)
    adx = dx.ewm(alpha=1/adx_len, adjust=False).mean()

    return plusDI, minusDI, adx

# ============ TF STATE OBJECT ===================
class TFState:
    def __init__(self, name):
        self.name = name
        self.prev_bar_time = None
        self.prev_adx_close = None
        self.prev_plus_close = None
        self.prev_minus_close = None

        self.adx_buf   = deque(maxlen=SLOPE_SMOOTH)
        self.plus_buf  = deque(maxlen=SLOPE_SMOOTH)
        self.minus_buf = deque(maxlen=SLOPE_SMOOTH)

        self.adx_min = self.adx_max = None
        self.plus_min = self.plus_max = None
        self.minus_min = self.minus_max = None

        self.last_values = None

    def reset_on_new_bar(self, bar_time, adx_c, plus_c, minus_c):
        self.prev_bar_time = bar_time
        self.prev_adx_close = adx_c
        self.prev_plus_close = plus_c
        self.prev_minus_close = minus_c

        self.adx_buf.clear()
        self.plus_buf.clear()
        self.minus_buf.clear()

        self.adx_min = self.adx_max = None
        self.plus_min = self.plus_max = None
        self.minus_min = self.minus_max = None

    def update_realtime(self, adx_rt, plus_rt, minus_rt):
        if self.prev_adx_close is None:
            return

        adx_s   = adx_rt   - self.prev_adx_close
        plus_s  = plus_rt  - self.prev_plus_close
        minus_s = minus_rt - self.prev_minus_close

        self.adx_buf.append(adx_s)
        self.plus_buf.append(plus_s)
        self.minus_buf.append(minus_s)

        adx_s = np.mean(self.adx_buf)
        plus_s = np.mean(self.plus_buf)
        minus_s = np.mean(self.minus_buf)

        self.adx_min = adx_s if self.adx_min is None else min(self.adx_min, adx_s)
        self.adx_max = adx_s if self.adx_max is None else max(self.adx_max, adx_s)

        self.plus_min = plus_s if self.plus_min is None else min(self.plus_min, plus_s)
        self.plus_max = plus_s if self.plus_max is None else max(self.plus_max, plus_s)

        self.minus_min = minus_s if self.minus_min is None else min(self.minus_min, minus_s)
        self.minus_max = minus_s if self.minus_max is None else max(self.minus_max, minus_s)

        self.last_values = (adx_rt, plus_rt, minus_rt, adx_s, plus_s, minus_s)

    def format_line(self, tick_time):
        if self.last_values is None:
            return f"{self.name}: initializing..."

        adx, plus, minus, adx_s, plus_s, minus_s = self.last_values
        t = datetime.fromtimestamp(tick_time).strftime('%H:%M:%S.%f')[:-3]

        return (
            f"{self.name}: {t} | "
            f"ADX:{adx:6.2f} | "
            f"+DI:{plus:6.2f} | "
            f"-DI:{minus:6.2f} | "
            f"ADX_S:{adx_s:+6.3f} | "
            f"+S:{plus_s:+6.3f} | "
            f"-S:{minus_s:+6.3f} | "
            f"+Min/Max:{self.plus_min:+5.2f}/{self.plus_max:+5.2f} | "
            f"-Min/Max:{self.minus_min:+5.2f}/{self.minus_max:+5.2f}"
        )

# ============ INIT TF STATES ====================
htf_state = TFState("HTF")
ltf_state = TFState("LTF")

last_tick_time = 0

# ============ MAIN LOOP =========================
while True:

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None or tick.time_msc == last_tick_time:
        continue
    last_tick_time = tick.time_msc

    # ===== Process both TFs =====
    for tf, state in [(HTF, htf_state), (LTF, ltf_state)]:

        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, 300)
        if rates is None or len(rates) < 50:
            continue

        df = pd.DataFrame(rates)
        plusDI, minusDI, adx = calculate_adx_di(df, DI_LEN, ADX_LEN)

        # Last closed candle time
        bar_time = df.iloc[-2]['time']

        # New candle detection
        if bar_time != state.prev_bar_time:
            state.reset_on_new_bar(
                bar_time,
                adx.iloc[-2],
                plusDI.iloc[-2],
                minusDI.iloc[-2]
            )

        # Realtime update (live candle)
        state.update_realtime(
            adx.iloc[-1],
            plusDI.iloc[-1],
            minusDI.iloc[-1]
        )

# ===== TERMINAL DISPLAY (2-LINE LIVE OVERWRITE) =====
        htf_line = htf_state.format_line(tick.time)
        ltf_line = ltf_state.format_line(tick.time)

# Move cursor up 1 line and clear screen lines
        sys.stdout.write("\033[2F")        # move cursor up 2 lines
        sys.stdout.write("\033[2K")        # clear line
        sys.stdout.write(htf_line + "\n")
        sys.stdout.write("\033[2K")        # clear next line
        sys.stdout.write(ltf_line)

    sys.stdout.flush()
