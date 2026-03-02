import json
import threading
import time
from collections import deque

import pandas as pd
import websocket


BYBIT_WS = "wss://stream.bybit.com/v5/public/spot"


class RealtimeStore:

    def __init__(self, symbol, base_df, max_trades=200):
        self.symbol = symbol
        self.df = base_df.copy()
        self.trades = deque(maxlen=max_trades)
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):

        def on_open(ws):
            sub_msg = {
                "op": "subscribe",
                "args": [
                    f"kline.1.{self.symbol}",
                    f"publicTrade.{self.symbol}"
                ]
            }
            ws.send(json.dumps(sub_msg))

        def on_message(ws, message):
            msg = json.loads(message)

            if "topic" not in msg:
                return

            with self.lock:

                if msg["topic"].startswith("kline"):
                    k = msg["data"][0]
                    ts = pd.to_datetime(int(k["start"]), unit="ms", utc=True)

                    row = {
                        "timestamp": ts,
                        "open": float(k["open"]),
                        "high": float(k["high"]),
                        "low": float(k["low"]),
                        "close": float(k["close"]),
                        "volume": float(k["volume"]),
                    }

                    if self.df.empty:
                        self.df = pd.DataFrame([row])
                    else:
                        if ts == self.df["timestamp"].iloc[-1]:
                            for col in row:
                                self.df.at[self.df.index[-1], col] = row[col]
                        elif ts > self.df["timestamp"].iloc[-1]:
                            self.df = pd.concat([self.df, pd.DataFrame([row])], ignore_index=True)

                if msg["topic"].startswith("publicTrade"):
                    for t in msg["data"]:
                        self.trades.appendleft({
                            "time": pd.to_datetime(int(t["T"]), unit="ms", utc=True),
                            "price": float(t["p"]),
                            "qty": float(t["v"]),
                            "side": t["S"],
                        })

        ws = websocket.WebSocketApp(
            BYBIT_WS,
            on_open=on_open,
            on_message=on_message,
        )

        ws.run_forever()
