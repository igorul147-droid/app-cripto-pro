import time
import pandas as pd
import requests
import streamlit as st

from .utils import normalize_ohlcv


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


@st.cache_data(ttl=3600)
def fetch_binance_usdt_spot_pairs() -> list[str]:
    endpoints = [
        "https://api.binance.com/api/v3/exchangeInfo",
        "https://api1.binance.com/api/v3/exchangeInfo",
        "https://api2.binance.com/api/v3/exchangeInfo",
        "https://api3.binance.com/api/v3/exchangeInfo",
        "https://data-api.binance.vision/api/v3/exchangeInfo",
    ]

    last_err = None
    for url in endpoints:
        try:
            payload = request_json(url, params={}, attempts=2, base_sleep=0.4)
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

            unique_pairs = sorted(list(dict.fromkeys(pairs)))
            if unique_pairs:
                return unique_pairs

        except Exception as e:
            last_err = e

    st.session_state["binance_pairs_error"] = str(last_err) if last_err else "Falha desconhecida"
    return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT"]


@st.cache_data(ttl=120)
def fetch_binance_ohlcv_paged(symbol: str, interval: str, total_limit: int) -> pd.DataFrame:
    url_candidates = [
        "https://api.binance.com/api/v3/klines",
        "https://api1.binance.com/api/v3/klines",
        "https://api2.binance.com/api/v3/klines",
        "https://api3.binance.com/api/v3/klines",
        "https://data-api.binance.vision/api/v3/klines",
    ]

    limit_step = 1000
    remaining = int(total_limit)
    end_time_ms = None
    chunks: list[pd.DataFrame] = []
    last_err = None

    while remaining > 0:
        step = min(limit_step, remaining)
        params = {"symbol": symbol, "interval": interval, "limit": str(step)}
        if end_time_ms is not None:
            params["endTime"] = str(end_time_ms)

        got = False
        for url in url_candidates:
            try:
                payload = request_json(url, params=params, attempts=2, base_sleep=0.3)
                if not payload:
                    raise RuntimeError("Binance klines vazio")

                df = pd.DataFrame(
                    payload,
                    columns=[
                        "timestamp", "open", "high", "low", "close", "volume",
                        "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore",
                    ],
                )
                df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
                df = df[["timestamp", "open", "high", "low", "close", "volume"]]
                df = normalize_ohlcv(df)
                if df.empty:
                    raise RuntimeError("Binance klines normalizado vazio")

                chunks.append(df)
                end_time_ms = int(df["timestamp"].min().value // 10**6) - 1
                remaining -= step
                got = True
                break

            except Exception as e:
                last_err = e

        if not got:
            raise RuntimeError(f"Falha ao paginar Binance: {last_err}")

        if len(chunks) >= 2 and chunks[-1]["timestamp"].max() >= chunks[-2]["timestamp"].min():
            break

    out = pd.concat(chunks, axis=0).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return out


@st.cache_data(ttl=120)
def fetch_binance_klines(symbol: str, interval: str = "1m", limit: int = 1200) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    payload = request_json(
        url,
        params={"symbol": symbol, "interval": interval, "limit": str(limit)},
        attempts=2,
        base_sleep=0.3,
    )

    df = pd.DataFrame(
        payload,
        columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore",
        ],
    )
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)
