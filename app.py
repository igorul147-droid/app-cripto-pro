import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import requests

# ==============================
# PAGE
# ==============================
st.set_page_config(layout="wide", page_title="Análise Cripto PRO+ — Premium")

# CSS (mais premium)
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.2rem;}
      .stMetric {background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
                padding: 14px; border-radius: 14px;}
      div[data-testid="stSidebar"] {border-right: 1px solid rgba(255,255,255,0.06);}
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🚀 Análise Cripto PRO+ — Premium")

# ==============================
# SIDEBAR CONTROLS
# ==============================
with st.sidebar:
    st.header("⚙️ Controles")

    auto_refresh = st.toggle("🔄 Atualização automática", value=False)
    refresh_seconds = st.select_slider("Intervalo (segundos)", options=[60, 120, 180, 300], value=120)
    if auto_refresh:
        st_autorefresh(interval=refresh_seconds * 1000, key="refresh")

    if st.button("🔁 Atualizar agora"):
        st.rerun()

    st.divider()
    timeframe = st.selectbox("Timeframe:", ["1h", "4h", "1d"], index=1)

    janela = st.selectbox("Janela inicial:", ["1W", "1M", "3M", "6M", "ALL"], index=0)

    st.divider()
    st.subheader("📌 Indicadores (limpo)")
    show_ma = st.toggle("MA 7/25/99 (estilo Binance)", value=True)
    show_bb = st.toggle("Bollinger Bands", value=False)
    show_rsi = st.toggle("RSI", value=False)
    show_macd = st.toggle("MACD", value=False)

    st.divider()
    st.subheader("🎛️ Aparência")
    clean_volume = st.toggle("Volume clean", value=True)
    volume_colored = st.toggle("Volume verde/vermelho", value=True)
    show_price_line = st.toggle("Linha do preço atual", value=True)

# ==============================
# COINS
# ==============================
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

# ==============================
# HELPERS
# ==============================
def fmt_price(moeda: str, p: float) -> str:
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

def add_range_buttons_to_xaxis(fig):
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

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()

    # MA estilo Binance (7 / 25 / 99)
    if show_ma:
        d["MA7"] = d["close"].rolling(7).mean()
        d["MA25"] = d["close"].rolling(25).mean()
        d["MA99"] = d["close"].rolling(99).mean()

    if show_bb:
        mid = d["close"].rolling(20).mean()
        std = d["close"].rolling(20).std()
        d["BB_MID"] = mid
        d["BB_UP"] = mid + 2 * std
        d["BB_LOW"] = mid - 2 * std

    if show_rsi:
        delta = d["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        d["RSI"] = 100 - (100 / (1 + rs))

    if show_macd:
        ema12 = d["close"].ewm(span=12, adjust=False).mean()
        ema26 = d["close"].ewm(span=26, adjust=False).mean()
        d["MACD"] = ema12 - ema26
        d["SIGNAL"] = d["MACD"].ewm(span=9, adjust=False).mean()
        d["HIST"] = d["MACD"] - d["SIGNAL"]

    return d

# ==============================
# DATA: CoinGecko OHLC (real candles)
# ==============================
@st.cache_data(ttl=300)
def fetch_coingecko_ohlc(coin_id: str, days: int):
    # /coins/{id}/ohlc -> OHLC real (granularidade automática)
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    headers = {"User-Agent": "Mozilla/5.0 (StreamlitApp)"}
    r = requests.get(url, params=params, headers=headers, timeout=25)
    r.raise_for_status()
    data = r.json()
    # formato: [timestamp, open, high, low, close]
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)

