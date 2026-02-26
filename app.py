import streamlit as st
import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import requests

st.set_page_config(layout="wide", page_title="App Cripto PRO+")
st.title("🚀 Análise Cripto PRO+")

# =============================
# SIDEBAR / CONTROLES
# =============================
with st.sidebar:
    st.header("⚙️ Controles")

    auto_refresh = st.toggle("🔄 Atualização automática", value=False)
    refresh_seconds = st.select_slider("Intervalo (segundos)", options=[60, 120, 180, 300], value=120)
    if auto_refresh:
        st_autorefresh(interval=refresh_seconds * 1000, key="refresh")

    if st.button("🔁 Atualizar agora"):
        st.rerun()

    timeframe = st.selectbox("Timeframe:", ["1h", "4h", "1d"], index=2)

    janela = st.selectbox(
        "Janela inicial do gráfico:",
        ["7 dias", "14 dias", "30 dias", "90 dias", "Tudo"],
        index=0
    )

    indicadores = st.multiselect(
        "Indicadores:",
        ["SMA20", "RSI", "MACD", "Bollinger Bands"],
        default=["SMA20", "RSI", "MACD", "Bollinger Bands"]
    )

# =============================
# MAPA COINGECKO IDs
# =============================
coin_map = {
    "BTC/USDT": "bitcoin",
    "ETH/USDT": "ethereum",
    "ADA/USDT": "cardano",
    "DOGE/USDT": "dogecoin",
    "PEPE/USDT": "pepe",
    "TURBO/USDT": "turbo",
}
meme_coins = ["DOGE/USDT", "PEPE/USDT", "TURBO/USDT"]

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    list(coin_map.keys()),
    default=["BTC/USDT"],
    max_selections=3
)

# =============================
# COINGECKO (prices + volumes)
# =============================
@st.cache_data(ttl=300)
def fetch_coingecko_market_chart(coin_id: str, days: int = 90):
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days}
    headers = {"User-Agent": "Mozilla/5.0 (StreamlitApp)"}
    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()

    prices = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
    volumes = pd.DataFrame(data["total_volumes"], columns=["timestamp", "volume"])

    prices["timestamp"] = pd.to_datetime(prices["timestamp"], unit="ms", utc=True)
    volumes["timestamp"] = pd.to_datetime(volumes["timestamp"], unit="ms", utc=True)

    df = prices.merge(volumes, on="timestamp", how="left").sort_values("timestamp").reset_index(drop=True)
    df["price"] = df["price"].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df

def resample_to_ohlc(df_ticks: pd.DataFrame, tf: str) -> pd.DataFrame:
    df = df_ticks.copy().set_index("timestamp")
    rule_map = {"1h": "1H", "4h": "4H", "1d": "1D"}
    rule = rule_map.get(tf, "1D")
    ohlc = df["price"].resample(rule).ohlc()
    vol = df["volume"].resample(rule).sum()
    out = ohlc.join(vol).dropna().reset_index()
    out.columns = ["timestamp", "open", "high", "low", "close", "volume"]
    return out

