#!/usr/bin/env python3
"""
DCA Dashboard - Vista combinada de estrategias Buy & Sell
Muestra estado de ambos sistemas en una sola vista
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import requests

# Rutas de bases de datos
BUY_DB = Path.home() / "dca-optimizer" / "dca_history.db"
SELL_DB = Path.home() / "dca-optimizer" / "dca_sell_history.db"


def get_btc_price():
    """Obtiene precio actual de Bitcoin"""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "bitcoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
        data = r.json()["bitcoin"]
        return data["usd"], data.get("usd_24h_change", 0)
    except:
        return None, None


def get_buy_stats():
    """Obtiene estadísticas del sistema de compra"""
    if not BUY_DB.exists():
        return None

    conn = sqlite3.connect(BUY_DB)

    stats = {
        "total_signals": 0,
        "turbo_buys": 0,
        "extra_buys": 0,
        "normal_dcas": 0,
        "skips": 0,
        "last_signal": None,
        "total_invested": 0,
    }

    try:
        # Contar señales por tipo
        counts = conn.execute("""
            SELECT signal_type, COUNT(*), SUM(suggested_amount)
            FROM signals GROUP BY signal_type
        """).fetchall()

        for stype, count, amount in counts:
            stats["total_signals"] += count
            if stype == "TURBO_BUY":
                stats["turbo_buys"] = count
                stats["total_invested"] += amount or 0
            elif stype == "EXTRA_BUY":
                stats["extra_buys"] = count
                stats["total_invested"] += amount or 0
            elif stype == "NORMAL_DCA":
                stats["normal_dcas"] = count
                stats["total_invested"] += amount or 0
            elif stype == "SKIP":
                stats["skips"] = count

        # Última señal
        last = conn.execute("""
            SELECT timestamp, signal_type, price, suggested_amount
            FROM signals ORDER BY timestamp DESC LIMIT 1
        """).fetchone()

        if last:
            stats["last_signal"] = {
                "timestamp": last[0],
                "type": last[1],
                "price": last[2],
                "amount": last[3],
            }
    except:
        pass

    conn.close()
    return stats


def get_sell_stats():
    """Obtiene estadísticas del sistema de venta"""
    if not SELL_DB.exists():
        return None

    conn = sqlite3.connect(SELL_DB)

    stats = {
        "position": None,
        "total_signals": 0,
        "sell_signals": 0,
        "executed_sales": 0,
        "last_signal": None,
        "total_sold_usd": 0,
        "avg_risk_score": 0,
    }

    try:
        # Posición
        pos = conn.execute("SELECT * FROM position WHERE id = 1").fetchone()
        if pos:
            stats["position"] = {
                "total_btc": pos[1],
                "sold_btc": pos[2],
                "remaining_btc": pos[1] - pos[2],
                "cost_basis": pos[3],
            }

        # Señales
        signal_data = conn.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN recommendation = 'SELL' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN executed = 1 THEN 1 ELSE 0 END),
                   AVG(risk_score)
            FROM sell_signals
        """).fetchone()

        if signal_data:
            stats["total_signals"] = signal_data[0] or 0
            stats["sell_signals"] = signal_data[1] or 0
            stats["executed_sales"] = signal_data[2] or 0
            stats["avg_risk_score"] = signal_data[3] or 0

        # Ventas realizadas
        sales = conn.execute(
            "SELECT SUM(usd_received) FROM sell_executions"
        ).fetchone()
        stats["total_sold_usd"] = sales[0] or 0

        # Última señal
        last = conn.execute("""
            SELECT timestamp, price, risk_score, recommendation
            FROM sell_signals ORDER BY timestamp DESC LIMIT 1
        """).fetchone()

        if last:
            stats["last_signal"] = {
                "timestamp": last[0],
                "price": last[1],
                "risk_score": last[2],
                "recommendation": last[3],
            }
    except:
        pass

    conn.close()
    return stats