@st.cache_data(ttl=300)
def fetch_volume_market_chart(coin_id: str, days: int):
    # pega volume via /market_chart (para casar com OHLC)
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days}
    headers = {"User-Agent": "Mozilla/5.0 (StreamlitApp)"}
    r = requests.get(url, params=params, headers=headers, timeout=25)
    r.raise_for_status()
    data = r.json()

    vol = pd.DataFrame(data["total_volumes"], columns=["timestamp", "volume"])
    vol["timestamp"] = pd.to_datetime(vol["timestamp"], unit="ms", utc=True)
    vol = vol.sort_values("timestamp").drop_duplicates("timestamp")
    return vol

def build_dataset(coin_id: str, timeframe: str):
    """
    CoinGecko OHLC: não entrega 1h para 7 dias.
    Mapeamento premium (honesto e estável):
      - "1h" => usa days=1 ou 2 (30m candles, intraday)
      - "4h" => days=7/14/30 (4h candles)
      - "1d" => days=365 (daily)
    """
    if timeframe == "1h":
        # Intraday de verdade (CoinGecko OHLC fica 30m em 1-2 dias) :contentReference[oaicite:1]{index=1}
        days = 2
        ohlc = fetch_coingecko_ohlc(coin_id, days=days)
        vol = fetch_volume_market_chart(coin_id, days=days)
        # merge aproximado de volume para o timestamp mais próximo
        df = pd.merge_asof(
            ohlc.sort_values("timestamp"),
            vol.sort_values("timestamp"),
            on="timestamp",
            direction="nearest",
            tolerance=pd.Timedelta("45min"),
        )
        df["volume"] = df["volume"].fillna(0)
        return df, "CoinGecko (30m candles - intraday)"
    elif timeframe == "4h":
        days = 30
        ohlc = fetch_coingecko_ohlc(coin_id, days=days)
        vol = fetch_volume_market_chart(coin_id, days=days)
        df = pd.merge_asof(
            ohlc.sort_values("timestamp"),
            vol.sort_values("timestamp"),
            on="timestamp",
            direction="nearest",
            tolerance=pd.Timedelta("3h"),
        )
        df["volume"] = df["volume"].fillna(0)
        return df, "CoinGecko (4h candles)"
    else:
        days = 365
        ohlc = fetch_coingecko_ohlc(coin_id, days=days)
        vol = fetch_volume_market_chart(coin_id, days=days)
        df = pd.merge_asof(
            ohlc.sort_values("timestamp"),
            vol.sort_values("timestamp"),
            on="timestamp",
            direction="nearest",
            tolerance=pd.Timedelta("12h"),
        )
        df["volume"] = df["volume"].fillna(0)
        return df, "CoinGecko (daily candles)"

# ==============================
# TABS
# ==============================
tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])

