import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import requests
import datetime

# ==============================
# PAGE + THEME
# ==============================
st.set_page_config(layout="wide", page_title="Análise Cripto PRO+ — Premium")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.1rem;}
      div[data-testid="stSidebar"] {border-right: 1px solid rgba(255,255,255,0.06);}
      .stMetric {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        padding: 14px;
        border-radius: 14px;
      }
      .small-note {opacity: .75; font-size: 0.9rem;}
      .badge {
        display:inline-block; padding:6px 10px; border-radius:999px;
        border:1px solid rgba(255,255,255,0.12);
        background: rgba(255,255,255,0.04);
        font-size: 0.9rem; opacity: 0.95;
      }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🚀 Análise Cripto PRO+ — Premium")

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
# SIDEBAR (CONTROLS)
# ==============================
with st.sidebar:
    st.header("⚙️ Controles")

    auto_refresh = st.toggle("🔄 Atualização automática", value=False)
    refresh_seconds = st.select_slider("Intervalo (segundos)", options=[30, 60, 120, 180, 300], value=60)
    if auto_refresh:
        st_autorefresh(interval=refresh_seconds * 1000, key="refresh")

    if st.button("🔁 Atualizar agora"):
        st.rerun()

    st.divider()

    timeframe = st.selectbox("Timeframe:", ["1h", "4h", "1d"], index=0)

    st.divider()
    st.subheader("📌 Indicadores (premium)")
    show_ma = st.toggle("MA 7/25/99 (igual Binance)", value=True)
    show_bb = st.toggle("Bollinger Bands (20, 2)", value=False)
    show_rsi = st.toggle("RSI (14)", value=True)
    show_macd = st.toggle("MACD (12/26/9)", value=True)

    st.divider()
    st.subheader("📊 Volume")
    clean_volume = st.toggle("Volume clean (mais discreto)", value=True)
    volume_colored = st.toggle("Volume verde/vermelho", value=True)
    show_vol_ma = st.toggle("Média do volume (linha)", value=True)
    vol_ma_period = st.slider("Período média do volume", 5, 50, 20, 1)

    st.divider()
    st.subheader("🎛️ Aparência")
    show_price_line = st.toggle("Linha do preço atual", value=True)
    show_crosshair = st.toggle("Crosshair (spikes)", value=True)
    chart_height = st.slider("Altura do gráfico", 620, 980, 840, 10)

# ==============================
# HELPERS
# ==============================
def fmt_price(moeda: str, p: float) -> str:
    return f"${p:,.6f}" if moeda in meme_coins else f"${p:,.2f}"

def add_range_buttons(fig):
    fig.update_xaxes(
        rangeselector=dict(
            buttons=list([
                dict(count=12, label="12H", step="hour", stepmode="backward"),
                dict(count=1, label="1D", step="day", stepmode="backward"),
                dict(count=2, label="2D", step="day", stepmode="backward"),
                dict(count=4, label="4D", step="day", stepmode="backward"),
                dict(count=7, label="1W", step="day", stepmode="backward"),
                dict(step="all", label="ALL"),
            ])
        )
    )

def apply_crosshair(fig):
    fig.update_layout(hovermode="x unified", spikedistance=-1)
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikecolor="rgba(255,255,255,0.35)",
    )
    fig.update_yaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikecolor="rgba(255,255,255,0.25)",
    )

def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    df = df[cols].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    df["volume"] = df["volume"].fillna(0)
    return df

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()

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

    if show_vol_ma:
        d["VOL_MA"] = d["volume"].rolling(vol_ma_period).mean()

    return d

# ==============================
# DATA (COINGECKO ONLY — STABLE)
# ==============================
@st.cache_data(ttl=180)
def fetch_coingecko_ohlc(coin_id: str, days: int):
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    headers = {"User-Agent": "Mozilla/5.0 (StreamlitApp)"}
    r = requests.get(url, params=params, headers=headers, timeout=25)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df["volume"] = 0.0
    return normalize_ohlcv(df)

@st.cache_data(ttl=180)
def fetch_coingecko_volume(coin_id: str, days: int):
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

@st.cache_data(ttl=180)
def build_dataset_cloud(coin_id: str, timeframe: str):
    """
    Regras de exibição (você pediu):
      - 1h -> 2 dias
      - 4h -> 4 dias
      - 1d -> 7 dias

    Regras de coleta no CoinGecko:
      - days=1/2 -> intraday (30m)
      - days=3..30 -> 4h
      - days>30 -> 4d (não precisamos aqui)
    """
    if timeframe == "1h":
        days_fetch = 2      # intraday (30m)
        window_days = 2
        tol = pd.Timedelta("60min")
    elif timeframe == "4h":
        days_fetch = 7      # pega intraday suficiente e já vem 4h
        window_days = 4
        tol = pd.Timedelta("3h")
    else:  # "1d"
        days_fetch = 30     # garante daily bom
        window_days = 7
        tol = pd.Timedelta("12h")

    ohlc = fetch_coingecko_ohlc(coin_id, days_fetch)
    vol = fetch_coingecko_volume(coin_id, days_fetch)

    df = pd.merge_asof(
        ohlc.sort_values("timestamp"),
        vol.sort_values("timestamp"),
        on="timestamp",
        direction="nearest",
        tolerance=tol,
    )

    df["volume"] = df["volume"].fillna(0)
    df = normalize_ohlcv(df)

    # aplica janela final fixa (2d / 4d / 7d)
    end = df["timestamp"].max()
    start = end - pd.Timedelta(days=window_days)
    df_view = df[df["timestamp"] >= start].copy()

    return df_view, f"CoinGecko (Cloud) — janela {window_days}d"

