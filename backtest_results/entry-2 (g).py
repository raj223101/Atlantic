import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import sys
import time
from datetime import datetime, timezone, timedelta
from collections import deque

# ================= USER CONFIG =================
# Replace with your specific credentials if different from the prompt
MT5_LOGIN = 52621105
MT5_PASSWORD = "m5llC@@6De1yaJ"
MT5_SERVER = "ICMarketsSC-Demo"

SYMBOL = "BTCUSD"
HTF_TF = mt5.TIMEFRAME_M2  # HTF
LTF_TF = mt5.TIMEFRAME_M1  # LTF

DI_LEN = 7
ADX_LEN = 7
SLOPE_SMOOTH = 1

# IST Offset (UTC + 5:30)
IST_OFFSET = timedelta(hours=5, minutes=30)
# ===============================================

# ============ INDICATOR CALCULATION ============
def calculate_adx_di(df, di_len, adx_len):
    """
    Exact calculation logic provided in requirements.
    """
    # Create copies to avoid SettingWithCopy warnings on the original DF
    high = df['high'].copy()
    low = df['low'].copy()
    close = df['close'].copy()

    up = high.diff()
    down = -low.diff()

    # True Range
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

    # Handle division by zero/NaN for DX
    sum_di = plusDI + minusDI
    dx = 100 * (plusDI - minusDI).abs() / sum_di.replace(0, np.nan)
    adx = dx.ewm(alpha=1/adx_len, adjust=False).mean()

    return plusDI, minusDI, adx

# ============ TF STATE ENGINE ===================
class TFState:
    def __init__(self, name):
        self.name = name
        self.prev_bar_time = None
        
        # Closing values of the *previous finished* candle
        self.prev_adx_close = None
        self.prev_plus_close = None
        self.prev_minus_close = None

        # Buffers for smoothing slope (though len=1 means instantaneous)
        self.adx_buf   = deque(maxlen=SLOPE_SMOOTH)
        self.plus_buf  = deque(maxlen=SLOPE_SMOOTH)
        self.minus_buf = deque(maxlen=SLOPE_SMOOTH)

        # Min/Max tracking for the current forming bar
        self.adx_min = self.adx_max = None
        self.plus_min = self.plus_max = None
        self.minus_min = self.minus_max = None

        # Latest calculated values (Realtime + Slopes)
        # Structure: (adx, plus, minus, adx_slope, plus_slope, minus_slope)
        self.last_values = None

    def reset_on_new_bar(self, bar_time, adx_c, plus_c, minus_c):
        """Called when a new candle is detected."""
        self.prev_bar_time = bar_time
        self.prev_adx_close = adx_c
        self.prev_plus_close = plus_c
        self.prev_minus_close = minus_c

        self.adx_buf.clear()
        self.plus_buf.clear()
        self.minus_buf.clear()

        # Reset Min/Max for the new bar
        self.adx_min = self.adx_max = None
        self.plus_min = self.plus_max = None
        self.minus_min = self.minus_max = None

    def update_realtime(self, adx_rt, plus_rt, minus_rt):
        """Called every tick with latest indicator values."""
        if self.prev_adx_close is None:
            return

        # Calculate slope: (Current Realtime Value - Previous Candle Close)
        adx_s   = adx_rt   - self.prev_adx_close
        plus_s  = plus_rt  - self.prev_plus_close
        minus_s = minus_rt - self.prev_minus_close

        self.adx_buf.append(adx_s)
        self.plus_buf.append(plus_s)
        self.minus_buf.append(minus_s)

        # Get smoothed slope
        final_adx_s = np.mean(self.adx_buf)
        final_plus_s = np.mean(self.plus_buf)
        final_minus_s = np.mean(self.minus_buf)

        # Update Min/Max tracking
        self.adx_min = final_adx_s if self.adx_min is None else min(self.adx_min, final_adx_s)
        self.adx_max = final_adx_s if self.adx_max is None else max(self.adx_max, final_adx_s)
        
        self.plus_min = final_plus_s if self.plus_min is None else min(self.plus_min, final_plus_s)
        self.plus_max = final_plus_s if self.plus_max is None else max(self.plus_max, final_plus_s)
        
        self.minus_min = final_minus_s if self.minus_min is None else min(self.minus_min, final_minus_s)
        self.minus_max = final_minus_s if self.minus_max is None else max(self.minus_max, final_minus_s)

        self.last_values = (adx_rt, plus_rt, minus_rt, final_adx_s, final_plus_s, final_minus_s)

    def get_data(self):
        """Returns tuple of current values or Zeros if initializing."""
        if self.last_values is None:
            return (0, 0, 0, 0, 0, 0)
        return self.last_values

