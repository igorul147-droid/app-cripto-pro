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
st.set_page_config(layout="wide", page_title="Análise Cripto PRO+ - Premium")
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
TZ_LOCAL = "America/Sao_Paulo"

def fmt_price(moeda: str, p: float) -> str:
    return f"${p:,.6f}" if moeda in meme_coins else f"${p:,.2f}"

def timeframe_freq(tf: str) -> str:
    return {"1h": "1H", "4h": "4H", "1d": "1D"}.get(tf, "1D")

def window_days_for_timeframe(tf: str) -> int:
    # regra do Igor
    return {"1h": 2, "4h": 4, "1d": 7}.get(tf, 7)

def limit_for_timeframe(tf: str) -> int:
    # limites seguros pra APIs
    return {"1h": 800, "4h": 600, "1d": 400}.get(tf, 400)

def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "")

def apply_time_window(df: pd.DataFrame, window_days: int) -> pd.DataFrame:
    if df.empty:
        return df
    end = df["timestamp"].max()
    start = end - pd.Timedelta(days=window_days)
    return df[df["timestamp"] >= start].copy()

def ensure_timestamp_utc(series: pd.Series) -> pd.Series:
    # garante datetime UTC tz-aware
    s = series
    if not pd.api.types.is_datetime64_any_dtype(s):
        s = pd.to_datetime(s, utc=True, errors="coerce")
    else:
        # se veio tz-naive, assume UTC
        if getattr(s.dt, "tz", None) is None:
            s = s.dt.tz_localize("UTC")
        else:
            s = s.dt.tz_convert("UTC")
    return s

def to_local_naive(df: pd.DataFrame) -> pd.DataFrame:
    # converte pra horário do Brasil e deixa "naive" pro Plotly renderizar bonito
    d = df.copy()
    d["timestamp"] = ensure_timestamp_utc(d["timestamp"]).dt.tz_convert(TZ_LOCAL).dt.tz_localize(None)
    return d

def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["timestamp"] = ensure_timestamp_utc(d["timestamp"])
    d = d.sort_values("timestamp").reset_index(drop=True)
    for c in ["open", "high", "low", "close", "volume"]:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if "volume" not in d.columns:
        d["volume"] = 0.0
    d["volume"] = d["volume"].fillna(0.0)
    # importante: deixa em UTC aqui (cálculos), converte pra local só antes do plot
    return d

def resample_to_ohlcv(df_close_vol: pd.DataFrame, tf: str) -> pd.DataFrame:
    """
    df_close_vol: colunas timestamp(UTC), close, volume
    resample em OHLCV real (isso resolve os candles 'tracinhos' do CoinGecko)
    """
    d = df_close_vol.copy()
    d["timestamp"] = ensure_timestamp_utc(d["timestamp"])
    d = d.sort_values("timestamp").dropna(subset=["close"]).reset_index(drop=True)
    d = d.set_index("timestamp")

    freq = timeframe_freq(tf)

    ohlc = d["close"].resample(freq).ohlc()
    vol = d["volume"].resample(freq).sum().rename("volume")

    out = pd.concat([ohlc, vol], axis=1).dropna(subset=["open", "high", "low", "close"])
    out = out.reset_index()
    out.columns = ["timestamp", "open", "high", "low", "close", "volume"]
    return normalize_ohlcv(out)

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

# ==============================
# NETWORK (RETRY)
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
            if r.status_code in (418, 429) or 500 <= r.status_code <= 599:
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
    # Bybit v5: [startTime, open, high, low, close, volume, turnover]
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
    url = "https://api.coingecko.com/api/v3/search"
    j = request_json(url, {"query": query}, attempts=2, base_sleep=0.6)
    coins = j.get("coins", [])
    if not coins:
        raise RuntimeError("CoinGecko search vazio")
    return coins[0]["id"]

@st.cache_data(ttl=300)
def fetch_coingecko_prices_and_volumes(coin_id: str, days: int) -> pd.DataFrame:
    """
    Puxa close + volume no CoinGecko e devolve timestamp(UTC), close, volume.
    Depois nós resampleamos em OHLCV real pro timeframe desejado.
    """
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
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df

