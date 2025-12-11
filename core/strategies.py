#!/usr/bin/env python3
"""
DCA Optimizer - Estrategias de Trading
Strategy Pattern para buy/sell decisions
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from .config import config, SignalType, RiskLevel
from .database import MarketData, BuySignal, SellSignal, Indicator, Position
from .market import market_service


# ============================================================================
# STRATEGY PROTOCOL
# ============================================================================

class TradingStrategy(Protocol):
    """Protocol para estrategias de trading"""
    
    def evaluate(self, market_data: MarketData) -> BuySignal | SellSignal:
        ...


# ============================================================================
# BUY STRATEGY
# ============================================================================

class DCABuyStrategy:
    """
    Estrategia de compra DCA optimizada
    
    Lógica:
    - SKIP si RSI > overbought (mercado caliente)
    - TURBO_BUY si precio < 97% MA7 O caída semanal > 3%
    - EXTRA_BUY si RSI < oversold
    - NORMAL_DCA en otros casos
    """
    
    def __init__(self):
        self.config = config.buy
    
    def evaluate(self, market_data: MarketData) -> BuySignal:
        reasons = []
        
        # Check SKIP primero
        if market_data.rsi > self.config.rsi_overbought:
            return self._create_signal(
                SignalType.SKIP,
                [f"RSI sobrecomprado ({market_data.rsi:.0f} > {self.config.rsi_overbought})"],
                market_data
            )
        
        # Check TURBO_BUY conditions
        turbo_reasons = []
        
        ma7_threshold = market_data.ma7 * self.config.ma_dip_threshold
        if market_data.price < ma7_threshold:
            turbo_reasons.append(
                f"Precio ${market_data.price:,.0f} < 97% MA7 (${ma7_threshold:,.0f})"
            )
        
        if market_data.pct_change_7d <= self.config.weekly_drop_threshold:
            turbo_reasons.append(
                f"Caída semanal fuerte: {market_data.pct_change_7d:.1f}%"
            )
        
        if turbo_reasons:
            return self._create_signal(
                SignalType.TURBO_BUY,
                turbo_reasons,
                market_data
            )
        
        # Check EXTRA_BUY
        if market_data.rsi < self.config.rsi_oversold:
            return self._create_signal(
                SignalType.EXTRA_BUY,
                [f"RSI en sobreventa ({market_data.rsi:.0f} < {self.config.rsi_oversold})"],
                market_data
            )
        
        # Default: NORMAL_DCA
        return self._create_signal(
            SignalType.NORMAL_DCA,
            ["Condiciones normales de mercado"],
            market_data
        )
    
    def _create_signal(
        self, 
        signal_type: SignalType, 
        reasons: list[str], 
        market_data: MarketData
    ) -> BuySignal:
        multiplier = self.config.multipliers.get(signal_type, 1.0)
        return BuySignal(
            signal_type=signal_type,
            multiplier=multiplier,
            suggested_amount=self.config.base_amount_usd * multiplier,
            reasons=reasons,
            market_data=market_data,
        )


# ============================================================================
# SELL STRATEGY
# ============================================================================

class DCASellStrategy:
    """
    Estrategia de venta DCA optimizada
    
    Evalúa múltiples indicadores on-chain y técnicos
    para detectar tops de mercado
    """
    
    def __init__(self):
        self.config = config.sell
        self._historical_df: pd.DataFrame = None
    
    def evaluate(self, market_data: MarketData, position: Position) -> SellSignal:
        # Obtener datos históricos para Pi Cycle
        self._historical_df = market_service.get_historical_prices(365)
        
        # Evaluar indicadores
        indicators = self._evaluate_indicators(market_data)
        
        # Contar señales por nivel
        counts = self._count_signals(indicators)
        
        # Verificar Pi Cycle
        pi_cycle = market_service.check_pi_cycle(self._historical_df)
        
        # Calcular risk score
        risk_score = self._calculate_risk_score(counts, pi_cycle)
        
        # Generar recomendación
        return self._generate_recommendation(
            indicators, counts, pi_cycle, risk_score, market_data, position
        )
    
    def _evaluate_indicators(self, data: MarketData) -> list[Indicator]:
        """Evalúa todos los indicadores y retorna lista"""
        indicators = []
        
        # MVRV Z-Score
        if data.mvrv_zscore is not None:
            indicators.append(self._create_indicator(
                "MVRV Z-Score", data.mvrv_zscore,
                self.config.mvrv_warning, self.config.mvrv_danger, self.config.mvrv_critical
            ))
        
        # NUPL
        if data.nupl is not None:
            indicators.append(self._create_indicator(
                "NUPL", data.nupl,
                self.config.nupl_warning, self.config.nupl_danger, self.config.nupl_critical
            ))
        
        # RSI
        indicators.append(self._create_indicator(
            "RSI (Daily)", data.rsi,
            self.config.rsi_warning, self.config.rsi_danger, self.config.rsi_critical
        ))
        
        # Mayer Multiple
        if data.mayer_multiple is not None:
            indicators.append(self._create_indicator(
                "Mayer Multiple", data.mayer_multiple,
                self.config.mayer_warning, self.config.mayer_danger, self.config.mayer_critical
            ))
        
        # Fear & Greed (invertido)
        if data.fear_greed is not None:
            indicators.append(self._create_indicator(
                "Fear & Greed", data.fear_greed,
                65, 75, 85
            ))
        
        return indicators
    
    def _create_indicator(
        self, name: str, value: float,
        warn: float, danger: float, critical: float
    ) -> Indicator:
        """Crea indicador con nivel calculado"""
        if value >= critical:
            level = RiskLevel.CRITICAL
        elif value >= danger:
            level = RiskLevel.DANGER
        elif value >= warn:
            level = RiskLevel.WARNING
        else:
            level = RiskLevel.SAFE
        
        return Indicator(
            name=name, value=value, level=level,
            threshold_warning=warn, threshold_danger=danger, threshold_critical=critical
        )
    
    def _count_signals(self, indicators: list[Indicator]) -> dict:
        """Cuenta señales por nivel"""
        return {
            "warning": sum(1 for i in indicators if i.level == RiskLevel.WARNING),
            "danger": sum(1 for i in indicators if i.level == RiskLevel.DANGER),
            "critical": sum(1 for i in indicators if i.level == RiskLevel.CRITICAL),
        }
    
    def _calculate_risk_score(self, counts: dict, pi_cycle: bool) -> int:
        """Calcula risk score 0-100"""
        score = 0
        score += counts["warning"] * 10
        score += counts["danger"] * 25
        score += counts["critical"] * 40
        if pi_cycle:
            score += 30
        return min(score, 100)
    
    def _generate_recommendation(
        self, 
        indicators: list[Indicator],
        counts: dict,
        pi_cycle: bool,
        risk_score: int,
        market_data: MarketData,
        position: Position
    ) -> SellSignal:
        """Genera recomendación de venta"""
        reasons = []
        sell_pct = 0.0
        
        # Pi Cycle es la señal más fuerte
        if pi_cycle:
            sell_pct = max(sell_pct, self.config.sell_tiers["pi_cycle"])
            reasons.append("🚨 PI CYCLE TOP - Señal histórica de techo de mercado")
        
        # Indicadores críticos
        for ind in indicators:
            if ind.level == RiskLevel.CRITICAL:
                sell_pct = max(sell_pct, self.config.sell_tiers[3])
                reasons.append(
                    f"🔴 {ind.name}: {ind.value:.2f} CRÍTICO (>{ind.threshold_critical})"
                )
            elif ind.level == RiskLevel.DANGER:
                sell_pct = max(sell_pct, self.config.sell_tiers.get(2, 0.15))
                reasons.append(
                    f"🟠 {ind.name}: {ind.value:.2f} en PELIGRO (>{ind.threshold_danger})"
                )
            elif ind.level == RiskLevel.WARNING and sell_pct == 0:
                sell_pct = self.config.sell_tiers.get(1, 0.10)
                reasons.append(
                    f"🟡 {ind.name}: {ind.value:.2f} en WARNING (>{ind.threshold_warning})"
                )
        
        # Calcular montos
        sell_btc = position.remaining_btc * sell_pct
        sell_usd = sell_btc * market_data.price
        
        # Determinar tipo de señal
        total_signals = counts["warning"] + counts["danger"] + counts["critical"]
        
        if total_signals >= self.config.min_signals_to_sell or pi_cycle:
            signal_type = SignalType.SELL
        elif total_signals >= self.config.min_signals_to_alert:
            signal_type = SignalType.ALERT
        else:
            signal_type = SignalType.HOLD
            reasons = ["✅ Todos los indicadores en zona segura"]
        
        return SellSignal(
            signal_type=signal_type,
            risk_score=risk_score,
            sell_percentage=sell_pct,
            sell_amount_btc=sell_btc,
            sell_amount_usd=sell_usd,
            reasons=reasons,
            indicators=indicators,
            market_data=market_data,
            pi_cycle_triggered=pi_cycle,
        )


# ============================================================================
# FACTORY
# ============================================================================

class StrategyFactory:
    """Factory para crear estrategias"""
    
    @staticmethod
    def create_buy_strategy() -> DCABuyStrategy:
        return DCABuyStrategy()
    
    @staticmethod
    def create_sell_strategy() -> DCASellStrategy:
        return DCASellStrategy()