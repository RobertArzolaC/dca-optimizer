#!/usr/bin/env python3
"""
DCA Optimizer - Sistema de Notificaciones
Mensajes claros, sin ambigüedad, con CTA explícito
"""

from abc import ABC, abstractmethod
from datetime import datetime, UTC

import requests

from .config import config, SignalType
from .database import BuySignal, SellSignal, Position


class NotificationService(ABC):
    """Interface para servicios de notificación"""
    
    @abstractmethod
    def send(self, message: str) -> bool:
        pass


class TelegramNotifier(NotificationService):
    """Implementación de notificaciones via Telegram"""
    
    def __init__(self):
        self.token = config.telegram.token
        self.chat_id = config.telegram.chat_id
    
    @property
    def is_configured(self) -> bool:
        return config.telegram.is_configured
    
    def send(self, message: str) -> bool:
        if not self.is_configured:
            print("⚠️ Telegram no configurado")
            return False
        
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
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


# ============================================================================
# MESSAGE FORMATTERS - MENSAJES CLAROS Y SIN AMBIGÜEDAD
# ============================================================================

class BuyMessageFormatter:
    """Formatea mensajes de COMPRA con CTA claro"""
    
    ACTION_MAP = {
        SignalType.TURBO_BUY: ("🚀 COMPRAR AHORA", "Oportunidad excepcional detectada"),
        SignalType.EXTRA_BUY: ("📈 COMPRAR", "Condiciones favorables"),
        SignalType.NORMAL_DCA: ("✅ DCA SEMANAL", "Ejecutar compra programada"),
        SignalType.SKIP: ("⏸️ NO COMPRAR", "Mercado sobrecomprado"),
    }
    
    @classmethod
    def format(cls, signal: BuySignal) -> str:
        action, description = cls.ACTION_MAP.get(
            signal.signal_type, 
            ("❓ REVISAR", "Señal desconocida")
        )
        
        data = signal.market_data
        now = datetime.now(UTC)
        
        # Timing óptimo
        timing_note = ""
        if now.weekday() == 6 and 2 <= now.hour <= 5:
            timing_note = "\n⏰ *Ventana óptima activa* (Early Asian session)"
        
        # Determinar si requiere acción inmediata
        is_actionable = signal.signal_type not in [SignalType.SKIP]
        
        if is_actionable:
            header = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━
{action}
━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 *Monto a invertir:* `${signal.suggested_amount:,.2f}`
📊 Precio BTC: `${data.price:,.2f}`
"""
        else:
            header = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━
{action}
━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ *No invertir esta semana*
📊 Precio BTC: `${data.price:,.2f}`
"""
        
        # Razones claras
        reasons_text = "\n".join([f"• {r}" for r in signal.reasons])
        
        return f"""
{header}
📈 *Indicadores:*
• RSI: `{data.rsi}` {'⚠️ Alto' if data.rsi > 65 else '✅ OK' if data.rsi > 35 else '🔥 Bajo'}
• vs MA7: `{((data.price/data.ma7)-1)*100:+.1f}%`
• 7 días: `{data.pct_change_7d:+.1f}%`

📝 *Razón:*
{reasons_text}
{timing_note}

_Multiplicador: x{signal.multiplier} | {description}_
""".strip()


class SellMessageFormatter:
    """Formatea mensajes de VENTA con CTA claro"""
    
    @classmethod
    def format(cls, signal: SellSignal, position: Position) -> str:
        data = signal.market_data
        
        # Calcular P&L
        current_value = position.remaining_btc * data.price
        cost_of_remaining = position.remaining_btc * position.cost_per_btc
        unrealized_pnl = current_value - cost_of_remaining
        pnl_pct = (unrealized_pnl / cost_of_remaining * 100) if cost_of_remaining > 0 else 0
        
        # Header según tipo de señal
        if signal.signal_type == SignalType.SELL:
            header = cls._format_sell_header(signal)
        elif signal.signal_type == SignalType.ALERT:
            header = cls._format_alert_header(signal)
        else:
            header = cls._format_hold_header(signal)
        
        # Risk bar visual
        risk_bar = "🔴" * (signal.risk_score // 20) + "⚪" * (5 - signal.risk_score // 20)
        
        # Indicadores críticos
        indicators_text = cls._format_indicators(signal.indicators)
        
        # Razones
        reasons_text = "\n".join(signal.reasons[:5])
        
        return f"""
{header}

📊 *Mercado:*
• Precio: `${data.price:,.2f}`
• 24h: `{data.pct_change_24h:+.1f}%` | 7d: `{data.pct_change_7d:+.1f}%`
• Risk Score: `{signal.risk_score}/100` {risk_bar}

{indicators_text}

💼 *Tu posición:*
• BTC restante: `{position.remaining_btc:.4f}` ({position.remaining_btc/position.total_btc*100:.0f}%)
• Valor actual: `${current_value:,.2f}`
• P&L: `${unrealized_pnl:+,.2f}` (`{pnl_pct:+.1f}%`)

📝 *Análisis:*
{reasons_text}

_Mejor horario para vender: Lun-Vie 14:00-21:00 UTC_
""".strip()
    
    @classmethod
    def _format_sell_header(cls, signal: SellSignal) -> str:
        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 VENDER {signal.sell_percentage*100:.0f}% DE TU POSICIÓN
━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ *ACCIÓN REQUERIDA*
💰 Vender: `{signal.sell_amount_btc:.4f} BTC`
💵 Valor aprox: `${signal.sell_amount_usd:,.2f}`
"""
    
    @classmethod
    def _format_alert_header(cls, signal: SellSignal) -> str:
        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ ALERTA: MERCADO EN ZONA DE PRECAUCIÓN
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 *ACCIÓN:* Monitorear de cerca
🎯 Preparar venta de `{signal.sell_percentage*100:.0f}%` si empeora
"""
    
    @classmethod
    def _format_hold_header(cls, signal: SellSignal) -> str:
        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ MANTENER POSICIÓN
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 *ACCIÓN:* No se requiere venta
🎯 Indicadores en zona segura
"""
    
    @classmethod
    def _format_indicators(cls, indicators: list) -> str:
        lines = ["📈 *Indicadores:*"]
        for ind in indicators:
            emoji = {"SAFE": "✅", "WARNING": "🟡", "DANGER": "🟠", "CRITICAL": "🔴"}
            level_emoji = emoji.get(ind.level.value, "❓")
            lines.append(f"• {level_emoji} {ind.name}: `{ind.value:.2f}`")
        return "\n".join(lines)


# ============================================================================
# NOTIFIER FACADE
# ============================================================================

class DCANotifier:
    """Facade para enviar notificaciones DCA"""
    
    def __init__(self):
        self.telegram = TelegramNotifier()
    
    def notify_buy_signal(self, signal: BuySignal) -> bool:
        """Envía notificación de señal de compra"""
        message = BuyMessageFormatter.format(signal)
        return self.telegram.send(message)
    
    def notify_sell_signal(self, signal: SellSignal, position: Position) -> bool:
        """Envía notificación de señal de venta"""
        message = SellMessageFormatter.format(signal, position)
        return self.telegram.send(message)
    
    def notify_custom(self, message: str) -> bool:
        """Envía mensaje personalizado"""
        return self.telegram.send(message)


# Singleton
notifier = DCANotifier()