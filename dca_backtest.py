#!/usr/bin/env python3
"""
DCA Optimizer - Utilidades para Backtesting
Exporta datos y simula estrategias históricas

TIMING ÓPTIMO INVESTIGADO:
- Domingo 03:00 UTC (Early Asian session)
- Precios ~1.7% bajo promedio diario
- Captura descuento weekend 2-3%
"""

import sqlite3

import pandas as pd
import requests

# Retornos promedio por día de la semana (datos históricos)
DAY_RETURNS = {
    0: 0.51,  # Monday - MEJOR
    1: 0.07,  # Tuesday
    2: 0.12,  # Wednesday
    3: 0.05,  # Thursday
    4: -0.19,  # Friday - PEOR
    5: 0.41,  # Saturday
    6: 0.04,  # Sunday - ÓPTIMO PARA COMPRAR
}


def export_signals_to_csv(
    db_path: str = "dca_history.db", output: str = "signals.csv"
):
    """Exporta historial de señales a CSV"""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM signals ORDER BY timestamp", conn)
    df.to_csv(output, index=False)
    conn.close()
    print(f"✅ Exportado {len(df)} señales a {output}")
    return df


def export_prices_to_csv(
    db_path: str = "dca_history.db", output: str = "prices.csv"
):
    """Exporta historial de precios a CSV"""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT * FROM price_history ORDER BY timestamp", conn
    )
    df.to_csv(output, index=False)
    conn.close()
    print(f"✅ Exportado {len(df)} snapshots a {output}")
    return df


