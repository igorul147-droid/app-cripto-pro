import streamlit as st
import pandas as pd
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import requests

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(layout="wide", page_title="App Cripto PRO+ (Premium)")
st.title("🚀 Análise Cripto PRO+ — Premium")

# =========================================================
# SIDEBAR (Premium Controls)
# =========================================================
with st.sidebar:
    st.header("⚙️ Controles")

    auto_refresh = st.toggle("🔄 Atualização automática", value=False)
    refresh_seconds = st.select_slider("Intervalo (segundos)", options=[60, 120, 180, 300], value=120)
    if auto_refresh:
        st_autorefresh(interval=refresh_seconds * 1000, key="refresh")

    if st.button("🔁 Atualizar agora"):
        st.rerun()

    timeframe = st.selectbox("Timeframe:", ["1h", "4h", "1d"], index=2)

    # Janela inicial (e botões no gráfico também)
    janela = st.selectbox("Janela inicial:", ["1W", "1M", "3M", "6M", "ALL"], index=0)

    st.divider()
    st.subheader("🧼 Indicadores (premium)")
    show_sma = st.toggle("SMA20", value=True)
    show_bb = st.toggle("Bollinger Bands", value=True)
    show_rsi = st.toggle("RSI", value=False)
    show_macd = st.toggle("MACD", value=False)

    st.divider()
    st.subheader("🎛️ Aparência")
    clean_volume = st.toggle("Volume clean", value=True)
    volume_colored = st.toggle("Volume verde/vermelho", value=True)
    show_price_line = st.toggle("Linha do preço atual", value=True)
    show_signal_badge = st.toggle("Badge (Compra/Venda/Neutro)", value=True)

# =========================================================
# COINS
# =========================================================
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

# =========================================================
# DATA (CoinGecko)
# =========================================================
@st.cache_data(ttl=300)
def fetch_coingecko_market_chart(coin_id: str, days: int):
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
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    return df

def resample_to_ohlc(df_ticks: pd.DataFrame, tf: str) -> pd.DataFrame:
    df = df_ticks.copy().set_index("timestamp").sort_index()
    rule_map = {"1h": "1H", "4h": "4H", "1d": "1D"}
    rule = rule_map.get(tf, "1D")

    ohlc = df["price"].resample(rule).ohlc()
    vol = df["volume"].resample(rule).sum()

    out = ohlc.join(vol).dropna()
    out = out[out["close"] > 0]
    out = out.reset_index()
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

def compute_signal(df: pd.DataFrame):
    """
    Sinal simples e honesto:
    - Compra: RSI<30 e MACD cruzou pra cima
    - Venda: RSI>70 e MACD cruzou pra baixo
    - Neutro: caso contrário
    """
    if "RSI" not in df.columns or "MACD" not in df.columns or "MACD_signal" not in df.columns:
        return "NEUTRO", "📎 Ative RSI+MACD para sinal completo."

    if len(df) < 3:
        return "NEUTRO", "Sem dados suficientes."

    rsi = df["RSI"].iloc[-1]
    macd = df["MACD"].iloc[-1]
    sig = df["MACD_signal"].iloc[-1]
    macd_prev = df["MACD"].iloc[-2]
    sig_prev = df["MACD_signal"].iloc[-2]

    cross_up = (macd_prev <= sig_prev) and (macd > sig)
    cross_down = (macd_prev >= sig_prev) and (macd < sig)

    if rsi < 30 and cross_up:
        return "COMPRA", f"RSI {rsi:.1f} + MACD cruzou pra cima."
    if rsi > 70 and cross_down:
        return "VENDA", f"RSI {rsi:.1f} + MACD cruzou pra baixo."
    return "NEUTRO", f"RSI {rsi:.1f} | MACD {macd:.3f} vs Signal {sig:.3f}"

# =========================================================
# TABS
# =========================================================
tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])

