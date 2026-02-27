# app.py
import time
import requests
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

# =========================================================
# PAGE
# =========================================================
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

# =========================================================
# SETTINGS / HELPERS
# =========================================================
TZ_LOCAL = "America/Sao_Paulo"

def request_json(url: str, params: dict, attempts: int = 3, base_sleep: float = 0.7):
    headers = {
        "User-Agent": "Mozilla/5.0 (StreamlitApp)",
        "Accept": "application/json,text/plain,*/*",
    }
    last_err = None
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=25)
            # rate limit / ban / server errors
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

def ensure_timestamp_utc(series: pd.Series) -> pd.Series:
    s = series
    if not pd.api.types.is_datetime64_any_dtype(s):
        s = pd.to_datetime(s, utc=True, errors="coerce")
    else:
        if getattr(s.dt, "tz", None) is None:
            s = s.dt.tz_localize("UTC")
        else:
            s = s.dt.tz_convert("UTC")
    return s

def to_local_naive(df: pd.DataFrame) -> pd.DataFrame:
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
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce").fillna(0.0)
    return d

def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "")

def window_days_for_timeframe(tf: str) -> int:
    # sua regra (janela padrão que aparece)
    return {"1h": 2, "4h": 4, "1d": 7}.get(tf, 7)

def fmt_price(moeda: str, p: float, meme_set: set[str]) -> str:
    return f"${p:,.6f}" if moeda in meme_set else f"${p:,.2f}"

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

def initial_view_range(df_local: pd.DataFrame, window_days: int):
    """
    Mantém o 'tamanho'/zoom inicial (2d/4d/7d), mas o dataset vem GIGANTE.
    Você arrasta pro passado usando o rangeslider/drag.
    """
    if df_local.empty:
        return None
    end = df_local["timestamp"].max()
    start = end - pd.Timedelta(days=window_days)
    return [start, end]

def add_indicators(df: pd.DataFrame,
                   show_ma: bool, show_bb: bool, show_rsi: bool, show_macd: bool,
                   show_vol_ma: bool, vol_ma_period: int) -> pd.DataFrame:
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

# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:
    st.header("⚙️ Controles")

    auto_refresh = st.toggle("🔄 Atualização automática", value=False)
    refresh_seconds = st.select_slider("Intervalo (segundos)", options=[30, 60, 120, 180, 300], value=60)
    if auto_refresh:
        st_autorefresh(interval=refresh_seconds * 1000, key="refresh")

    if st.button("🔁 Atualizar agora"):
        st.rerun()

    st.divider()
    timeframe = st.selectbox("Prazo:", ["1h", "4h", "1d"], index=0)

    st.divider()
    st.subheader("📌 Indicadores (premium)")
    show_ma = st.toggle("MA 7/25/99 (igual Binance)", value=True)
    show_bb = st.toggle("Bandas de Bollinger (20, 2)", value=False)
    show_rsi = st.toggle("RSI (14)", value=True)
    show_macd = st.toggle("MACD (12/26/9)", value=True)

    st.divider()
    st.subheader("📊 Volume")
    clean_volume = st.toggle("Volume limpo (mais discreto)", value=True)
    volume_colored = st.toggle("Volume verde/vermelho", value=True)
    show_vol_ma = st.toggle("Média do volume (linha)", value=True)
    vol_ma_period = st.slider("Período média do volume", 5, 50, 20, 1)

    st.divider()
    st.subheader("🎛️ Aparência")
    show_price_line = st.toggle("Linha do preço atual", value=True)
    show_crosshair = st.toggle("Crosshair (spikes)", value=True)
    chart_height = st.slider("Altura do gráfico", 620, 980, 840, 10)

    st.divider()
    debug_mode = st.toggle("🧪 Debug (mostrar erros)", value=False)

# =========================================================
# BINANCE UNIVERSE (ALL USDT SPOT) — SEM FDUSD E USDC
# =========================================================
@st.cache_data(ttl=60 * 60)
def fetch_binance_usdt_spot_pairs() -> list[str]:
    """
    Lista TODOS pares USDT spot em TRADING, excluindo FDUSD e USDC.
    Robusto para Streamlit Cloud com fallback de endpoints.
    """
    endpoints = [
        "https://api.binance.com/api/v3/exchangeInfo",
        "https://api1.binance.com/api/v3/exchangeInfo",
        "https://api2.binance.com/api/v3/exchangeInfo",
        "https://api3.binance.com/api/v3/exchangeInfo",
        "https://data-api.binance.vision/api/v3/exchangeInfo",
    ]

    last_err = None
    for url in endpoints:
        try:
            j = request_json(url, params={}, attempts=2, base_sleep=0.6)
            symbols = j.get("symbols", [])
            out = []
            for s in symbols:
                if s.get("status") != "TRADING":
                    continue
                if s.get("isSpotTradingAllowed") is not True:
                    continue
                quote = s.get("quoteAsset")
                if quote != "USDT":
                    continue
                base = s.get("baseAsset")
                if not base:
                    continue

                # exclui “moedas” que você não quer na lista
                if base in {"USDC", "FDUSD"}:
                    continue

                out.append(f"{base}/USDT")

            out = sorted(list(dict.fromkeys(out)))
            if out:
                return out
        except Exception as e:
            last_err = e

    st.session_state["binance_pairs_error"] = str(last_err) if last_err else "Falha desconhecida"
    # fallback mínimo (pra app não quebrar)
    return [
        "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
        "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "MATIC/USDT",
        "PEPE/USDT", "SHIB/USDT", "TURBO/USDT"
    ]

