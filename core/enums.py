from enum import Enum


class SignalType(Enum):
    """Tipos de señal unificados para buy/sell"""
    # Buy signals
    TURBO_BUY = "TURBO_BUY"
    EXTRA_BUY = "EXTRA_BUY"
    NORMAL_DCA = "NORMAL_DCA"
    SKIP = "SKIP"
    # Sell signals
    SELL = "SELL"
    ALERT = "ALERT"
    HOLD = "HOLD"


class RiskLevel(Enum):
    """Niveles de riesgo para indicadores"""
    SAFE = "SAFE"
    WARNING = "WARNING"
    DANGER = "DANGER"
    CRITICAL = "CRITICAL"