def print_dashboard():
    """Imprime dashboard combinado"""
    price, change_24h = get_btc_price()
    buy_stats = get_buy_stats()
    sell_stats = get_sell_stats()

    print("\n" + "=" * 70)
    print("🎯 DCA OPTIMIZER - DASHBOARD COMBINADO")
    print("=" * 70)
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Precio actual
    if price:
        change_emoji = "📈" if change_24h and change_24h > 0 else "📉"
        print(
            f"\n💰 Bitcoin: ${price:,.2f} {change_emoji} {change_24h:+.1f}% (24h)"
        )

    # Sistema de Compra
    print("\n" + "-" * 70)
    print("📥 SISTEMA DE COMPRA (DCA-IN)")
    print("-" * 70)

    if buy_stats:
        print(f"   Señales totales: {buy_stats['total_signals']}")
        print(
            f"   • Turbo Buy: {buy_stats['turbo_buys']} | Extra Buy: {buy_stats['extra_buys']}"
        )
        print(
            f"   • Normal DCA: {buy_stats['normal_dcas']} | Skip: {buy_stats['skips']}"
        )
        print(f"   Total invertido: ${buy_stats['total_invested']:,.2f}")

        if buy_stats["last_signal"]:
            ls = buy_stats["last_signal"]
            print(f"\n   Última señal: {ls['type']} @ ${ls['price']:,.0f}")
            print(f"   Fecha: {ls['timestamp'][:16]}")
    else:
        print("   ⚠️ Base de datos no encontrada")
        print(f"   Esperada en: {BUY_DB}")

    # Sistema de Venta
    print("\n" + "-" * 70)
    print("📤 SISTEMA DE VENTA (DCA-OUT)")
    print("-" * 70)

    if sell_stats:
        pos = sell_stats["position"]
        if pos:
            remaining_pct = (pos["remaining_btc"] / pos["total_btc"]) * 100
            sold_pct = 100 - remaining_pct

            print(
                f"   Posición original: {pos['total_btc']:.4f} BTC (${pos['cost_basis']:,.0f})"
            )
            print(
                f"   • Restante: {pos['remaining_btc']:.4f} BTC ({remaining_pct:.1f}%)"
            )
            print(f"   • Vendido: {pos['sold_btc']:.4f} BTC ({sold_pct:.1f}%)")

            if price:
                current_value = pos["remaining_btc"] * price
                cost_per_btc = pos["cost_basis"] / pos["total_btc"]
                unrealized_pnl = current_value - (
                    pos["remaining_btc"] * cost_per_btc
                )
                pnl_pct = (
                    unrealized_pnl / (pos["remaining_btc"] * cost_per_btc)
                ) * 100

                print(f"\n   Valor actual: ${current_value:,.2f}")
                print(
                    f"   P&L no realizado: ${unrealized_pnl:+,.2f} ({pnl_pct:+.1f}%)"
                )

        print(f"\n   Señales generadas: {sell_stats['total_signals']}")
        print(f"   • Alertas de venta: {sell_stats['sell_signals']}")
        print(f"   • Ventas ejecutadas: {sell_stats['executed_sales']}")
        print(f"   Risk score promedio: {sell_stats['avg_risk_score']:.0f}/100")

        if sell_stats["total_sold_usd"] > 0:
            print(f"   Total vendido: ${sell_stats['total_sold_usd']:,.2f}")

        if sell_stats["last_signal"]:
            ls = sell_stats["last_signal"]
            risk_bar = "🔴" * (ls["risk_score"] // 20) + "⚪" * (
                5 - ls["risk_score"] // 20
            )
            print(
                f"\n   Última señal: {ls['recommendation']} (Risk: {ls['risk_score']})"
            )
            print(f"   {risk_bar}")
            print(f"   Fecha: {ls['timestamp'][:16]}")
    else:
        print("   ⚠️ Base de datos no encontrada")
        print(f"   Esperada en: {SELL_DB}")

    # Resumen de timing
    print("\n" + "-" * 70)
    print("⏰ TIMING ÓPTIMO")
    print("-" * 70)
    print("   COMPRAS:  Domingo 03:00 UTC (Early Asian session)")
    print("   VENTAS:   Lun-Mar 14:00-21:00 UTC (Horario institucional)")

    # Próximos pasos sugeridos
    #print("\n" + "-" * 70)
    #print("📋 COMANDOS RÁPIDOS")
    #print("-" * 70)
    #print("   # Ver señales de compra")
    #print("   python3 ~/dca-optimizer/dca_backtest.py export")
    #print("")
    #print("   # Ver posición de venta")
    #print("   python3 ~/dca-sell-optimizer/dca_sell_utils.py position")
    #print("")
    #print("   # Registrar venta manual")
    #print(
    #    "   python3 ~/dca-sell-optimizer/dca_sell_utils.py sell <btc> <price>"
    #)

    print("\n" + "=" * 70)


if __name__ == "__main__":
    print_dashboard()