def build_dataset_hybrid(moeda: str, timeframe: str):
    sym = symbol_compact(moeda)   # BTCUSDT
    base = moeda.split("/")[0]    # BTC
    limit = limit_for_timeframe(timeframe)
    window_days = window_days_for_timeframe(timeframe)

    errors = {}

    # 1) Bybit
    try:
        df = fetch_bybit_ohlcv(sym, timeframe, limit)
        return df, "Bybit (spot)", window_days, errors
    except Exception as e:
        errors["Bybit"] = str(e)[:260]

    # 2) Binance
    try:
        df = fetch_binance_ohlcv(sym, timeframe, limit)
        return df, "Binance (spot)", window_days, errors
    except Exception as e:
        errors["Binance"] = str(e)[:260]

    # 3) CoinGecko (fallback com resample)
    try:
        # dias "grossos" pra garantir janela + resample
        days_fetch = 5 if timeframe == "1h" else 12 if timeframe == "4h" else 30

        cg_id = coin_map.get(moeda)
        if not cg_id:
            cg_id = coingecko_resolve_id(base)

        try:
            raw = fetch_coingecko_prices_and_volumes(cg_id, days_fetch)
        except Exception:
            cg_id = coingecko_resolve_id(base)
            raw = fetch_coingecko_prices_and_volumes(cg_id, days_fetch)

        df = resample_to_ohlcv(raw, timeframe)
        return df, "CoinGecko (fallback)", window_days, errors
    except Exception as e:
        errors["CoinGecko"] = str(e)[:260]

    raise RuntimeError("Falha geral de dados", errors)

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
            df_full_utc, source, window_days, errors = build_dataset_hybrid(moeda, timeframe)
        except Exception as e:
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

        # janela fixa (2d/4d/7d)
        df_view_utc = apply_time_window(df_full_utc, window_days)
        if df_view_utc.empty or len(df_view_utc) < 10:
            st.warning("Poucos dados para renderizar. Tente outro timeframe.")
            st.caption(f"Fonte: {source}")
            continue

        # indicadores (em UTC)
        df_view_utc = add_indicators(df_view_utc)

        # converte pra Brasil só pra plot/tooltip
        df_view = to_local_naive(df_view_utc)

        ultimo = float(df_view_utc["close"].iloc[-1])
        first = float(df_view_utc["close"].iloc[0])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

        st.caption(f"📡 Fonte: **{source}**")
        st.markdown(
            f"<span class='badge'>Timeframe: <b>{timeframe}</b></span>"
            f"<span class='badge'>Janela: <b>{window_days} dias</b></span>"
            f"<span class='badge'>TZ: <b>{TZ_LOCAL}</b></span>",
            unsafe_allow_html=True
        )

        k1, k2, k3 = st.columns([1.6, 1, 1])
        k1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo), f"{var_pct:.2f}%")
        k2.metric("📈 Máxima (janela)", fmt_price(moeda, float(df_view_utc["high"].max())))
        k3.metric("📉 Mínima (janela)", fmt_price(moeda, float(df_view_utc["low"].min())))

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

            # Candles mais "fortes"
            fig.add_trace(
                go.Candlestick(
                    x=df_view["timestamp"],
                    open=df_view["open"], high=df_view["high"], low=df_view["low"], close=df_view["close"],
                    increasing_line_color="#00C896",
                    decreasing_line_color="#FF4B4B",
                    increasing_fillcolor="rgba(0,200,150,0.88)",
                    decreasing_fillcolor="rgba(255,75,75,0.88)",
                    whiskerwidth=0.7,
                    showlegend=False,
                    name="Preço",
                    hovertemplate=(
                        "<b>%{x|%d/%m/%Y %H:%M}</b><br>"
                        "Open: %{open}<br>"
                        "High: %{high}<br>"
                        "Low: %{low}<br>"
                        "Close: %{close}<extra></extra>"
                    )
                ),
                row=1, col=1
            )

            if show_price_line:
                fig.add_hline(y=ultimo, line_dash="dot", opacity=0.55, row=1, col=1)

            # MAs
            if show_ma and "MA7" in df_view.columns:
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA7"], mode="lines", opacity=0.9, name="MA7"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA25"], mode="lines", opacity=0.9, name="MA25"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["MA99"], mode="lines", opacity=0.9, name="MA99"), row=1, col=1)

            # BB
            if show_bb and "BB_UP" in df_view.columns:
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["BB_UP"], mode="lines", opacity=0.55, name="BB Upper"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["BB_MID"], mode="lines", opacity=0.55, name="BB Mid"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_view["timestamp"], y=df_view["BB_LOW"], mode="lines", opacity=0.55, name="BB Lower"), row=1, col=1)

            # Volume
            if volume_colored:
                vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df_view["open"], df_view["close"])]
            else:
                vol_colors = "rgba(255,255,255,0.22)"

            fig.add_trace(
                go.Bar(
                    x=df_view["timestamp"],
                    y=df_view["volume"],
                    marker_color=vol_colors,
                    opacity=0.18 if clean_volume else 0.42,
                    showlegend=False,
                    hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Volume: %{y}<extra></extra>"
                ),
                row=2, col=1
            )

            if show_vol_ma and "VOL_MA" in df_view.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_view["timestamp"],
                        y=df_view["VOL_MA"],
                        mode="lines",
                        opacity=0.75,
                        name="Vol MA",
                        hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Vol MA: %{y}<extra></extra>"
                    ),
                    row=2, col=1
                )

            # rangeslider e botões
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
            add_range_buttons(fig)

            fig.update_layout(
                template="plotly_dark",
                height=chart_height,
                margin=dict(l=10, r=10, t=10, b=10),
                dragmode="pan",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
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

st.info("✅ Modo híbrido ativo)



