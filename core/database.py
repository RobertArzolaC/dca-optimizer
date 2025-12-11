#!/usr/bin/env python3
"""
DCA Optimizer - Capa de Base de Datos
Repository Pattern para acceso unificado a SQLite
"""

import json
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import config, SignalType, RiskLevel


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class MarketData:
    """Datos de mercado compartidos"""
    price: float
    ma7: float
    ma21: float
    ma200: float
    pct_change_24h: float
    pct_change_7d: float
    rsi: float
    timestamp: str
    
    # Opcionales para sell
    mvrv_zscore: Optional[float] = None
    nupl: Optional[float] = None
    mayer_multiple: Optional[float] = None
    fear_greed: Optional[int] = None


@dataclass
class BuySignal:
    """Señal de compra"""
    signal_type: SignalType
    multiplier: float
    suggested_amount: float
    reasons: list[str]
    market_data: MarketData
    id: Optional[int] = None
    notification_sent: bool = False
    executed: bool = False


@dataclass
class Indicator:
    """Indicador individual para sell"""
    name: str
    value: float
    level: RiskLevel
    threshold_warning: float
    threshold_danger: float
    threshold_critical: float


@dataclass
class SellSignal:
    """Señal de venta"""
    signal_type: SignalType  # SELL, ALERT, HOLD
    risk_score: int
    sell_percentage: float
    sell_amount_btc: float
    sell_amount_usd: float
    reasons: list[str]
    indicators: list[Indicator]
    market_data: MarketData
    pi_cycle_triggered: bool = False
    id: Optional[int] = None
    notification_sent: bool = False
    executed: bool = False


@dataclass
class Position:
    """Posición de BTC"""
    total_btc: float
    sold_btc: float
    cost_basis: float
    
    @property
    def remaining_btc(self) -> float:
        return self.total_btc - self.sold_btc
    
    @property
    def cost_per_btc(self) -> float:
        return self.cost_basis / self.total_btc if self.total_btc > 0 else 0


# ============================================================================
# REPOSITORY BASE
# ============================================================================

class BaseRepository(ABC):
    """Repositorio base con conexión compartida"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_tables()
    
    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    @abstractmethod
    def _init_tables(self):
        pass


# ============================================================================
# BUY REPOSITORY
# ============================================================================

class BuyRepository(BaseRepository):
    """Repositorio para señales de compra"""
    
    def __init__(self, db_path: Path = None):
        super().__init__(db_path or config.db_path)
    
    def _init_tables(self):
        with self.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    multiplier REAL NOT NULL,
                    suggested_amount REAL NOT NULL,
                    reasons TEXT,
                    price REAL NOT NULL,
                    ma7 REAL,
                    ma21 REAL,
                    ma200 REAL,
                    rsi REAL,
                    pct_change_7d REAL,
                    notification_sent INTEGER DEFAULT 0,
                    executed INTEGER DEFAULT 0,
                    actual_amount REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    price REAL NOT NULL,
                    ma7 REAL,
                    ma21 REAL,
                    rsi REAL
                )
            """)
    
    def save_signal(self, signal: BuySignal) -> int:
        with self.connection() as conn:
            cursor = conn.execute("""
                INSERT INTO signals (
                    timestamp, signal_type, multiplier, suggested_amount, reasons,
                    price, ma7, ma21, ma200, rsi, pct_change_7d
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.market_data.timestamp,
                signal.signal_type.value,
                signal.multiplier,
                signal.suggested_amount,
                json.dumps(signal.reasons),
                signal.market_data.price,
                signal.market_data.ma7,
                signal.market_data.ma21,
                signal.market_data.ma200,
                signal.market_data.rsi,
                signal.market_data.pct_change_7d,
            ))
            return cursor.lastrowid
    
    def mark_notified(self, signal_id: int):
        with self.connection() as conn:
            conn.execute(
                "UPDATE signals SET notification_sent = 1 WHERE id = ?",
                (signal_id,)
            )
    
    def save_price_snapshot(self, data: MarketData):
        with self.connection() as conn:
            conn.execute("""
                INSERT INTO price_history (timestamp, price, ma7, ma21, rsi)
                VALUES (?, ?, ?, ?, ?)
            """, (data.timestamp, data.price, data.ma7, data.ma21, data.rsi))
    
    def get_recent_signals(self, limit: int = 10) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute("""
                SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]