ALL_USDT = fetch_binance_usdt_spot_pairs()

# =========================================================
# TOP UI: BUSCA + MULTISELECT (sem quebrar)
# =========================================================
search = st.text_input("Buscar moeda (ex: BTC, PEPE, SOL):", value="", placeholder="Digite o ticker…")
search_upper = search.strip().upper()

if search_upper:
    filtered = [p for p in ALL_USDT if p.startswith(search_upper + "/") or p.split("/")[0].startswith(search_upper)]
    # se não achar, não quebra
    options = filtered if filtered else ALL_USDT
else:
    options = ALL_USDT

# defaults seguros (evita o erro do multiselect quando o default não existe no filtro)
default_list = []
if "BTC/USDT" in options:
    default_list = ["BTC/USDT"]
elif options:
    default_list = [options[0]]

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    options,
    default=default_list,
    max_selections=3
)

if "binance_pairs_error" in st.session_state:
    st.warning(
        "⚠️ Não consegui carregar a lista completa da Binance agora (Cloud às vezes bloqueia). "
        "Usei fallback temporário. Tente ‘Atualizar agora’ depois."
    )
    if st.sidebar.toggle("🧪 Debug lista Binance", value=False):
        st.sidebar.code(st.session_state["binance_pairs_error"])

# meme set (pra formatação)
meme_tickers = {"DOGE", "PEPE", "TURBO", "SHIB", "FLOKI", "BONK"}
meme_coins = {m for m in ALL_USDT if m.split("/")[0] in meme_tickers}

# =========================================================
# DATA SOURCES (HISTÓRICO MÁXIMO)
# =========================================================
def max_limit_for_source() -> int:
    # Binance spot klines max = 1000
    # Bybit v5 limit geralmente até 1000
    return 1000

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
    # [startTime, open, high, low, close, volume, turnover]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)

@st.cache_data(ttl=180)
def fetch_binance_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    interval_map = {"1h": "1h", "4h": "4h", "1d": "1d"}
    url_candidates = [
        "https://api.binance.com/api/v3/klines",
        "https://api1.binance.com/api/v3/klines",
        "https://api2.binance.com/api/v3/klines",
        "https://api3.binance.com/api/v3/klines",
        "https://data-api.binance.vision/api/v3/klines",
    ]
    params = {"symbol": symbol, "interval": interval_map[timeframe], "limit": str(limit)}

    last_err = None
    for url in url_candidates:
        try:
            j = request_json(url, params=params, attempts=2, base_sleep=0.6)
            df = pd.DataFrame(j, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore"
            ])
            df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            return normalize_ohlcv(df)
        except Exception as e:
            last_err = e
    raise last_err

# CoinGecko só pra “não quebrar” se Bybit+Binance falharem
@st.cache_data(ttl=600)
def coingecko_resolve_id(query: str) -> str:
    url = "https://api.coingecko.com/api/v3/search"
    j = request_json(url, {"query": query}, attempts=2, base_sleep=0.6)
    coins = j.get("coins", [])
    if not coins:
        raise RuntimeError("CoinGecko search vazio")
    return coins[0]["id"]

@st.cache_data(ttl=300)
def fetch_coingecko_ohlc(coin_id: str, days: int) -> pd.DataFrame:
    """
    CoinGecko OHLC: [timestamp, open, high, low, close]
    Volume vem do market_chart total_volumes (merge no mais próximo).
    """
    url_ohlc = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    j_ohlc = request_json(url_ohlc, {"vs_currency": "usd", "days": days})

    df_ohlc = pd.DataFrame(j_ohlc, columns=["timestamp", "open", "high", "low", "close"])
    df_ohlc["timestamp"] = pd.to_datetime(pd.to_numeric(df_ohlc["timestamp"]), unit="ms", utc=True)

    url_mc = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    j_mc = request_json(url_mc, {"vs_currency": "usd", "days": days})
    df_vol = pd.DataFrame(j_mc.get("total_volumes", []), columns=["timestamp", "volume"])

    if not df_vol.empty:
        df_vol["timestamp"] = pd.to_datetime(pd.to_numeric(df_vol["timestamp"]), unit="ms", utc=True)
        df_vol["volume"] = pd.to_numeric(df_vol["volume"], errors="coerce").fillna(0.0)

        df_ohlc = pd.merge_asof(
            df_ohlc.sort_values("timestamp"),
            df_vol.sort_values("timestamp"),
            on="timestamp",
            direction="nearest",
            tolerance=pd.Timedelta("2H"),
        )
        df_ohlc["volume"] = pd.to_numeric(df_ohlc.get("volume", 0.0), errors="coerce").fillna(0.0)
    else:
        df_ohlc["volume"] = 0.0

    df_ohlc = df_ohlc[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df_ohlc)