# =========================================================
# MAIN LOOP
# =========================================================
for moeda in moedas:
    coin_id = coin_map[moeda]

    with st.expander(f"Detalhes de {moeda}", expanded=True):

        # === Melhor granularidade por timeframe (evita candle “traço”)
        days_map = {
            "1h": 7,     # CoinGecko é bem melhor até 7 dias em 1h
            "4h": 30,    # 4h fica ótimo com 30 dias
            "1d": 365    # 1 ano no diário
        }
        days = days_map.get(timeframe, 30)

        try:
            ticks = fetch_coingecko_market_chart(coin_id, days=days)
        except Exception:
            st.error(f"Falha ao buscar dados no CoinGecko para {moeda}.")
            continue

        df = resample_to_ohlc(ticks, timeframe)

        # Para sinal, precisamos das colunas
        df = add_indicators(df, show_sma, show_bb, show_rsi or show_signal_badge, show_macd or show_signal_badge)

        if df.empty:
            st.error("Sem dados suficientes.")
            continue

        # =============================
        # KPIs (topo)
        # =============================
        ultimo_preco = df["close"].iloc[-1]
        preco_inicial = df["close"].iloc[0]
        variacao_pct = ((ultimo_preco - preco_inicial) / preco_inicial) * 100

        c1, c2, c3 = st.columns([1.4, 1, 1])
        with c1:
            st.metric(f"💰 Preço atual {moeda}", value=price_fmt(moeda, ultimo_preco), delta=f"{variacao_pct:.2f}%")
        with c2:
            st.metric("📈 Máx (período)", value=price_fmt(moeda, df["high"].max()))
        with c3:
            st.metric("📉 Mín (período)", value=price_fmt(moeda, df["low"].min()))

        # =============================
        # Badge de sinal (Compra/Venda/Neutro)
        # =============================
        if show_signal_badge:
            signal, reason = compute_signal(df)
            if signal == "COMPRA":
                st.success(f"🟢 SINAL: COMPRA — {reason}")
            elif signal == "VENDA":
                st.error(f"🔴 SINAL: VENDA — {reason}")
            else:
                st.info(f"⚪ SINAL: NEUTRO — {reason}")

        # =============================
        # TAB: GRÁFICO PRINCIPAL (Premium)
        # =============================
        with tab_chart:
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.84, 0.16],
                vertical_spacing=0.02,
                row_titles=["Preço", "Volume"]
            )

            # Candles Premium (preenchido)
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

            # Linha do preço atual
            if show_price_line:
                fig.add_hline(
                    y=ultimo_preco,
                    line_dash="dot",
                    opacity=0.5,
                    row=1, col=1
                )

            # SMA / BB (sem legenda gigante)
            if show_sma and "SMA20" in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["timestamp"], y=df["SMA20"],
                    mode="lines",
                    name="SMA20",
                    showlegend=False
                ), row=1, col=1)

            if show_bb and "BB_upper" in df.columns:
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_upper"], mode="lines", name="BB Upper", showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_middle"], mode="lines", name="BB Mid", showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df["timestamp"], y=df["BB_lower"], mode="lines", name="BB Low", showlegend=False), row=1, col=1)

            # Volume (clean e opcionalmente colorido)
            if volume_colored:
                vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df["open"], df["close"])]
            else:
                vol_colors = None

            fig.add_trace(go.Bar(
                x=df["timestamp"],
                y=df["volume"],
                marker_color=vol_colors,
                opacity=0.22 if clean_volume else 0.40,
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
                height=740,
                hovermode="x unified",
                margin=dict(l=10, r=10, t=10, b=10)
            )
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
            fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)")

            st.plotly_chart(fig, use_container_width=True)

        # =============================
        # TAB: RSI
        # =============================
        with tab_rsi:
            if not show_rsi or "RSI" not in df.columns:
                st.info("Ative o RSI no menu lateral para ver aqui.")
            else:
                fig_rsi = go.Figure()
                fig_rsi.add_trace(go.Scatter(x=df["timestamp"], y=df["RSI"], mode="lines", name="RSI"))
                fig_rsi.add_hline(y=70, line_dash="dot", opacity=0.6)
                fig_rsi.add_hline(y=30, line_dash="dot", opacity=0.6)
                start, end = initial_range(df, janela)
                fig_rsi.update_xaxes(range=[start, end], rangeslider=dict(visible=True, thickness=0.06))
                add_range_buttons(fig_rsi)
                fig_rsi.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_rsi, use_container_width=True)

        # =============================
        # TAB: MACD
        # =============================
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

        st.caption("Dica: use o slider do gráfico pra arrastar e navegar no tempo.")

st.info("✅ Premium: candles corretos por timeframe + volume verde/vermelho + linha do preço + badge de sinal.")



