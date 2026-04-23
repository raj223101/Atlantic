import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import sys
from datetime import datetime
from collections import deque

# ================= USER CONFIG =================
MT5_LOGIN = 52621105
MT5_PASSWORD = "m5llC@@6De1yaJ"
MT5_SERVER = "ICMarketsSC-Demo"

SYMBOL = "BTCUSD"
TIMEFRAME = mt5.TIMEFRAME_M1

# INDICATOR SETTINGS
DI_LEN = 7
SLOPE_SMOOTH = 1
EXIT_THRESHOLD = 3.5 

# TESTING MODE
# Set True to read actual BUY/SELL trades from your MT5 terminal.
# Set False to force the bot to pretend it has the position specified in MANUAL_TEST_POSITION.
AUTO_DETECT_MT5_POSITION = True 

# Only used if AUTO_DETECT is False
MANUAL_TEST_POSITION = "BUY"  # Options: "BUY", "SELL", None
# ===============================================

class ExitEngine:
    """
    Unified Exit Engine.
    Handles both BUY and SELL logic statefully.
    """
    def __init__(self, slope_smooth_len=1):
        self.slope_smooth_len = slope_smooth_len
        
        # State: Previous Bar Closing Values
        self.prev_bar_time = None
        self.prev_close_di_plus = None
        self.prev_close_di_minus = None

        # State: Current Bar Buffers
        self.slope_plus_buf = deque(maxlen=slope_smooth_len)
        self.slope_minus_buf = deque(maxlen=slope_smooth_len)
        
        # Dashboard Stats
        self.stats = {
            "dlp_max": -999.0, "dlp_min": 999.0,
            "dlm_max": -999.0, "dlm_min": 999.0,
            "current_dl_plus": 0.0,
            "current_dl_minus": 0.0,
            "di_plus": 0.0,
            "di_minus": 0.0
        }

    def on_new_bar(self, bar_time, close_di_plus, close_di_minus):
        """Reset internal stats on new candle."""
        self.prev_bar_time = bar_time
        self.prev_close_di_plus = close_di_plus
        self.prev_close_di_minus = close_di_minus
        
        self.slope_plus_buf.clear()
        self.slope_minus_buf.clear()
        
        # Reset min/max trackers for the new minute
        self.stats["dlp_max"] = -999.0; self.stats["dlp_min"] = 999.0
        self.stats["dlm_max"] = -999.0; self.stats["dlm_min"] = 999.0

    def evaluate(self, tick_time, current_di_plus, current_di_minus, current_position):
        """
        Calculates slopes and checks exit conditions based on current_position.
        """
        # 1. Guard: Need history
        if self.prev_close_di_plus is None:
            return None

        # 2. Calculate Slopes (Realtime - Prev Close)
        raw_slope_plus = current_di_plus - self.prev_close_di_plus
        raw_slope_minus = current_di_minus - self.prev_close_di_minus

        self.slope_plus_buf.append(raw_slope_plus)
        self.slope_minus_buf.append(raw_slope_minus)
        
        dl_plus = np.mean(self.slope_plus_buf)
        dl_minus = np.mean(self.slope_minus_buf)

        # 3. Update Stats
        self.stats["current_dl_plus"] = dl_plus
        self.stats["current_dl_minus"] = dl_minus
        self.stats["di_plus"] = current_di_plus
        self.stats["di_minus"] = current_di_minus
        
        self.stats["dlp_max"] = max(self.stats["dlp_max"], dl_plus)
        self.stats["dlp_min"] = min(self.stats["dlp_min"], dl_plus)
        self.stats["dlm_max"] = max(self.stats["dlm_max"], dl_minus)
        self.stats["dlm_min"] = min(self.stats["dlm_min"], dl_minus)

        # 4. EXIT LOGIC
        exit_signal = None
        
        if current_position == "BUY":
            # BUY EXIT: Watch DL- Slope
            if dl_minus >= EXIT_THRESHOLD:
                exit_signal = "EXIT_BUY"
                
        elif current_position == "SELL":
            # SELL EXIT: Watch DL+ Slope
            if dl_plus >= EXIT_THRESHOLD:
                exit_signal = "EXIT_SELL"

        return exit_signal

# ============ HELPER: MT5 POSITION CHECK ============
def get_mt5_position_type(symbol):
    """Returns 'BUY', 'SELL', or None based on actual MT5 open positions."""
    positions = mt5.positions_get(symbol=symbol)
    if positions is None or len(positions) == 0:
        return None
    
    # Just take the first position found for this symbol
    pos = positions[0]
    if pos.type == mt5.ORDER_TYPE_BUY:
        return "BUY"
    elif pos.type == mt5.ORDER_TYPE_SELL:
        return "SELL"
    return None

