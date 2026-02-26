import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import requests
import datetime

# opcional (mas recomendado)
try:
    import ccxt
except Exception:
    ccxt = None


# ==============================
# PAGE + THEME
# ==============================
st.set_page_config(layout="wide", page_title="Análise Cripto PRO+ — Premium")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.1rem;}
      div[data-testid="stSidebar"] {border-right: 1px solid rgba(255,255,255,0.06);}
      .stMetric {background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
                padding: 14px; border-radius: 14px;}
      .small-note {opacity: .75; font-size: 0.9rem;}
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🚀 Análise Cripto PRO+ — Premium (Binance Style)")


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

    window_mode = st.radio("Modo da janela:", ["Presets", "Manual (datas)"], horizontal=True, index=0)
    janela = st.selectbox("Janela (preset):", ["1W", "1M", "3M", "6M", "ALL"], index=0)

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
    chart_height = st.slider("Altura do gráfico", 600, 950, 820, 10)

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


def apply_crosshair(fig):
    # Crosshair estilo TradingView: spikes no eixo X e Y
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

    if show_vol_ma and "volume" in d.columns:
        d["VOL_MA"] = d["volume"].rolling(vol_ma_period).mean()

    return d


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    # garante colunas e ordenação
    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    df = df[cols].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    df["volume"] = df["volume"].fillna(0)
    return df


# ==============================
# DATA (HYBRID): CCXT -> COINGECKO
# ==============================
@st.cache_data(ttl=120)
def fetch_ccxt_ohlcv(exchange_id: str, symbol: str, timeframe: str, limit: int = 500):
    if ccxt is None:
        raise RuntimeError("ccxt não disponível no ambiente.")

    ex_class = getattr(ccxt, exchange_id)
    ex = ex_class({"enableRateLimit": True})
    # alguns ambientes precisam de user-agent
    ex.headers = {"User-Agent": "Mozilla/5.0 (StreamlitApp)"}

    ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return normalize_ohlcv(df)


@st.cache_data(ttl=300)
def fetch_coingecko_ohlc(coin_id: str, days: int):
    # OHLC real (granularidade automática)
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


@st.cache_data(ttl=300)
def fetch_coingecko_volume(coin_id: str, days: int):
    # volume via market_chart
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


def build_dataset(symbol: str, coin_id: str, timeframe: str):
    """
    Ordem:
    1) tenta CCXT Bybit
    2) tenta CCXT OKX
    3) cai pro CoinGecko (estável no cloud)

    CoinGecko OHLC:
      - days 1/2 -> 30m
      - 3..30  -> 4h
      - >30    -> 4d
    """
    # janela de dados maior do que a janela exibida (pra indicadores ficarem melhores)
    if timeframe == "1h":
        limit = 800
        days_fallback = 2  # 30m intraday
    elif timeframe == "4h":
        limit = 800
        days_fallback = 30  # 4h candles
    else:
        limit = 800
        days_fallback = 365  # daily-ish

    # CCXT FIRST (pra 1h real)
    if ccxt is not None:
        for ex_id in ["bybit", "okx"]:
            try:
                df = fetch_ccxt_ohlcv(ex_id, symbol, timeframe, limit=limit)
                return df, f"{ex_id.upper()} (ccxt)"
            except Exception:
                pass

    # FALLBACK CoinGecko
    ohlc = fetch_coingecko_ohlc(coin_id, days=days_fallback)
    vol = fetch_coingecko_volume(coin_id, days=days_fallback)

    # junta volume no candle mais próximo
    tol = pd.Timedelta("45min") if timeframe == "1h" else (pd.Timedelta("3h") if timeframe == "4h" else pd.Timedelta("12h"))
    df = pd.merge_asof(
        ohlc.sort_values("timestamp"),
        vol.sort_values("timestamp"),
        on="timestamp",
        direction="nearest",
        tolerance=tol,
        suffixes=("", "_v"),
    )
    if "volume_v" in df.columns:
        df["volume"] = df["volume_v"].fillna(df["volume"])
        df = df.drop(columns=["volume_v"])
    df["volume"] = df["volume"].fillna(0)
    return normalize_ohlcv(df), "CoinGecko (fallback)"


