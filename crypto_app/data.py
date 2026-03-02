import time
import pandas as pd
import requests
import streamlit as st

from .utils import normalize_ohlcv


def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "").upper()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_pairs():
    # lista fixa pra não depender de exchangeInfo
    return [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "PEPE/USDT",
    ]


def _session():
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
    )
    return s


def _get_json(url: str, params: dict, timeout: int = 12, attempts: int = 2):
    s = _session()
    last = None
    for i in range(attempts):
        try:
            r = s.get(url, params=params, timeout=timeout)
            # guarda debug
            st.session_state["last_http_debug"] = {
                "url": url,
                "status": r.status_code,
                "text": r.text[:220],
            }
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(0.35 * (i + 1))
    raise last


@st.cache_data(ttl=120, show_spinner=False)
def fetch_bybit_klines(symbol: str, interval: str = "1", limit: int = 800) -> pd.DataFrame:
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": str(min(int(limit), 1000))}
    data = _get_json(url, params=params, timeout=12, attempts=2)

    if str(data.get("retCode")) != "0":
        raise RuntimeError(f"Bybit retCode={data.get('retCode')} msg={data.get('retMsg')}")

    rows = data["result"]["list"]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_okx_klines(symbol: str, limit: int = 800) -> pd.DataFrame:
    # OKX usa instId com hífen: BTC-USDT
    base = symbol.replace("USDT", "")
    inst = f"{base}-USDT"
    url = "https://www.okx.com/api/v5/market/candles"
    params = {"instId": inst, "bar": "1m", "limit": str(min(int(limit), 1000))}
    data = _get_json(url, params=params, timeout=12, attempts=2)

    # data["data"] = [[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm], ...]
    rows = data.get("data", [])
    if not rows:
        raise RuntimeError("OKX candles vazio")

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "volCcy", "volQuote", "confirm"])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_history_1m(symbol: str, limit: int = 800) -> pd.DataFrame:
    # tenta Bybit primeiro, se der 403/qualquer erro -> OKX
    try:
        return fetch_bybit_klines(symbol, interval="1", limit=limit)
    except Exception as e:
        st.session_state["history_provider"] = f"OKX (fallback). Motivo: {type(e).__name__}"
        return fetch_okx_klines(symbol, limit=limit)
