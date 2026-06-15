"""
Local technical analysis implementation for market-scanner.

Fetches OHLCV data with yfinance, computes indicators with the `ta` package,
and returns the result shape consumed by scan_market.py and the report template.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, MACD, SMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator


def _empty_series(index: pd.Index) -> pd.Series:
    return pd.Series(index=index, dtype="float64")


def _indicator(fn, index: pd.Index) -> pd.Series:
    try:
        return fn()
    except Exception:
        return _empty_series(index)


def _round_float(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def _last(series: pd.Series, digits: int = 4) -> float | None:
    values = series.dropna()
    if values.empty:
        return None
    return _round_float(values.iloc[-1], digits)


def _previous(series: pd.Series, digits: int = 4) -> float | None:
    values = series.dropna()
    if len(values) < 2:
        return None
    return _round_float(values.iloc[-2], digits)


def _relation(left: float | None, right: float | None) -> str:
    if left is None or right is None:
        return "unknown"
    return "above" if left > right else "below"


def _bool_relation(left: float | None, right: float | None) -> bool | None:
    if left is None or right is None:
        return None
    return left > right


def _trend_from_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "rising" if value else "falling"


def _is_rising(series: pd.Series, lookback: int = 5) -> bool | None:
    values = series.dropna()
    if len(values) < lookback:
        return None
    return float(values.iloc[-1]) > float(values.iloc[-lookback])


def _safe_int(value: Any) -> int | None:
    rounded = _round_float(value, 0)
    return None if rounded is None else int(rounded)


def _label_for_score(score: int) -> str:
    if score >= 6:
        return "STRONG BUY"
    if score >= 3:
        return "BUY"
    if score >= -1:
        return "HOLD"
    if score >= -4:
        return "SELL"
    return "STRONG SELL"


def _score_signals(snapshot: dict[str, Any]) -> tuple[int, str, dict[str, list[str]]]:
    score = 0
    signals = {"bullish": [], "bearish": [], "neutral": []}

    def check(condition: bool | None, bullish: str, bearish: str, neutral: str) -> None:
        nonlocal score
        if condition is None:
            signals["neutral"].append(neutral)
        elif condition:
            score += 1
            signals["bullish"].append(bullish)
        else:
            score -= 1
            signals["bearish"].append(bearish)

    price_now = snapshot.get("price_now")
    ema50 = snapshot.get("ema50")
    ema200 = snapshot.get("ema200")
    macd = snapshot.get("macd")
    macd_signal = snapshot.get("macd_signal")
    macd_hist = snapshot.get("macd_hist")
    rsi14 = snapshot.get("rsi14")
    stoch_k = snapshot.get("stoch_k")
    stoch_d = snapshot.get("stoch_d")
    bb_pct = snapshot.get("bb_pct")
    obv_rising = snapshot.get("obv_rising")
    volume_ratio = snapshot.get("volume_ratio")

    check(
        _bool_relation(price_now, ema200),
        "Price above EMA200",
        "Price below EMA200",
        "Price vs EMA200 unavailable",
    )
    check(
        _bool_relation(ema50, ema200),
        "EMA50 above EMA200",
        "EMA50 below EMA200",
        "EMA50 vs EMA200 unavailable",
    )
    check(
        _bool_relation(macd, macd_signal),
        "MACD above signal",
        "MACD below signal",
        "MACD signal unavailable",
    )
    check(
        None if macd_hist is None else macd_hist > 0,
        "MACD histogram positive",
        "MACD histogram negative",
        "MACD histogram unavailable",
    )
    check(
        None if rsi14 is None else 40 <= rsi14 <= 70,
        "RSI in healthy range",
        "RSI outside healthy range",
        "RSI unavailable",
    )
    check(
        _bool_relation(stoch_k, stoch_d),
        "Stochastic K above D",
        "Stochastic K below D",
        "Stochastic unavailable",
    )
    check(
        None if bb_pct is None else 0.2 <= bb_pct <= 0.8,
        "Bollinger position in healthy range",
        "Bollinger position outside healthy range",
        "Bollinger position unavailable",
    )
    check(
        obv_rising,
        "OBV rising",
        "OBV falling",
        "OBV trend unavailable",
    )

    if rsi14 is not None and rsi14 < 35 and price_now is not None and ema50 is not None and price_now > ema50:
        score += 1
        signals["bullish"].append("Oversold bounce setup")

    if volume_ratio is not None and volume_ratio > 1.5 and macd_hist is not None and macd_hist > 0:
        score += 1
        signals["bullish"].append("Volume surge with positive MACD")

    return score, _label_for_score(score), signals


def _fast_info_value(ticker: yf.Ticker, name: str) -> Any:
    try:
        fast_info = ticker.fast_info
        if isinstance(fast_info, dict):
            return fast_info.get(name)
        return getattr(fast_info, name, None)
    except Exception:
        return None


def _load_history(ticker: yf.Ticker, period: str, interval: str) -> pd.DataFrame:
    return ticker.history(period=period, interval=interval)


def _prepare_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLCV column(s): {', '.join(missing)}")

    prepared = df.copy()
    for column in required:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    prepared = prepared.dropna(subset=["High", "Low", "Close"])
    return prepared


def _levels(df: pd.DataFrame, price_now: float | None) -> dict[str, float | None]:
    if price_now is None or df.empty:
        return {"pivot": None, "R1": None, "S1": None}

    recent = df.tail(20)
    high = _round_float(recent["High"].max())
    low = _round_float(recent["Low"].min())
    if high is None or low is None:
        return {"pivot": None, "R1": None, "S1": None}

    pivot = round((high + low + price_now) / 3, 4)
    return {
        "pivot": pivot,
        "R1": round(2 * pivot - low, 4),
        "S1": round(2 * pivot - high, 4),
    }


def analyze(ticker: str, period: str = "6mo", interval: str = "1d") -> dict:
    """Fetch data, compute local TA indicators, score signals, and return a result dict."""
    symbol = ticker.strip().upper()
    if not symbol:
        return {"error": "Ticker is required"}

    try:
        yf_ticker = yf.Ticker(symbol)
        history = _load_history(yf_ticker, period, interval)
    except Exception as exc:
        return {"ticker": symbol, "error": f"Failed to fetch market data: {exc}"}

    if history.empty:
        return {"ticker": symbol, "error": f"No data returned for ticker '{symbol}'"}

    try:
        df = _prepare_ohlcv(history)
    except ValueError as exc:
        return {"ticker": symbol, "error": str(exc)}

    if df.empty:
        return {"ticker": symbol, "error": f"No usable OHLCV rows returned for ticker '{symbol}'"}

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"].fillna(0)
    index = df.index

    ema20 = _indicator(lambda: EMAIndicator(close=close, window=20).ema_indicator(), index)
    ema50 = _indicator(lambda: EMAIndicator(close=close, window=50).ema_indicator(), index)
    ema200 = _indicator(lambda: EMAIndicator(close=close, window=200).ema_indicator(), index)
    sma50 = _indicator(lambda: SMAIndicator(close=close, window=50).sma_indicator(), index)

    macd = _indicator(lambda: MACD(close=close).macd(), index)
    macd_signal = _indicator(lambda: MACD(close=close).macd_signal(), index)
    macd_hist = _indicator(lambda: MACD(close=close).macd_diff(), index)

    rsi = _indicator(lambda: RSIIndicator(close=close, window=14).rsi(), index)
    stoch_k = _indicator(lambda: StochasticOscillator(high=high, low=low, close=close).stoch(), index)
    stoch_d = _indicator(lambda: StochasticOscillator(high=high, low=low, close=close).stoch_signal(), index)

    bb_upper = _indicator(lambda: BollingerBands(close=close, window=20, window_dev=2).bollinger_hband(), index)
    bb_mid = _indicator(lambda: BollingerBands(close=close, window=20, window_dev=2).bollinger_mavg(), index)
    bb_lower = _indicator(lambda: BollingerBands(close=close, window=20, window_dev=2).bollinger_lband(), index)
    bb_pct = _indicator(lambda: BollingerBands(close=close, window=20, window_dev=2).bollinger_pband(), index)
    atr = _indicator(lambda: AverageTrueRange(high=high, low=low, close=close).average_true_range(), index)

    obv = _indicator(lambda: OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume(), index)

    price_now = _last(close)
    price_prev = _previous(close)
    change_pct = (
        round((price_now - price_prev) / price_prev * 100, 2)
        if price_now is not None and price_prev not in (None, 0)
        else None
    )

    avg_volume_20 = _last(volume.rolling(20).mean(), digits=0)
    last_volume = _safe_int(volume.iloc[-1])
    volume_ratio = (
        round(last_volume / avg_volume_20, 2)
        if last_volume is not None and avg_volume_20 not in (None, 0)
        else None
    )

    ema20_v = _last(ema20)
    ema50_v = _last(ema50)
    ema200_v = _last(ema200)
    macd_v = _last(macd)
    macd_signal_v = _last(macd_signal)
    macd_hist_v = _last(macd_hist)
    rsi_v = _last(rsi)
    stoch_k_v = _last(stoch_k)
    stoch_d_v = _last(stoch_d)
    bb_pct_v = _last(bb_pct)
    atr_v = _last(atr)
    obv_rising = _is_rising(obv)

    score, label, signals = _score_signals(
        {
            "price_now": price_now,
            "ema50": ema50_v,
            "ema200": ema200_v,
            "macd": macd_v,
            "macd_signal": macd_signal_v,
            "macd_hist": macd_hist_v,
            "rsi14": rsi_v,
            "stoch_k": stoch_k_v,
            "stoch_d": stoch_d_v,
            "bb_pct": bb_pct_v,
            "obv_rising": obv_rising,
            "volume_ratio": volume_ratio,
        }
    )

    return {
        "ticker": symbol,
        "name": None,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "period": period,
        "interval": interval,
        "bars": len(df),
        "market_cap": _fast_info_value(yf_ticker, "market_cap"),
        "score": score,
        "max_score": 8,
        "label": label,
        "price": {
            "current": price_now,
            "change_1d_pct": change_pct,
            "high_period": _round_float(high.max()),
            "low_period": _round_float(low.min()),
        },
        "trend": {
            "ema20": ema20_v,
            "ema50": ema50_v,
            "ema200": ema200_v,
            "sma50": _last(sma50),
            "price_vs_ema20": _relation(price_now, ema20_v),
            "price_vs_ema50": _relation(price_now, ema50_v),
            "price_vs_ema200": _relation(price_now, ema200_v),
            "ema20_vs_ema50": _relation(ema20_v, ema50_v),
            "golden_cross": _bool_relation(ema50_v, ema200_v),
            "macd": macd_v,
            "macd_signal": macd_signal_v,
            "macd_hist": macd_hist_v,
            "macd_bullish": _bool_relation(macd_v, macd_signal_v),
        },
        "momentum": {
            "rsi14": rsi_v,
            "stoch_k": stoch_k_v,
            "stoch_d": stoch_d_v,
        },
        "volatility": {
            "bb_upper": _last(bb_upper),
            "bb_mid": _last(bb_mid),
            "bb_lower": _last(bb_lower),
            "bb_pct_band": bb_pct_v,
            "atr14": atr_v,
            "atr_pct": round(atr_v / price_now * 100, 2) if atr_v is not None and price_now else None,
        },
        "volume": {
            "last": last_volume,
            "avg_20d": _safe_int(avg_volume_20),
            "ratio": volume_ratio,
            "obv": _last(obv),
            "obv_trend": _trend_from_bool(obv_rising),
        },
        "levels": _levels(df, price_now),
        "signals": signals,
    }
