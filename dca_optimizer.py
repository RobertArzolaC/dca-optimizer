#!/usr/bin/env python3
"""
DCA Optimizer - Script Standalone
Ejecutar via cronjob: 0 9 * * 1 /usr/bin/python3 /path/to/dca_optimizer.py

Requisitos: pip install requests pandas
"""

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

import pandas as pd
import requests

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

# TIMING ÓPTIMO (basado en investigación histórica):
# - Domingo 03:00 UTC: Early Asian session, precios ~1.7% bajo promedio diario
# - Captura descuento de fin de semana (2-3% vs mid-week)
# - Posiciona antes del lunes (día con mayor retorno promedio +0.51%)
# - Evitar: 14:00-21:00 UTC weekdays (peak institucional, precios premium)
#
# Crontab recomendado: 0 3 * * 0 (Domingo 03:00 UTC)

CONFIG = {
    "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    "base_amount_usd": float(os.getenv("DCA_BASE_AMOUNT", "100")),
    "db_path": os.getenv("DCA_DB_PATH", "dca_history.db"),
    # Umbrales de señales
    "rsi_oversold": 35,
    "rsi_overbought": 70,
    "ma_dip_threshold": 0.97,  # 3% bajo MA7
    "weekly_drop_threshold": -3.0,
}

MULTIPLIERS = {
    "TURBO_BUY": 1.6,
    "EXTRA_BUY": 1.3,
    "NORMAL_DCA": 1.0,
    "SKIP": 0.0,
}


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class MarketData:
    price: float
    ma7: float
    ma21: float
    pct_change_7d: float
    rsi: float
    timestamp: str


@dataclass
class Signal:
    signal_type: str
    multiplier: float
    suggested_amount: float
    reasons: str  # JSON string para SQLite
    market_data: MarketData


# ============================================================================
# DATABASE (SQLite)
# ============================================================================


def init_db(db_path: str) -> sqlite3.Connection:
    """Inicializa DB y crea tablas si no existen"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            multiplier REAL NOT NULL,
            suggested_amount REAL NOT NULL,
            reasons TEXT,
            price REAL NOT NULL,
            ma7 REAL NOT NULL,
            ma21 REAL NOT NULL,
            rsi REAL NOT NULL,
            pct_change_7d REAL NOT NULL,
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
            rsi REAL,
            volume REAL
        )
    """)

    conn.commit()
    return conn


