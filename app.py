import time
import json
import math
import requests
import numpy as np
import pandas as pd
import streamlit as st

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.utils import PlotlyJSONEncoder
from streamlit_autorefresh import st_autorefresh


# ==============================
# PAGE
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
        margin-right: 8px;
      }
      code {font-size: 0.9rem;}
      /* deixa o modo-bar mais discreto */
      .modebar {opacity: .35 !important;}
      .modebar:hover {opacity: 1 !important;}
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🚀 Análise Cripto PRO+ — Premium")


# ==============================
# SETTINGS / HELPERS
# ==============================
TZ_LOCAL = "America/Sao_Paulo"

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
    d["volume"] = d["volume"].fillna(0.0)
    return d

def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "")

def fmt_price(moeda: str, p: float, meme_set: set[str]) -> str:
    return f"${p:,.6f}" if moeda in meme_set else f"${p:,.2f}"

def timeframe_to_binance(tf: str) -> str:
    return {"1h": "1h", "4h": "4h", "1d": "1d"}.get(tf, "1h")

def timeframe_to_bybit(tf: str) -> str:
    return {"1h": "60", "4h": "240", "1d": "D"}.get(tf, "60")

def window_days_for_timeframe(tf: str) -> int:
    return {"1h": 2, "4h": 4, "1d": 14}.get(tf, 14)  # (visual/metric window)

def initial_days_open(tf: str) -> int:
    # abre “zoomado” em ~2 semanas (ou equivalente)
    # 1h: 14 dias; 4h: 28 dias (parece 2 semanas “visuais”); 1d: 14 dias
    return {"1h": 14, "4h": 28, "1d": 14}.get(tf, 14)

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
# BINANCE PAIRS (USDT ONLY, exclude FDUSD/USDC)
# ==============================
@st.cache_data(ttl=60 * 60)
def fetch_binance_usdt_spot_pairs() -> list[str]:
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
                base = s.get("baseAsset")

                # USDT somente (sem FDUSD/USDC)
                if quote != "USDT":
                    continue
                if base in ("FDUSD", "USDC"):
                    continue

                if base and quote:
                    out.append(f"{base}/{quote}")

            out = sorted(list(dict.fromkeys(out)))
            if out:
                return out
        except Exception as e:
            last_err = e

    st.session_state["binance_pairs_error"] = str(last_err) if last_err else "Falha desconhecida"
    return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "ADA/USDT", "DOGE/USDT", "PEPE/USDT", "TURBO/USDT"]


# ==============================
# DATA SOURCES
# ==============================
@st.cache_data(ttl=180)
def fetch_bybit_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "spot",
        "symbol": symbol,
        "interval": timeframe_to_bybit(timeframe),
        "limit": str(limit),
    }
    j = request_json(url, params)
    if str(j.get("retCode")) != "0":
        raise RuntimeError(f"Bybit retCode={j.get('retCode')} msg={j.get('retMsg')}")
    rows = j["result"]["list"]  # [startTime, open, high, low, close, volume, turnover]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df)