# ============ CALCULATIONS ============
def calculate_di_series(df, length):
    high, low, close = df['high'], df['low'], df['close']
    up = high.diff()
    down = -low.diff()
    
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    plus_dm = np.where((up > down) & (up > 0), up, 0)
    minus_dm = np.where((down > up) & (down > 0), down, 0)

    tr_rma = tr.ewm(alpha=1/length, adjust=False).mean()
    plus_dm_rma = pd.Series(plus_dm).ewm(alpha=1/length, adjust=False).mean()
    minus_dm_rma = pd.Series(minus_dm).ewm(alpha=1/length, adjust=False).mean()

    tr_rma = tr_rma.replace(0, np.nan)
    return 100 * (plus_dm_rma / tr_rma), 100 * (minus_dm_rma / tr_rma)

# ============ DASHBOARD ============
def print_dashboard(engine, signal, position, timestamp):
    s = engine.stats
    dt = datetime.fromtimestamp(timestamp)
    time_str = dt.strftime('%H:%M:%S.%f')[:-3]
    
    if position == "BUY":
        mode_str = "ACTIVE: BUY POZ (Watching DL-)"
    elif position == "SELL":
        mode_str = "ACTIVE: SELL POZ (Watching DL+)"
    else:
        mode_str = "IDLE (No Position)"

    exit_alert = f"🔴 {signal} !!" if signal else f"🟢 {mode_str}"
    
    # Dynamic display: Highlight the relevant slope with brackets []
    if position == "BUY":
        p_fmt = f" {s['current_dl_plus']:+05.2f} "
        m_fmt = f"[{s['current_dl_minus']:+05.2f}]" # Highlighted
    elif position == "SELL":
        p_fmt = f"[{s['current_dl_plus']:+05.2f}]" # Highlighted
        m_fmt = f" {s['current_dl_minus']:+05.2f} "
    else:
        p_fmt = f" {s['current_dl_plus']:+05.2f} "
        m_fmt = f" {s['current_dl_minus']:+05.2f} "

    output = (
        f"\r{time_str} | "
        f"DI+:{s['di_plus']:05.2f} DI-:{s['di_minus']:05.2f} | "
        f"Slope+:{p_fmt} Slope-:{m_fmt} | "
        f"{exit_alert}"
    )
    
    sys.stdout.write(output)
    sys.stdout.flush()
    
    if signal:
        print("\n" + "="*80)
        print(f"🚀 EXIT TRIGGERED at {time_str}")
        print(f"   Signal: {signal}")
        val = s['current_dl_minus'] if signal == "EXIT_BUY" else s['current_dl_plus']
        print(f"   Value: {val:.4f} >= {EXIT_THRESHOLD}")
        print("="*80 + "\n")

# ============ RUNNER ============
def run_live_bot():
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print("MT5 Init Failed")
        return
    mt5.symbol_select(SYMBOL, True)
    
    print(f"✅ COMBINED ENGINE STARTED: {SYMBOL}")
    print(f"   Mode: {'AUTO-DETECT MT5' if AUTO_DETECT_MT5_POSITION else 'MANUAL TEST'}")
    print(f"   Exit Threshold: {EXIT_THRESHOLD}")

    engine = ExitEngine(slope_smooth_len=SLOPE_SMOOTH)
    last_processed_tick_time = 0
    
    # Init history
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 200)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    di_plus, di_minus = calculate_di_series(df, DI_LEN)
    engine.on_new_bar(df.iloc[-1]['time'], di_plus.iloc[-2], di_minus.iloc[-2])

    print("Waiting for ticks...")

    while True:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None or tick.time_msc == last_processed_tick_time:
            continue
        last_processed_tick_time = tick.time_msc

        # 1. Determine Position
        if AUTO_DETECT_MT5_POSITION:
            current_position = get_mt5_position_type(SYMBOL)
        else:
            current_position = MANUAL_TEST_POSITION

        # 2. Update Data
        rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 200)
        if rates is None: continue
        df = pd.DataFrame(rates)
        
        # 3. New Bar Check
        current_bar_time = df.iloc[-1]['time']
        if current_bar_time != engine.prev_bar_time:
            full_dp, full_dm = calculate_di_series(df, DI_LEN)
            engine.on_new_bar(current_bar_time, full_dp.iloc[-2], full_dm.iloc[-2])
        
        # 4. Realtime Indicators
        rt_dp, rt_dm = calculate_di_series(df, DI_LEN)
        
        # 5. Evaluate
        exit_signal = engine.evaluate(
            tick.time, 
            rt_dp.iloc[-1], 
            rt_dm.iloc[-1], 
            current_position
        )

        # 6. Dashboard
        print_dashboard(engine, exit_signal, current_position, tick.time)

if __name__ == "__main__":
    run_live_bot()