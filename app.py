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
# MAPA COIN IDs (CoinGecko)
# =============================
coin_map = {
    "BTC/USDT": "bitcoin",
    "ETH/USDT": "ethereum",
    "ADA/USDT": "cardano",
    "DOGE/USDT": "dogecoin",
    "PEPE/USDT": "pepe",
    "TURBO/USDT": "turbo",
}

available_pairs = list(coin_map.keys())

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    available_pairs,
    default=["BTC/USDT"],
    max_selections=3
)

timeframe = st.selectbox("Escolha o timeframe:", ["1d", "4h", "1h"])

indicadores = st.multiselect(
    "Indicadores:",
    ["SMA20", "RSI", "MACD"],
    default=["SMA20", "RSI", "MACD"]
)

meme_coins = ["DOGE/USDT", "PEPE/USDT", "TURBO/USDT"]

# =============================
# BUSCA DADOS COINGECKO
# =============================
@st.cache_data(ttl=300)
def fetch_data_coingecko(coin_id):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        params = {"vs_currency": "usd", "days": 30}
        headers = {"User-Agent": "Mozilla/5.0"}

        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()

        prices = data["prices"]

        df = pd.DataFrame(prices, columns=["timestamp","price"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        df["open"] = df["price"]
        df["high"] = df["price"]
        df["low"] = df["price"]
        df["close"] = df["price"]
        df["volume"] = 0

        return df

    except Exception:
        return None

# =============================
# LOOP
# =============================
for moeda in moedas:

    with st.expander(f"Detalhes de {moeda}", expanded=True):

        if moeda in meme_coins:
            st.warning("🧪 Meme coin — alta volatilidade")

        coin_id = coin_map[moeda]
        df = fetch_data_coingecko(coin_id)

        if df is None or df.empty:
            st.error(f"Não foi possível obter dados para {moeda}.")
            continue

        preco_inicial = df["close"].iloc[0]
        preco_final = df["close"].iloc[-1]
        variacao_pct = ((preco_final - preco_inicial) / preco_inicial) * 100
        ultimo_preco = df["close"].iloc[-1]

        preco_fmt = f"${ultimo_preco:,.6f}" if moeda in meme_coins else f"${ultimo_preco:,.2f}"

        st.metric(
            label=f"💰 Preço atual {moeda}",
            value=preco_fmt,
            delta=f"{variacao_pct:.2f}%"
        )

        # INDICADORES
        if "SMA20" in indicadores:
            df["SMA20"] = df["close"].rolling(20).mean()

        if "RSI" in indicadores:
            delta = df["close"].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss
            df["RSI"] = 100 - (100 / (1 + rs))

        if "MACD" in indicadores:
            ema12 = df["close"].ewm(span=12, adjust=False).mean()
            ema26 = df["close"].ewm(span=26, adjust=False).mean()
            df["MACD"] = ema12 - ema26
            df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

        # GRÁFICO
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True)

        fig.add_trace(go.Scatter(
            x=df["timestamp"],
            y=df["close"],
            name="Preço",
            mode="lines"
        ), row=1, col=1)

        fig.add_trace(go.Bar(
            x=df["timestamp"],
            y=df["volume"],
            name="Volume"
        ), row=2, col=1)

        fig.update_layout(
            template="plotly_dark",
            height=700
        )

        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Últimos preços")
        st.dataframe(df.tail(10))

if auto_refresh:
    st.info(f"🔄 Atualização automática a cada {refresh_seconds} segundos.")
else:
    st.info("🔄 Atualização automática desativada.")
