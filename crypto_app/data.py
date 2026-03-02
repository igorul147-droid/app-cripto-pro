import time

import pandas as pd
import requests
import streamlit as st

from .utils import normalize_ohlcv


def binance_interval(tf: str) -> str:
    return {"1h": "1h", "4h": "4h", "1d": "1d"}.get(tf, "1d")


def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "")


def request_json(url: str, params: dict, attempts: int = 3, base_sleep: float = 0.8):
    headers = {
        "User-Agent": "Mozilla/5.0 (StreamlitApp)",
        "Accept": "application/json,text/plain,*/*",
    }
    last_err = None
    for i in range(attempts):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=25)
            if response.status_code in (418, 429) or 500 <= response.status_code <= 599:
                last_err = RuntimeError(f"HTTP {response.status_code}: {response.text[:250]}")
                time.sleep(base_sleep * (i + 1))
                continue
            response.raise_for_status()
            return response.json()
        except Exception as err:
            last_err = err
            time.sleep(base_sleep * (i + 1))
    raise last_err


@st.cache_data(ttl=60 * 60)
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
            payload = request_json(url, params={}, attempts=2, base_sleep=0.6)
            symbols = payload.get("symbols", [])
            pairs = []
            for symbol in symbols:
                if symbol.get("status") != "TRADING":
                    continue
                if symbol.get("isSpotTradingAllowed") is not True:
                    continue

                quote = symbol.get("quoteAsset")
                base = symbol.get("baseAsset")

                if quote != "USDT" or not base:
                    continue

                pairs.append(f"{base}/{quote}")

            unique_pairs = sorted(list(dict.fromkeys(pairs)))
            if unique_pairs:
                return unique_pairs
        except Exception as err:
            last_err = err

    st.session_state["binance_pairs_error"] = str(last_err) if last_err else "Falha desconhecida"
    return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT", "PEPE/USDT", "TURBO/USDT"]


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
                payload = request_json(url, params=params, attempts=2, base_sleep=0.5)
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
            except Exception as err:
                last_err = err

        if not got:
            raise RuntimeError(f"Falha ao paginar Binance: {last_err}")

        if len(chunks) >= 2 and chunks[-1]["timestamp"].max() >= chunks[-2]["timestamp"].min():
            break

    out = pd.concat(chunks, axis=0).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return out


@st.cache_data(ttl=120)
def fetch_bybit_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    interval_map = {"1h": "60", "4h": "240", "1d": "D"}
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "spot",
        "symbol": symbol,
        "interval": interval_map[timeframe],
        "limit": str(min(limit, 1000)),
    }
    payload = request_json(url, params=params)
    if str(payload.get("retCode")) != "0":
        raise RuntimeError(f"Bybit retCode={payload.get('retCode')} msg={payload.get('retMsg')}")
    rows = payload["result"]["list"]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)
