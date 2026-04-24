"""Standardized snapshot key names used by the live execution stack."""

# ---------------------------------------------------------------------------
# ADX / Directional Indicators
# ---------------------------------------------------------------------------

ADX = "adx"
DI_PLUS = "di_plus"
DI_MINUS = "di_minus"

SLOPE_ADX_BB = "slope_adx_bb"
SLOPE_ADX_LR = "slope_adx_lr"
SLOPE_DIP_BB = "slope_di_plus_bb"
SLOPE_DIP_LR = "slope_di_plus_lr"
SLOPE_DIM_BB = "slope_di_minus_bb"
SLOPE_DIM_LR = "slope_di_minus_lr"


# ---------------------------------------------------------------------------
# TEMA (Triple EMA)
# ---------------------------------------------------------------------------

def TEMA(length: int) -> str:
    """Get TEMA key for a given length."""
    return f"tema_{length}_tema"


def TEMA_BB(length: int) -> str:
    """Get TEMA bar-to-bar slope key."""
    return f"tema_{length}_tema_slope_bb"


def TEMA_LR(length: int) -> str:
    """Get TEMA linear regression slope key."""
    return f"tema_{length}_tema_slope_lr"


# ---------------------------------------------------------------------------
# UT Bot (Chandelier Trailing Stop)
# ---------------------------------------------------------------------------

def UT_VALUE(keyvalue: float, atrperiod: int) -> str:
    """Get UT trailing stop value key."""
    return f"ut_{keyvalue}_{atrperiod}_ut_value"


def UT_STATE(keyvalue: float, atrperiod: int) -> str:
    """Get UT state (BULL/BEAR) key."""
    return f"ut_{keyvalue}_{atrperiod}_ut_state"


def UT_SLOPE_BB(keyvalue: float, atrperiod: int) -> str:
    """Get UT bar-to-bar slope key."""
    return f"ut_{keyvalue}_{atrperiod}_ut_slope_bb"


def UT_SLOPE_LR(keyvalue: float, atrperiod: int) -> str:
    """Get UT linear regression slope key."""
    return f"ut_{keyvalue}_{atrperiod}_ut_slope_lr"


# ---------------------------------------------------------------------------
# VWMA (Volume-Weighted Moving Average)
# ---------------------------------------------------------------------------

VWMA = "vwma"
VWMA_BB = "vwma_slope_bb"
VWMA_LR = "vwma_slope_lr"


# ---------------------------------------------------------------------------
# CVD (Cumulative Volume Delta)
# ---------------------------------------------------------------------------

CVD = "cvd"
CVD_BB = "cvd_slope_bb"
CVD_LR = "cvd_slope_lr"


# ---------------------------------------------------------------------------
# All keys as a reference
# ---------------------------------------------------------------------------

ALL_INDICATOR_KEYS = {
    # ADX
    ADX, DI_PLUS, DI_MINUS,
    SLOPE_ADX_BB, SLOPE_ADX_LR,
    SLOPE_DIP_BB, SLOPE_DIP_LR,
    SLOPE_DIM_BB, SLOPE_DIM_LR,
    # Volume
    VWMA, VWMA_BB, VWMA_LR,
    CVD, CVD_BB, CVD_LR,
}
