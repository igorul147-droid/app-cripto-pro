import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

from crypto_app.data import fetch_pairs, fetch_history_1m, symbol_compact
from crypto_app.realtime import RealtimeStore
from crypto_app.utils import to_local_naive, add_indicators


st.set_page_config(layout="wide")
st.title("🚀 Análise Cripto PRO+ (1m Live)")

# =========================
# SIDEBAR
# =========================
with st.sidebar:

    refresh = st.toggle("🔄 Refresh UI (1s)", True)
    if refresh:
        st_autorefresh(interval=1000)

    candles = st.slider("Histórico 1m", 300, 2000, 800)

    show_debug = st.toggle("🧪 Mostrar Debug HTTP", False)

# =========================
# PARES
# =========================
pairs = fetch_pairs()
moeda = st.selectbox("Par", pairs)
symbol = symbol_compact(moeda)

# =========================
# HISTÓRICO COM FALLBACK
# =========================
if "store" not in st.session_state or st.session_state.get("symbol") != symbol:

    try:
        base = fetch_history_1m(symbol, limit=candles)
        provider = st.session_state.get("history_provider", "Bybit (se não bloqueou) / OKX (fallback)")
    except Exception:
        base = pd.DataFrame(columns=["timestamp","open","high","low","close","volume"])
        provider = "Falhou REST (usando apenas WS)"
        st.warning("⚠️ Não consegui puxar histórico agora. O WS vai preencher em tempo real.")

    store = RealtimeStore(symbol, base)
    store.start()

    st.session_state.store = store
    st.session_state.symbol = symbol
    st.session_state.history_provider = provider

store = st.session_state.store

st.caption(f"📡 Histórico: {st.session_state.get('history_provider')}")

# =========================
# SNAPSHOT REALTIME
# =========================
with store.lock:
    df = store.df.copy()
    trades = list(store.trades)

if df.empty:
    st.warning("Aguardando dados do WebSocket...")
    st.stop()

# =========================
# INDICADORES
# =========================
df = add_indicators(df)
df_plot = to_local_naive(df)

# =========================
# GRÁFICO
# =========================
fig = make_subplots(
    rows=2,
    cols=1,
    shared_xaxes=True,
    row_heights=[0.8, 0.2],
    vertical_spacing=0.02,
)

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
        name=moeda,
    ),
    row=1, col=1
)

fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA7"], name="MA7"), row=1, col=1)
fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA25"], name="MA25"), row=1, col=1)
fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA99"], name="MA99"), row=1, col=1)

fig.update_layout(
    template="plotly_dark",
    height=850,
    xaxis_rangeslider_visible=False,
    margin=dict(l=10, r=10, t=10, b=10),
    dragmode="pan",
)

st.plotly_chart(fig, use_container_width=True)

# =========================
# TAPE (TIME & TRADES)
# =========================
st.subheader("📼 Time & Trades")

if trades:
    tdf = pd.DataFrame(trades)
    tdf["hora"] = tdf["time"].dt.tz_convert("America/Sao_Paulo").dt.strftime("%H:%M:%S")
    st.dataframe(
        tdf[["hora","side","price","qty"]].head(100),
        use_container_width=True
    )
else:
    st.info("Aguardando trades...")

# =========================
# DEBUG HTTP
# =========================
if show_debug and "last_http_debug" in st.session_state:
    with st.expander("🧪 Debug HTTP", expanded=True):
        st.json(st.session_state["last_http_debug"])