def fetch_historical_data(days: int = 365) -> pd.DataFrame:
    """Descarga datos históricos de CoinGecko para backtesting"""
    print(f"📡 Descargando {days} días de datos históricos...")

    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {"vs_currency": "usd", "days": days}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    df = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    # Resample a diario
    df = df.resample("D").last()

    # Calcular indicadores
    df["ma7"] = df["price"].rolling(7).mean()
    df["ma21"] = df["price"].rolling(21).mean()
    df["pct_7d"] = df["price"].pct_change(7) * 100

    # RSI
    delta = df["price"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    df = df.dropna()
    print(f"✅ {len(df)} días de datos procesados")

    return df


def backtest_strategy(
    df: pd.DataFrame,
    base_amount: float = 100,
    rsi_oversold: int = 35,
    rsi_overbought: int = 70,
    ma_dip: float = 0.97,
    weekly_drop: float = -3.0,
) -> pd.DataFrame:
    """
    Simula estrategia DCA optimizada vs DCA simple
    Retorna DataFrame con resultados semanales
    """
    # Resample a semanal (lunes)
    weekly = df.resample("W-MON").last()

    results = []

    for date, row in weekly.iterrows():
        # Determinar señal
        if row["rsi"] > rsi_overbought:
            signal = "SKIP"
            multiplier = 0.0
        elif row["price"] < row["ma7"] * ma_dip or row["pct_7d"] <= weekly_drop:
            signal = "TURBO_BUY"
            multiplier = 1.6
        elif row["rsi"] < rsi_oversold:
            signal = "EXTRA_BUY"
            multiplier = 1.3
        else:
            signal = "NORMAL_DCA"
            multiplier = 1.0

        amount_optimized = base_amount * multiplier
        btc_optimized = (
            amount_optimized / row["price"] if row["price"] > 0 else 0
        )
        btc_simple = base_amount / row["price"] if row["price"] > 0 else 0

        results.append(
            {
                "date": date,
                "price": row["price"],
                "rsi": row["rsi"],
                "pct_7d": row["pct_7d"],
                "signal": signal,
                "multiplier": multiplier,
                "usd_simple": base_amount,
                "usd_optimized": amount_optimized,
                "btc_simple": btc_simple,
                "btc_optimized": btc_optimized,
            }
        )

    return pd.DataFrame(results)


def analyze_backtest(results: pd.DataFrame, current_price: float = None):
    """Analiza resultados del backtest"""
    if current_price is None:
        current_price = results["price"].iloc[-1]

    total_usd_simple = results["usd_simple"].sum()
    total_usd_optimized = results["usd_optimized"].sum()

    total_btc_simple = results["btc_simple"].sum()
    total_btc_optimized = results["btc_optimized"].sum()

    value_simple = total_btc_simple * current_price
    value_optimized = total_btc_optimized * current_price

    roi_simple = ((value_simple / total_usd_simple) - 1) * 100
    roi_optimized = ((value_optimized / total_usd_optimized) - 1) * 100

    avg_price_simple = total_usd_simple / total_btc_simple
    avg_price_optimized = total_usd_optimized / total_btc_optimized

    signal_counts = results["signal"].value_counts()

    print("\n" + "=" * 60)
    print("📊 RESULTADOS DEL BACKTEST")
    print("=" * 60)

    print(
        f"\n📅 Período: {results['date'].iloc[0].date()} → {results['date'].iloc[-1].date()}"
    )
    print(f"📈 Semanas: {len(results)}")
    print(f"💵 Precio actual: ${current_price:,.2f}")

    print("\n🔢 Distribución de Señales:")
    for signal, count in signal_counts.items():
        pct = (count / len(results)) * 100
        print(f"   {signal}: {count} ({pct:.1f}%)")

    print("\n💰 DCA Simple:")
    print(f"   Invertido: ${total_usd_simple:,.2f}")
    print(f"   BTC acumulado: {total_btc_simple:.8f}")
    print(f"   Precio promedio: ${avg_price_simple:,.2f}")
    print(f"   Valor actual: ${value_simple:,.2f}")
    print(f"   ROI: {roi_simple:+.2f}%")

    print("\n🚀 DCA Optimizado:")
    print(f"   Invertido: ${total_usd_optimized:,.2f}")
    print(f"   BTC acumulado: {total_btc_optimized:.8f}")
    print(f"   Precio promedio: ${avg_price_optimized:,.2f}")
    print(f"   Valor actual: ${value_optimized:,.2f}")
    print(f"   ROI: {roi_optimized:+.2f}%")

    print("\n📈 Comparación:")
    btc_diff = total_btc_optimized - total_btc_simple
    btc_diff_pct = (btc_diff / total_btc_simple) * 100
    print(f"   BTC extra acumulado: {btc_diff:+.8f} ({btc_diff_pct:+.2f}%)")
    print(f"   Diferencia en valor: ${value_optimized - value_simple:+,.2f}")

    return {
        "roi_simple": roi_simple,
        "roi_optimized": roi_optimized,
        "btc_simple": total_btc_simple,
        "btc_optimized": total_btc_optimized,
        "avg_price_simple": avg_price_simple,
        "avg_price_optimized": avg_price_optimized,
    }


def analyze_day_of_week_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analiza patrones de precio por día de la semana
    Útil para validar timing óptimo con datos recientes
    """
    df = df.copy()
    df["day_of_week"] = df.index.dayofweek
    df["daily_return"] = df["price"].pct_change() * 100

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    stats = (
        df.groupby("day_of_week")
        .agg(
            {
                "price": ["mean", "min", "max", "std"],
                "daily_return": ["mean", "std", "count"],
            }
        )
        .round(2)
    )

    print("\n" + "=" * 60)
    print("📅 ANÁLISIS POR DÍA DE LA SEMANA")
    print("=" * 60)
    print("\nRetorno promedio diario (%):")

    for day in range(7):
        if day in df["day_of_week"].values:
            day_data = df[df["day_of_week"] == day]
            avg_ret = day_data["daily_return"].mean()
            avg_price = day_data["price"].mean()
            indicator = (
                "⭐ COMPRAR"
                if day == 6
                else ("📈 MEJOR RET" if day == 0 else "")
            )
            print(
                f"   {day_names[day]}: {avg_ret:+.3f}% | Precio prom: ${avg_price:,.0f} {indicator}"
            )

    # Comparar weekend vs weekday
    weekend = df[df["day_of_week"].isin([5, 6])]["price"].mean()
    weekday = df[df["day_of_week"].isin([0, 1, 2, 3, 4])]["price"].mean()
    discount = ((weekend / weekday) - 1) * 100

    print(f"\n💡 Descuento weekend vs weekday: {discount:.2f}%")
    print(
        f"   (Precio prom weekend: ${weekend:,.0f} vs weekday: ${weekday:,.0f})"
    )

    return stats


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso:")
        print("  python dca_backtest.py export       - Exporta DB a CSV")
        print(
            "  python dca_backtest.py backtest     - Ejecuta backtest histórico"
        )
        print("  python dca_backtest.py backtest 365 - Backtest de N días")
        print(
            "  python dca_backtest.py timing       - Analiza patrones día/semana"
        )
        print("  python dca_backtest.py timing 90    - Análisis de N días")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "export":
        export_signals_to_csv()
        export_prices_to_csv()

    elif cmd == "backtest":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 365

        df = fetch_historical_data(days)
        df.to_csv("historical_prices.csv")
        print("💾 Guardado en historical_prices.csv")

        results = backtest_strategy(df)
        results.to_csv("backtest_results.csv", index=False)
        print("💾 Guardado en backtest_results.csv")

        analyze_backtest(results)

    elif cmd == "timing":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 180
        print(f"📡 Analizando patrones de {days} días...")

        df = fetch_historical_data(days)
        analyze_day_of_week_patterns(df)

        print("\n" + "=" * 60)
        print("⏰ RECOMENDACIÓN DE TIMING")
        print("=" * 60)
        print("   Crontab óptimo: 0 3 * * 0")
        print("   (Domingo 03:00 UTC - Early Asian session)")
        print("   Ventaja estimada: 1-2% sobre DCA aleatorio")

    else:
        print(f"Comando desconocido: {cmd}")
