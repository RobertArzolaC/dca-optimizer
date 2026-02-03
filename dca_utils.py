#!/usr/bin/env python3
"""
DCA Optimizer - CLI Unificada
Comandos de gestión para buy y sell

Uso:
    python dca_utils.py buy run [--dry-run]
    python dca_utils.py buy history [n]
    python dca_utils.py sell run [--dry-run]
    python dca_utils.py sell position
    python dca_utils.py sell signals [n]
    python dca_utils.py sell record <btc> <price>
    python dca_utils.py sell reset <btc> <cost>
    python dca_utils.py dashboard
    python dca_utils.py backtest [days]
"""

import sys
from datetime import datetime

from core.database import BuyRepository, SellRepository
from core.market import market_service


# ============================================================================
# BUY COMMANDS
# ============================================================================

def buy_run(dry_run: bool = False):
    """Ejecuta el bot de compra"""
    from dca_buy import main
    return main(dry_run)


def buy_history(limit: int = 10):
    """Muestra historial de señales de compra"""
    repo = BuyRepository()
    signals = repo.get_recent_signals(limit)
    
    print(f"\n{'='*60}")
    print(f"📊 ÚLTIMAS {limit} SEÑALES DE COMPRA")
    print(f"{'='*60}")
    
    for s in signals:
        emoji = {
            "TURBO_BUY": "🚀", "EXTRA_BUY": "📈",
            "NORMAL_DCA": "✅", "SKIP": "⏸️"
        }.get(s["signal_type"], "❓")
        
        exec_str = " ✓EXEC" if s.get("executed") else ""
        print(f"\n{emoji} {s['timestamp'][:16]} | {s['signal_type']}{exec_str}")
        print(f"   Precio: ${s['price']:,.0f} | Monto: ${s['suggested_amount']:,.0f}")


# ============================================================================
# SELL COMMANDS
# ============================================================================

def sell_run(dry_run: bool = False, force: bool = False):
    """Ejecuta el bot de venta"""
    from dca_sell import main
    return main(dry_run, force)


def sell_position():
    """Muestra estado de la posición"""
    repo = SellRepository()
    pos = repo.get_or_create_position()
    
    # Precio actual
    try:
        price_data = market_service.get_current_price()
        price = price_data["price"]
    except Exception:
        price = 0
    
    current_value = pos.remaining_btc * price
    cost_of_remaining = pos.remaining_btc * pos.cost_per_btc
    pnl = current_value - cost_of_remaining
    pnl_pct = (pnl / cost_of_remaining * 100) if cost_of_remaining > 0 else 0
    
    print(f"\n{'='*60}")
    print("💼 ESTADO DE POSICIÓN")
    print(f"{'='*60}")
    print(f"\n📊 Precio BTC: ${price:,.2f}")
    print(f"\n🎯 Posición original: {pos.total_btc:.4f} BTC")
    print(f"   Costo base: ${pos.cost_basis:,.2f}")
    print(f"   Costo/BTC: ${pos.cost_per_btc:,.2f}")
    print(f"\n📈 Restante: {pos.remaining_btc:.4f} BTC ({pos.remaining_btc/pos.total_btc*100:.1f}%)")
    print(f"   Valor: ${current_value:,.2f}")
    print(f"   P&L: ${pnl:+,.2f} ({pnl_pct:+.1f}%)")
    print(f"\n💰 Vendido: {pos.sold_btc:.4f} BTC ({pos.sold_btc/pos.total_btc*100:.1f}%)")


def sell_signals(limit: int = 10):
    """Muestra señales de venta recientes"""
    repo = SellRepository()
    
    with repo.connection() as conn:
        signals = conn.execute(f"""
            SELECT timestamp, price, risk_score, signal_type, 
                   sell_percentage, pi_cycle_triggered, executed
            FROM sell_signals ORDER BY timestamp DESC LIMIT {limit}
        """).fetchall()
    
    print(f"\n{'='*60}")
    print(f"📊 ÚLTIMAS {limit} SEÑALES DE VENTA")
    print(f"{'='*60}")
    
    for s in signals:
        emoji = "🔴" if s[2] >= 70 else ("🟠" if s[2] >= 50 else ("🟡" if s[2] >= 30 else "✅"))
        pi_str = " 🚨PI" if s[5] else ""
        exec_str = " ✓EXEC" if s[6] else ""
        
        print(f"\n{emoji} {s[0][:16]} | {s[3]} | Risk: {s[2]}/100{pi_str}{exec_str}")
        print(f"   Precio: ${s[1]:,.0f} | Sugerido: {s[4]*100:.0f}%")


def sell_record(btc: float, price: float, exchange: str = "manual"):
    """Registra una venta ejecutada"""
    repo = SellRepository()
    usd = repo.record_sale(btc, price, exchange)
    print(f"✅ Venta registrada: {btc:.4f} BTC @ ${price:,.2f} = ${usd:,.2f}")


