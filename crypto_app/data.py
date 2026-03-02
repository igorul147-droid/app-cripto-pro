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
    last_status = None
    last_text = None

    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            last_status = r.status_code
            last_text = r.text[:220]

            if r.status_code in (418, 429) or 500 <= r.status_code <= 599:
                last_err = RuntimeError(f"HTTP {r.status_code}: {last_text}")
                time.sleep(base_sleep * (i + 1))
                continue

            r.raise_for_status()
            return r.json()

        except Exception as e:
            last_err = e
            time.sleep(base_sleep * (i + 1))

    st.session_state["last_http_error"] = {
        "url": url,
        "params": params,
        "status": last_status,
        "text": last_text,
        "err": str(last_err)[:300],
    }
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
def fetch_binance_klines(symbol: str, interval: str = "1m", limit: int = 800) -> pd.DataFrame:
    url_candidates = [
        "https://api.binance.com/api/v3/klines",
        "https://api1.binance.com/api/v3/klines",
        "https://api2.binance.com/api/v3/klines",
        "https://api3.binance.com/api/v3/klines",
        "https://data-api.binance.vision/api/v3/klines",
    ]

    params = {"symbol": symbol, "interval": interval, "limit": str(int(limit))}
    last_err = None

    for url in url_candidates:
        try:
            payload = request_json(url, params=params, attempts=2, base_sleep=0.35)

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
                raise RuntimeError("klines vazio")

            return df

        except Exception as e:
            last_err = e

    raise RuntimeError(f"Falha ao obter klines ({symbol}) em todos endpoints: {last_err}")
