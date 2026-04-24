"""
Execution-native registry for the selected live strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from config import ACTIVE_TRADING_SYMBOLS, ALL_INSTRUMENTS, EXIT_COMPONENT_LEVEL, INSTRUMENTS
from core.logger import log


Condition = Dict[str, Any]
RuleGroup = Dict[str, Any]


def _cmp(left: str, op: str, right: Any, *, tf: int) -> Condition:
    return {
        "left": left,
        "op": op,
        "right": right,
        "tf": int(tf),
    }


def _active_symbols() -> tuple[str, ...]:
    symbols = tuple(symbol for symbol in ACTIVE_TRADING_SYMBOLS if symbol in INSTRUMENTS)
    if symbols:
        return symbols
    return tuple(INSTRUMENTS)


def _classic_calculation_aliases() -> Dict[str, str]:
    return {
        "S_ADX_BB": "slope_adx_bb",
        "DI_PLUS": "di_plus",
        "DI_MINUS": "di_minus",
        "S_DIP_BB": "slope_di_plus_bb",
        "S_DIM_BB": "slope_di_minus_bb",
        "TEMA_9_BB": "tema_9_tema_slope_bb",
        "TEMA_16_BB": "tema_16_tema_slope_bb",
        "TEMA_21_BB": "tema_21_tema_slope_bb",
        "UT_0.75_1_STATE": "ut_0.75_1_ut_state",
        "UT_0.75_1_VALUE": "ut_0.75_1_ut_value",
        "UT_0.75_1_ANG": "ut_0.75_1_ut_angle",
        "UT_0.5_1_STATE": "ut_0.5_1_ut_state",
        "UT_0.5_1_VALUE": "ut_0.5_1_ut_value",
        "UT_0.5_1_ANG": "ut_0.5_1_ut_angle",
        "TEMA_9_ANG": "tema_9_tema_angle",
        # The selected files refer to DELTA_ANGLE; the live engine exposes
        # the equivalent directional spread as dl_angle_spread.
        "DELTA_ANGLE": "dl_angle_spread",
        "EXIT_SLOPE_LONG": "slope_di_minus_bb",
        "EXIT_SLOPE_SHORT": "slope_di_plus_bb",
    }


def _classic_entry_conditions(*, entry_tf: int, delta_angle_threshold: float) -> Dict[str, List[Condition]]:
    return {
        "long": [
            _cmp("S_ADX_BB", ">", -1.0, tf=entry_tf),
            _cmp("DI_PLUS", ">", 24.0, tf=entry_tf),
            _cmp("S_DIP_BB", ">", 0.0, tf=entry_tf),
            _cmp("TEMA_9_BB", ">", 0.0, tf=entry_tf),
            _cmp("TEMA_16_BB", ">", 0.0, tf=entry_tf),
            _cmp("TEMA_21_BB", ">", 0.0, tf=entry_tf),
            _cmp("UT_0.75_1_STATE", "==", "BULL", tf=entry_tf),
            _cmp("DELTA_ANGLE", ">", float(delta_angle_threshold), tf=entry_tf),
        ],
        "short": [
            _cmp("S_ADX_BB", ">", -1.0, tf=entry_tf),
            _cmp("DI_MINUS", ">", 24.0, tf=entry_tf),
            _cmp("S_DIM_BB", ">", 0.0, tf=entry_tf),
            _cmp("TEMA_9_BB", "<", 0.0, tf=entry_tf),
            _cmp("TEMA_16_BB", "<", 0.0, tf=entry_tf),
            _cmp("TEMA_21_BB", "<", 0.0, tf=entry_tf),
            _cmp("UT_0.75_1_STATE", "==", "BEAR", tf=entry_tf),
            _cmp("DELTA_ANGLE", "<", -float(delta_angle_threshold), tf=entry_tf),
        ],
    }


def _append_entry_confirmations(
    base_conditions: Dict[str, List[Condition]],
    *,
    long_extra: List[Condition],
    short_extra: List[Condition],
) -> Dict[str, List[Condition]]:
    return {
        "long": list(base_conditions.get("long", [])) + list(long_extra),
        "short": list(base_conditions.get("short", [])) + list(short_extra),
    }


def _with_htf_confirmation(
    *,
    entry_tf: int,
    htf: int,
    delta_angle_threshold: float,
) -> Dict[str, List[Condition]]:
    return _append_entry_confirmations(
        _classic_entry_conditions(entry_tf=entry_tf, delta_angle_threshold=delta_angle_threshold),
        long_extra=_classic_entry_conditions(entry_tf=htf, delta_angle_threshold=delta_angle_threshold)["long"],
        short_extra=_classic_entry_conditions(entry_tf=htf, delta_angle_threshold=delta_angle_threshold)["short"],
    )


def _tema_slope_confirmation(*, include_angle_gate: bool) -> Dict[str, List[Condition]]:
    long_rules: List[Condition] = []
    short_rules: List[Condition] = []

    if include_angle_gate:
        long_rules.extend(
            [
                _cmp("TEMA_9_ANG", ">", 30.0, tf=30),
                _cmp("TEMA_9_ANG", ">", 30.0, tf=15),
            ]
        )
        short_rules.extend(
            [
                _cmp("TEMA_9_ANG", "<", -30.0, tf=30),
                _cmp("TEMA_9_ANG", "<", -30.0, tf=15),
            ]
        )

    long_rules.extend(
        [
            _cmp("TEMA_9_BB", ">", 1.0, tf=30),
            _cmp("TEMA_9_BB", ">", 1.0, tf=15),
        ]
    )
    short_rules.extend(
        [
            _cmp("TEMA_9_BB", "<", 1.0, tf=30),
            _cmp("TEMA_9_BB", "<", 1.0, tf=15),
        ]
    )
    return {
        "long": long_rules,
        "short": short_rules,
    }


def _classic_exit_rules(*, entry_tf: int, exit_tf: int) -> Dict[str, List[RuleGroup]]:
    return {
        "long": [
            {
                "name": "LONG_TRAILING_STOP",
                "all": [
                    _cmp("price", "<", "UT_0.75_1_VALUE", tf=entry_tf),
                    _cmp("EXIT_SLOPE_LONG", ">", EXIT_COMPONENT_LEVEL, tf=exit_tf),
                ],
            }
        ],
        "short": [
            {
                "name": "SHORT_TRAILING_STOP",
                "all": [
                    _cmp("price", ">", "UT_0.75_1_VALUE", tf=entry_tf),
                    _cmp("EXIT_SLOPE_SHORT", ">", EXIT_COMPONENT_LEVEL, tf=exit_tf),
                ],
            }
        ],
    }


def _exit_test_rules(*, entry_tf: int, exit_tf: int) -> Dict[str, List[RuleGroup]]:
    return {
        "long": [
            {
                "name": "LONG_TEMA9_BB_FLIP_EXIT",
                "all": [
                    _cmp("TEMA_9_BB", "<", -0.5, tf=entry_tf),
                ],
            },
            {
                "name": "LONG_UT_0.5_1_TRAILING_STOP",
                "all": [
                    _cmp("price", "<", "UT_0.5_1_VALUE", tf=entry_tf),
                    _cmp("EXIT_SLOPE_LONG", ">", EXIT_COMPONENT_LEVEL, tf=exit_tf),
                ],
            },
        ],
        "short": [
            {
                "name": "SHORT_TEMA9_BB_FLIP_EXIT",
                "all": [
                    _cmp("TEMA_9_BB", ">", 0.5, tf=entry_tf),
                ],
            },
            {
                "name": "SHORT_UT_0.5_1_TRAILING_STOP",
                "all": [
                    _cmp("price", ">", "UT_0.5_1_VALUE", tf=entry_tf),
                    _cmp("EXIT_SLOPE_SHORT", ">", EXIT_COMPONENT_LEVEL, tf=exit_tf),
                ],
            },
        ],
    }


COMMON_CALCULATION_ALIASES = {
    "DI_PLUS": "di_plus",
    "DI_MINUS": "di_minus",
    "S_DIP_BB": "slope_di_plus_bb",
    "S_DIM_BB": "slope_di_minus_bb",
    "DL_PLUS_BB": "slope_di_plus_bb",
    "DL_MINUS_BB": "slope_di_minus_bb",
    "TEMA_9_BB": "tema_9_tema_slope_bb",
    "TEMA_9_ANG": "tema_9_tema_angle",
    "UT_0.5_1_STATE": "ut_0.5_1_ut_state",
    "UT_0.5_1_VALUE": "ut_0.5_1_ut_value",
    "UT_0.5_1_ANG": "ut_0.5_1_ut_angle",
    "UT_0.75_1_STATE": "ut_0.75_1_ut_state",
    "UT_0.75_1_VALUE": "ut_0.75_1_ut_value",
    "UT_0.75_1_ANG": "ut_0.75_1_ut_angle",
    "UT_1.5_1_STATE": "ut_1.5_1_ut_state",
    "UT_1.5_1_VALUE": "ut_1.5_1_ut_value",
    "UT_1.5_1_ANG": "ut_1.5_1_ut_angle",
    "DL_ANGLE_SPREAD": "dl_angle_spread",
    "DELTA_ANGLE": "dl_angle_spread",
    "EXIT_SLOPE_LONG": "slope_di_minus_bb",
    "EXIT_SLOPE_SHORT": "slope_di_plus_bb",
}


def _build_entry_conditions(
    *,
    entry_tf: int,
    exit_tf: int,
    include_dl_bias_gate: bool,
) -> Dict[str, List[Condition]]:
    long_rules = [
        _cmp("UT_0.75_1_ANG", ">=", 30.0, tf=entry_tf),
        _cmp("UT_0.75_1_ANG", ">=", 10.0, tf=exit_tf),
        _cmp("UT_0.75_1_STATE", "==", "BULL", tf=entry_tf),
        _cmp("UT_1.5_1_STATE", "==", "BULL", tf=entry_tf),
        _cmp("DL_ANGLE_SPREAD", ">", 0.0, tf=entry_tf),
        _cmp("DL_ANGLE_SPREAD", ">", 0.0, tf=exit_tf),
        _cmp("TEMA_9_BB", ">", 0.0, tf=entry_tf),
        _cmp("DI_PLUS", ">", "DI_MINUS", tf=entry_tf),
    ]
    short_rules = [
        _cmp("UT_0.75_1_ANG", "<=", -30.0, tf=entry_tf),
        _cmp("UT_0.75_1_ANG", "<=", -10.0, tf=exit_tf),
        _cmp("UT_0.75_1_STATE", "==", "BEAR", tf=entry_tf),
        _cmp("UT_1.5_1_STATE", "==", "BEAR", tf=entry_tf),
        _cmp("DL_ANGLE_SPREAD", "<", 0.0, tf=entry_tf),
        _cmp("DL_ANGLE_SPREAD", "<", 0.0, tf=exit_tf),
        _cmp("TEMA_9_BB", "<", 0.0, tf=entry_tf),
        _cmp("DI_MINUS", ">", "DI_PLUS", tf=entry_tf),
    ]
    if include_dl_bias_gate:
        long_rules.insert(7, _cmp("DL_PLUS_BB", ">", 0.0, tf=entry_tf))
        short_rules.insert(7, _cmp("DL_MINUS_BB", ">", 0.0, tf=entry_tf))
    return {
        "long": long_rules,
        "short": short_rules,
    }


def _build_layered_exit_rules(*, exit_tf: int) -> Dict[str, List[RuleGroup]]:
    return {
        "long": [
            {
                "name": "LONG_ANGLE_FLIP_45S",
                "all": [
                    _cmp("UT_0.75_1_ANG", "<", -15.0, tf=exit_tf),
                    _cmp("hold_secs", ">=", 45.0, tf=exit_tf),
                ],
            },
            {
                "name": "LONG_PRICE_STOP",
                "all": [
                    _cmp("price", "<", "UT_0.75_1_VALUE", tf=exit_tf),
                    _cmp("S_DIM_BB", ">", 3.5, tf=exit_tf),
                ],
            },
            {
                "name": "LONG_DEAD_TRADE_CUT",
                "all": [
                    _cmp("hold_secs", ">=", 25.0, tf=exit_tf),
                    _cmp("hold_secs", "<=", 35.0, tf=exit_tf),
                    _cmp("price_minus_entry", "<", 0.5, tf=exit_tf),
                ],
            },
        ],
        "short": [
            {
                "name": "SHORT_ANGLE_FLIP_45S",
                "all": [
                    _cmp("UT_0.75_1_ANG", ">", 15.0, tf=exit_tf),
                    _cmp("hold_secs", ">=", 45.0, tf=exit_tf),
                ],
            },
            {
                "name": "SHORT_PRICE_STOP",
                "all": [
                    _cmp("price", ">", "UT_0.75_1_VALUE", tf=exit_tf),
                    _cmp("S_DIP_BB", ">", 3.5, tf=exit_tf),
                ],
            },
            {
                "name": "SHORT_DEAD_TRADE_CUT",
                "all": [
                    _cmp("hold_secs", ">=", 25.0, tf=exit_tf),
                    _cmp("hold_secs", "<=", 35.0, tf=exit_tf),
                    _cmp("entry_minus_price", "<", 0.5, tf=exit_tf),
                ],
            },
        ],
    }


def _build_s9_test_rule_spec(
    *,
    entry_tf: int,
    variant_label: str,
    include_dl_bias_gate: bool,
    exit_tf: int = 5,
) -> Dict[str, Any]:
    return {
        "base_strategy": "S9",
        "strategy_type": "2TF",
        "variant_label": str(variant_label),
        "timeframes": {
            "entry_tf": int(entry_tf),
            "exit_tf": int(exit_tf),
            "reentry_tf": int(entry_tf),
        },
        "calculation_aliases": dict(COMMON_CALCULATION_ALIASES),
        "entry_conditions": _build_entry_conditions(
            entry_tf=int(entry_tf),
            exit_tf=int(exit_tf),
            include_dl_bias_gate=include_dl_bias_gate,
        ),
        "runtime_exit_rules": _build_layered_exit_rules(exit_tf=int(exit_tf)),
        "notes": [
            f"S9 experiment {variant_label}",
            f"Decision timeframe={int(entry_tf)}s, execution timeframe={int(exit_tf)}s",
            "Both decision and 5s confirmation frames must agree before entry.",
            "Exit uses layered angle-flip, price-stop, and dead-trade cut logic.",
            "Moved from Selected_Strategies into the live execution registry.",
        ],
    }


@dataclass(frozen=True)
class StrategyDefinition:
    name: str
    base_strategy: str
    variant: int
    strategy_type: str
    logic_profile: str
    tf_htf: int
    tf_entry: int
    tf_exit: int
    tf_reentry: int
    symbols: tuple[str, ...]
    option_bucket: str
    enabled: bool
    ml_enabled: bool
    stoploss_enabled: bool
    rule_spec: Dict[str, Any] = field(default_factory=dict)
    source_path: str = ""

    @property
    def primary_tf(self) -> int:
        return int(self.tf_entry)

    @property
    def required_timeframes(self) -> tuple[int, ...]:
        values = {
            int(self.tf_htf),
            int(self.tf_entry),
            int(self.tf_exit),
            int(self.tf_reentry),
        }
        return tuple(sorted(values))


SELECTED_STRATEGIES: List[StrategyDefinition] = [
    StrategyDefinition(
        name="strategy_S5-10",
        base_strategy="S5",
        variant=10,
        strategy_type="2TF",
        logic_profile="2TF_BATCH_S5",
        tf_htf=10,
        tf_entry=10,
        tf_exit=5,
        tf_reentry=10,
        symbols=_active_symbols(),
        option_bucket="ITM1",
        enabled=True,
        ml_enabled=True,
        stoploss_enabled=False,
        rule_spec={
            "base_strategy": "S5",
            "strategy_type": "2TF",
            "timeframes": {
                "entry_tf": 10,
                "exit_tf": 5,
                "reentry_tf": 10,
            },
            "calculation_aliases": _classic_calculation_aliases(),
            "entry_conditions": _classic_entry_conditions(entry_tf=10, delta_angle_threshold=80.0),
            "runtime_exit_rules": _classic_exit_rules(entry_tf=10, exit_tf=5),
            "notes": [
                "Migrated from Selected_Strategies/S5-10 into execution.",
                "Re-entry timeframe matches the decision timeframe.",
                "Classic S5 gate uses a stronger directional-angle threshold.",
            ],
        },
        source_path="Selected_Strategies/S5-10/strategy/two_timeframe_batch_90/strategy_S5-10/strategy_S5_10.py",
    ),
    StrategyDefinition(
        name="strategy_S9-4",
        base_strategy="S9",
        variant=4,
        strategy_type="2TF",
        logic_profile="2TF_BATCH_S9",
        tf_htf=30,
        tf_entry=30,
        tf_exit=15,
        tf_reentry=30,
        symbols=_active_symbols(),
        option_bucket="ITM1",
        enabled=True,
        ml_enabled=True,
        stoploss_enabled=False,
        rule_spec={
            "base_strategy": "S9",
            "strategy_type": "2TF",
            "timeframes": {
                "entry_tf": 30,
                "exit_tf": 15,
                "reentry_tf": 30,
            },
            "calculation_aliases": _classic_calculation_aliases(),
            "entry_conditions": _classic_entry_conditions(entry_tf=30, delta_angle_threshold=50.0),
            "runtime_exit_rules": _classic_exit_rules(entry_tf=30, exit_tf=15),
            "notes": [
                "Execution-native S9-4 variant.",
                "Decision timeframe set to 30s with 15s exit confirmation.",
                "Uses TYPE_B execution only through the active execution mode filter.",
            ],
        },
        source_path="Execution-native variant requested for S9-4",
    ),
    StrategyDefinition(
        name="strategy_S5-10_TEST1",
        base_strategy="S5",
        variant=101,
        strategy_type="2TF",
        logic_profile="2TF_BATCH_S5_TEST1",
        tf_htf=10,
        tf_entry=10,
        tf_exit=5,
        tf_reentry=10,
        symbols=_active_symbols(),
        option_bucket="ITM1",
        enabled=True,
        ml_enabled=True,
        stoploss_enabled=False,
        rule_spec={
            "base_strategy": "S5",
            "strategy_type": "2TF",
            "timeframes": {
                "entry_tf": 10,
                "exit_tf": 5,
                "reentry_tf": 10,
            },
            "calculation_aliases": _classic_calculation_aliases(),
            "entry_conditions": _append_entry_confirmations(
                _classic_entry_conditions(entry_tf=10, delta_angle_threshold=80.0),
                long_extra=_tema_slope_confirmation(include_angle_gate=True)["long"],
                short_extra=_tema_slope_confirmation(include_angle_gate=True)["short"],
            ),
            "runtime_exit_rules": _classic_exit_rules(entry_tf=10, exit_tf=5),
            "notes": [
                "S5-10 test 1.",
                "Adds 30s and 15s TEMA angle > 30 confirmation plus TEMA slope > 1 for buys.",
                "Adds 30s and 15s TEMA angle < -30 confirmation plus TEMA slope < 1 for sells.",
            ],
        },
        source_path="Execution-native test variant requested for S5-10 10s/5s",
    ),
    StrategyDefinition(
        name="strategy_S5-10_EXIT_TEST1",
        base_strategy="S5",
        variant=111,
        strategy_type="2TF",
        logic_profile="2TF_BATCH_S5_EXIT_TEST1",
        tf_htf=10,
        tf_entry=10,
        tf_exit=5,
        tf_reentry=10,
        symbols=_active_symbols(),
        option_bucket="ITM1",
        enabled=True,
        ml_enabled=True,
        stoploss_enabled=False,
        rule_spec={
            "base_strategy": "S5",
            "strategy_type": "2TF",
            "timeframes": {
                "entry_tf": 10,
                "exit_tf": 5,
                "reentry_tf": 10,
            },
            "calculation_aliases": _classic_calculation_aliases(),
            "entry_conditions": _classic_entry_conditions(entry_tf=10, delta_angle_threshold=80.0),
            "runtime_exit_rules": _exit_test_rules(entry_tf=10, exit_tf=5),
            "notes": [
                "S5-10 exit test 1.",
                "Entry rules are identical to core strategy_S5-10.",
                "Exit triggers on first match of TEMA_9_BB flip or UT 0.5/1 trailing stop.",
            ],
        },
        source_path="Execution-native exit test variant requested for strategy_S5-10",
    ),
    StrategyDefinition(
        name="strategy_S9-4_EXIT_TEST2",
        base_strategy="S9",
        variant=42,
        strategy_type="2TF",
        logic_profile="2TF_BATCH_S9_EXIT_TEST2",
        tf_htf=30,
        tf_entry=30,
        tf_exit=15,
        tf_reentry=30,
        symbols=_active_symbols(),
        option_bucket="ITM1",
        enabled=True,
        ml_enabled=True,
        stoploss_enabled=False,
        rule_spec={
            "base_strategy": "S9",
            "strategy_type": "2TF",
            "timeframes": {
                "entry_tf": 30,
                "exit_tf": 15,
                "reentry_tf": 30,
            },
            "calculation_aliases": _classic_calculation_aliases(),
            "entry_conditions": _classic_entry_conditions(entry_tf=30, delta_angle_threshold=50.0),
            "runtime_exit_rules": _exit_test_rules(entry_tf=30, exit_tf=15),
            "notes": [
                "S9-4 exit test 2.",
                "Entry rules are identical to core strategy_S9-4.",
                "Exit triggers on first match of TEMA_9_BB flip or UT 0.5/1 trailing stop.",
            ],
        },
        source_path="Execution-native exit test variant requested for strategy_S9-4",
    ),
    StrategyDefinition(
        name="strategy_S5-10_TEST1_EXIT_TEST1",
        base_strategy="S5",
        variant=112,
        strategy_type="2TF",
        logic_profile="2TF_BATCH_S5_TEST1_EXIT_TEST1",
        tf_htf=10,
        tf_entry=10,
        tf_exit=5,
        tf_reentry=10,
        symbols=_active_symbols(),
        option_bucket="ITM1",
        enabled=True,
        ml_enabled=True,
        stoploss_enabled=False,
        rule_spec={
            "base_strategy": "S5",
            "strategy_type": "2TF",
            "timeframes": {
                "entry_tf": 10,
                "exit_tf": 5,
                "reentry_tf": 10,
            },
            "calculation_aliases": _classic_calculation_aliases(),
            "entry_conditions": _append_entry_confirmations(
                _classic_entry_conditions(entry_tf=10, delta_angle_threshold=80.0),
                long_extra=_tema_slope_confirmation(include_angle_gate=True)["long"],
                short_extra=_tema_slope_confirmation(include_angle_gate=True)["short"],
            ),
            "runtime_exit_rules": _exit_test_rules(entry_tf=10, exit_tf=5),
            "notes": [
                "S5-10 TEST1 exit test 1.",
                "Entry rules are identical to strategy_S5-10_TEST1.",
                "Exit triggers on first match of TEMA_9_BB flip or UT 0.5/1 trailing stop.",
            ],
        },
        source_path="Execution-native exit test variant requested for strategy_S5-10_TEST1",
    ),
    StrategyDefinition(
        name="strategy_1min_hft",
        base_strategy="S5",
        variant=201,
        strategy_type="3TF",
        logic_profile="3TF_BATCH_S5_HTF_1MIN",
        tf_htf=60,
        tf_entry=30,
        tf_exit=10,
        tf_reentry=30,
        symbols=_active_symbols(),
        option_bucket="ITM1",
        enabled=True,
        ml_enabled=True,
        stoploss_enabled=False,
        rule_spec={
            "base_strategy": "S5",
            "strategy_type": "3TF",
            "timeframes": {
                "htf_tf": 60,
                "entry_tf": 30,
                "exit_tf": 10,
                "reentry_tf": 30,
            },
            "calculation_aliases": _classic_calculation_aliases(),
            "entry_conditions": _with_htf_confirmation(
                entry_tf=30,
                htf=60,
                delta_angle_threshold=80.0,
            ),
            "runtime_exit_rules": _classic_exit_rules(entry_tf=30, exit_tf=10),
            "notes": [
                "S5-derived HTF confirmation variant.",
                "Entry uses classic S5 gate on both 30s and 1m before allowing a trade.",
                "Exit keeps the classic S5 structure with 30s decision and 10s exit confirmation.",
            ],
        },
        source_path="Execution-native HTF confirmation variant requested as 1min hft",
    ),
    StrategyDefinition(
        name="strategy_2min_hft",
        base_strategy="S5",
        variant=202,
        strategy_type="3TF",
        logic_profile="3TF_BATCH_S5_HTF_2MIN",
        tf_htf=120,
        tf_entry=60,
        tf_exit=30,
        tf_reentry=60,
        symbols=_active_symbols(),
        option_bucket="ITM1",
        enabled=True,
        ml_enabled=True,
        stoploss_enabled=False,
        rule_spec={
            "base_strategy": "S5",
            "strategy_type": "3TF",
            "timeframes": {
                "htf_tf": 120,
                "entry_tf": 60,
                "exit_tf": 30,
                "reentry_tf": 60,
            },
            "calculation_aliases": _classic_calculation_aliases(),
            "entry_conditions": _with_htf_confirmation(
                entry_tf=60,
                htf=120,
                delta_angle_threshold=80.0,
            ),
            "runtime_exit_rules": _classic_exit_rules(entry_tf=60, exit_tf=30),
            "notes": [
                "S5-derived HTF confirmation variant.",
                "Entry uses classic S5 gate on both 1m and 2m before allowing a trade.",
                "Exit keeps the classic S5 structure with 1m decision and 30s exit confirmation.",
            ],
        },
        source_path="Execution-native HTF confirmation variant requested as 2min hft",
    ),
]


def get_enabled_strategies() -> List[StrategyDefinition]:
    return [
        definition
        for definition in SELECTED_STRATEGIES
        if definition.enabled and definition.symbols
    ]


def required_timeframes() -> List[int]:
    timeframes = {
        tf
        for definition in get_enabled_strategies()
        for tf in definition.required_timeframes
    }
    return sorted(int(tf) for tf in timeframes)


def validate_config() -> bool:
    strategies = get_enabled_strategies()
    if not strategies:
        log.error("[StrategyDefinitions] no enabled execution strategies")
        return False

    missing_symbols = sorted(
        {
            symbol
            for definition in strategies
            for symbol in definition.symbols
            if symbol not in ALL_INSTRUMENTS
        }
    )
    if missing_symbols:
        log.error("[StrategyDefinitions] unknown symbols in strategy registry: %s", ", ".join(missing_symbols))
        return False

    log.info(
        "[StrategyDefinitions] loaded | strategies=%d names=%s",
        len(strategies),
        ", ".join(definition.name for definition in strategies),
    )
    return True
