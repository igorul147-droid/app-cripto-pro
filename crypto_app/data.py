import pandas as pd
import requests
import streamlit as st

from .utils import normalize_ohlcv


def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "").upper()


@st.cache_data(ttl=120, show_spinner=False)
def fetch_pairs():
    return [
        "BTC/USDT","ETH/USDT","SOL/USDT","XRP/USDT","BNB/USDT",
        "DOGE/USDT","ADA/USDT","AVAX/USDT","LINK/USDT","PEPE/USDT"
    ]


@st.cache_data(ttl=120, show_spinner=False)
def fetch_bybit_klines(symbol: str, interval="1", limit=800):
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "spot",
        "symbol": symbol,
        "interval": interval,
        "limit": str(limit),
    }

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    rows = data["result"]["list"]
    df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume","turnover"])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = df[["timestamp","open","high","low","close","volume"]]
    return normalize_ohlcv(df)
