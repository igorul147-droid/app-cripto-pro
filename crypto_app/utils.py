import pandas as pd
import numpy as np

TZ_LOCAL = "America/Sao_Paulo"


def to_local_naive(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True).dt.tz_convert(TZ_LOCAL).dt.tz_localize(None)
    return out


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna().sort_values("timestamp").reset_index(drop=True)
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["MA7"] = d["close"].rolling(7).mean()
    d["MA25"] = d["close"].rolling(25).mean()
    d["MA99"] = d["close"].rolling(99).mean()
    return d
