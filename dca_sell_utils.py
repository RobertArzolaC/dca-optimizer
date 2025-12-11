#!/usr/bin/env python3
"""
DCA Sell Optimizer - Utilidades
- Registrar ventas ejecutadas
- Ver historial de señales
- Exportar datos para análisis
- Dashboard de posición
"""

import os
import sqlite3
import sys
from datetime import datetime

import pandas as pd

DB_PATH = os.getenv("DCA_DB_PATH", "dca_sell_history.db")


def init_db(db_path: str) -> sqlite3.Connection:
    """Inicializa DB y crea tablas si no existen"""
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


def get_connection():
    """Obtiene conexión inicializando tablas si es necesario"""
    return init_db(DB_PATH)


def show_position():
    """Muestra estado actual de la posición"""
    conn = get_connection()

    pos = conn.execute("SELECT * FROM position WHERE id = 1").fetchone()
    if not pos:
        print("❌ No hay posición registrada")
        return

    total, sold, cost = pos[1], pos[2], pos[3]
    remaining = total - sold

    # Obtener precio actual
    try:
        import requests

        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            timeout=10,
        )
        price = r.json()["bitcoin"]["usd"]
    except:
        price = 0

    cost_per_btc = cost / total if total > 0 else 0
    current_value = remaining * price
    realized_value = sold * price  # Aproximado
    total_value = current_value
    unrealized_pnl = current_value - (remaining * cost_per_btc)
    pnl_pct = (
        (unrealized_pnl / (remaining * cost_per_btc)) * 100
        if remaining > 0
        else 0
    )

    print("\n" + "=" * 60)
    print("💼 ESTADO DE POSICIÓN")
    print("=" * 60)
    print(f"\n📊 Precio BTC actual: ${price:,.2f}")
    print(f"\n🎯 Posición original: {total:.4f} BTC")
    print(f"   Costo base total: ${cost:,.2f}")
    print(f"   Costo por BTC: ${cost_per_btc:,.2f}")

    print(
        f"\n📈 BTC restante: {remaining:.4f} BTC ({remaining / total * 100:.1f}%)"
    )
    print(f"   Valor actual: ${current_value:,.2f}")
    print(f"   P&L no realizado: ${unrealized_pnl:+,.2f} ({pnl_pct:+.1f}%)")

    print(f"\n💰 BTC vendido: {sold:.4f} BTC ({sold / total * 100:.1f}%)")

    # Mostrar ventas ejecutadas
    sales = conn.execute("""
        SELECT timestamp, btc_sold, price_at_sale, usd_received
        FROM sell_executions ORDER BY timestamp
    """).fetchall()

    if sales:
        print("\n📜 Historial de ventas:")
        total_received = 0
        for sale in sales:
            ts, btc, price_sale, usd = sale
            total_received += usd
            print(
                f"   • {ts[:10]}: {btc:.4f} BTC @ ${price_sale:,.2f} = ${usd:,.2f}"
            )
        print(f"\n   Total recibido: ${total_received:,.2f}")

    conn.close()