# ==============================
# TABS
# ==============================
tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])

# ==============================
# MAIN LOOP
# ==============================
for moeda in moedas:
    coin_id = coin_map[moeda]

    with st.expander(f"Detalhes de {moeda}", expanded=True):
        if moeda in meme_coins:
            st.warning("🧪 Meme coin — alta volatilidade")

        try:
            df_view, source = build_dataset_cloud(coin_id, timeframe)
        except Exception as e:
            st.error(f"Não foi possível obter dados para {moeda}.")
            st.caption(f"Detalhe técnico: {type(e).__name__}")
            continue

        if df_view.empty or len(df_view) < 10:
            st.warning("Poucos dados para renderizar. Tente outro timeframe.")
            continue

        df_view = add_indicators(df_view)

        ultimo = float(df_view["close"].iloc[-1])
        first = float(df_view["close"].iloc[0])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

        st.caption(f"📡 Fonte: **{source}**")
        st.markdown(f"<span class='badge'>Timeframe: <b>{timeframe}</b></span>", unsafe_allow_html=True)

        k1, k2, k3 = st.columns([1.6, 1, 1])
        k1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo), f"{var_pct:.2f}%")
        k2.metric("📈 Máxima (janela)", fmt_price(moeda, float(df_view["high"].max())))
        k3.metric("📉 Mínima (janela)", fmt_price(moeda, float(df_view["low"].min())))

        # ======================
        # TAB: CHART
        # ======================
        with tab_chart:
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.82, 0.18],
                vertical_spacing=0.02,
                row_titles=["Preço", "Volume"]
            )

            fig.add_trace(
                go.Candlestick(
                    x=df_view["timestamp"],
                    open=df_view["open"], high=df_view["high"], low=df_view["low"], close=df_view["close"],
                    increasing_line_color="#00C896",
                    decreasing_line_color="#FF4B4B",
                    increasing_fillcolor="rgba(0,200,150,0.85)",
                    decreasing_fillcolor="rgba(255,75,75,0.85)",
                    whiskerwidth=0.7,
                    name="Preço",
                    showlegend=False,
                ),
                row=1, col=1
            )

            if show_price_line:
                fig.add_hline(y=ultimo, line_dash="dot", opacity=0.55, row=1, col=1)

            # MA (7/25/99)
            if show_ma and "MA7" in df_view.columns:
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA7"], mode="lines", opacity=0.85, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA25"], mode="lines", opacity=0.85, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA99"], mode="lines", opacity=0.85, showlegend=False), row=1, col=1)

            # BB
            if show_bb and "BB_UP" in df_view.columns:
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["BB_UP"], mode="lines", opacity=0.55, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["BB_MID"], mode="lines", opacity=0.55, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["BB_LOW"], mode="lines", opacity=0.55, showlegend=False), row=1, col=1)

            # Volume
            if volume_colored:
                vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df_view["open"], df_view["close"])]
            else:
                vol_colors = "rgba(255,255,255,0.25)"

            fig.add_trace(
                go.Bar(
                    x=df_view["timestamp"],
                    y=df_view["volume"],
                    marker_color=vol_colors,
                    opacity=0.20 if clean_volume else 0.42,
                    showlegend=False
                ),
                row=2, col=1
            )

            if show_vol_ma and "VOL_MA" in df_view.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_view["timestamp"], y=df_view["VOL_MA"],
                        mode="lines", opacity=0.70, showlegend=False
                    ),
                    row=2, col=1
                )

            # slider + botões
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
            add_range_buttons(fig)

            # layout premium
            fig.update_layout(
                template="plotly_dark",
                height=chart_height,
                margin=dict(l=10, r=10, t=10, b=10),
                dragmode="pan",
            )
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
            fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)")

            if show_crosshair:
                apply_crosshair(fig)
            else:
                fig.update_layout(hovermode="x unified")

            st.plotly_chart(
                fig, use_container_width=True,
                config={"scrollZoom": True, "displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
            )

            st.markdown("<div class='small-note'>Dica: slider inferior para arrastar no tempo. Scroll do mouse = zoom.</div>", unsafe_allow_html=True)

        # ======================
        # TAB: RSI
        # ======================
        with tab_rsi:
            if not show_rsi or "RSI" not in df_view.columns:
                st.info("Ative RSI no menu lateral.")
            else:
                fr = go.Figure()
                fr.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["RSI"], mode="lines", name="RSI"))
                fr.add_hline(y=70, line_dash="dot", opacity=0.55)
                fr.add_hline(y=30, line_dash="dot", opacity=0.55)
                fr.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                fr.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                add_range_buttons(fr)
                if show_crosshair:
                    apply_crosshair(fr)
                st.plotly_chart(fr, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

        # ======================
        # TAB: MACD
        # ======================
        with tab_macd:
            if not show_macd or "MACD" not in df_view.columns:
                st.info("Ative MACD no menu lateral.")
            else:
                fm = go.Figure()
                fm.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MACD"], mode="lines", name="MACD"))
                fm.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["SIGNAL"], mode="lines", name="Signal"))
                if "HIST" in df_view.columns:
                    fm.add_trace(go.Bar(x=df_view["timestamp"], y=df_view["HIST"], name="Hist", opacity=0.25))
                fm.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                fm.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                add_range_buttons(fm)
                if show_crosshair:
                    apply_crosshair(fm)
                st.plotly_chart(fm, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

st.info("✅ Premium ativo: MA 7/25/99 + Volume clean + Média do Volume + Crosshair + Zoom + Arrastar + Janelas fixas por timeframe (2d/4d/7d) — estável no Streamlit Cloud.")


