import streamlit as st
import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import requests
import datetime

st.set_page_config(layout="wide", page_title="App Cripto PRO+")
st.title("🚀 Análise Cripto PRO+")

# =============================
# CONTROLES
# =============================
auto_refresh = st.toggle("🔄 Atualização automática", value=False)
refresh_seconds = st.select_slider("Intervalo (segundos)", options=[60,120,180,300], value=120)

if auto_refresh:
    st_autorefresh(interval=refresh_seconds * 1000, key="refresh")

# =============================
# LISTA FIXA (mais estável no cloud)
# =============================
available_pairs = [
    "BTC/USDT",
    "ETH/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "PEPE/USDT",
    "TURBO/USDT",
]

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    available_pairs,
    default=["BTC/USDT"],
    max_selections=3
)

timeframe_map = {
    "1d": "1d",
    "4h": "4h",
    "1h": "1h"
}

timeframe = st.selectbox("Escolha o timeframe:", list(timeframe_map.keys()))

indicadores = st.multiselect(
    "Indicadores:",
    ["SMA20", "RSI", "MACD", "Bollinger Bands"],
    default=["SMA20", "RSI", "MACD", "Bollinger Bands"]
)

meme_coins = ["DOGE/USDT", "PEPE/USDT", "TURBO/USDT"]

# =============================
# BUSCA DADOS DIRETO NA BINANCE (REST)
# =============================
@st.cache_data(ttl=300)
def fetch_binance_data(symbol, interval):
    try:
        base = symbol.replace("/", "")
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": base,
            "interval": interval,
            "limit": 500
        }

        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()

        data = r.json()

        df = pd.DataFrame(data, columns=[
            "timestamp","open","high","low","close","volume",
            "_","_","_","_","_","_"
        ])

        df = df[["timestamp","open","high","low","close","volume"]]

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df[["open","high","low","close","volume"]] = df[["open","high","low","close","volume"]].astype(float)

        return df

    except Exception:
        return None

# =============================
# LOOP PRINCIPAL
# =============================
for moeda in moedas:

    with st.expander(f"Detalhes de {moeda}", expanded=True):

        if moeda in meme_coins:
            st.warning("🧪 Meme coin — alta volatilidade")

        df = fetch_binance_data(moeda, timeframe_map[timeframe])

        if df is None or df.empty:
            st.error(f"Não foi possível obter dados para {moeda}.")
            continue

        # FILTRA MÊS ATUAL
        now = datetime.datetime.now()
        df_mes = df[
            (df["timestamp"].dt.month == now.month) &
            (df["timestamp"].dt.year == now.year)
        ].copy()

        if df_mes.empty:
            df_mes = df.tail(100)

        preco_inicial = df_mes["close"].iloc[0]
        preco_final = df_mes["close"].iloc[-1]
        variacao_pct = ((preco_final - preco_inicial) / preco_inicial) * 100
        ultimo_preco = df_mes["close"].iloc[-1]

        preco_fmt = f"${ultimo_preco:,.6f}" if moeda in meme_coins else f"${ultimo_preco:,.2f}"

        st.metric(
            label=f"💰 Preço atual {moeda}",
            value=preco_fmt,
            delta=f"{variacao_pct:.2f}%"
        )

        # =============================
        # INDICADORES
        # =============================
        if "SMA20" in indicadores:
            df_mes["SMA20"] = df_mes["close"].rolling(20).mean()

        if "RSI" in indicadores:
            delta = df_mes["close"].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss
            df_mes["RSI"] = 100 - (100 / (1 + rs))

        if "MACD" in indicadores:
            ema12 = df_mes["close"].ewm(span=12, adjust=False).mean()
            ema26 = df_mes["close"].ewm(span=26, adjust=False).mean()
            df_mes["MACD"] = ema12 - ema26
            df_mes["MACD_signal"] = df_mes["MACD"].ewm(span=9, adjust=False).mean()

        # =============================
        # GRÁFICO
        # =============================
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True)

        fig.add_trace(go.Candlestick(
            x=df_mes["timestamp"],
            open=df_mes["open"],
            high=df_mes["high"],
            low=df_mes["low"],
            close=df_mes["close"],
            name="Preço"
        ), row=1, col=1)

        fig.add_trace(go.Bar(
            x=df_mes["timestamp"],
            y=df_mes["volume"],
            name="Volume"
        ), row=2, col=1)

        fig.update_layout(
            template="plotly_dark",
            height=700,
            xaxis_rangeslider_visible=False
        )

        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Últimos preços")
        st.dataframe(df_mes.tail(10))

if auto_refresh:
    st.info(f"🔄 Atualização automática a cada {refresh_seconds} segundos.")
else:
    st.info("🔄 Atualização automática desativada.")
