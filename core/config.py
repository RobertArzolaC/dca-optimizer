#!/usr/bin/env python3
"""
DCA Optimizer - Configuración Centralizada
Singleton pattern para configuración global
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


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


@dataclass
class TelegramConfig:
    token: str = field(default_factory=lambda: os.getenv("TELEGRAM_TOKEN", ""))
    chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    
    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)


@dataclass
class BuyConfig:
    """Configuración para estrategia de compra"""
    base_amount_usd: float = field(
        default_factory=lambda: float(os.getenv("DCA_BASE_AMOUNT", "100"))
    )
    rsi_oversold: int = 35
    rsi_overbought: int = 70
    ma_dip_threshold: float = 0.97  # 3% bajo MA7
    weekly_drop_threshold: float = -3.0
    
    multipliers: dict = field(default_factory=lambda: {
        SignalType.TURBO_BUY: 1.6,
        SignalType.EXTRA_BUY: 1.3,
        SignalType.NORMAL_DCA: 1.0,
        SignalType.SKIP: 0.0,
    })


@dataclass
class SellConfig:
    """Configuración para estrategia de venta"""
    total_btc: float = field(
        default_factory=lambda: float(os.getenv("TOTAL_BTC", "0.5"))
    )
    cost_basis_usd: float = field(
        default_factory=lambda: float(os.getenv("COST_BASIS", "25000"))
    )
    
    # Umbrales On-Chain
    mvrv_warning: float = 3.0
    mvrv_danger: float = 5.0
    mvrv_critical: float = 7.0
    nupl_warning: float = 0.5
    nupl_danger: float = 0.65
    nupl_critical: float = 0.75
    
    # Umbrales Técnicos
    rsi_warning: int = 70
    rsi_danger: int = 80
    rsi_critical: int = 88
    mayer_warning: float = 1.5
    mayer_danger: float = 2.0
    mayer_critical: float = 2.4
    
    # Porcentajes de venta escalonada
    sell_tiers: dict = field(default_factory=lambda: {
        1: 0.10,  # 1 indicador warning
        2: 0.15,  # 2 indicadores
        3: 0.25,  # 3+ indicadores
        "pi_cycle": 0.25,
    })
    
    min_signals_to_alert: int = 1
    min_signals_to_sell: int = 2


@dataclass 
class Config:
    """Configuración global - Singleton"""
    _instance = None
    
    project_dir: Path = field(
        default_factory=lambda: Path.home() / "dca-optimizer"
    )
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    buy: BuyConfig = field(default_factory=BuyConfig)
    sell: SellConfig = field(default_factory=SellConfig)
    
    @property
    def db_path(self) -> Path:
        return self.project_dir / "dca.db"
    
    @property
    def log_path(self) -> Path:
        return self.project_dir / "dca.log"
    
    @classmethod
    def get_instance(cls) -> "Config":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# Singleton global
config = Config.get_instance()
