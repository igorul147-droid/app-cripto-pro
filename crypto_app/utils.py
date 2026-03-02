diff --git a/crypto_app/utils.py b/crypto_app/utils.py
new file mode 100644
index 0000000000000000000000000000000000000000..4869f1108e96c9e50e1100e6981313e601b0d99c
--- /dev/null
+++ b/crypto_app/utils.py
@@ -0,0 +1,101 @@
+import pandas as pd
+import numpy as np
+
+TZ_LOCAL = "America/Sao_Paulo"
+
+
+def default_visible_candles(tf: str) -> int:
+    return {"1h": 336, "4h": 84, "1d": 14}.get(tf, 336)
+
+
+def fmt_price(moeda: str, p: float, meme_coins: set[str]) -> str:
+    return f"${p:,.6f}" if moeda in meme_coins else f"${p:,.2f}"
+
+
+def ensure_timestamp_utc(series: pd.Series) -> pd.Series:
+    parsed = series
+    if not pd.api.types.is_datetime64_any_dtype(parsed):
+        parsed = pd.to_datetime(parsed, utc=True, errors="coerce")
+    elif getattr(parsed.dt, "tz", None) is None:
+        parsed = parsed.dt.tz_localize("UTC")
+    else:
+        parsed = parsed.dt.tz_convert("UTC")
+    return parsed
+
+
+def to_local_naive(df: pd.DataFrame) -> pd.DataFrame:
+    out = df.copy()
+    out["timestamp"] = ensure_timestamp_utc(out["timestamp"]).dt.tz_convert(TZ_LOCAL).dt.tz_localize(None)
+    return out
+
+
+def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
+    normalized = df.copy()
+    normalized["timestamp"] = ensure_timestamp_utc(normalized["timestamp"])
+    normalized = normalized.sort_values("timestamp").reset_index(drop=True)
+    for col in ["open", "high", "low", "close", "volume"]:
+        if col in normalized.columns:
+            normalized[col] = pd.to_numeric(normalized[col], errors="coerce")
+    normalized = normalized.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
+    if "volume" not in normalized.columns:
+        normalized["volume"] = 0.0
+    normalized["volume"] = normalized["volume"].fillna(0.0)
+    return normalized
+
+
+def compute_dtick_for_range(ymin: float, ymax: float) -> float | None:
+    rng = float(ymax - ymin)
+    if rng <= 0 or not np.isfinite(rng):
+        return None
+    if rng <= 25000:
+        return 1000.0
+    if rng <= 80000:
+        return 5000.0
+    if rng <= 200000:
+        return 10000.0
+    return None
+
+
+def add_indicators(
+    df: pd.DataFrame,
+    show_ma: bool,
+    show_bb: bool,
+    show_rsi: bool,
+    show_macd: bool,
+    show_vol_ma: bool,
+    vol_ma_period: int,
+) -> pd.DataFrame:
+    d = df.copy()
+
+    if show_ma:
+        d["MA7"] = d["close"].rolling(7).mean()
+        d["MA25"] = d["close"].rolling(25).mean()
+        d["MA99"] = d["close"].rolling(99).mean()
+
+    if show_bb:
+        mid = d["close"].rolling(20).mean()
+        std = d["close"].rolling(20).std()
+        d["BB_MID"] = mid
+        d["BB_UP"] = mid + 2 * std
+        d["BB_LOW"] = mid - 2 * std
+
+    if show_rsi:
+        delta = d["close"].diff()
+        gain = delta.clip(lower=0)
+        loss = -delta.clip(upper=0)
+        avg_gain = gain.rolling(14).mean()
+        avg_loss = loss.rolling(14).mean()
+        rs = avg_gain / avg_loss
+        d["RSI"] = 100 - (100 / (1 + rs))
+
+    if show_macd:
+        ema12 = d["close"].ewm(span=12, adjust=False).mean()
+        ema26 = d["close"].ewm(span=26, adjust=False).mean()
+        d["MACD"] = ema12 - ema26
+        d["SIGNAL"] = d["MACD"].ewm(span=9, adjust=False).mean()
+        d["HIST"] = d["MACD"] - d["SIGNAL"]
+
+    if show_vol_ma:
+        d["VOL_MA"] = d["volume"].rolling(vol_ma_period).mean()
+
+    return d