@st.cache_data(ttl=180)
def fetch_binance_ohlcv(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": timeframe_to_binance(timeframe), "limit": str(limit)}
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
def fetch_coingecko_ohlc(coin_id: str, days: int) -> pd.DataFrame:
    # OHLC
    url_ohlc = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    j_ohlc = request_json(url_ohlc, {"vs_currency": "usd", "days": days})

    df_ohlc = pd.DataFrame(j_ohlc, columns=["timestamp", "open", "high", "low", "close"])
    df_ohlc["timestamp"] = pd.to_datetime(pd.to_numeric(df_ohlc["timestamp"]), unit="ms", utc=True)

    # Volume
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
        df_ohlc["volume"] = df_ohlc["volume"].fillna(0.0)
    else:
        df_ohlc["volume"] = 0.0

    df_ohlc = df_ohlc[["timestamp", "open", "high", "low", "close", "volume"]]
    return normalize_ohlcv(df_ohlc)


def build_dataset_hybrid(moeda: str, timeframe: str, limit: int):
    sym = symbol_compact(moeda)
    base = moeda.split("/")[0]
    errors = {}

    # 1) Bybit
    try:
        df = fetch_bybit_ohlcv(sym, timeframe, limit)
        return df, "Bybit (spot)", errors
    except Exception as e:
        errors["Bybit"] = str(e)[:260]

    # 2) Binance
    try:
        df = fetch_binance_ohlcv(sym, timeframe, limit)
        return df, "Binance (spot)", errors
    except Exception as e:
        errors["Binance"] = str(e)[:260]

    # 3) CoinGecko OHLC (fallback)
    try:
        # CG OHLC aceita days: 1, 7, 14, 30, 90, 180, 365, max
        if timeframe == "1h":
            days_fetch = 14
        elif timeframe == "4h":
            days_fetch = 30
        else:
            days_fetch = 90

        cg_id = coingecko_resolve_id(base)
        df = fetch_coingecko_ohlc(cg_id, days_fetch)
        return df, "CoinGecko OHLC (fallback)", errors
    except Exception as e:
        errors["CoinGecko"] = str(e)[:260]

    raise RuntimeError("Falha geral de dados", errors)


# ==============================
# INDICATORS
# ==============================
def add_indicators(df: pd.DataFrame, show_ma: bool, show_bb: bool, show_rsi: bool, show_macd: bool, show_vol_ma: bool, vol_ma_period: int) -> pd.DataFrame:
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
# PLOTLY “AUTO-Y BINANCE” via HTML (sem bug de JSON)
# ==============================
def plotly_autoy_html(fig: go.Figure, height: int, y_min_range_hint: float = 10000.0):
    """
    Renderiza Plotly em HTML e ajusta o Y automaticamente baseado no X visível (estilo Binance).
    - y_min_range_hint: “largura mínima” do range Y (ex.: 10000 no BTC)
    """
    fig_dict = fig.to_plotly_json()
    payload = json.dumps(fig_dict, cls=PlotlyJSONEncoder)

    # Observação:
    # - dtick é calculado no JS com base no range (ex.: 1000 em BTC)
    # - remove rangeselector (quadradinhos brancos) => só rangeslider
    html = f"""
    <div id="chart" style="height:{height}px;"></div>
    <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
    <script>
      const fig = {payload};
      const gd = document.getElementById('chart');

      const config = {{
        scrollZoom: true,
        displaylogo: false,
        responsive: true,
        modeBarButtonsToRemove: ["lasso2d","select2d"],
      }};

      function toMs(x) {{
        // x pode vir como string ISO
        const t = Date.parse(x);
        return isNaN(t) ? null : t;
      }}

      function computeVisibleYRange() {{
        const fullLayout = gd._fullLayout || {{}};
        const xr = (fullLayout.xaxis && fullLayout.xaxis.range) ? fullLayout.xaxis.range : null;
        if (!xr || xr.length < 2) return null;

        const x0 = toMs(xr[0]);
        const x1 = toMs(xr[1]);
        if (x0 === null || x1 === null) return null;

        let ymin = Infinity;
        let ymax = -Infinity;

        const data = gd.data || [];
        for (const tr of data) {{
          if (!tr || !tr.x) continue;

          const xs = tr.x;
          const isCandle = (tr.type === "candlestick" || tr.type === "ohlc");

          // preço: usa low/high nos candles; senão usa y
          let ysLow = null;
          let ysHigh = null;
          let ys = null;

          if (isCandle) {{
            ysLow = tr.low;
            ysHigh = tr.high;
          }} else {{
            ys = tr.y;
          }}

          for (let i = 0; i < xs.length; i++) {{
            const xm = toMs(xs[i]);
            if (xm === null) continue;
            if (xm < x0 || xm > x1) continue;

            if (isCandle) {{
              const lo = (ysLow && ysLow[i] != null) ? Number(ysLow[i]) : NaN;
              const hi = (ysHigh && ysHigh[i] != null) ? Number(ysHigh[i]) : NaN;
              if (!isNaN(lo)) ymin = Math.min(ymin, lo);
              if (!isNaN(hi)) ymax = Math.max(ymax, hi);
            }} else if (ys) {{
              const yv = Number(ys[i]);
              if (!isNaN(yv)) {{
                ymin = Math.min(ymin, yv);
                ymax = Math.max(ymax, yv);
              }}
            }}
          }}
        }}

        if (!isFinite(ymin) || !isFinite(ymax)) return null;

        // padding + range mínimo (ex.: 10k em BTC)
        let span = ymax - ymin;
        if (!isFinite(span) || span <= 0) span = {y_min_range_hint};

        // força span mínimo (para ficar “bonito” sem esmagar)
        const minSpan = {y_min_range_hint};
        span = Math.max(span, minSpan);

        // padding proporcional
        const pad = span * 0.08;

        // centraliza, garantindo que cubra min/max
        const center = (ymin + ymax) / 2.0;
        let y0 = center - (span / 2.0) - pad;
        let y1 = center + (span / 2.0) + pad;

        // dtick “binance-like”
        const finalSpan = y1 - y0;
        let dtick = 1000; // default
        if (finalSpan > 60000) dtick = 5000;
        else if (finalSpan > 25000) dtick = 2000;
        else if (finalSpan > 14000) dtick = 1000;
        else if (finalSpan > 7000) dtick = 500;
        else if (finalSpan > 2500) dtick = 200;
        else if (finalSpan > 1200) dtick = 100;
        else if (finalSpan > 400) dtick = 50;
        else dtick = 10;

        return {{y0, y1, dtick}};
      }}

      function applyAutoY() {{
        const r = computeVisibleYRange();
        if (!r) return;
        Plotly.relayout(gd, {{
          "yaxis.range": [r.y0, r.y1],
          "yaxis.dtick": r.dtick,
          "yaxis.tickformat": ",.0f"
        }});
      }}

      Plotly.newPlot(gd, fig.data, fig.layout, config).then(() => {{
        // primeira aplicação
        applyAutoY();

        // quando mexe (pan/zoom), recalcula
        gd.on('plotly_relayout', () => {{
          // evita loop infinito: espera a mudança estabilizar
          clearTimeout(window.__autoy_t);
          window.__autoy_t = setTimeout(applyAutoY, 50);
        }});
      }});
    </script>
    """
    return html


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
    timeframe = st.selectbox("Prazo:", ["1h", "4h", "1d"], index=0)

    st.divider()
    st.subheader("🕰️ Histórico (candles)")
    # carrega bastante, mas deixa abrir com 2 semanas
    default_limit = 2000
    limit = st.slider("Quantos candles carregar (mais = mais histórico)", 500, 4000, default_limit, 100)

    visible_open = st.slider("Candles visíveis ao abrir (zoom inicial)", 80, 600, 200, 10)

    colA, colB = st.columns(2)
    with colA:
        add_1000 = st.button("➕ Carregar +1000")
    with colB:
        reset_hist = st.button("↩️ Reset")

    if "extra_limit" not in st.session_state:
        st.session_state["extra_limit"] = 0
    if add_1000:
        st.session_state["extra_limit"] = min(8000, st.session_state["extra_limit"] + 1000)
        st.rerun()
    if reset_hist:
        st.session_state["extra_limit"] = 0
        st.rerun()

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
    vol_ma_period = st.slider("Período média do volume", 5, 60, 20, 1)

    st.divider()
    st.subheader("🎛️ Aparência")
    show_price_line = st.toggle("Linha do preço atual", value=True)
    show_crosshair = st.toggle("Crosshair (spikes)", value=True)
    chart_height = st.slider("Altura do gráfico", 620, 1020, 860, 10)

    st.divider()
    debug_mode = st.toggle("🧪 Debug (mostrar erros das fontes)", value=False)


# ==============================
# COINS + SEARCH
# ==============================
ALL_USDT = fetch_binance_usdt_spot_pairs()

if "binance_pairs_error" in st.session_state:
    st.warning(
        "⚠️ Não consegui carregar a lista completa da Binance agora (cloud às vezes bloqueia). "
        "Usei uma lista reduzida. Tente ‘Atualizar agora’ depois."
    )
    if st.sidebar.toggle("🧪 Debug lista Binance", value=False):
        st.sidebar.code(st.session_state["binance_pairs_error"])

meme_set = {m for m in ALL_USDT if m.split("/")[0] in {"DOGE", "PEPE", "TURBO", "SHIB"}}

q = st.text_input("Digite o ticker…", value="", placeholder="Ex: BTC, PEPE, SOL")
if q.strip():
    qn = q.strip().upper()
    filtered = [p for p in ALL_USDT if p.startswith(qn + "/") or p.replace("/", "").startswith(qn)]
    options = filtered if filtered else ALL_USDT
else:
    options = ALL_USDT

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    options,
    default=["BTC/USDT"] if "BTC/USDT" in options else ([options[0]] if options else []),
    max_selections=3
)


