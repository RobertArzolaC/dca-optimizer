#!/usr/bin/env python3
"""
DCA Sell Optimizer - Sistema Event-Driven de Señales de Venta
Detecta tops de mercado usando indicadores on-chain + técnicos

Ejecutar via cronjob cada 4-6 horas:
0 */4 * * * /usr/bin/python3 /path/to/dca_sell.py

Para ventas óptimas: ejecutar 14:00-21:00 UTC (horario institucional)
0 15,19 * * 1-5 /usr/bin/python3 /path/to/dca_sell.py
"""

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import pandas as pd
import requests

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

CONFIG = {
    "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    "db_path": os.getenv("DCA_DB_PATH", "dca_sell_history.db"),
    # Tu posición
    "total_btc": float(os.getenv("TOTAL_BTC", "0.5")),
    "cost_basis_usd": float(os.getenv("COST_BASIS", "25000")),
    # Umbrales On-Chain (basados en investigación histórica)
    "mvrv_warning": 3.0,  # Zona de precaución
    "mvrv_danger": 5.0,  # Zona de peligro (ciclos anteriores: 7+)
    "mvrv_critical": 7.0,  # Top histórico
    "nupl_warning": 0.5,  # Belief zone
    "nupl_danger": 0.65,  # Euphoria approaching
    "nupl_critical": 0.75,  # Euphoria (top histórico)
    # Umbrales Técnicos
    "rsi_warning": 70,
    "rsi_danger": 80,
    "rsi_critical": 88,
    "mayer_warning": 1.5,  # Sobre 200 MA
    "mayer_danger": 2.0,  # Zona caliente
    "mayer_critical": 2.4,  # Top histórico
    # Estrategia de venta escalonada (% de posición)
    "sell_tiers": {
        1: 0.10,  # 1 indicador en warning: vender 10%
        2: 0.15,  # 2 indicadores: vender 15%
        3: 0.25,  # 3+ indicadores: vender 25%
        "pi_cycle": 0.25,  # Pi Cycle triggered: vender 25%
    },
    # Mínimo de señales para alertar
    "min_signals_to_alert": 1,
    "min_signals_to_sell": 2,
}


class SignalLevel(Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    DANGER = "DANGER"
    CRITICAL = "CRITICAL"


@dataclass
class Indicator:
    name: str
    value: float
    level: SignalLevel
    threshold_warning: float
    threshold_danger: float
    threshold_critical: float
    description: str = ""


@dataclass
class MarketAnalysis:
    price: float
    price_change_24h: float
    price_change_7d: float
    indicators: list[Indicator] = field(default_factory=list)
    signals_warning: int = 0
    signals_danger: int = 0
    signals_critical: int = 0
    pi_cycle_triggered: bool = False
    timestamp: str = ""

    @property
    def total_signals(self) -> int:
        return (
            self.signals_warning + self.signals_danger + self.signals_critical
        )

    @property
    def risk_score(self) -> int:
        """0-100 score de riesgo de top"""
        score = 0
        score += self.signals_warning * 10
        score += self.signals_danger * 25
        score += self.signals_critical * 40
        if self.pi_cycle_triggered:
            score += 30
        return min(score, 100)


@dataclass
class SellRecommendation:
    should_alert: bool
    should_sell: bool
    sell_percentage: float
    sell_amount_btc: float
    sell_amount_usd: float
    reasons: list[str]
    analysis: MarketAnalysis
    position_remaining: float


# ============================================================================
# DATABASE
# ============================================================================


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)

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
            signals_warning INTEGER,
            signals_danger INTEGER,
            signals_critical INTEGER,
            pi_cycle_triggered INTEGER,
            mvrv_zscore REAL,
            nupl REAL,
            rsi REAL,
            mayer_multiple REAL,
            recommendation TEXT,
            sell_percentage REAL,
            sell_amount_btc REAL,
            notification_sent INTEGER DEFAULT 0,
            executed INTEGER DEFAULT 0,
            indicators_json TEXT
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

    conn.commit()
    return conn