def sell_reset(total_btc: float, cost_basis: float):
    """Reinicia posición (¡borra historial!)"""
    confirm = input("⚠️ Esto borrará todo el historial. ¿Continuar? (yes/no): ")
    if confirm.lower() != "yes":
        print("Cancelado")
        return
    
    repo = SellRepository()
    repo.reset_position(total_btc, cost_basis)
    print(f"✅ Posición reiniciada: {total_btc} BTC @ ${cost_basis:,.2f}")


# ============================================================================
# DASHBOARD
# ============================================================================

def dashboard():
    """Dashboard combinado buy/sell"""
    try:
        price_data = market_service.get_current_price()
        price = price_data["price"]
        change = price_data["change_24h"]
    except Exception:
        price, change = 0, 0
    
    print(f"\n{'='*70}")
    print("🎯 DCA OPTIMIZER - DASHBOARD")
    print(f"{'='*70}")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    if price:
        emoji = "📈" if change > 0 else "📉"
        print(f"\n💰 Bitcoin: ${price:,.2f} {emoji} {change:+.1f}% (24h)")
    
    # Buy stats
    print(f"\n{'-'*70}")
    print("📥 SISTEMA DE COMPRA")
    print(f"{'-'*70}")
    
    try:
        buy_repo = BuyRepository()
        signals = buy_repo.get_recent_signals(100)
        
        counts = {"TURBO_BUY": 0, "EXTRA_BUY": 0, "NORMAL_DCA": 0, "SKIP": 0}
        total_invested = 0
        for s in signals:
            counts[s["signal_type"]] = counts.get(s["signal_type"], 0) + 1
            if s["signal_type"] != "SKIP":
                total_invested += s["suggested_amount"]
        
        print(f"   Señales totales: {len(signals)}")
        print(f"   • Turbo: {counts['TURBO_BUY']} | Extra: {counts['EXTRA_BUY']}")
        print(f"   • Normal: {counts['NORMAL_DCA']} | Skip: {counts['SKIP']}")
        print(f"   Total sugerido: ${total_invested:,.2f}")
    except Exception:
        print("   ⚠️ Sin datos de compra")
    
    # Sell stats
    print(f"\n{'-'*70}")
    print("📤 SISTEMA DE VENTA")
    print(f"{'-'*70}")
    
    try:
        sell_repo = SellRepository()
        pos = sell_repo.get_or_create_position()
        
        print(f"   Posición: {pos.total_btc:.4f} BTC (${pos.cost_basis:,.0f})")
        print(f"   • Restante: {pos.remaining_btc:.4f} ({pos.remaining_btc/pos.total_btc*100:.1f}%)")
        print(f"   • Vendido: {pos.sold_btc:.4f} ({pos.sold_btc/pos.total_btc*100:.1f}%)")
        
        if price:
            value = pos.remaining_btc * price
            pnl = value - (pos.remaining_btc * pos.cost_per_btc)
            print(f"\n   Valor actual: ${value:,.2f}")
            print(f"   P&L: ${pnl:+,.2f}")
    except Exception:
        print("   ⚠️ Sin datos de venta")
    
    print(f"\n{'-'*70}")
    print("⏰ TIMING ÓPTIMO")
    print(f"{'-'*70}")
    print("   COMPRAS:  Domingo 03:00 UTC")
    print("   VENTAS:   Lun-Vie 14:00-21:00 UTC")
    print(f"\n{'='*70}")


# ============================================================================
# MAIN CLI
# ============================================================================

def print_help():
    print(__doc__)


def main():
    if len(sys.argv) < 2:
        print_help()
        return 0
    
    cmd = sys.argv[1].lower()
    
    if cmd == "buy":
        subcmd = sys.argv[2] if len(sys.argv) > 2 else "help"
        if subcmd == "run":
            return buy_run("--dry-run" in sys.argv)
        elif subcmd == "history":
            n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
            buy_history(n)
        else:
            print("Uso: dca_utils.py buy [run|history] [args]")
    
    elif cmd == "sell":
        subcmd = sys.argv[2] if len(sys.argv) > 2 else "help"
        if subcmd == "run":
            return sell_run("--dry-run" in sys.argv, "--force" in sys.argv)
        elif subcmd == "position":
            sell_position()
        elif subcmd == "signals":
            n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
            sell_signals(n)
        elif subcmd == "record":
            if len(sys.argv) < 5:
                print("Uso: dca_utils.py sell record <btc> <price>")
                return 1
            sell_record(float(sys.argv[3]), float(sys.argv[4]))
        elif subcmd == "reset":
            if len(sys.argv) < 5:
                print("Uso: dca_utils.py sell reset <btc> <cost>")
                return 1
            sell_reset(float(sys.argv[3]), float(sys.argv[4]))
        else:
            print("Uso: dca_utils.py sell [run|position|signals|record|reset] [args]")
    
    elif cmd == "dashboard":
        dashboard()
    
    else:
        print_help()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())