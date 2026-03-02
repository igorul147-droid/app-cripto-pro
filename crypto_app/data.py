import time
import pandas as pd
import requests
import streamlit as st

from .utils import normalize_ohlcv


# ==========================================================
# UTIL
# ==========================================================

def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "").upper()


def request_json(url: str, params: dict, attempts: int = 3, base_sleep: float = 0.6):
    headers = {
        "User-Agent": "Mozilla/5.0 (StreamlitApp)",
        "Accept": "application/json,text/plain,*/*",
    }

    last_err = None

    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)

            if r.status_code in (418, 429) or 500 <= r.status_code <= 599:
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(base_sleep * (i + 1))
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            last_err = e
            time.sleep(base_sleep * (i + 1))

    raise last_err


# ==========================================================
# PARES BINANCE
# ==========================================================

@st.cache_data(ttl=3600)
def fetch_binance_usdt_spot_pairs() -> list[str]:
    endpoints = [
        "https://api.binance.com/api/v3/exchangeInfo",
        "https://api1.binance.com/api/v3/exchangeInfo",
        "https://api2.binance.com/api/v3/exchangeInfo",
        "https://api3.binance.com/api/v3/exchangeInfo",
        "https://data-api.binance.vision/api/v3/exchangeInfo",
    ]

    for url in endpoints:
        try:
            payload = request_json(url, params={}, attempts=2)
            symbols = payload.get("symbols", [])
            pairs = []

            for s in symbols:
                if s.get("status") != "TRADING":
                    continue
                if s.get("quoteAsset") != "USDT":
                    continue
                if not s.get("isSpotTradingAllowed", False):
                    continue

                base = s.get("baseAsset")
                if base:
                    pairs.append(f"{base}/USDT")

            if pairs:
                return sorted(list(dict.fromkeys(pairs)))

        except Exception:
            continue

    # fallback
    return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]


# ==========================================================
# HISTÓRICO REST (PAGINADO)
# ==========================================================

@st.cache_data(ttl=120)
def fetch_binance_ohlcv_paged(symbol: str, interval: str, total_limit: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"

    limit_step = 1000
    remaining = int(total_limit)
    end_time_ms = None
    chunks = []

    while remaining > 0:
        step = min(limit_step, remaining)

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": str(step),
        }

        if end_time_ms is not None:
            params["endTime"] = str(end_time_ms)

        payload = request_json(url, params=params, attempts=2)

        if not payload:
            break

        df = pd.DataFrame(
            payload,
            columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore",
            ],
        )

        df["timestamp"] = pd.to_datetime(
            pd.to_numeric(df["timestamp"]),
            unit="ms",
            utc=True,
        )

        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = normalize_ohlcv(df)

        if df.empty:
            break

        chunks.append(df)

        end_time_ms = int(df["timestamp"].min().value // 10**6) - 1
        remaining -= step

    if not chunks:
        return pd.DataFrame()

    out = (
        pd.concat(chunks, axis=0)
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    return out


# ==========================================================
# KLINES 1m PARA INICIAR WEBSOCKET
# ==========================================================

@st.cache_data(ttl=120)
def fetch_binance_klines(symbol: str, interval: str = "1m", limit: int = 1200) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"

    payload = request_json(
        url,
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": str(limit),
        },
        attempts=2,
    )

    df = pd.DataFrame(
        payload,
        columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore",
        ],
    )

    df["timestamp"] = pd.to_datetime(
        pd.to_numeric(df["timestamp"]),
        unit="ms",
        utc=True,
    )

    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)
