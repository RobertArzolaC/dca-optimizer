#!/usr/bin/env python3
"""
DCA Optimizer - Fetching y Cálculos de Mercado
Centraliza todas las llamadas a APIs externas
"""

from datetime import datetime
from typing import Optional

import pandas as pd
import requests

from .database import MarketData


class MarketDataService:
    """Servicio centralizado para obtener datos de mercado"""
    
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"
    FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
    COINMETRICS_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._price_cache: Optional[dict] = None
        self._historical_cache: Optional[pd.DataFrame] = None
    
    # ========================================================================
    # PRICE DATA
    # ========================================================================
    
    def get_current_price(self) -> dict:
        """Precio actual con cambios 24h/7d"""
        url = f"{self.COINGECKO_BASE}/coins/bitcoin"
        params = {"localization": "false", "tickers": "false", "community_data": "false"}
        
        r = requests.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()["market_data"]
        
        self._price_cache = {
            "price": data["current_price"]["usd"],
            "change_24h": data["price_change_percentage_24h"] or 0,
            "change_7d": data["price_change_percentage_7d"] or 0,
            "ath": data["ath"]["usd"],
            "ath_change": data["ath_change_percentage"]["usd"],
        }
        return self._price_cache
    
    def get_historical_prices(self, days: int = 365) -> pd.DataFrame:
        """Precios históricos con indicadores calculados"""
        url = f"{self.COINGECKO_BASE}/coins/bitcoin/market_chart"
        params = {"vs_currency": "usd", "days": days}
        
        r = requests.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        
        df = pd.DataFrame(data["prices"], columns=["ts", "price"])
        df["date"] = pd.to_datetime(df["ts"], unit="ms")
        df.set_index("date", inplace=True)
        df = df.resample("D").last()
        
        # Calcular MAs
        df["ma7"] = df["price"].rolling(7).mean()
        df["ma21"] = df["price"].rolling(21).mean()
        df["ma50"] = df["price"].rolling(50).mean()
        df["ma200"] = df["price"].rolling(200).mean()
        
        # RSI
        df["rsi"] = self.calculate_rsi(df["price"], 14)
        
        # Cambio 7d
        df["pct_7d"] = df["price"].pct_change(7) * 100
        
        self._historical_cache = df.dropna()
        return self._historical_cache
    
    # ========================================================================
    # TECHNICAL INDICATORS
    # ========================================================================
    
    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """Calcula RSI - método unificado"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def calculate_mayer_multiple(price: float, ma_200: float) -> float:
        """Mayer Multiple = Price / 200 MA"""
        return price / ma_200 if ma_200 > 0 else 1.0
    
    def check_pi_cycle(self, df: pd.DataFrame) -> bool:
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
            if (ma_111.iloc[i] >= ma_350_x2.iloc[i] and 
                ma_111.iloc[i - 1] < ma_350_x2.iloc[i - 1]):
                return True
        
        # Alertar si está muy cerca del cruce (<2%)
        current_gap = (ma_350_x2.iloc[-1] - ma_111.iloc[-1]) / ma_350_x2.iloc[-1]
        return current_gap < 0.02
    
    # ========================================================================
    # ON-CHAIN & SENTIMENT
    # ========================================================================
    
    def get_fear_greed_index(self) -> int:
        """Fear & Greed Index (0-100)"""
        try:
            r = requests.get(self.FEAR_GREED_URL, timeout=10)
            return int(r.json()["data"][0]["value"])
        except Exception:
            return 50  # Neutral si falla
    
    def get_onchain_metrics(self) -> dict:
        """Métricas on-chain de fuentes gratuitas"""
        metrics = {"mvrv_zscore": None, "nupl": None}
        
        try:
            params = {
                "assets": "btc",
                "metrics": "CapMVRVCur",
                "frequency": "1d",
                "page_size": 1,
                "sort": "time",
                "sort_ascending": "false",
            }
            r = requests.get(self.COINMETRICS_URL, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("data"):
                    mvrv = float(data["data"][0]["CapMVRVCur"])
                    metrics["mvrv_zscore"] = (mvrv - 1.5) / 0.8
        except Exception:
            pass
        
        return metrics
    
    def estimate_mvrv_from_price(self, price: float, df: pd.DataFrame) -> float:
        """Estima MVRV Z-Score basado en desviación del precio"""
        if len(df) < 200:
            return 1.0
        
        mean_price = df["price"].mean()
        std_price = df["price"].std()
        z_score = (price - mean_price) / std_price if std_price > 0 else 0
        return max(0, min(10, z_score * 1.5 + 2))
    
    def estimate_nupl(self, price: float, df: pd.DataFrame) -> float:
        """Estima NUPL basado en % de días en ganancia"""
        if len(df) < 100:
            return 0.5
        
        days_in_profit = (df["price"] < price).sum()
        total_days = len(df)
        nupl = (days_in_profit / total_days) - 0.5
        return max(-1, min(1, nupl * 1.5))
    
    # ========================================================================
    # MARKET DATA BUILDER
    # ========================================================================
    
    def get_full_market_data(self, for_sell: bool = False) -> MarketData:
        """Obtiene MarketData completo para buy o sell"""
        price_data = self.get_current_price()
        historical = self.get_historical_prices(365 if for_sell else 30)
        
        current_price = price_data["price"]
        latest = historical.iloc[-1]
        
        market_data = MarketData(
            price=round(current_price, 2),
            ma7=round(latest["ma7"], 2),
            ma21=round(latest["ma21"], 2),
            ma200=round(latest.get("ma200", latest["ma21"]), 2),
            pct_change_24h=round(price_data["change_24h"], 2),
            pct_change_7d=round(price_data["change_7d"], 2),
            rsi=round(float(latest["rsi"]), 2),
            timestamp=datetime.now().isoformat(),
        )
        
        if for_sell:
            onchain = self.get_onchain_metrics()
            market_data.mvrv_zscore = onchain.get("mvrv_zscore") or \
                self.estimate_mvrv_from_price(current_price, historical)
            market_data.nupl = self.estimate_nupl(current_price, historical)
            market_data.mayer_multiple = self.calculate_mayer_multiple(
                current_price, latest["ma200"]
            )
            market_data.fear_greed = self.get_fear_greed_index()
        
        return market_data


# Singleton instance
market_service = MarketDataService()