def add_indicators(df: pd.DataFrame, indicadores: list[str]) -> pd.DataFrame:
    d = df.copy()

    if "SMA20" in indicadores:
        d["SMA20"] = d["close"].rolling(20).mean()

    if "Bollinger Bands" in indicadores:
        mid = d["close"].rolling(20).mean()
        std = d["close"].rolling(20).std()
        d["BB_middle"] = mid
        d["BB_upper"] = mid + 2 * std
        d["BB_lower"] = mid - 2 * std

    if "RSI" in indicadores:
        delta = d["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        d["RSI"] = 100 - (100 / (1 + rs))

    if "MACD" in indicadores:
        ema12 = d["close"].ewm(span=12, adjust=False).mean()
        ema26 = d["close"].ewm(span=26, adjust=False).mean()
        d["MACD"] = ema12 - ema26
        d["MACD_signal"] = d["MACD"].ewm(span=9, adjust=False).mean()
        d["MACD_hist"] = d["MACD"] - d["MACD_signal"]

    return d

def price_fmt(moeda: str, price: float) -> str:
    return f"${price:,.6f}" if moeda in meme_coins else f"${price:,.2f}"

def initial_range(df: pd.DataFrame, janela_label: str):
    if df.empty:
        return None, None
    end = df["timestamp"].max()
    if janela_label == "7 dias":
        start = end - pd.Timedelta(days=7)
    elif janela_label == "14 dias":
        start = end - pd.Timedelta(days=14)
    elif janela_label == "30 dias":
        start = end - pd.Timedelta(days=30)
    elif janela_label == "90 dias":
        start = end - pd.Timedelta(days=90)
    else:
        start = df["timestamp"].min()
    return start, end

# =============================
# LOOP PRINCIPAL
# =============================
for moeda in moedas:
    coin_id = coin_map[moeda]

    with st.expander(f"Detalhes de {moeda}", expanded=True):
        if moeda in meme_coins:
            st.warning("🧪 Meme coin — alta volatilidade")

        try:
            ticks = fetch_coingecko_market_chart(coin_id, days=180)  # mais histórico p/ arrastar
        except Exception:
            st.error(f"Não foi possível obter dados para {moeda} via CoinGecko.")
            continue

        df = resample_to_ohlc(ticks, timeframe)
        if df.empty:
            st.error(f"Sem dados suficientes para {moeda} nesse timeframe.")
            continue

        df = add_indicators(df, indicadores)

        preco_inicial = df["close"].iloc[0]
        preco_final = df["close"].iloc[-1]
        variacao_pct = ((preco_final - preco_inicial) / preco_inicial) * 100
        ultimo_preco = df["close"].iloc[-1]

        st.metric(
            label=f"💰 Preço atual {moeda}",
            value=price_fmt(moeda, ultimo_preco),
            delta=f"{variacao_pct:.2f}%"
        )

        # =============================
        # SUBPLOTS
        # =============================
        rows = 2
        heights = [0.74, 0.10]  # volume bem menor (mais clean)
        titles = ["Preço", "Volume"]

        has_rsi = "RSI" in indicadores
        has_macd = "MACD" in indicadores

        if has_rsi:
            rows += 1
            heights.append(0.08)
            titles.append("RSI")

        if has_macd:
            rows += 1
            heights.append(0.08)
            titles.append("MACD")

        fig = make_subplots(
            rows=rows,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.02,
            row_heights=heights,
            row_titles=titles
        )

        # Candles
        fig.add_trace(go.Candlestick(
            x=df["timestamp"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
            name="Preço"
        ), row=1, col=1)

        # SMA + Bollinger
        if "SMA20" in indicadores and "SMA20" in df.columns:
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["SMA20"], name="SMA20", mode="lines"), row=1, col=1)

        if "Bollinger Bands" in indicadores and "BB_upper" in df.columns:
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_upper"], name="BB Upper", mode="lines"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_middle"], name="BB Middle", mode="lines"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_lower"], name="BB Lower", mode="lines"), row=1, col=1)

        # Volume (clean: opacidade e sem destaque)
        fig.add_trace(go.Bar(
            x=df["timestamp"],
            y=df["volume"],
            name="Volume",
            opacity=0.35
        ), row=2, col=1)

        current_row = 3

        # RSI
        if has_rsi and "RSI" in df.columns:
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["RSI"], name="RSI", mode="lines"), row=current_row, col=1)
            fig.add_hline(y=70, line_dash="dot", row=current_row, col=1)
            fig.add_hline(y=30, line_dash="dot", row=current_row, col=1)
            current_row += 1

        # MACD
        if has_macd and "MACD" in df.columns:
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["MACD"], name="MACD", mode="lines"), row=current_row, col=1)
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["MACD_signal"], name="Signal", mode="lines"), row=current_row, col=1)
            if "MACD_hist" in df.columns:
                fig.add_trace(go.Bar(x=df["timestamp"], y=df["MACD_hist"], name="Hist", opacity=0.35), row=current_row, col=1)

        # Range inicial + slider para arrastar
        start, end = initial_range(df, janela)
        fig.update_xaxes(range=[start, end], row=1, col=1)
        fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))  # slider estilo TradingView

        fig.update_layout(
            template="plotly_dark",
            height=820,
            hovermode="x unified",
            legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center")
        )

        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Últimos candles")
        st.dataframe(df[["timestamp", "open", "high", "low", "close", "volume"]].tail(15))

st.info("✅ Rodando via CoinGecko (estável no Streamlit Cloud).")