# ============================================================================
# SELL REPOSITORY
# ============================================================================

class SellRepository(BaseRepository):
    """Repositorio para señales de venta"""
    
    def __init__(self, db_path: Path = None):
        super().__init__(db_path)
    
    def _init_tables(self):
        with self.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS position (
                    id INTEGER PRIMARY KEY,
                    total_btc REAL NOT NULL,
                    sold_btc REAL DEFAULT 0,
                    cost_basis REAL NOT NULL,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sell_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    price REAL NOT NULL,
                    risk_score INTEGER,
                    signal_type TEXT,
                    sell_percentage REAL,
                    sell_amount_btc REAL,
                    pi_cycle_triggered INTEGER,
                    indicators_json TEXT,
                    reasons_json TEXT,
                    notification_sent INTEGER DEFAULT 0,
                    executed INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sell_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER,
                    timestamp TEXT,
                    btc_sold REAL,
                    price_at_sale REAL,
                    usd_received REAL,
                    exchange TEXT,
                    notes TEXT,
                    FOREIGN KEY (signal_id) REFERENCES sell_signals(id)
                )
            """)
    
    def get_or_create_position(self) -> Position:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM position WHERE id = 1"
            ).fetchone()
            
            if not row:
                conn.execute("""
                    INSERT INTO position (id, total_btc, sold_btc, cost_basis, created_at, updated_at)
                    VALUES (1, ?, 0, ?, ?, ?)
                """, (
                    config.sell.total_btc,
                    config.sell.cost_basis_usd,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ))
                return Position(
                    total_btc=config.sell.total_btc,
                    sold_btc=0,
                    cost_basis=config.sell.cost_basis_usd
                )
            
            return Position(
                total_btc=row["total_btc"],
                sold_btc=row["sold_btc"],
                cost_basis=row["cost_basis"]
            )
    
    def save_signal(self, signal: SellSignal) -> int:
        indicators_json = json.dumps([
            {"name": i.name, "value": i.value, "level": i.level.value}
            for i in signal.indicators
        ])
        
        with self.connection() as conn:
            cursor = conn.execute("""
                INSERT INTO sell_signals (
                    timestamp, price, risk_score, signal_type, sell_percentage,
                    sell_amount_btc, pi_cycle_triggered, indicators_json, reasons_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.market_data.timestamp,
                signal.market_data.price,
                signal.risk_score,
                signal.signal_type.value,
                signal.sell_percentage,
                signal.sell_amount_btc,
                int(signal.pi_cycle_triggered),
                indicators_json,
                json.dumps(signal.reasons),
            ))
            return cursor.lastrowid
    
    def mark_notified(self, signal_id: int):
        with self.connection() as conn:
            conn.execute(
                "UPDATE sell_signals SET notification_sent = 1 WHERE id = ?",
                (signal_id,)
            )
    
    def record_sale(self, btc_amount: float, price: float, 
                    exchange: str = "manual", signal_id: int = None) -> float:
        usd_received = btc_amount * price
        
        with self.connection() as conn:
            conn.execute("""
                INSERT INTO sell_executions 
                (signal_id, timestamp, btc_sold, price_at_sale, usd_received, exchange)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (signal_id, datetime.now().isoformat(), btc_amount, price, usd_received, exchange))
            
            conn.execute("""
                UPDATE position SET sold_btc = sold_btc + ?, updated_at = ? WHERE id = 1
            """, (btc_amount, datetime.now().isoformat()))
            
            if signal_id:
                conn.execute(
                    "UPDATE sell_signals SET executed = 1 WHERE id = ?",
                    (signal_id,)
                )
        
        return usd_received
    
    def reset_position(self, total_btc: float, cost_basis: float):
        with self.connection() as conn:
            conn.execute("DELETE FROM sell_executions")
            conn.execute("DELETE FROM sell_signals")
            conn.execute("DELETE FROM position")
            conn.execute("""
                INSERT INTO position (id, total_btc, sold_btc, cost_basis, created_at, updated_at)
                VALUES (1, ?, 0, ?, ?, ?)
            """, (total_btc, cost_basis, datetime.now().isoformat(), datetime.now().isoformat()))