# ==============================
# MANUAL WINDOW (DATES)
# ==============================
manual_start, manual_end = None, None
if window_mode.startswith("Manual"):
    c1, c2 = st.columns(2)
    with c1:
        manual_start = st.date_input("Início", value=(datetime.date.today() - datetime.timedelta(days=7)))
    with c2:
        manual_end = st.date_input("Fim", value=datetime.date.today())


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
            df, source = build_dataset(moeda, coin_id, timeframe)
        except Exception:
            st.error(f"Não foi possível obter dados para {moeda}.")
            continue

        if df.empty:
            st.error("Sem dados suficientes.")
            continue

        # aviso honesto se caiu em CoinGecko (principalmente no 1h)
        if "CoinGecko" in source and timeframe == "1h":
            st.info("ℹ️ Você está em fallback CoinGecko: intraday é **30m** e só cobre **1–2 dias**. Para semana inteira, use **4h**.")

        df = add_indicators(df)

        # aplicar janela (preset/manual) só na visualização (não no cálculo dos indicadores)
        df_view = df.copy()
        if window_mode.startswith("Manual") and manual_start and manual_end:
            start_dt = pd.to_datetime(manual_start).tz_localize("UTC")
            end_dt = pd.to_datetime(manual_end + datetime.timedelta(days=1)).tz_localize("UTC")
            df_view = df_view[(df_view["timestamp"] >= start_dt) & (df_view["timestamp"] < end_dt)]
        else:
            start, end = initial_range(df_view, janela)
            df_view = df_view[(df_view["timestamp"] >= start) & (df_view["timestamp"] <= end)]

        if df_view.empty:
            st.warning("A janela selecionada não tem dados suficientes. Tente aumentar a janela.")
            continue

        # KPIs (usando a janela exibida)
        ultimo = float(df_view["close"].iloc[-1])
        first = float(df_view["close"].iloc[0])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

        st.caption(f"📡 Fonte: **{source}**")

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

            # Candles (preenchidos, mais “fortes”)
            fig.add_trace(
                go.Candlestick(
                    x=df_view["timestamp"],
                    open=df_view["open"], high=df_view["high"], low=df_view["low"], close=df_view["close"],
                    increasing_line_color="#00C896",
                    decreasing_line_color="#FF4B4B",
                    increasing_fillcolor="rgba(0,200,150,0.85)",
                    decreasing_fillcolor="rgba(255,75,75,0.85)",
                    whiskerwidth=0.6,
                    name="Preço",
                    showlegend=False,
                ),
                row=1, col=1
            )

            # Linha do preço atual
            if show_price_line:
                fig.add_hline(y=ultimo, line_dash="dot", opacity=0.55, row=1, col=1)

            # MAs (7/25/99)
            if show_ma and "MA7" in df_view.columns:
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA7"], mode="lines", name="MA7", opacity=0.9, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA25"], mode="lines", name="MA25", opacity=0.9, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA99"], mode="lines", name="MA99", opacity=0.9, showlegend=False), row=1, col=1)

            # Bollinger
            if show_bb and "BB_UP" in df_view.columns:
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["BB_UP"], mode="lines", name="BB Up", opacity=0.65, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["BB_MID"], mode="lines", name="BB Mid", opacity=0.65, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["BB_LOW"], mode="lines", name="BB Low", opacity=0.65, showlegend=False), row=1, col=1)

            # Volume (clean)
            if volume_colored:
                vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df_view["open"], df_view["close"])]
            else:
                vol_colors = "rgba(255,255,255,0.25)"

            fig.add_trace(
                go.Bar(
                    x=df_view["timestamp"],
                    y=df_view["volume"],
                    marker_color=vol_colors,
                    opacity=0.22 if clean_volume else 0.45,
                    name="Volume",
                    showlegend=False
                ),
                row=2, col=1
            )

            # média do volume (linha)
            if show_vol_ma and "VOL_MA" in df_view.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_view["timestamp"], y=df_view["VOL_MA"],
                        mode="lines", name=f"Vol MA({vol_ma_period})",
                        opacity=0.7,
                        showlegend=False
                    ),
                    row=2, col=1
                )

            # rangeslider (arrastar no tempo) + botões
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
            add_range_buttons(fig)

            # grid e layout premium
            fig.update_layout(
                template="plotly_dark",
                height=chart_height,
                margin=dict(l=10, r=10, t=10, b=10),
                dragmode="pan",  # arrastar padrão (zoom ainda funciona com scroll)
            )
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
            fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)")

            if show_crosshair:
                apply_crosshair(fig)
            else:
                fig.update_layout(hovermode="x unified")

            # Render
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={
                    "scrollZoom": True,     # zoom com scroll
                    "displaylogo": False,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"]
                },
            )

            st.markdown("<div class='small-note'>Dica: use o slider inferior para arrastar e navegar no tempo. Scroll do mouse = zoom.</div>", unsafe_allow_html=True)

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

st.info("✅ Premium ativo: MA 7/25/99 + Volume clean + Média do Volume + Crosshair + Zoom + Arrastar + Janela Preset/Manual + Hybrid data (ccxt→CoinGecko).")