# ==============================
# MAIN
# ==============================
for moeda in moedas:
    coin_id = coin_map[moeda]

    with st.expander(f"Detalhes de {moeda}", expanded=True):
        if moeda in meme_coins:
            st.warning("🧪 Meme coin — alta volatilidade")

        try:
            df, source = build_dataset(coin_id, timeframe)
        except Exception:
            st.error(f"Não foi possível obter dados para {moeda}.")
            continue

        if df.empty:
            st.error("Sem dados suficientes.")
            continue

        df = add_indicators(df)

        st.caption(f"📡 Fonte: **{source}**")

        # KPIs
        ultimo = float(df["close"].iloc[-1])
        first = float(df["close"].iloc[0])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

        c1, c2, c3 = st.columns([1.5, 1, 1])
        c1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo), f"{var_pct:.2f}%")
        c2.metric("📈 Máxima (período)", fmt_price(moeda, float(df["high"].max())))
        c3.metric("📉 Mínima (período)", fmt_price(moeda, float(df["low"].min())))

        # Se o usuário quiser “1W” com 1h, avisa (porque 1h real não existe via OHLC público)
        if timeframe == "1h" and janela in ("1W", "1M", "3M", "6M", "ALL"):
            st.info("ℹ️ No CoinGecko, candles intraday são **30m** (até 1–2 dias). Para **1 semana**, use **4h** para ficar igual corretora.")

        # ======================
        # TAB: CHART (TradingView-ish)
        # ======================
        with tab_chart:
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.82, 0.18],
                vertical_spacing=0.02,
                row_titles=["Preço", "Volume"]
            )

            # Candles (mais “visíveis”)
            fig.add_trace(go.Candlestick(
                x=df["timestamp"],
                open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                increasing_line_color="#00C896",
                decreasing_line_color="#FF4B4B",
                increasing_fillcolor="#00C896",
                decreasing_fillcolor="#FF4B4B",
                name="Preço",
                showlegend=False
            ), row=1, col=1)

            # Linha preço atual
            if show_price_line:
                fig.add_hline(y=ultimo, line_dash="dot", opacity=0.55, row=1, col=1)

            # MA's (7/25/99)
            if show_ma and "MA7" in df.columns:
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["MA7"], mode="lines", name="MA7", showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["MA25"], mode="lines", name="MA25", showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["MA99"], mode="lines", name="MA99", showlegend=False), row=1, col=1)

            # Bollinger
            if show_bb and "BB_UP" in df.columns:
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_UP"], mode="lines", name="BB Up", showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_MID"], mode="lines", name="BB Mid", showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_LOW"], mode="lines", name="BB Low", showlegend=False), row=1, col=1)

            # Volume clean + verde/vermelho
            if volume_colored:
                vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df["open"], df["close"])]
            else:
                vol_colors = None

            fig.add_trace(go.Bar(
                x=df["timestamp"],
                y=df["volume"],
                marker_color=vol_colors,
                opacity=0.22 if clean_volume else 0.45,
                name="Volume",
                showlegend=False
            ), row=2, col=1)

            # Range inicial + slider + botões
            start, end = initial_range(df, janela)
            fig.update_xaxes(range=[start, end])
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
            add_range_buttons_to_xaxis(fig)

            fig.update_layout(
                template="plotly_dark",
                height=740,
                hovermode="x unified",
                margin=dict(l=10, r=10, t=10, b=10)
            )
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
            fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)")

            st.plotly_chart(fig, use_container_width=True)

        # ======================
        # TAB: RSI
        # ======================
        with tab_rsi:
            if not show_rsi or "RSI" not in df.columns:
                st.info("Ative RSI no menu lateral.")
            else:
                fr = go.Figure()
                fr.add_trace(go.Scatter(x=df["timestamp"], y=df["RSI"], mode="lines", name="RSI"))
                fr.add_hline(y=70, line_dash="dot", opacity=0.6)
                fr.add_hline(y=30, line_dash="dot", opacity=0.6)
                start, end = initial_range(df, janela)
                fr.update_xaxes(range=[start, end], rangeslider=dict(visible=True, thickness=0.06))
                add_range_buttons_to_xaxis(fr)
                fr.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fr, use_container_width=True)

        # ======================
        # TAB: MACD
        # ======================
        with tab_macd:
            if not show_macd or "MACD" not in df.columns:
                st.info("Ative MACD no menu lateral.")
            else:
                fm = go.Figure()
                fm.add_trace(go.Scatter(x=df["timestamp"], y=df["MACD"], mode="lines", name="MACD"))
                fm.add_trace(go.Scatter(x=df["timestamp"], y=df["SIGNAL"], mode="lines", name="Signal"))
                if "HIST" in df.columns:
                    fm.add_trace(go.Bar(x=df["timestamp"], y=df["HIST"], name="Hist", opacity=0.25))
                start, end = initial_range(df, janela)
                fm.update_xaxes(range=[start, end], rangeslider=dict(visible=True, thickness=0.06))
                add_range_buttons_to_xaxis(fm)
                fm.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fm, use_container_width=True)

        st.caption("Dica: use o slider inferior para arrastar e navegar no tempo.")

st.info("✅ Premium: MA 7/25/99 + Volume clean + Janela inicial + Range buttons + Slider + Layout mais profissional.")


