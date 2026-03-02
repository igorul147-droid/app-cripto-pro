import json
import threading
import time
from collections import deque

import pandas as pd
import websocket  # websocket-client

BINANCE_WS = "wss://stream.binance.com:9443/stream?streams="


def _to_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def _kline_row_from_msg(k: dict) -> dict:
    ts = pd.to_datetime(int(k["t"]), unit="ms", utc=True)
    return {
        "timestamp": ts,
        "open": _to_float(k["o"]),
        "high": _to_float(k["h"]),
        "low": _to_float(k["l"]),
        "close": _to_float(k["c"]),
        "volume": _to_float(k["v"]),
    }


def _trade_row_from_msg(t: dict) -> dict:
    ts = pd.to_datetime(int(t["T"]), unit="ms", utc=True)
    return {
        "time": ts,
        "price": _to_float(t["p"]),
        "qty": _to_float(t["q"]),
        "is_maker": bool(t.get("m", False)),  # True ~ sell agressivo
    }


class RealtimeStore:
    def __init__(self, symbol_compact: str, base_df_ohlcv: pd.DataFrame, max_trades: int = 250):
        self.symbol = symbol_compact.upper()
        self.lock = threading.Lock()

        self.df_ohlcv = base_df_ohlcv.copy()
        self.trades = deque(maxlen=max_trades)

        self.last_update_ts = time.time()
        self.last_ws_error = None

        self._stop = threading.Event()
        self._thread = None

    def stop(self):
        self._stop.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running():
            return
        self._stop.clear()
        t = threading.Thread(target=self._run, name=f"ws-{self.symbol}", daemon=True)
        self._thread = t
        t.start()

    def _run(self):
        streams = f"{self.symbol.lower()}@kline_1m/{self.symbol.lower()}@aggTrade"
        url = BINANCE_WS + streams

        def on_message(ws, message):
            try:
                msg = json.loads(message)
                data = msg.get("data", {})
                event_type = data.get("e")

                with self.lock:
                    if event_type == "kline":
                        k = data["k"]
                        row = _kline_row_from_msg(k)

                        if self.df_ohlcv.empty:
                            self.df_ohlcv = pd.DataFrame([row])
                        else:
                            last_ts = self.df_ohlcv["timestamp"].iloc[-1]
                            if row["timestamp"] == last_ts:
                                for col in ["open", "high", "low", "close", "volume"]:
                                    self.df_ohlcv.at[self.df_ohlcv.index[-1], col] = row[col]
                            elif row["timestamp"] > last_ts:
                                self.df_ohlcv = pd.concat([self.df_ohlcv, pd.DataFrame([row])], ignore_index=True)

                        if len(self.df_ohlcv) > 8000:
                            self.df_ohlcv = self.df_ohlcv.tail(8000).reset_index(drop=True)

                    elif event_type == "aggTrade":
                        tr = _trade_row_from_msg(data)
                        self.trades.appendleft(tr)

                    self.last_update_ts = time.time()

            except Exception as e:
                with self.lock:
                    self.last_ws_error = str(e)[:300]

        def on_error(ws, error):
            with self.lock:
                self.last_ws_error = str(error)[:300]

        def on_close(ws, status_code, msg):
            with self.lock:
                self.last_ws_error = f"closed: {status_code} {msg}"[:300]

        while not self._stop.is_set():
            try:
                ws = websocket.WebSocketApp(url, on_message=on_message, on_error=on_error, on_close=on_close)
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                with self.lock:
                    self.last_ws_error = str(e)[:300]

            for _ in range(10):
                if self._stop.is_set():
                    break
                time.sleep(0.3)

    def snapshot(self):
        with self.lock:
            df = self.df_ohlcv.copy()
            trades = list(self.trades)
            meta = {"last_update_ts": self.last_update_ts, "last_ws_error": self.last_ws_error}
        return df, trades, meta