def save_signal(conn: sqlite3.Connection, signal: Signal) -> int:
    """Guarda señal y retorna ID"""
    cursor = conn.execute(
        """
        INSERT INTO signals (
            timestamp, signal_type, multiplier, suggested_amount, reasons,
            price, ma7, ma21, rsi, pct_change_7d
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            signal.market_data.timestamp,
            signal.signal_type,
            signal.multiplier,
            signal.suggested_amount,
            signal.reasons,
            signal.market_data.price,
            signal.market_data.ma7,
            signal.market_data.ma21,
            signal.market_data.rsi,
            signal.market_data.pct_change_7d,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def update_notification_sent(conn: sqlite3.Connection, signal_id: int):
    """Marca notificación como enviada"""
    conn.execute(
        "UPDATE signals SET notification_sent = 1 WHERE id = ?", (signal_id,)
    )
    conn.commit()


def save_price_snapshot(conn: sqlite3.Connection, data: MarketData):
    """Guarda snapshot de precio para historial"""
    conn.execute(
        """
        INSERT INTO price_history (timestamp, price, ma7, ma21, rsi)
        VALUES (?, ?, ?, ?, ?)
    """,
        (data.timestamp, data.price, data.ma7, data.ma21, data.rsi),
    )
    conn.commit()


# ============================================================================
# MARKET ANALYZER
# ============================================================================


def fetch_market_data() -> MarketData:
    """Obtiene datos de CoinGecko y calcula indicadores"""
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {"vs_currency": "usd", "days": 30}

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    df = pd.DataFrame(data["prices"], columns=["ts", "price"])

    current_price = float(df["price"].iloc[-1])
    ma7 = float(df["price"].rolling(7).mean().iloc[-1])
    ma21 = float(df["price"].rolling(21).mean().iloc[-1])

    price_7d_ago = (
        float(df["price"].iloc[-7]) if len(df) >= 7 else current_price
    )
    pct_change_7d = ((current_price / price_7d_ago) - 1) * 100

    rsi = calculate_rsi(df["price"])

    return MarketData(
        price=round(current_price, 2),
        ma7=round(ma7, 2),
        ma21=round(ma21, 2),
        pct_change_7d=round(pct_change_7d, 2),
        rsi=round(rsi, 2),
        timestamp=datetime.now().isoformat(),
    )


def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    """Calcula RSI"""
    deltas = prices.diff()
    gains = deltas.where(deltas > 0, 0).rolling(period).mean()
    losses = (-deltas.where(deltas < 0, 0)).rolling(period).mean()

    rs = gains / losses
    rsi = 100 - (100 / (1 + rs))

    return float(rsi.iloc[-1])


# ============================================================================
# DECISION ENGINE
# ============================================================================


def evaluate_market(data: MarketData) -> Signal:
    """Evalúa mercado y genera señal"""
    reasons = []

    # SKIP si sobrecomprado
    if data.rsi > CONFIG["rsi_overbought"]:
        return Signal(
            signal_type="SKIP",
            multiplier=MULTIPLIERS["SKIP"],
            suggested_amount=0,
            reasons=f"RSI sobrecomprado: {data.rsi}",
            market_data=data,
        )

    # TURBO_BUY conditions
    turbo = []
    if data.price < data.ma7 * CONFIG["ma_dip_threshold"]:
        turbo.append(
            f"Precio ${data.price:,} < 97% MA7 (${data.ma7 * 0.97:,.0f})"
        )

    if data.pct_change_7d <= CONFIG["weekly_drop_threshold"]:
        turbo.append(f"Caída semanal: {data.pct_change_7d}%")

    if turbo:
        return Signal(
            signal_type="TURBO_BUY",
            multiplier=MULTIPLIERS["TURBO_BUY"],
            suggested_amount=CONFIG["base_amount_usd"]
            * MULTIPLIERS["TURBO_BUY"],
            reasons=" | ".join(turbo),
            market_data=data,
        )

    # EXTRA_BUY si RSI bajo
    if data.rsi < CONFIG["rsi_oversold"]:
        return Signal(
            signal_type="EXTRA_BUY",
            multiplier=MULTIPLIERS["EXTRA_BUY"],
            suggested_amount=CONFIG["base_amount_usd"]
            * MULTIPLIERS["EXTRA_BUY"],
            reasons=f"RSI sobreventa: {data.rsi}",
            market_data=data,
        )

    # NORMAL_DCA
    return Signal(
        signal_type="NORMAL_DCA",
        multiplier=MULTIPLIERS["NORMAL_DCA"],
        suggested_amount=CONFIG["base_amount_usd"],
        reasons="Condiciones normales",
        market_data=data,
    )


# ============================================================================
# TELEGRAM
# ============================================================================


def send_telegram(message: str) -> bool:
    """Envía mensaje a Telegram"""
    if not CONFIG["telegram_token"] or not CONFIG["telegram_chat_id"]:
        print("⚠️  Telegram no configurado")
        return False

    url = f"https://api.telegram.org/bot{CONFIG['telegram_token']}/sendMessage"
    payload = {
        "chat_id": CONFIG["telegram_chat_id"],
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Error Telegram: {e}")
        return False


def format_message(signal: Signal) -> str:
    """Formatea mensaje para Telegram"""
    data = signal.market_data

    emoji = {
        "TURBO_BUY": "🚀",
        "EXTRA_BUY": "📈",
        "NORMAL_DCA": "✅",
        "SKIP": "⏸️",
    }.get(signal.signal_type, "❓")

    now = datetime.now(UTC)
    timing_note = ""
    if now.weekday() == 6 and 2 <= now.hour <= 5:  # Domingo early Asian
        timing_note = "\n⏰ _Ventana óptima: Early Asian session_"

    return f"""
{emoji} *Weekly DCA Signal*

📊 *Mercado*
• Precio: `${data.price:,.2f}`
• MA7: `${data.ma7:,.2f}`
• MA21: `${data.ma21:,.2f}`
• RSI: `{data.rsi}`
• 7d: `{data.pct_change_7d:+.1f}%`

🎯 *{signal.signal_type}* (x{signal.multiplier})
💰 Monto: `${signal.suggested_amount:,.2f}`

📝 _{signal.reasons}_{timing_note}
""".strip()


# ============================================================================
# MAIN
# ============================================================================


def main():
    print(f"🔄 DCA Optimizer - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("-" * 50)

    # Init DB
    db_path = Path(CONFIG["db_path"])
    conn = init_db(str(db_path))
    print(f"📁 DB: {db_path.absolute()}")

    # Fetch market data
    print("📡 Obteniendo datos de mercado...")
    try:
        market_data = fetch_market_data()
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

    print(f"   Precio: ${market_data.price:,}")
    print(f"   RSI: {market_data.rsi}")
    print(f"   7d: {market_data.pct_change_7d:+.1f}%")

    # Save price snapshot
    save_price_snapshot(conn, market_data)

    # Evaluate
    signal = evaluate_market(market_data)
    print(f"\n🎯 Señal: {signal.signal_type}")
    print(f"   Multiplicador: x{signal.multiplier}")
    print(f"   Monto: ${signal.suggested_amount:,.2f}")
    print(f"   Razón: {signal.reasons}")

    # Save signal
    signal_id = save_signal(conn, signal)
    print(f"\n💾 Guardado en DB (ID: {signal_id})")

    # Send notification
    if signal.signal_type != "SKIP" or CONFIG.get("notify_skip", False):
        message = format_message(signal)
        if send_telegram(message):
            update_notification_sent(conn, signal_id)
            print("📱 Notificación enviada")

    conn.close()
    print("\n✅ Completado")
    return 0


if __name__ == "__main__":
    exit(main())