def build_dataset_hybrid(moeda: str, timeframe: str):
    sym = symbol_compact(moeda)   # BTCUSDT
    base = moeda.split("/")[0]    # BTC
    limit = max_limit_for_source()
    window_days = window_days_for_timeframe(timeframe)

    errors = {}

    # 1) Bybit
    try:
        df = fetch_bybit_ohlcv(sym, timeframe, limit)
        if len(df) >= 50:
            return df, "Bybit (spot)", window_days, errors
    except Exception as e:
        errors["Bybit"] = str(e)[:260]

    # 2) Binance
    try:
        df = fetch_binance_ohlcv(sym, timeframe, limit)
        if len(df) >= 50:
            return df, "Binance (spot)", window_days, errors
    except Exception as e:
        errors["Binance"] = str(e)[:260]

    # 3) CoinGecko (fallback)
    try:
        # CG OHLC aceita days: 1, 7, 14, 30, 90, 180, 365, max
        if timeframe == "1h":
            days_fetch = 7
        elif timeframe == "4h":
            days_fetch = 14
        else:
            days_fetch = 30

        cg_id = coingecko_resolve_id(base)
        df = fetch_coingecko_ohlc(cg_id, days_fetch)
        return df, "CoinGecko OHLC (fallback)", window_days, errors
    except Exception as e:
        errors["CoinGecko"] = str(e)[:260]

    raise RuntimeError("Falha geral de dados", errors)

# =========================================================
# TABS
# =========================================================
tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])