# ==============================
# TABS
# ==============================
tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])


# ==============================
# MAIN
# ==============================
for moeda in moedas:
    with st.expander(f"Detalhes de {moeda}", expanded=True):
        if moeda in meme_set:
            st.warning("🧪 Meme coin — alta volatilidade")

        # limit total com “carregar +1000”
        total_limit = min(8000, int(limit + st.session_state.get("extra_limit", 0)))

        try:
            df_full_utc, source, errors = build_dataset_hybrid(moeda, timeframe, total_limit)
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

        if df_full_utc.empty or len(df_full_utc) < 20:
            st.warning("Poucos dados para renderizar.")
            st.caption(f"Fonte: {source}")
            continue

        # indicadores (em UTC)
        df_full_utc = add_indicators(
            df_full_utc,
            show_ma=show_ma,
            show_bb=show_bb,
            show_rsi=show_rsi,
            show_macd=show_macd,
            show_vol_ma=show_vol_ma,
            vol_ma_period=vol_ma_period
        )

        # para plot (BR)
        df_plot = to_local_naive(df_full_utc)

        # janela visual/metrics (pra cards)
        wdays = window_days_for_timeframe(timeframe)
        end_ts = df_full_utc["timestamp"].max()
        start_ts = end_ts - pd.Timedelta(days=wdays)
        df_view_utc = df_full_utc[df_full_utc["timestamp"] >= start_ts].copy()
        df_view = to_local_naive(df_view_utc)

        ultimo = float(df_view_utc["close"].iloc[-1])
        first = float(df_view_utc["close"].iloc[0])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

        st.caption(f"📡 Fonte: **{source}**")
        st.markdown(
            f"<span class='badge'>Prazo: <b>{timeframe}</b></span>"
            f"<span class='badge'>Janela (cards): <b>{wdays} dias</b></span>"
            f"<span class='badge'>TZ: <b>{TZ_LOCAL}</b></span>"
            f"<span class='badge'>Histórico carregado: <b>{len(df_plot)} candles</b></span>",
            unsafe_allow_html=True
        )

        k1, k2, k3 = st.columns([1.6, 1, 1])
        k1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo, meme_set), f"{var_pct:.2f}%")
        k2.metric("📈 Máxima (janela)", fmt_price(moeda, float(df_view_utc["high"].max()), meme_set))
        k3.metric("📉 Mínima (janela)", fmt_price(moeda, float(df_view_utc["low"].min()), meme_set))

        # ======================
        # CHART (Auto-Y Binance)
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
                    x=df_plot["timestamp"],
                    open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"],
                    increasing_line_color="#00C896",
                    decreasing_line_color="#FF4B4B",
                    increasing_fillcolor="rgba(0,200,150,0.88)",
                    decreasing_fillcolor="rgba(255,75,75,0.88)",
                    whiskerwidth=0.6,
                    name="Preço",
                    showlegend=True,
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
            if show_ma and "MA7" in df_plot.columns:
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA7"], mode="lines", opacity=0.9, name="MA7"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA25"], mode="lines", opacity=0.9, name="MA25"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA99"], mode="lines", opacity=0.9, name="MA99"), row=1, col=1)

            # BB
            if show_bb and "BB_UP" in df_plot.columns:
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_UP"], mode="lines", opacity=0.55, name="BB Upper"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_MID"], mode="lines", opacity=0.55, name="BB Mid"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_LOW"], mode="lines", opacity=0.55, name="BB Lower"), row=1, col=1)

            # Volume
            if volume_colored:
                vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df_plot["open"], df_plot["close"])]
            else:
                vol_colors = "rgba(255,255,255,0.22)"

            fig.add_trace(
                go.Bar(
                    x=df_plot["timestamp"],
                    y=df_plot["volume"],
                    marker_color=vol_colors,
                    opacity=0.18 if clean_volume else 0.42,
                    name="Volume",
                    showlegend=True,
                    hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Volume: %{y}<extra></extra>"
                ),
                row=2, col=1
            )

            if show_vol_ma and "VOL_MA" in df_plot.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_plot["timestamp"],
                        y=df_plot["VOL_MA"],
                        mode="lines",
                        opacity=0.75,
                        name="Vol MA",
                        hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Vol MA: %{y}<extra></extra>"
                    ),
                    row=2, col=1
                )

            # rangeslider (SEM rangeselector => sem quadradinhos brancos)
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06), row=1, col=1)

            fig.update_layout(
                template="plotly_dark",
                height=chart_height,
                margin=dict(l=10, r=10, t=10, b=10),
                dragmode="pan",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                hovermode="x unified",
            )
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
            fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)")

            if show_crosshair:
                fig.update_layout(hovermode="x unified", spikedistance=-1)
                fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                                 spikethickness=1, spikecolor="rgba(255,255,255,0.35)")
                fig.update_yaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                                 spikethickness=1, spikecolor="rgba(255,255,255,0.25)")

            # ===== abre “zoomado” em ~2 semanas (ou candles visíveis ao abrir) =====
            # preferimos “visible_open” candles porque é consistente em qualquer timeframe.
            if len(df_plot) > visible_open:
                x_end0 = df_plot["timestamp"].iloc[-1]
                x_start0 = df_plot["timestamp"].iloc[-visible_open]
                fig.update_xaxes(range=[x_start0, x_end0], row=1, col=1)

            # ===== AUTO-Y estilo Binance =====
            # - BTC/ETH e majors: mínimo 10k de range Y pra ficar bonito
            # - meme coins: range mínimo bem menor
            if moeda in meme_set:
                y_hint = 0.0005  # range mínimo pra não esmagar
            else:
                y_hint = 10000.0  # ~10k como você pediu

            st.components.v1.html(
                plotly_autoy_html(fig, height=chart_height, y_min_range_hint=y_hint),
                height=chart_height + 30,
                scrolling=False
            )

            st.markdown(
                "<div class='small-note'>Dica: arraste no gráfico (pan) e use scroll para zoom. "
                "O eixo Y se ajusta automaticamente ao intervalo X visível (estilo Binance).</div>",
                unsafe_allow_html=True
            )

        # ======================
        # RSI
        # ======================
        with tab_rsi:
            if not show_rsi or "RSI" not in df_plot.columns:
                st.info("Ative RSI no menu lateral.")
            else:
                fr = go.Figure()
                fr.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["RSI"], mode="lines", name="RSI"))
                fr.add_hline(y=70, line_dash="dot", opacity=0.55)
                fr.add_hline(y=30, line_dash="dot", opacity=0.55)
                fr.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                fr.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                if show_crosshair:
                    fr.update_layout(hovermode="x unified", spikedistance=-1)
                    fr.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                                    spikethickness=1, spikecolor="rgba(255,255,255,0.35)")
                    fr.update_yaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                                    spikethickness=1, spikecolor="rgba(255,255,255,0.25)")
                st.plotly_chart(fr, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

        # ======================
        # MACD
        # ======================
        with tab_macd:
            if not show_macd or "MACD" not in df_plot.columns:
                st.info("Ative MACD no menu lateral.")
            else:
                fm = go.Figure()
                fm.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MACD"], mode="lines", name="MACD"))
                fm.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["SIGNAL"], mode="lines", name="Signal"))
                if "HIST" in df_plot.columns:
                    fm.add_trace(go.Bar(x=df_plot["timestamp"], y=df_plot["HIST"], name="Hist", opacity=0.25))
                fm.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                fm.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                if show_crosshair:
                    fm.update_layout(hovermode="x unified", spikedistance=-1)
                    fm.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                                    spikethickness=1, spikecolor="rgba(255,255,255,0.35)")
                    fm.update_yaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                                    spikethickness=1, spikecolor="rgba(255,255,255,0.25)")
                st.plotly_chart(fm, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

st.info("✅ Modo híbrido ativo")



























