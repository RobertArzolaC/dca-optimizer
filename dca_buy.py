#!/usr/bin/env python3
"""
DCA Buy Optimizer - Script Principal
Ejecutar via cronjob: 0 3 * * 0 (Domingo 03:00 UTC)

Ejemplo de uso:
    python dca_buy.py           # Ejecución normal
    python dca_buy.py --dry-run # Sin enviar notificación
"""

import sys
from datetime import datetime

from core.config import config, SignalType
from core.database import BuyRepository
from core.market import market_service
from core.notifications import notifier
from core.strategies import StrategyFactory


def main(dry_run: bool = False) -> int:
    print(f"🔄 DCA Buy Optimizer - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    
    # Inicializar componentes
    repo = BuyRepository()
    strategy = StrategyFactory.create_buy_strategy()
    
    # Obtener datos de mercado
    print("📡 Obteniendo datos de mercado...")
    try:
        market_data = market_service.get_full_market_data(for_sell=False)
    except Exception as e:
        print(f"❌ Error obteniendo datos: {e}")
        return 1
    
    print(f"   Precio: ${market_data.price:,.2f}")
    print(f"   RSI: {market_data.rsi}")
    print(f"   7d: {market_data.pct_change_7d:+.1f}%")
    
    # Guardar snapshot de precio
    repo.save_price_snapshot(market_data)
    
    # Evaluar estrategia
    signal = strategy.evaluate(market_data)
    
    print(f"\n🎯 Señal: {signal.signal_type.value}")
    print(f"   Multiplicador: x{signal.multiplier}")
    print(f"   Monto: ${signal.suggested_amount:,.2f}")
    for reason in signal.reasons:
        print(f"   • {reason}")
    
    # Guardar señal
    signal_id = repo.save_signal(signal)
    print(f"\n💾 Guardado (ID: {signal_id})")
    
    # Enviar notificación
    if dry_run:
        print("📱 Modo dry-run: notificación no enviada")
    elif signal.signal_type != SignalType.SKIP:
        if notifier.notify_buy_signal(signal):
            repo.mark_notified(signal_id)
            print("📱 Notificación enviada")
        else:
            print("⚠️ Error enviando notificación")
    else:
        print("📱 SKIP: sin notificación (mercado sobrecomprado)")
    
    print("\n✅ Completado")
    return 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    sys.exit(main(dry_run))