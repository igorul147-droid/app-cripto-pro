import streamlit as st
import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import requests

st.set_page_config(layout="wide", page_title="App Cripto PRO+")
st.title("🚀 Análise Cripto PRO+")

# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.header("⚙️ Controles")

    auto_refresh = st.toggle("🔄 Atualização automática", value=False)
    refresh_seconds = st.select_slider("Intervalo (segundos)", options=[60, 120, 180, 300], value=120)
    if auto_refresh:
        st_autorefresh(interval=refresh_seconds * 1000, key="refresh")

    if st.button("🔁 Atualizar agora"):
        st.rerun()

    timeframe = st.selectbox("Timeframe:", ["1h", "4h", "1d"], index=2)

    janela = st.selectbox("Janela inicial:", ["1W", "1M", "3M", "6M", "ALL"], index=0)

    st.divider()
    st.subheader("📌 Indicadores (limpo)")
    show_sma = st.toggle("SMA20", value=True)
    show_bb = st.toggle("Bollinger Bands", value=True)
    show_rsi = st.toggle("RSI", value=False)
    show_macd = st.toggle("MACD", value=False)

# -----------------------------
# Coin map
# -----------------------------
coin_map = {
    "BTC/USDT": "bitcoin",
    "ETH/USDT": "ethereum",
    "ADA/USDT": "cardano",
    "DOGE/USDT": "dogecoin",
    "PEPE/USDT": "pepe",
    "TURBO/USDT": "turbo",
}
meme_coins = {"DOGE/USDT", "PEPE/USDT", "TURBO/USDT"}

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    list(coin_map.keys()),
    default=["BTC/USDT"],
    max_selections=3
)

# -----------------------------
# Data fetch (CoinGecko)
# -----------------------------
@st.cache_data(ttl=300)
def fetch_coingecko_market_chart(coin_id: str, days: int = 365):
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

def add_indicators(df: pd.DataFrame, sma: bool, bb: bool, rsi: bool, macd: bool) -> pd.DataFrame:
    d = df.copy()

    if sma:
        d["SMA20"] = d["close"].rolling(20).mean()

    if bb:
        mid = d["close"].rolling(20).mean()
        std = d["close"].rolling(20).std()
        d["BB_middle"] = mid
        d["BB_upper"] = mid + 2 * std
        d["BB_lower"] = mid - 2 * std

    if rsi:
        delta = d["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        d["RSI"] = 100 - (100 / (1 + rs))

    if macd:
        ema12 = d["close"].ewm(span=12, adjust=False).mean()
        ema26 = d["close"].ewm(span=26, adjust=False).mean()
        d["MACD"] = ema12 - ema26
        d["MACD_signal"] = d["MACD"].ewm(span=9, adjust=False).mean()
        d["MACD_hist"] = d["MACD"] - d["MACD_signal"]

    return d

def price_fmt(moeda: str, p: float) -> str:
    return f"${p:,.6f}" if moeda in meme_coins else f"${p:,.2f}"

def initial_range(df: pd.DataFrame, janela_label: str):
    end = df["timestamp"].max()
    if janela_label == "1W":
        start = end - pd.Timedelta(days=7)
    elif janela_label == "1M":
        start = end - pd.Timedelta(days=30)
    elif janela_label == "3M":
        start = end - pd.Timedelta(days=90)
    elif janela_label == "6M":
        start = end - pd.Timedelta(days=180)
    else:
        start = df["timestamp"].min()
    return start, end

def add_range_buttons(fig):
    fig.update_xaxes(
        rangeselector=dict(
            buttons=list([
                dict(count=7, label="1W", step="day", stepmode="backward"),
                dict(count=1, label="1M", step="month", stepmode="backward"),
                dict(count=3, label="3M", step="month", stepmode="backward"),
                dict(count=6, label="6M", step="month", stepmode="backward"),
                dict(step="all", label="ALL"),
            ])
        )
    )

# -----------------------------
# Tabs (melhor leitura)
# -----------------------------
tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])