# =========================================================
# MAIN
# =========================================================
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

        if df_full_utc.empty or len(df_full_utc) < 10:
            st.warning("Poucos dados para renderizar.")
            st.caption(f"Fonte: {source}")
            continue

        # indicadores no dataset inteiro (pra você arrastar e manter MAs coerentes)
        df_full_utc = add_indicators(
            df_full_utc,
            show_ma=show_ma,
            show_bb=show_bb,
            show_rsi=show_rsi,
            show_macd=show_macd,
            show_vol_ma=show_vol_ma,
            vol_ma_period=vol_ma_period,
        )

        # converte pra Brasil só pra plot/tooltip
        df_full_local = to_local_naive(df_full_utc)

        # janela inicial (mas com histórico máximo carregado)
        view_range = initial_view_range(df_full_local, window_days)

        ultimo = float(df_full_utc["close"].iloc[-1])
        first = float(df_full_utc["close"].iloc[0])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

        st.caption(f"📡 Fonte: **{source}**")
        st.markdown(
            f"<span class='badge'>Prazo: <b>{timeframe}</b></span>"
            f"<span class='badge'>Janela inicial: <b>{window_days} dias</b></span>"
            f"<span class='badge'>Histórico: <b>{len(df_full_utc)} candles</b></span>"
            f"<span class='badge'>TZ: <b>{TZ_LOCAL}</b></span>",
            unsafe_allow_html=True
        )

        k1, k2, k3 = st.columns([1.6, 1, 1])
        k1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo, meme_coins), f"{var_pct:.2f}%")
        k2.metric("📈 Máxima (histórico carregado)", fmt_price(moeda, float(df_full_utc["high"].max()), meme_coins))
        k3.metric("📉 Mínima (histórico carregado)", fmt_price(moeda, float(df_full_utc["low"].min()), meme_coins))

        # =========================================================
        # CHART (estilo Binance + histórico grande + janela inicial fixa)
        # =========================================================
        with tab_chart:
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.82, 0.18],
                vertical_spacing=0.02,
                row_titles=["Preço", "Volume"]
            )

            fig.add_trace(
                go.Candlestick(
                    x=df_full_local["timestamp"],
                    open=df_full_local["open"], high=df_full_local["high"],
                    low=df_full_local["low"], close=df_full_local["close"],
                    increasing_line_color="#00C896",
                    decreasing_line_color="#FF4B4B",
                    increasing_fillcolor="rgba(0,200,150,0.90)",
                    decreasing_fillcolor="rgba(255,75,75,0.90)",
                    whiskerwidth=0.6,
                    name="Preço",
                    hovertemplate=(
                        "<b>%{x|%d/%m/%Y %H:%M}</b><br>"
                        "Abertura: %{open}<br>"
                        "Máxima: %{high}<br>"
                        "Mínima: %{low}<br>"
                        "Fechamento: %{close}"
                        "<extra></extra>"
                    )
                ),
                row=1, col=1
            )

            if show_price_line:
                fig.add_hline(y=ultimo, line_dash="dot", opacity=0.55, row=1, col=1)

            # MAs (7/25/99)
            if show_ma and "MA7" in df_full_local.columns:
                fig.add_trace(go.Scatter(x=df_full_local["timestamp"], y=df_full_local["MA7"], mode="lines", opacity=0.95, name="MA7"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_full_local["timestamp"], y=df_full_local["MA25"], mode="lines", opacity=0.95, name="MA25"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_full_local["timestamp"], y=df_full_local["MA99"], mode="lines", opacity=0.95, name="MA99"), row=1, col=1)

            # BB
            if show_bb and "BB_UP" in df_full_local.columns:
                fig.add_trace(go.Scatter(x=df_full_local["timestamp"], y=df_full_local["BB_UP"], mode="lines", opacity=0.55, name="BB Upper"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_full_local["timestamp"], y=df_full_local["BB_MID"], mode="lines", opacity=0.55, name="BB Mid"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_full_local["timestamp"], y=df_full_local["BB_LOW"], mode="lines", opacity=0.55, name="BB Lower"), row=1, col=1)

            # Volume
            if volume_colored:
                vol_colors = ["#00C896" if c >= o else "#FF4B4B"
                              for o, c in zip(df_full_local["open"], df_full_local["close"])]
            else:
                vol_colors = "rgba(255,255,255,0.22)"

            fig.add_trace(
                go.Bar(
                    x=df_full_local["timestamp"],
                    y=df_full_local["volume"],
                    marker_color=vol_colors,
                    opacity=0.18 if clean_volume else 0.42,
                    name="Volume",
                    hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Volume: %{y}<extra></extra>"
                ),
                row=2, col=1
            )

            if show_vol_ma and "VOL_MA" in df_full_local.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_full_local["timestamp"],
                        y=df_full_local["VOL_MA"],
                        mode="lines",
                        opacity=0.80,
                        name="Vol MA",
                        hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Vol MA: %{y}<extra></extra>"
                    ),
                    row=2, col=1
                )

            # rangeslider + botões
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
            add_range_buttons(fig)

            # janela inicial fixa (mas com histórico carregado)
            if view_range:
                fig.update_xaxes(range=view_range)

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
                fig,
                use_container_width=True,
                config={
                    "scrollZoom": True,
                    "displaylogo": False,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                }
            )
            st.markdown(
                "<div class='small-note'>Dica: o gráfico abre em 2d/4d/7d, mas o histórico vem no máximo. Use o slider inferior e arraste pro passado.</div>",
                unsafe_allow_html=True
            )

        # =========================================================
        # RSI
        # =========================================================
        with tab_rsi:
            if not show_rsi or "RSI" not in df_full_local.columns:
                st.info("Ative RSI no menu lateral.")
            else:
                fr = go.Figure()
                fr.add_trace(go.Scatter(x=df_full_local["timestamp"], y=df_full_local["RSI"], mode="lines", name="RSI"))
                fr.add_hline(y=70, line_dash="dot", opacity=0.55)
                fr.add_hline(y=30, line_dash="dot", opacity=0.55)
                fr.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                fr.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                add_range_buttons(fr)
                if view_range:
                    fr.update_xaxes(range=view_range)
                if show_crosshair:
                    apply_crosshair(fr)
                st.plotly_chart(fr, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

        # =========================================================
        # MACD
        # =========================================================
        with tab_macd:
            if not show_macd or "MACD" not in df_full_local.columns:
                st.info("Ative MACD no menu lateral.")
            else:
                fm = go.Figure()
                fm.add_trace(go.Scatter(x=df_full_local["timestamp"], y=df_full_local["MACD"], mode="lines", name="MACD"))
                fm.add_trace(go.Scatter(x=df_full_local["timestamp"], y=df_full_local["SIGNAL"], mode="lines", name="Signal"))
                if "HIST" in df_full_local.columns:
                    fm.add_trace(go.Bar(x=df_full_local["timestamp"], y=df_full_local["HIST"], name="Hist", opacity=0.25))
                fm.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                fm.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                add_range_buttons(fm)
                if view_range:
                    fm.update_xaxes(range=view_range)
                if show_crosshair:
                    apply_crosshair(fm)
                st.plotly_chart(fm, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

st.info("✅ Modo híbrido ativo")















