import time
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import requests

# ==============================
# PAGE
# ==============================
st.set_page_config(layout="wide", page_title="Análise Cripto PRO+ — Premium (Hybrid)")
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
        margin-right: 8px;
      }
      code {font-size: 0.9rem;}
    </style>
    """,
    unsafe_allow_html=True
)
st.title("🚀 Análise Cripto PRO+ — Premium (Hybrid: Bybit → Binance → CoinGecko)")

# ==============================
# COINS
# ==============================
# (IDs do CoinGecko ajudam, mas agora temos resolver automático também)
coin_map = {
    "BTC/USDT": "bitcoin",
    "ETH/USDT": "ethereum",
    "ADA/USDT": "cardano",
    "DOGE/USDT": "dogecoin",
    "PEPE/USDT": "pepe",
    # TURBO é instável no CoinGecko dependendo do listing; resolver vai ajudar se esse ID falhar
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
# SIDEBAR
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

    st.divider()
    debug_mode = st.toggle("🧪 Debug (mostrar erros das fontes)", value=True)

# ==============================
# HELPERS
# ==============================
def fmt_price(moeda: str, p: float) -> str:
    return f"${p:,.6f}" if moeda in meme_coins else f"${p:,.2f}"

def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    df["volume"] = df["volume"].fillna(0.0)
    return df

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
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikecolor="rgba(255,255,255,0.35)",
    )
    fig.update_yaxes(
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikecolor="rgba(255,255,255,0.25)",
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

    if show_vol_ma:
        d["VOL_MA"] = d["volume"].rolling(vol_ma_period).mean()

    return d

def window_days_for_timeframe(tf: str) -> int:
    return {"1h": 2, "4h": 4, "1d": 7}.get(tf, 7)

def limit_for_timeframe(tf: str) -> int:
    return {"1h": 600, "4h": 400, "1d": 300}.get(tf, 300)

def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "")

def apply_time_window(df: pd.DataFrame, window_days: int) -> pd.DataFrame:
    if df.empty:
        return df
    end = df["timestamp"].max()
    start = end - pd.Timedelta(days=window_days)
    return df[df["timestamp"] >= start].copy()

# ==============================
# NETWORK (RETRY + BETTER ERRORS)
# ==============================
def request_json(url: str, params: dict, attempts: int = 3, base_sleep: float = 0.8):
    headers = {
        "User-Agent": "Mozilla/5.0 (StreamlitApp)",
        "Accept": "application/json,text/plain,*/*",
    }
    last_err = None
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=25)
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                # retry rápido
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:250]}")
                time.sleep(base_sleep * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(base_sleep * (i + 1))
    raise last_err

# ==============================
# DATA SOURCES
# ==============================
@st.cache_data(ttl=180)
def fetch_bybit_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    interval_map = {"1h": "60", "4h": "240", "1d": "D"}
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "spot",
        "symbol": symbol,
        "interval": interval_map[timeframe],
        "limit": str(limit),
    }
    j = request_json(url, params)
    if str(j.get("retCode")) != "0":
        raise RuntimeError(f"Bybit retCode={j.get('retCode')} msg={j.get('retMsg')}")
    rows = j["result"]["list"]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)

@st.cache_data(ttl=180)
def fetch_binance_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    interval_map = {"1h": "1h", "4h": "4h", "1d": "1d"}
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval_map[timeframe], "limit": str(limit)}
    j = request_json(url, params)
    df = pd.DataFrame(j, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore"
    ])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)

@st.cache_data(ttl=600)
def coingecko_resolve_id(query: str) -> str:
    # resolve por search quando o id padrão falhar
    url = "https://api.coingecko.com/api/v3/search"
    j = request_json(url, {"query": query}, attempts=2, base_sleep=0.6)
    coins = j.get("coins", [])
    if not coins:
        raise RuntimeError("CoinGecko search vazio")
    # tenta pegar o primeiro mais relevante
    return coins[0]["id"]

@st.cache_data(ttl=300)
def fetch_coingecko_market_chart(coin_id: str, days: int) -> pd.DataFrame:
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    j = request_json(url, {"vs_currency": "usd", "days": days})
    prices = pd.DataFrame(j["prices"], columns=["timestamp", "close"])
    prices["timestamp"] = pd.to_datetime(pd.to_numeric(prices["timestamp"]), unit="ms", utc=True)

    volumes = pd.DataFrame(j["total_volumes"], columns=["timestamp", "volume"])
    volumes["timestamp"] = pd.to_datetime(pd.to_numeric(volumes["timestamp"]), unit="ms", utc=True)

    df = pd.merge_asof(
        prices.sort_values("timestamp"),
        volumes.sort_values("timestamp"),
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("30min")
    )
    df["volume"] = df["volume"].fillna(0.0)

    # CoinGecko não entrega OHLC completo no market_chart -> simulamos OHLC = close
    df["open"] = df["close"]
    df["high"] = df["close"]
    df["low"] = df["close"]
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)

def build_dataset_hybrid(moeda: str, timeframe: str):
    sym = symbol_compact(moeda)     # BTCUSDT
    base = moeda.split("/")[0]      # BTC
    limit = limit_for_timeframe(timeframe)
    window_days = window_days_for_timeframe(timeframe)

    errors = {}

    # 1) Bybit
    try:
        df = fetch_bybit_ohlcv(sym, timeframe, limit)
        return df, "Bybit (spot)", window_days, errors
    except Exception as e:
        errors["Bybit"] = str(e)[:220]

    # 2) Binance
    try:
        df = fetch_binance_ohlcv(sym, timeframe, limit)
        return df, "Binance (spot)", window_days, errors
    except Exception as e:
        errors["Binance"] = str(e)[:220]

    # 3) CoinGecko
    try:
        # para 1h/4h/1d, pegamos poucos dias pra ficar leve
        days_fetch = 2 if timeframe == "1h" else 7 if timeframe == "4h" else 30

        cg_id = coin_map.get(moeda, None)
        if not cg_id:
            cg_id = coingecko_resolve_id(base)

        try:
            df = fetch_coingecko_market_chart(cg_id, days_fetch)
        except Exception:
            # se o id fixo falhar, tenta resolver por search
            cg_id = coingecko_resolve_id(base)
            df = fetch_coingecko_market_chart(cg_id, days_fetch)

        return df, "CoinGecko (fallback)", window_days, errors
    except Exception as e:
        errors["CoinGecko"] = str(e)[:220]

    raise RuntimeError("Falha geral de dados"), errors

# ==============================
# TABS
# ==============================
tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])

# ==============================
# MAIN
# ==============================
for moeda in moedas:
    with st.expander(f"Detalhes de {moeda}", expanded=True):
        if moeda in meme_coins:
            st.warning("🧪 Meme coin — alta volatilidade")

        try:
            df_full, source, window_days, errors = build_dataset_hybrid(moeda, timeframe)
        except Exception as e:
            # e pode trazer errors no segundo elemento (raise acima)
            err_map = None
            if isinstance(e.args, tuple) and len(e.args) >= 2 and isinstance(e.args[1], dict):
                err_map = e.args[1]

            st.error(f"Não foi possível obter dados para {moeda}.")
            st.caption(f"Detalhe técnico: {type(e).__name__}")

            if debug_mode and err_map:
                st.markdown("**Erros por fonte:**")
                for k, v in err_map.items():
                    st.code(f"{k}: {v}", language="text")
            continue

        df_view = apply_time_window(df_full, window_days)
        if df_view.empty or len(df_view) < 10:
            st.warning("Poucos dados para renderizar. Tente outro timeframe.")
            st.caption(f"Fonte: {source}")
            continue

        df_view = add_indicators(df_view)

        ultimo = float(df_view["close"].iloc[-1])
        first = float(df_view["close"].iloc[0])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

        st.caption(f"📡 Fonte: **{source}**")
        st.markdown(
            f"<span class='badge'>Timeframe: <b>{timeframe}</b></span>"
            f"<span class='badge'>Janela: <b>{window_days} dias</b></span>",
            unsafe_allow_html=True
        )

        k1, k2, k3 = st.columns([1.6, 1, 1])
        k1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo), f"{var_pct:.2f}%")
        k2.metric("📈 Máxima (janela)", fmt_price(moeda, float(df_view["high"].max())))
        k3.metric("📉 Mínima (janela)", fmt_price(moeda, float(df_view["low"].min())))

        # ======================
        # CHART
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
                    showlegend=False,
                    name="Preço",
                ),
                row=1, col=1
            )

            if show_price_line:
                fig.add_hline(y=ultimo, line_dash="dot", opacity=0.55, row=1, col=1)

            if show_ma and "MA7" in df_view.columns:
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA7"], mode="lines", opacity=0.85, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA25"], mode="lines", opacity=0.85, showlegend=False), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA99"], mode="lines", opacity=0.85, showlegend=False), row=1, col=1)

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
                    go.Scatter(x=df_view["timestamp"], y=df_view["VOL_MA"], mode="lines", opacity=0.70, showlegend=False),
                    row=2, col=1
                )

            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
            add_range_buttons(fig)

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

        # RSI
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

        # MACD
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

st.info("✅ Modo híbrido ativo: Bybit → Binance → CoinGecko (fallback). Janela automática: 1h=2d, 4h=4d, 1d=7d.")



