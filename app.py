import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

from crypto_app.data import fetch_pairs, fetch_bybit_klines, symbol_compact
from crypto_app.realtime import RealtimeStore
from crypto_app.utils import to_local_naive, add_indicators

st.set_page_config(layout="wide")

st.title("🚀 Análise Cripto PRO+ (BYBIT WS 1m)")

with st.sidebar:
    refresh = st.toggle("Refresh UI (1s)", True)
    if refresh:
        st_autorefresh(interval=1000)

    candles = st.slider("Histórico 1m", 300, 2000, 800)

pairs = fetch_pairs()

moeda = st.selectbox("Par", pairs)
symbol = symbol_compact(moeda)

if "store" not in st.session_state:
    base = fetch_bybit_klines(symbol, limit=candles)
    store = RealtimeStore(symbol, base)
    store.start()
    st.session_state.store = store

store = st.session_state.store
df, trades = None, None

with store.lock:
    df = store.df.copy()
    trades = list(store.trades)

if df.empty:
    st.warning("Aguardando dados...")
    st.stop()

df = add_indicators(df)
df_plot = to_local_naive(df)

fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8,0.2])

fig.add_trace(
    go.Candlestick(
        x=df_plot["timestamp"],
        open=df_plot["open"],
        high=df_plot["high"],
        low=df_plot["low"],
        close=df_plot["close"],
        increasing_fillcolor="#00C896",
        decreasing_fillcolor="#FF4B4B",
        whiskerwidth=0.4,
    ),
    row=1,col=1
)

fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA7"], name="MA7"), row=1,col=1)
fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA25"], name="MA25"), row=1,col=1)
fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA99"], name="MA99"), row=1,col=1)

fig.update_layout(template="plotly_dark", height=850, xaxis_rangeslider_visible=False)
st.plotly_chart(fig, use_container_width=True)

st.subheader("📼 Time & Trades")
if trades:
    tdf = pd.DataFrame(trades)
    st.dataframe(tdf.head(100), use_container_width=True)