# ============ HELPERS ===========================
def get_ist_time(timestamp_utc):
    """Converts unix timestamp to string IST."""
    dt = datetime.fromtimestamp(timestamp_utc, timezone.utc) + IST_OFFSET
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def get_time_str(timestamp_utc):
    dt = datetime.fromtimestamp(timestamp_utc, timezone.utc) + IST_OFFSET
    return dt.strftime('%H:%M:%S')

# ============ MAIN APPLICATION ==================
def main():
    # 1. MT5 INIT
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print(f"MT5 init failed, error: {mt5.last_error()}")
        sys.exit()

    if not mt5.symbol_select(SYMBOL, True):
        print(f"Failed to select {SYMBOL}")
        sys.exit()

    print(f"✅ REALTIME DUAL-TF ENGINE STARTED ({SYMBOL})")
    print("Waiting for ticks...")

    # 2. STATE INITIALIZATION
    htf_state = TFState("HTF")
    ltf_state = TFState("LTF")

    # Tracking logic for signals (Latch mechanism)
    # We use these to prevent duplicate signals for the same "excursion" above the threshold
    ltf_buy_latched = False  
    ltf_sell_latched = False

    last_tick_time = 0
    
    # For Terminal Dashboard UI
    lines_printed = False

    # 3. REALTIME LOOP
    while True:
        # A. Connection Safety
        if not mt5.terminal_info().connected:
            print("⚠️ MT5 Disconnected. Reconnecting...")
            mt5.shutdown()
            time.sleep(1)
            if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
                continue

        # B. Tick Fetch
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            time.sleep(0.1)
            continue
            
        # Optimization: Only process if tick time changed (new tick event)
        if tick.time_msc == last_tick_time:
            time.sleep(0.001) # Tiny sleep to prevent 100% CPU usage loop
            continue
            
        last_tick_time = tick.time_msc

        # C. Process Timeframes (HTF & LTF)
        # We loop through both configs to update the TFState objects
        tf_configs = [(HTF_TF, htf_state), (LTF_TF, ltf_state)]
        
        for tf, state in tf_configs:
            # Fetch data (enough for calculation)
            rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, 100)
            if rates is None or len(rates) < 50:
                continue

            df = pd.DataFrame(rates)
            # Calculate Indicators
            plusDI, minusDI, adx = calculate_adx_di(df, DI_LEN, ADX_LEN)

            # Identification of "Closed" candle vs "Live" candle
            # iloc[-2] is the last fully closed candle
            # iloc[-1] is the current forming candle
            
            bar_time_closed = df.iloc[-2]['time']

            # 1. Check for New Bar Event to reset buffers
            if bar_time_closed != state.prev_bar_time:
                state.reset_on_new_bar(
                    bar_time_closed,
                    adx.iloc[-2],
                    plusDI.iloc[-2],
                    minusDI.iloc[-2]
                )

            # 2. Update Realtime State
            state.update_realtime(
                adx.iloc[-1],
                plusDI.iloc[-1],
                minusDI.iloc[-1]
            )

        # D. Logic Engine - Extract Data
        # HTF Data
        h_adx, h_plus, h_minus, h_adx_s, h_plus_s, h_minus_s = htf_state.get_data()
        
        # LTF Data
        l_adx, l_plus, l_minus, l_adx_s, l_plus_s, l_minus_s = ltf_state.get_data()

        # E. HTF Trend Evaluation
        # Rules:
        # BULL: +DI > 21 AND +DI_Slope > 0 AND ADX_Slope > -2
        # BEAR: -DI > 21 AND -DI_Slope > 0 AND ADX_Slope > -2
        
        htf_status = "NEUTRAL"
        
        is_htf_bull_cond = (h_plus > 21) and (h_plus_s > 0) and (h_adx_s > -2)
        is_htf_bear_cond = (h_minus > 21) and (h_minus_s > 0) and (h_adx_s > -2)

        if is_htf_bull_cond:
            htf_status = "BULL"
        elif is_htf_bear_cond:
            htf_status = "BEAR"

        # F. LTF Signal Evaluation
        # Signal Rules:
        # BUY: HTF=BULL, LTF +DI > 24 (Cross Logic), LTF ADX Slope > -2
        # SELL: HTF=BEAR, LTF -DI > 24 (Cross Logic), LTF ADX Slope > -2
        
        signal_event = None
        
        # --- BUY LOGIC ---
        # 1. Check if LTF is in "Buy Zone"
        ltf_in_buy_zone = (l_plus > 24)
        
        # 2. Manage Latch (Reset if we drop out of zone)
        if not ltf_in_buy_zone:
            ltf_buy_latched = False
            
        # 3. Check Signal Trigger
        # Condition: In Zone + Slope OK + HTF OK + Not Already Triggered for this zone
        if ltf_in_buy_zone and (l_adx_s > -2) and (htf_status == "BULL") and not ltf_buy_latched:
            signal_event = "BUY"
            ltf_buy_latched = True # Lock to prevent duplicate prints
            
        # --- SELL LOGIC ---
        # 1. Check if LTF is in "Sell Zone"
        ltf_in_sell_zone = (l_minus > 24)
        
        # 2. Manage Latch
        if not ltf_in_sell_zone:
            ltf_sell_latched = False
            
        # 3. Check Signal Trigger
        if ltf_in_sell_zone and (l_adx_s > -2) and (htf_status == "BEAR") and not ltf_sell_latched:
            signal_event = "SELL"
            ltf_sell_latched = True # Lock to prevent duplicate prints

        # G. Display & Logging
        
        # If signal occurred, clear dashboard lines first (if they exist), print event, then loop will reprint dashboard
        if signal_event:
            if lines_printed:
                sys.stdout.write("\033[2F\033[J") # Move up 2 lines and clear down
            
            print("════════════════════════════════════")
            print(f"{signal_event} SIGNAL")
            print(f"TIME  : {get_ist_time(tick.time)} IST")
            print(f"PRICE : {tick.bid if signal_event == 'SELL' else tick.ask}")
            print(f"HTF   : {htf_status}")
            print("CHECKS:")
            if signal_event == "BUY":
                print(f" ✔ +DI Cross (>24): {l_plus:.2f}")
            else:
                print(f" ✔ -DI Cross (>24): {l_minus:.2f}")
            print(f" ✔ ADX Slope > -2 : {l_adx_s:.3f}")
            print("════════════════════════════════════")
            
            lines_printed = False # Reset flag so we don't try to clear the event log next time

        # H. Realtime Dashboard (Overwrite 2 Lines)
        # If we previously printed the dashboard, move cursor up.
        # If we just printed an event (lines_printed=False), we stay where we are.
        if lines_printed:
            sys.stdout.write("\033[2F") # Move up 2 lines
        
        # Format Strings
        # HTF
        htf_str = (
            f"HTF | {get_time_str(tick.time)} | "
            f"ADX:{h_adx:5.1f} | +DI:{h_plus:5.1f} | -DI:{h_minus:5.1f} | "
            f"ADX_S:{h_adx_s:+5.2f} | +S:{h_plus_s:+5.2f} | -S:{h_minus_s:+5.2f} | "
            f"STATUS: {htf_status}"
        )
        
        # LTF (Signal Status)
        sig_status = "WAIT"
        if ltf_buy_latched: sig_status = "BUY_ACTIVE"
        if ltf_sell_latched: sig_status = "SELL_ACTIVE"
        
        ltf_str = (
            f"LTF | {get_time_str(tick.time)} | "
            f"ADX:{l_adx:5.1f} | +DI:{l_plus:5.1f} | -DI:{l_minus:5.1f} | "
            f"ADX_S:{l_adx_s:+5.2f} | +S:{l_plus_s:+5.2f} | -S:{l_minus_s:+5.2f} | "
            f"SIGNAL: {sig_status}"
        )

        sys.stdout.write("\033[2K" + htf_str + "\n") # Clear line + Print HTF
        sys.stdout.write("\033[2K" + ltf_str + "\n") # Clear line + Print LTF
        sys.stdout.flush()
        
        lines_printed = True

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Exiting...")
        mt5.shutdown()