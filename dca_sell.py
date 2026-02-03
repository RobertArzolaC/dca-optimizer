import sys
from datetime import datetime

from core.enums import SignalType
from core.database import SellRepository
from core.market import market_service
from core.notifications import notifier
from core.strategies import StrategyFactory


def main(dry_run: bool = False, force_notify: bool = False) -> int:
    print(f"🔄 DCA Sell Optimizer - {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    
    # Inicializar componentes
    repo = SellRepository()
    strategy = StrategyFactory.create_sell_strategy()
    
    # Obtener posición actual
    position = repo.get_or_create_position()
    print(f"💼 Posición: {position.remaining_btc:.4f} BTC restantes")
    print(f"   (Vendidos: {position.sold_btc:.4f} BTC)")
    
    # Obtener datos de mercado
    print("\n📡 Obteniendo datos de mercado...")
    try:
        market_data = market_service.get_full_market_data(for_sell=True)
    except Exception as e:
        print(f"❌ Error obteniendo datos: {e}")
        return 1
    
    print(f"   Precio: ${market_data.price:,.2f}")
    print(f"   RSI: {market_data.rsi}")
    print(f"   MVRV: {market_data.mvrv_zscore:.2f}")
    print(f"   Mayer: {market_data.mayer_multiple:.2f}")
    print(f"   Fear/Greed: {market_data.fear_greed}")
    
    # Evaluar estrategia
    signal = strategy.evaluate(market_data, position)
    
    print(f"\n🎯 Señal: {signal.signal_type.value}")
    print(f"   Risk Score: {signal.risk_score}/100")
    if signal.pi_cycle_triggered:
        print("   🚨 PI CYCLE TOP TRIGGERED!")
    
    if signal.signal_type == SignalType.SELL:
        print(f"\n💰 Recomendación: Vender {signal.sell_percentage*100:.0f}%")
        print(f"   = {signal.sell_amount_btc:.4f} BTC")
        print(f"   ≈ ${signal.sell_amount_usd:,.2f}")
    
    print("\n📊 Indicadores:")
    for ind in signal.indicators:
        emoji = {"SAFE": "✅", "WARNING": "🟡", "DANGER": "🟠", "CRITICAL": "🔴"}
        print(f"   {emoji.get(ind.level.value, '❓')} {ind.name}: {ind.value:.2f}")
    
    # Guardar señal
    signal_id = repo.save_signal(signal)
    print(f"\n💾 Guardado (ID: {signal_id})")
    
    # Enviar notificación
    should_notify = (
        signal.signal_type in [SignalType.SELL, SignalType.ALERT] 
        or force_notify
    )
    
    if dry_run:
        print("📱 Modo dry-run: notificación no enviada")
    elif should_notify:
        if notifier.notify_sell_signal(signal, position):
            repo.mark_notified(signal_id)
            print("📱 Notificación enviada")
        else:
            print("⚠️ Error enviando notificación")
    else:
        print("📱 HOLD: sin notificación (mercado en zona segura)")
    
    print("\n✅ Completado")
    return 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    force_notify = "--force" in sys.argv
    sys.exit(main(dry_run, force_notify))