for moeda in moedas:
    coin_id = coin_map[moeda]

    with st.expander(f"Detalhes de {moeda}", expanded=True):
        try:
            ticks = fetch_coingecko_market_chart(coin_id, days=365)
        except Exception:
            st.error(f"Falha ao buscar dados no CoinGecko para {moeda}.")
            continue

        df = resample_to_ohlc(ticks, timeframe)
        df = add_indicators(df, show_sma, show_bb, show_rsi, show_macd)
        if df.empty:
            st.error("Sem dados suficientes.")
            continue

        # metric
        preco_inicial = df["close"].iloc[0]
        preco_final = df["close"].iloc[-1]
        variacao_pct = ((preco_final - preco_inicial) / preco_inicial) * 100
        ultimo_preco = df["close"].iloc[-1]

        st.metric(
            label=f"💰 Preço atual {moeda}",
            value=price_fmt(moeda, ultimo_preco),
            delta=f"{variacao_pct:.2f}%"
        )

        # -------------------------
        # TAB: GRÁFICO PRINCIPAL
        # -------------------------
        with tab_chart:
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.82, 0.18],
                vertical_spacing=0.02,
                row_titles=["Preço", "Volume"]
            )

            fig.add_trace(go.Candlestick(
                x=df["timestamp"],
                open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                name="Preço",
                showlegend=False
            ), row=1, col=1)

            # SMA / BB (sem entupir a legenda)
            if show_sma and "SMA20" in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["timestamp"], y=df["SMA20"],
                    mode="lines", name="SMA20",
                    showlegend=False
                ), row=1, col=1)

            if show_bb and "BB_upper" in df.columns:
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_upper"], mode="lines", name="BB Upper", showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_middle"], mode="lines", name="BB Mid", showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_lower"], mode="lines", name="BB Low", showlegend=False), row=1, col=1)

            # Volume clean (discreto)
            fig.add_trace(go.Bar(
                x=df["timestamp"],
                y=df["volume"],
                opacity=0.25,
                name="Volume",
                showlegend=False
            ), row=2, col=1)

            # range inicial + slider + botões
            start, end = initial_range(df, janela)
            fig.update_xaxes(range=[start, end])
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
            add_range_buttons(fig)

            fig.update_layout(
                template="plotly_dark",
                height=720,
                hovermode="x unified",
                margin=dict(l=10, r=10, t=10, b=10)
            )

            st.plotly_chart(fig, use_container_width=True)

        # -------------------------
        # TAB: RSI
        # -------------------------
        with tab_rsi:
            if not show_rsi or "RSI" not in df.columns:
                st.info("Ative o RSI no menu lateral para ver aqui.")
            else:
                fig_rsi = go.Figure()
                fig_rsi.add_trace(go.Scatter(x=df["timestamp"], y=df["RSI"], mode="lines", name="RSI"))
                fig_rsi.add_hline(y=70, line_dash="dot")
                fig_rsi.add_hline(y=30, line_dash="dot")
                start, end = initial_range(df, janela)
                fig_rsi.update_xaxes(range=[start, end], rangeslider=dict(visible=True, thickness=0.06))
                add_range_buttons(fig_rsi)
                fig_rsi.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_rsi, use_container_width=True)

        # -------------------------
        # TAB: MACD
        # -------------------------
        with tab_macd:
            if not show_macd or "MACD" not in df.columns:
                st.info("Ative o MACD no menu lateral para ver aqui.")
            else:
                fig_m = go.Figure()
                fig_m.add_trace(go.Scatter(x=df["timestamp"], y=df["MACD"], mode="lines", name="MACD"))
                fig_m.add_trace(go.Scatter(x=df["timestamp"], y=df["MACD_signal"], mode="lines", name="Signal"))
                if "MACD_hist" in df.columns:
                    fig_m.add_trace(go.Bar(x=df["timestamp"], y=df["MACD_hist"], name="Hist", opacity=0.25))
                start, end = initial_range(df, janela)
                fig_m.update_xaxes(range=[start, end], rangeslider=dict(visible=True, thickness=0.06))
                add_range_buttons(fig_m)
                fig_m.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_m, use_container_width=True)

        st.caption("Dica: Use o slider abaixo do gráfico pra arrastar e navegar no tempo.")