def record_sale(
    btc_amount: float, price: float, exchange: str = "manual", notes: str = ""
):
    """Registra una venta ejecutada"""
    conn = get_connection()

    # Obtener última señal no ejecutada
    signal = conn.execute("""
        SELECT id FROM sell_signals
        WHERE executed = 0
        ORDER BY timestamp DESC LIMIT 1
    """).fetchone()

    signal_id = signal[0] if signal else None

    usd_received = btc_amount * price

    conn.execute(
        """
        INSERT INTO sell_executions (signal_id, timestamp, btc_sold, price_at_sale, usd_received, exchange, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            signal_id,
            datetime.now().isoformat(),
            btc_amount,
            price,
            usd_received,
            exchange,
            notes,
        ),
    )

    # Actualizar posición
    conn.execute(
        """
        UPDATE position SET sold_btc = sold_btc + ?, updated_at = ? WHERE id = 1
    """,
        (btc_amount, datetime.now().isoformat()),
    )

    # Marcar señal como ejecutada
    if signal_id:
        conn.execute(
            "UPDATE sell_signals SET executed = 1 WHERE id = ?", (signal_id,)
        )

    conn.commit()
    conn.close()

    print(
        f"✅ Venta registrada: {btc_amount:.4f} BTC @ ${price:,.2f} = ${usd_received:,.2f}"
    )


def show_signals(limit: int = 10):
    """Muestra historial de señales"""
    conn = get_connection()

    signals = conn.execute(f"""
        SELECT timestamp, price, risk_score, signals_warning, signals_danger,
               signals_critical, pi_cycle_triggered, recommendation, sell_percentage,
               notification_sent, executed
        FROM sell_signals
        ORDER BY timestamp DESC
        LIMIT {limit}
    """).fetchall()

    print("\n" + "=" * 60)
    print(f"📊 ÚLTIMAS {limit} SEÑALES")
    print("=" * 60)

    for s in signals:
        ts, price, risk, sw, sd, sc, pi, rec, pct, notif, exec = s

        emoji = (
            "🔴"
            if risk >= 70
            else ("🟠" if risk >= 50 else ("🟡" if risk >= 30 else "✅"))
        )
        pi_str = " 🚨PI" if pi else ""
        exec_str = " ✓EXEC" if exec else ""

        print(f"\n{emoji} {ts[:16]} | Risk: {risk}/100{pi_str}{exec_str}")
        print(
            f"   Price: ${price:,.0f} | Signals: {sw}W/{sd}D/{sc}C | Rec: {rec}"
        )
        if pct > 0:
            print(f"   Sugerencia: Vender {pct * 100:.0f}%")

    conn.close()


def export_data():
    """Exporta datos a CSV para análisis"""
    conn = get_connection()

    # Señales
    df_signals = pd.read_sql_query(
        "SELECT * FROM sell_signals ORDER BY timestamp", conn
    )
    df_signals.to_csv("sell_signals_export.csv", index=False)
    print(
        f"✅ Exportado: sell_signals_export.csv ({len(df_signals)} registros)"
    )

    # Ventas
    df_sales = pd.read_sql_query(
        "SELECT * FROM sell_executions ORDER BY timestamp", conn
    )
    df_sales.to_csv("sell_executions_export.csv", index=False)
    print(
        f"✅ Exportado: sell_executions_export.csv ({len(df_sales)} registros)"
    )

    conn.close()


def analyze_performance():
    """Analiza rendimiento de la estrategia"""
    conn = get_connection()

    pos = conn.execute("SELECT * FROM position WHERE id = 1").fetchone()
    if not pos:
        print("❌ No hay datos")
        return

    total, sold, cost = pos[1], pos[2], pos[3]
    cost_per_btc = cost / total

    # Ventas realizadas
    sales = conn.execute("""
        SELECT SUM(btc_sold), SUM(usd_received), AVG(price_at_sale)
        FROM sell_executions
    """).fetchone()

    btc_sold = sales[0] or 0
    usd_received = sales[1] or 0
    avg_sell_price = sales[2] or 0

    # Costo de lo vendido
    cost_of_sold = btc_sold * cost_per_btc
    realized_profit = usd_received - cost_of_sold

    print("\n" + "=" * 60)
    print("📈 ANÁLISIS DE RENDIMIENTO")
    print("=" * 60)

    print("\n💰 Ventas realizadas:")
    print(f"   BTC vendido: {btc_sold:.4f}")
    print(f"   USD recibido: ${usd_received:,.2f}")
    print(f"   Precio promedio venta: ${avg_sell_price:,.2f}")
    print(f"   Costo base vendido: ${cost_of_sold:,.2f}")
    print(f"   Ganancia realizada: ${realized_profit:+,.2f}")

    if cost_of_sold > 0:
        roi = (realized_profit / cost_of_sold) * 100
        print(f"   ROI realizado: {roi:+.1f}%")

    # Señales generadas
    signal_stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN recommendation = 'SELL' THEN 1 ELSE 0 END) as sell_signals,
            SUM(CASE WHEN executed = 1 THEN 1 ELSE 0 END) as executed,
            AVG(risk_score) as avg_risk
        FROM sell_signals
    """).fetchone()

    print("\n📊 Estadísticas de señales:")
    print(f"   Total generadas: {signal_stats[0]}")
    print(f"   Señales de venta: {signal_stats[1]}")
    print(f"   Ejecutadas: {signal_stats[2]}")
    print(f"   Risk score promedio: {signal_stats[3]:.1f}")

    conn.close()


def reset_position(total_btc: float, cost_basis: float):
    """Reinicia la posición (útil para testing)"""
    conn = get_connection()  # Esto ahora crea las tablas si no existen

    conn.execute("DELETE FROM sell_executions")
    conn.execute("DELETE FROM sell_signals")
    conn.execute("DELETE FROM position")

    conn.execute(
        """
        INSERT INTO position (id, total_btc, sold_btc, cost_basis, created_at, updated_at)
        VALUES (1, ?, 0, ?, ?, ?)
    """,
        (
            total_btc,
            cost_basis,
            datetime.now().isoformat(),
            datetime.now().isoformat(),
        ),
    )

    conn.commit()
    conn.close()

    print(f"✅ Posición reiniciada: {total_btc} BTC @ ${cost_basis:,.2f}")


# ============================================================================
# CLI
# ============================================================================


def print_help():
    print("""
DCA Sell Optimizer - Utilidades

Uso: python dca_sell_utils.py <comando> [args]

Comandos:
  position              Ver estado actual de la posición
  signals [n]           Ver últimas N señales (default: 10)
  sell <btc> <price>    Registrar venta ejecutada
  export                Exportar datos a CSV
  performance           Analizar rendimiento de la estrategia
  reset <btc> <cost>    Reiniciar posición (⚠️ borra historial)

Ejemplos:
  python dca_sell_utils.py position
  python dca_sell_utils.py signals 20
  python dca_sell_utils.py sell 0.05 95000
  python dca_sell_utils.py reset 0.5 25000
""")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_help()
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "position":
        show_position()

    elif cmd == "signals":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        show_signals(limit)

    elif cmd == "sell":
        if len(sys.argv) < 4:
            print("Uso: python dca_sell_utils.py sell <btc_amount> <price>")
            sys.exit(1)
        btc = float(sys.argv[2])
        price = float(sys.argv[3])
        exchange = sys.argv[4] if len(sys.argv) > 4 else "manual"
        record_sale(btc, price, exchange)

    elif cmd == "export":
        export_data()

    elif cmd == "performance":
        analyze_performance()

    elif cmd == "reset":
        if len(sys.argv) < 4:
            print(
                "Uso: python dca_sell_utils.py reset <total_btc> <cost_basis>"
            )
            sys.exit(1)
        confirm = input(
            "⚠️ Esto borrará todo el historial. ¿Continuar? (yes/no): "
        )
        if confirm.lower() == "yes":
            reset_position(float(sys.argv[2]), float(sys.argv[3]))
        else:
            print("Cancelado")

    else:
        print(f"Comando desconocido: {cmd}")
        print_help()