def get_position(conn: sqlite3.Connection) -> dict:
    """Obtiene posición actual o crea una nueva"""
    row = conn.execute("SELECT * FROM position WHERE id = 1").fetchone()

    if not row:
        conn.execute(
            """
            INSERT INTO position (id, total_btc, sold_btc, cost_basis, created_at, updated_at)
            VALUES (1, ?, 0, ?, ?, ?)
        """,
            (
                CONFIG["total_btc"],
                CONFIG["cost_basis_usd"],
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return {
            "total_btc": CONFIG["total_btc"],
            "sold_btc": 0,
            "remaining_btc": CONFIG["total_btc"],
            "cost_basis": CONFIG["cost_basis_usd"],
        }

    return {
        "total_btc": row[1],
        "sold_btc": row[2],
        "remaining_btc": row[1] - row[2],
        "cost_basis": row[3],
    }


def save_signal(conn: sqlite3.Connection, rec: SellRecommendation) -> int:
    a = rec.analysis
    indicators_json = json.dumps(
        [
            {"name": i.name, "value": i.value, "level": i.level.value}
            for i in a.indicators
        ]
    )

    cursor = conn.execute(
        """
        INSERT INTO sell_signals (
            timestamp, price, risk_score, signals_warning, signals_danger,
            signals_critical, pi_cycle_triggered, mvrv_zscore, nupl, rsi,
            mayer_multiple, recommendation, sell_percentage, sell_amount_btc,
            indicators_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            a.timestamp,
            a.price,
            a.risk_score,
            a.signals_warning,
            a.signals_danger,
            a.signals_critical,
            int(a.pi_cycle_triggered),
            next(
                (i.value for i in a.indicators if i.name == "MVRV Z-Score"),
                None,
            ),
            next((i.value for i in a.indicators if i.name == "NUPL"), None),
            next(
                (i.value for i in a.indicators if i.name == "RSI (Daily)"), None
            ),
            next(
                (i.value for i in a.indicators if i.name == "Mayer Multiple"),
                None,
            ),
            "SELL"
            if rec.should_sell
            else ("ALERT" if rec.should_alert else "HOLD"),
            rec.sell_percentage,
            rec.sell_amount_btc,
            indicators_json,
        ),
    )
    conn.commit()
    return cursor.lastrowid


# ============================================================================
# DATA FETCHING
# ============================================================================


def fetch_price_data() -> dict:
    """Obtiene precio actual y datos básicos de CoinGecko"""
    url = "https://api.coingecko.com/api/v3/coins/bitcoin"
    params = {
        "localization": "false",
        "tickers": "false",
        "community_data": "false",
    }

    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    return {
        "price": data["market_data"]["current_price"]["usd"],
        "change_24h": data["market_data"]["price_change_percentage_24h"],
        "change_7d": data["market_data"]["price_change_percentage_7d"],
        "ath": data["market_data"]["ath"]["usd"],
        "ath_change": data["market_data"]["ath_change_percentage"]["usd"],
    }


def fetch_historical_prices(days: int = 365) -> pd.DataFrame:
    """Obtiene precios históricos para calcular MAs y RSI"""
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {"vs_currency": "usd", "days": days}

    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    df = pd.DataFrame(data["prices"], columns=["ts", "price"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms")
    df.set_index("date", inplace=True)
    df = df.resample("D").last()

    return df


def fetch_fear_greed_index() -> int:
    """Fear & Greed Index como proxy de sentimiento"""
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        r = requests.get(url, timeout=10)
        return int(r.json()["data"][0]["value"])
    except:
        return 50  # Neutral si falla


def fetch_onchain_metrics() -> dict:
    """
    Intenta obtener métricas on-chain de fuentes gratuitas.
    Si no están disponibles, usa estimaciones basadas en precio.
    """
    metrics = {
        "mvrv_zscore": None,
        "nupl": None,
        "pi_cycle_triggered": False,
    }

    # Intenta CoinMetrics Community API
    try:
        url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
        params = {
            "assets": "btc",
            "metrics": "CapMVRVCur",
            "frequency": "1d",
            "page_size": 1,
            "sort": "time",
            "sort_ascending": "false",
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("data"):
                mvrv = float(data["data"][0]["CapMVRVCur"])
                # Convertir MVRV a Z-Score aproximado
                metrics["mvrv_zscore"] = (
                    mvrv - 1.5
                ) / 0.8  # Normalización aproximada
    except Exception as e:
        print(f"⚠️ CoinMetrics error: {e}")

    # Intenta blockchain.info para datos adicionales
    try:
        # Puell Multiple proxy (ingresos mineros relativos)
        url = "https://api.blockchain.info/charts/miners-revenue?timespan=30days&format=json"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            values = [p["y"] for p in data["values"]]
            if values:
                current = values[-1]
                avg_365 = sum(values) / len(values)
                metrics["puell_approx"] = (
                    current / avg_365 if avg_365 > 0 else 1.0
                )
    except:
        pass

    return metrics


# ============================================================================
# INDICATOR CALCULATIONS
# ============================================================================


def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def calculate_mayer_multiple(current_price: float, ma_200: float) -> float:
    return current_price / ma_200 if ma_200 > 0 else 1.0


def check_pi_cycle(df: pd.DataFrame) -> bool:
    """
    Pi Cycle Top: 111 DMA cruza por encima de 2x 350 DMA
    Históricamente predijo tops con 3 días de precisión
    """
    if len(df) < 350:
        return False

    ma_111 = df["price"].rolling(111).mean()
    ma_350_x2 = df["price"].rolling(350).mean() * 2

    # Verificar cruce reciente (últimos 3 días)
    for i in range(-3, 0):
        if (
            ma_111.iloc[i] >= ma_350_x2.iloc[i]
            and ma_111.iloc[i - 1] < ma_350_x2.iloc[i - 1]
        ):
            return True

    # También alertar si está muy cerca del cruce
    current_gap = (ma_350_x2.iloc[-1] - ma_111.iloc[-1]) / ma_350_x2.iloc[-1]
    if current_gap < 0.02:  # Menos de 2% de diferencia
        return True

    return False


def estimate_mvrv_from_price(
    current_price: float, historical_prices: pd.DataFrame
) -> float:
    """
    Estima MVRV Z-Score basado en desviación del precio vs promedio histórico.
    No es preciso como on-chain real, pero útil como proxy.
    """
    if len(historical_prices) < 200:
        return 1.0

    mean_price = historical_prices["price"].mean()
    std_price = historical_prices["price"].std()

    z_score = (current_price - mean_price) / std_price if std_price > 0 else 0

    # Normalizar a escala similar a MVRV Z-Score (0-10)
    return max(0, min(10, z_score * 1.5 + 2))


def estimate_nupl(
    current_price: float, historical_prices: pd.DataFrame
) -> float:
    """
    Estima NUPL basado en % de días que el precio actual está en ganancia.
    Proxy simplificado del verdadero NUPL on-chain.
    """
    if len(historical_prices) < 100:
        return 0.5

    days_in_profit = (historical_prices["price"] < current_price).sum()
    total_days = len(historical_prices)

    # NUPL aproximado: proporción de "holders" en ganancia
    nupl = (days_in_profit / total_days) - 0.5

    return max(-1, min(1, nupl * 1.5))


# ============================================================================
# ANALYSIS ENGINE
# ============================================================================


def analyze_market() -> MarketAnalysis:
    """Analiza el mercado y genera señales"""

    print("📡 Obteniendo datos de mercado...")
    price_data = fetch_price_data()
    historical = fetch_historical_prices(365)
    onchain = fetch_onchain_metrics()
    fear_greed = fetch_fear_greed_index()

    current_price = price_data["price"]

    # Calcular indicadores técnicos
    ma_200 = float(historical["price"].rolling(200).mean().iloc[-1])
    ma_50 = float(historical["price"].rolling(50).mean().iloc[-1])
    rsi_daily = calculate_rsi(historical["price"], 14)
    rsi_weekly = calculate_rsi(historical["price"].resample("W").last(), 14)
    mayer = calculate_mayer_multiple(current_price, ma_200)
    pi_cycle = check_pi_cycle(historical)

    # Obtener o estimar métricas on-chain
    mvrv = onchain.get("mvrv_zscore") or estimate_mvrv_from_price(
        current_price, historical
    )
    nupl = estimate_nupl(current_price, historical)

    # Crear indicadores
    indicators = []
    signals_w, signals_d, signals_c = 0, 0, 0

    def add_indicator(name, value, warn, danger, crit, desc=""):
        nonlocal signals_w, signals_d, signals_c

        if value >= crit:
            level = SignalLevel.CRITICAL
            signals_c += 1
        elif value >= danger:
            level = SignalLevel.DANGER
            signals_d += 1
        elif value >= warn:
            level = SignalLevel.WARNING
            signals_w += 1
        else:
            level = SignalLevel.SAFE

        indicators.append(
            Indicator(name, value, level, warn, danger, crit, desc)
        )

    # Agregar todos los indicadores
    add_indicator(
        "MVRV Z-Score",
        mvrv,
        CONFIG["mvrv_warning"],
        CONFIG["mvrv_danger"],
        CONFIG["mvrv_critical"],
        "On-chain: Market vs Realized Value",
    )

    add_indicator(
        "NUPL",
        nupl,
        CONFIG["nupl_warning"],
        CONFIG["nupl_danger"],
        CONFIG["nupl_critical"],
        "On-chain: Net Unrealized Profit/Loss",
    )

    add_indicator(
        "RSI (Daily)",
        rsi_daily,
        CONFIG["rsi_warning"],
        CONFIG["rsi_danger"],
        CONFIG["rsi_critical"],
        "Technical: Relative Strength Index",
    )

    add_indicator(
        "Mayer Multiple",
        mayer,
        CONFIG["mayer_warning"],
        CONFIG["mayer_danger"],
        CONFIG["mayer_critical"],
        "Technical: Price / 200 MA",
    )

    # Fear & Greed (invertido: alto = peligro)
    add_indicator(
        "Fear & Greed",
        fear_greed,
        65,
        75,
        85,
        "Sentiment: Market emotion index",
    )

    return MarketAnalysis(
        price=current_price,
        price_change_24h=price_data["change_24h"],
        price_change_7d=price_data["change_7d"],
        indicators=indicators,
        signals_warning=signals_w,
        signals_danger=signals_d,
        signals_critical=signals_c,
        pi_cycle_triggered=pi_cycle,
        timestamp=datetime.now().isoformat(),
    )


def generate_recommendation(
    analysis: MarketAnalysis, position: dict
) -> SellRecommendation:
    """Genera recomendación de venta basada en análisis"""

    remaining = position["remaining_btc"]
    reasons = []
    sell_pct = 0.0

    # Determinar % a vender basado en señales
    total_signals = analysis.total_signals

    if analysis.pi_cycle_triggered:
        sell_pct = max(sell_pct, CONFIG["sell_tiers"]["pi_cycle"])
        reasons.append("🚨 PI CYCLE TOP TRIGGERED - Señal histórica de top")

    if analysis.signals_critical > 0:
        sell_pct = max(sell_pct, CONFIG["sell_tiers"][3])
        for ind in analysis.indicators:
            if ind.level == SignalLevel.CRITICAL:
                reasons.append(
                    f"🔴 {ind.name}: {ind.value:.2f} (CRÍTICO > {ind.threshold_critical})"
                )

    if analysis.signals_danger > 0:
        sell_pct = max(sell_pct, CONFIG["sell_tiers"].get(2, 0.15))
        for ind in analysis.indicators:
            if ind.level == SignalLevel.DANGER:
                reasons.append(
                    f"🟠 {ind.name}: {ind.value:.2f} (PELIGRO > {ind.threshold_danger})"
                )

    if analysis.signals_warning > 0 and sell_pct == 0:
        sell_pct = CONFIG["sell_tiers"].get(1, 0.10)
        for ind in analysis.indicators:
            if ind.level == SignalLevel.WARNING:
                reasons.append(
                    f"🟡 {ind.name}: {ind.value:.2f} (WARNING > {ind.threshold_warning})"
                )

    # Calcular montos
    sell_btc = remaining * sell_pct
    sell_usd = sell_btc * analysis.price

    should_alert = (
        total_signals >= CONFIG["min_signals_to_alert"]
        or analysis.pi_cycle_triggered
    )
    should_sell = (
        total_signals >= CONFIG["min_signals_to_sell"]
        or analysis.pi_cycle_triggered
    )

    if not reasons:
        reasons.append("✅ Todos los indicadores en zona segura")

    return SellRecommendation(
        should_alert=should_alert,
        should_sell=should_sell,
        sell_percentage=sell_pct,
        sell_amount_btc=sell_btc,
        sell_amount_usd=sell_usd,
        reasons=reasons,
        analysis=analysis,
        position_remaining=remaining,
    )


# ============================================================================
# TELEGRAM
# ============================================================================


def send_telegram(message: str) -> bool:
    if not CONFIG["telegram_token"] or not CONFIG["telegram_chat_id"]:
        print("⚠️ Telegram no configurado")
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


def format_sell_alert(rec: SellRecommendation, position: dict) -> str:
    a = rec.analysis

    # Emoji basado en riesgo
    if a.risk_score >= 70:
        header = "🚨 *ALERTA CRÍTICA DE VENTA*"
    elif a.risk_score >= 50:
        header = "⚠️ *SEÑAL DE VENTA DETECTADA*"
    elif a.risk_score >= 30:
        header = "📊 *Indicadores en zona de precaución*"
    else:
        header = "✅ *Mercado en zona segura*"

    # Calcular P&L
    cost_per_btc = position["cost_basis"] / position["total_btc"]
    current_value = position["remaining_btc"] * a.price
    total_cost = position["remaining_btc"] * cost_per_btc
    unrealized_pnl = current_value - total_cost
    pnl_pct = (unrealized_pnl / total_cost) * 100 if total_cost > 0 else 0

    msg = f"""
{header}

📈 *Precio BTC:* `${a.price:,.2f}`
24h: `{a.price_change_24h:+.1f}%` | 7d: `{a.price_change_7d:+.1f}%`

🎯 *Risk Score:* `{a.risk_score}/100`
{"🔴" * (a.risk_score // 20)}{"⚪" * (5 - a.risk_score // 20)}

📊 *Indicadores:*
"""

    for ind in a.indicators:
        emoji = {
            "SAFE": "✅",
            "WARNING": "🟡",
            "DANGER": "🟠",
            "CRITICAL": "🔴",
        }[ind.level.value]
        msg += f"• {emoji} {ind.name}: `{ind.value:.2f}`\n"

    if a.pi_cycle_triggered:
        msg += "\n🚨 *PI CYCLE TOP ACTIVADO*\n"

    msg += f"""
💼 *Tu Posición:*
• Restante: `{position["remaining_btc"]:.4f} BTC`
• Valor: `${current_value:,.2f}`
• P&L: `${unrealized_pnl:+,.2f}` (`{pnl_pct:+.1f}%`)

"""

    if rec.should_sell:
        msg += f"""🎯 *RECOMENDACIÓN: VENDER {rec.sell_percentage * 100:.0f}%*
• Cantidad: `{rec.sell_amount_btc:.4f} BTC`
• Valor aprox: `${rec.sell_amount_usd:,.2f}`

📝 *Razones:*
"""
        for reason in rec.reasons[:5]:
            msg += f"{reason}\n"

        msg += "\n⏰ _Mejor horario: 14:00-21:00 UTC (Lun-Vie)_"
    else:
        msg += "📝 *Estado:* Monitoreo activo, sin acción requerida"

    return msg.strip()


# ============================================================================
# MAIN
# ============================================================================


def main():
    print(
        f"🔄 DCA Sell Optimizer - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
    )
    print("=" * 60)

    # Init DB
    conn = init_db(CONFIG["db_path"])
    position = get_position(conn)

    print(f"💼 Posición: {position['remaining_btc']:.4f} BTC restantes")
    print(f"   (Vendidos: {position['sold_btc']:.4f} BTC)")

    # Analizar mercado
    try:
        analysis = analyze_market()
    except Exception as e:
        print(f"❌ Error analizando mercado: {e}")
        return 1

    print(f"\n📊 Precio: ${analysis.price:,.2f}")
    print(f"   Risk Score: {analysis.risk_score}/100")
    print(
        f"   Señales: {analysis.signals_warning}W / {analysis.signals_danger}D / {analysis.signals_critical}C"
    )

    if analysis.pi_cycle_triggered:
        print("   🚨 PI CYCLE TOP TRIGGERED!")

    # Generar recomendación
    rec = generate_recommendation(analysis, position)

    print(f"\n🎯 Recomendación: {'VENDER' if rec.should_sell else 'HOLD'}")
    if rec.should_sell:
        print(
            f"   Vender: {rec.sell_percentage * 100:.0f}% = {rec.sell_amount_btc:.4f} BTC"
        )
        print(f"   Valor: ~${rec.sell_amount_usd:,.2f}")

    # Guardar señal
    signal_id = save_signal(conn, rec)
    print(f"\n💾 Señal guardada (ID: {signal_id})")

    # Enviar notificación si hay alerta
    if rec.should_alert:
        message = format_sell_alert(rec, position)
        if send_telegram(message):
            conn.execute(
                "UPDATE sell_signals SET notification_sent = 1 WHERE id = ?",
                (signal_id,),
            )
            conn.commit()
            print("📱 Notificación enviada")
    else:
        print("📱 Sin alerta (mercado en zona segura)")

    conn.close()
    print("\n✅ Completado")
    return 0


if __name__ == "__main__":
    exit(main())
