# app.py
# =========================================================
# Análise Cripto PRO+ — Premium (Binance-like)
# - Lista TODAS as pairs USDT Spot da Binance (sem FDUSD/USDC)
# - Candles "idênticos" (Binance Klines), MA 7/25/99, BB, Volume + Vol MA
# - Histórico grande (paginação Binance) + botão "Carregar mais histórico"
# - Abre SEMPRE com ~2 semanas (zoom inicial), mas dá pra arrastar/voltar no tempo
# - Auto-Y estilo Binance (o Y se ajusta automaticamente ao X visível)
# - Sem “quadradinhos brancos” (removi rangeselector; fica só rangeslider)
# =========================================================

import time
import json
import math
import requests
import numpy as np
import pandas as pd
import streamlit as st

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

from streamlit_autorefresh import st_autorefresh

# ------------------------------
# PAGE
# ------------------------------
st.set_page_config(layout="wide", page_title="Análise Cripto PRO+ — Premium")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.0rem;}
      div[data-testid="stSidebar"] {border-right: 1px solid rgba(255,255,255,0.06);}
      .stMetric {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        padding: 14px;
        border-radius: 14px;
      }
      .small-note {opacity: .78; font-size: 0.92rem;}
      .badge {
        display:inline-block; padding:6px 10px; border-radius:999px;
        border:1px solid rgba(255,255,255,0.12);
        background: rgba(255,255,255,0.04);
        font-size: 0.9rem; opacity: 0.95;
        margin-right: 8px;
      }
      code {font-size: 0.9rem;}
      /* deixa o app mais "trade terminal" */
      .stTabs [data-baseweb="tab-list"] button {padding-top: 8px; padding-bottom: 8px;}
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🚀 Análise Cripto PRO+ — Premium")

# ------------------------------
# SETTINGS / HELPERS
# ------------------------------
TZ_LOCAL = "America/Sao_Paulo"

BINANCE_EXINFO_ENDPOINTS = [
    "https://api.binance.com/api/v3/exchangeInfo",
    "https://api1.binance.com/api/v3/exchangeInfo",
    "https://api2.binance.com/api/v3/exchangeInfo",
    "https://api3.binance.com/api/v3/exchangeInfo",
    "https://data-api.binance.vision/api/v3/exchangeInfo",
]

BINANCE_KLINES_ENDPOINTS = [
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api2.binance.com/api/v3/klines",
    "https://api3.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
]

# excluídos como você pediu
EXCLUDE_QUOTES = {"FDUSD", "USDC"}

# meme list só pra formatação (6 casas) — opcional
MEME_BASES = {"DOGE", "PEPE", "TURBO", "SHIB", "FLOKI", "BONK"}

def fmt_price(pair: str, p: float) -> str:
    base = pair.split("/")[0]
    return f"${p:,.6f}" if base in MEME_BASES else f"${p:,.2f}"

def request_json(url: str, params: dict, attempts: int = 3, base_sleep: float = 0.6):
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

def timeframe_to_binance_interval(tf: str) -> str:
    return {"1h": "1h", "4h": "4h", "1d": "1d"}.get(tf, "1d")

def initial_range_last_two_weeks(df_plot_local: pd.DataFrame, timeframe: str):
    """
    Zoom inicial:
      - 1h/4h: últimas 2 semanas (14 dias)
      - 1d: últimos 14 candles
    """
    if df_plot_local.empty:
        return None, None

    x_end = df_plot_local["timestamp"].iloc[-1]
    if timeframe in ("1h", "4h"):
        x_start = x_end - pd.Timedelta(days=14)
    else:
        n = min(14, len(df_plot_local))
        x_start = df_plot_local["timestamp"].iloc[-n]
    return x_start, x_end

def add_indicators(df: pd.DataFrame, show_ma: bool, show_bb: bool, show_rsi: bool, show_macd: bool,
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

def symbol_compact(pair: str) -> str:
    return pair.replace("/", "")

# ------------------------------
# BINANCE PAIRS (ALL USDT SPOT)
# ------------------------------
@st.cache_data(ttl=60 * 60)
def fetch_binance_usdt_spot_pairs() -> list[str]:
    last_err = None
    for url in BINANCE_EXINFO_ENDPOINTS:
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
                if not quote or not base:
                    continue

                # só USDT e SEM FDUSD/USDC
                if quote != "USDT":
                    continue
                if quote in EXCLUDE_QUOTES:
                    continue

                out.append(f"{base}/{quote}")

            out = sorted(list(dict.fromkeys(out)))
            if out:
                return out
        except Exception as e:
            last_err = e

    # fallback mínimo (não derruba o app)
    st.session_state["binance_pairs_error"] = str(last_err) if last_err else "Falha desconhecida"
    return [
        "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
        "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "MATIC/USDT",
        "PEPE/USDT", "SHIB/USDT", "TURBO/USDT"
    ]

# ------------------------------
# BINANCE KLINES (PAGINADO) — histórico “máximo possível”
# ------------------------------
@st.cache_data(ttl=120)
def fetch_binance_ohlcv_paginated(symbol: str, interval: str, total_limit: int) -> pd.DataFrame:
    """
    Binance Klines:
      - max 1000 por request
      - pra pegar 2000/4000/5000 velas, a gente pagina usando endTime

    total_limit: até 5000 (ou mais, mas recomendo 5000 pra não travar cloud)
    """
    chunk = 1000
    remaining = int(total_limit)
    end_time = None  # ms
    rows_all = []

    # tenta endpoints em ordem
    last_err = None
    for base_url in BINANCE_KLINES_ENDPOINTS:
        try:
            remaining = int(total_limit)
            end_time = None
            rows_all = []

            safety = 0
            while remaining > 0 and safety < 20:
                safety += 1
                lim = min(chunk, remaining)
                params = {"symbol": symbol, "interval": interval, "limit": str(lim)}
                if end_time is not None:
                    params["endTime"] = str(end_time)

                data = request_json(base_url, params=params, attempts=2, base_sleep=0.6)
                if not data:
                    break

                # data vem do mais antigo -> mais novo
                rows_all = data + rows_all

                # prepara próxima página “para trás”
                oldest_open_time = data[0][0]  # ms
                end_time = oldest_open_time - 1

                # se veio menos do que pediu, não tem mais histórico
                if len(data) < lim:
                    break

                remaining -= lim

                # pequena pausa pra não tomar rate limit
                time.sleep(0.08)

            if not rows_all:
                raise RuntimeError("Binance klines vazio")

            df = pd.DataFrame(rows_all, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore"
            ])
            df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            return normalize_ohlcv(df)

        except Exception as e:
            last_err = e
            continue

    raise last_err if last_err else RuntimeError("Falha geral Binance")

# ------------------------------
# CoinGecko fallback (só pra não quebrar)
# ------------------------------
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
    url_ohlc = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    j_ohlc = request_json(url_ohlc, {"vs_currency": "usd", "days": days})
    df_ohlc = pd.DataFrame(j_ohlc, columns=["timestamp", "open", "high", "low", "close"])
    df_ohlc["timestamp"] = pd.to_datetime(pd.to_numeric(df_ohlc["timestamp"]), unit="ms", utc=True)
    df_ohlc["volume"] = 0.0
    return normalize_ohlcv(df_ohlc[["timestamp", "open", "high", "low", "close", "volume"]])

def build_dataset(moeda: str, timeframe: str, max_candles: int):
    """
    Fonte principal: Binance (pra ficar igual Binance).
    Fallback: CoinGecko (se Binance bloquear no Cloud)
    """
    sym = symbol_compact(moeda)  # BTCUSDT
    base = moeda.split("/")[0]
    interval = timeframe_to_binance_interval(timeframe)

    errors = {}

    try:
        df = fetch_binance_ohlcv_paginated(sym, interval, max_candles)
        return df, "Binance (spot)", errors
    except Exception as e:
        errors["Binance"] = str(e)[:260]

    # fallback bem simples só pra não quebrar
    try:
        days = 30 if timeframe == "1d" else 14
        cg_id = coingecko_resolve_id(base)
        df = fetch_coingecko_ohlc(cg_id, days)
        return df, "CoinGecko (fallback)", errors
    except Exception as e:
        errors["CoinGecko"] = str(e)[:260]

    raise RuntimeError("Falha geral de dados", errors)

# ------------------------------
# AUTO-Y (Binance-style) via HTML Plotly.js
# ------------------------------
def plotly_autoy_html(fig: go.Figure, height: int = 820, x_start=None, x_end=None) -> str:
    """
    Renderiza o Plotly no iframe e:
      - Auto-Y: ajusta o range do Y sempre que o X visível mudar
      - Header OHLC: mostra OHLC do candle em hover (dentro do gráfico, estilo Binance)
    """
    fig_json = pio.to_json(fig, validate=False)  # já serializa tudo certinho
    # ranges iniciais (opcional)
    x_start_js = json.dumps(str(x_start)) if x_start is not None else "null"
    x_end_js = json.dumps(str(x_end)) if x_end is not None else "null"

    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
  <style>
    html, body {{ margin:0; padding:0; background:#0b0f14; }}
    #wrap {{ position: relative; width: 100%; height: {height}px; }}
    #chart {{ width:100%; height:100%; }}
    #ohlcbar {{
      position:absolute; left:14px; top:10px;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      font-size: 12px; letter-spacing: 0.2px;
      color: rgba(255,255,255,0.88);
      background: rgba(0,0,0,0.25);
      border: 1px solid rgba(255,255,255,0.10);
      border-radius: 999px;
      padding: 6px 10px;
      backdrop-filter: blur(6px);
      user-select:none;
      pointer-events:none;
      z-index: 5;
    }}
    #ohlcbar span {{ opacity: 0.95; }}
    #ohlcbar .muted {{ opacity: 0.70; }}
  </style>
</head>
<body>
  <div id="wrap">
    <div id="ohlcbar">
      <span class="muted">Passe o mouse no candle</span>
    </div>
    <div id="chart"></div>
  </div>

<script>
  const fig = JSON.parse({json.dumps(fig_json)});
  const gd = document.getElementById('chart');
  const ohlcbar = document.getElementById('ohlcbar');

  // Plotly figure parts
  const data = fig.data || [];
  const layout = fig.layout || {{}};
  const config = Object.assign({{
    scrollZoom: true,
    displaylogo: false,
    responsive: true,
    modeBarButtonsToRemove: ["lasso2d","select2d"]
  }}, fig.config || {{}});

  // aplica range inicial no X, se vier
  const xStart = {x_start_js};
  const xEnd   = {x_end_js};
  if (xStart && xEnd) {{
    layout.xaxis = layout.xaxis || {{}};
    layout.xaxis.range = [xStart, xEnd];
  }}

  Plotly.newPlot(gd, data, layout, config);

  // acha o trace de candlestick (primeiro candlestick)
  function findCandleTrace() {{
    for (let i=0; i<data.length; i++) {{
      if ((data[i].type || "").toLowerCase() === "candlestick") return data[i];
    }}
    return null;
  }}

  function clamp(v, a, b) {{
    return Math.max(a, Math.min(b, v));
  }}

  function toTime(x) {{
    // x pode ser string ISO, Date, etc.
    const t = new Date(x).getTime();
    return isFinite(t) ? t : NaN;
  }}

  function computeYRangeFromVisibleX(x0, x1) {{
    const tr = findCandleTrace();
    if (!tr) return null;

    const xs = tr.x || [];
    const highs = tr.high || [];
    const lows  = tr.low  || [];

    const t0 = toTime(x0);
    const t1 = toTime(x1);
    if (!isFinite(t0) || !isFinite(t1)) return null;

    const lo = Math.min(t0, t1);
    const hi = Math.max(t0, t1);

    let ymin = Infinity, ymax = -Infinity;
    for (let i=0; i<xs.length; i++) {{
      const tx = toTime(xs[i]);
      if (!isFinite(tx)) continue;
      if (tx < lo || tx > hi) continue;

      const h = +highs[i];
      const l = +lows[i];
      if (isFinite(h) && h > ymax) ymax = h;
      if (isFinite(l) && l < ymin) ymin = l;
    }}

    if (!isFinite(ymin) || !isFinite(ymax) || ymin === ymax) return null;

    const pad = (ymax - ymin) * 0.06; // padding bonito
    return [ymin - pad, ymax + pad];
  }}

  function currentVisibleX() {{
    const xr = (gd.layout && gd.layout.xaxis && gd.layout.xaxis.range) ? gd.layout.xaxis.range : null;
    if (xr && xr.length === 2) return xr;

    // fallback: usa full range do trace
    const tr = findCandleTrace();
    if (!tr || !tr.x || tr.x.length < 2) return null;
    return [tr.x[0], tr.x[tr.x.length - 1]];
  }}

  function applyAutoY() {{
    try {{
      const xr = currentVisibleX();
      if (!xr) return;
      const yr = computeYRangeFromVisibleX(xr[0], xr[1]);
      if (!yr) return;

      // yaxis principal é yaxis (subplot row1)
      Plotly.relayout(gd, {{
        "yaxis.range": yr,
        "yaxis.autorange": false
      }});
    }} catch (e) {{}}
  }}

  // aplica auto-y na abertura
  setTimeout(applyAutoY, 50);

  // auto-y ao mudar o range do X (pan, zoom, rangeslider)
  gd.on('plotly_relayout', (ev) => {{
    if (!ev) return;
    // mudanças típicas no x:
    const keys = Object.keys(ev);
    const hasX =
      keys.includes("xaxis.range[0]") ||
      keys.includes("xaxis.range[1]") ||
      keys.includes("xaxis.autorange") ||
      keys.includes("xaxis.range");

    if (hasX) {{
      // atualiza o range local do gd
      setTimeout(applyAutoY, 0);
    }}
  }});

  // OHLC header (hover)
  gd.on('plotly_hover', (ev) => {{
    try {{
      const pt = ev && ev.points && ev.points[0];
      if (!pt) return;

      const i = pt.pointNumber;
      const tr = pt.data;
      if (!tr || (tr.type || "").toLowerCase() !== "candlestick") return;

      const x = (tr.x && tr.x[i]) || "";
      const o = (tr.open && tr.open[i]);
      const h = (tr.high && tr.high[i]);
      const l = (tr.low  && tr.low[i]);
      const c = (tr.close&& tr.close[i]);

      const dt = new Date(x);
      const dts = isFinite(dt.getTime())
        ? dt.toLocaleString("pt-BR", {{ hour12:false }})
        : String(x);

      const fmt = (v) => {{
        const n = +v;
        if (!isFinite(n)) return "-";
        // sem exagerar: 2 casas pra preços grandes, 6 pra muito pequenos
        if (Math.abs(n) >= 1) return n.toLocaleString("en-US", {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
        return n.toLocaleString("en-US", {{ minimumFractionDigits: 6, maximumFractionDigits: 6 }});
      }};

      const up = (+c >= +o);
      const col = up ? "rgba(0,200,150,0.95)" : "rgba(255,75,75,0.95)";
      ohlcbar.innerHTML =
        `<span class="muted">${{dts}}</span>
         <span style="margin-left:10px;color:${{col}}">O</span> ${{fmt(o)}}
         <span style="margin-left:8px;color:${{col}}">H</span> ${{fmt(h)}}
         <span style="margin-left:8px;color:${{col}}">L</span> ${{fmt(l)}}
         <span style="margin-left:8px;color:${{col}}">C</span> ${{fmt(c)}}`;
    }} catch (e) {{}}
  }});

</script>
</body>
</html>
"""

# ------------------------------
# SIDEBAR
# ------------------------------
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

    if "max_candles_state" not in st.session_state:
        st.session_state["max_candles_state"] = 2000

    max_candles = st.slider(
        "Quantos candles carregar (mais = mais histórico)",
        300, 5000, int(st.session_state["max_candles_state"]), 50
    )

    cA, cB = st.columns(2)
    with cA:
        if st.button("⬅️ Carregar +1000"):
            st.session_state["max_candles_state"] = min(5000, max_candles + 1000)
            st.rerun()
    with cB:
        if st.button("🧹 Reset"):
            st.session_state["max_candles_state"] = 2000
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
    vol_ma_period = st.slider("Período média do volume", 5, 100, 20, 1)

    st.divider()
    st.subheader("🎛️ Aparência")
    show_price_line = st.toggle("Linha do preço atual", value=True)
    show_crosshair = st.toggle("Crosshair (spikes)", value=True)
    chart_height = st.slider("Altura do gráfico", 620, 980, 860, 10)

    st.divider()
    debug_mode = st.toggle("🧪 Debug (mostrar erros)", value=False)

# ------------------------------
# COINS + SEARCH
# ------------------------------
ALL_USDT = fetch_binance_usdt_spot_pairs()

if "binance_pairs_error" in st.session_state:
    st.warning(
        "⚠️ Não consegui carregar a lista completa da Binance agora (Cloud pode bloquear). "
        "Usei uma lista reduzida temporária. Tente ‘Atualizar agora’ depois."
    )
    if st.sidebar.toggle("🧪 Debug lista Binance", value=False):
        st.sidebar.code(st.session_state["binance_pairs_error"])

search = st.text_input("Digite o ticker… (ex: BTC, PEPE, SOL)", value="").strip().upper()

if search:
    filtered = [p for p in ALL_USDT if p.startswith(search + "/") or p.split("/")[0].startswith(search)]
    if filtered:
        ALL_PICK = filtered
    else:
        ALL_PICK = ALL_USDT
        st.caption("Nada exato encontrado — mostrando lista completa.")
else:
    ALL_PICK = ALL_USDT

default_pair = "BTC/USDT" if "BTC/USDT" in ALL_PICK else (ALL_PICK[0] if ALL_PICK else "BTC/USDT")

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    ALL_PICK,
    default=[default_pair],
    max_selections=3
)

# ------------------------------
# TABS
# ------------------------------
tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])

# ------------------------------
# CROSSHAIR (Plotly native) — sem dtick aqui (dtick=1000 estava quebrando RSI)
# ------------------------------
def apply_crosshair(fig: go.Figure):
    fig.update_layout(hovermode="x unified", spikedistance=-1)
    fig.update_xaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikecolor="rgba(255,255,255,0.30)",
    )
    fig.update_yaxes(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikecolor="rgba(255,255,255,0.22)",
    )

# ------------------------------
# MAIN
# ------------------------------
for moeda in moedas:
    with st.expander(f"Detalhes de {moeda}", expanded=True):
        errors_map = {}

        try:
            df_full_utc, source, errors_map = build_dataset(moeda, timeframe, max_candles)
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
            st.warning("Poucos dados para renderizar. Tente outro timeframe.")
            st.caption(f"Fonte: {source}")
            continue

        # indicadores no FULL (pra RSI/MACD baterem)
        df_full_utc = add_indicators(
            df_full_utc,
            show_ma=show_ma,
            show_bb=show_bb,
            show_rsi=show_rsi,
            show_macd=show_macd,
            show_vol_ma=show_vol_ma,
            vol_ma_period=vol_ma_period
        )

        df_plot = to_local_naive(df_full_utc)

        ultimo = float(df_full_utc["close"].iloc[-1])
        first = float(df_full_utc["close"].iloc[0])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

        st.caption(f"📡 Fonte: **{source}**")
        st.markdown(
            f"<span class='badge'>Prazo: <b>{timeframe}</b></span>"
            f"<span class='badge'>Histórico: <b>{len(df_plot)} candles</b></span>"
            f"<span class='badge'>TZ: <b>{TZ_LOCAL}</b></span>",
            unsafe_allow_html=True
        )

        k1, k2, k3 = st.columns([1.6, 1, 1])
        k1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo), f"{var_pct:.2f}%")
        k2.metric("📈 Máxima (hist.)", fmt_price(moeda, float(df_full_utc["high"].max())))
        k3.metric("📉 Mínima (hist.)", fmt_price(moeda, float(df_full_utc["low"].min())))

        # ------------------------------
        # CHART (Auto-Y + Binance look)
        # ------------------------------
        with tab_chart:
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.78, 0.22],
                vertical_spacing=0.02
            )

            # Candles
            fig.add_trace(
                go.Candlestick(
                    x=df_plot["timestamp"],
                    open=df_plot["open"], high=df_plot["high"],
                    low=df_plot["low"], close=df_plot["close"],
                    increasing_line_color="#00C896",
                    decreasing_line_color="#FF4B4B",
                    increasing_fillcolor="rgba(0,200,150,0.92)",
                    decreasing_fillcolor="rgba(255,75,75,0.92)",
                    whiskerwidth=0.55,
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
                fig.add_hline(y=ultimo, line_dash="dot", opacity=0.5, row=1, col=1)

            # MAs
            if show_ma and "MA7" in df_plot.columns:
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA7"], mode="lines", opacity=0.95, name="MA7"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA25"], mode="lines", opacity=0.95, name="MA25"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA99"], mode="lines", opacity=0.95, name="MA99"), row=1, col=1)

            # BB
            if show_bb and "BB_UP" in df_plot.columns:
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_UP"], mode="lines", opacity=0.55, name="BB Upper"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_MID"], mode="lines", opacity=0.55, name="BB Mid"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_LOW"], mode="lines", opacity=0.55, name="BB Lower"), row=1, col=1)

            # Volume
            if volume_colored:
                vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df_plot["open"], df_plot["close"])]
            else:
                vol_colors = "rgba(255,255,255,0.18)"

            fig.add_trace(
                go.Bar(
                    x=df_plot["timestamp"],
                    y=df_plot["volume"],
                    marker_color=vol_colors,
                    opacity=0.16 if clean_volume else 0.40,
                    name="Volume",
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

            # IMPORTANTÍSSIMO: sem rangeselector (era o que virava “quadradinho branco”)
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06), row=2, col=1)
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06), row=1, col=1)

            fig.update_layout(
                template="plotly_dark",
                height=chart_height,
                margin=dict(l=10, r=10, t=10, b=10),
                dragmode="pan",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="left",
                    x=0,
                    font=dict(size=11)
                ),
                hovermode="x unified",
            )
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)", zerolinecolor="rgba(255,255,255,0.06)")
            fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)")

            if show_crosshair:
                apply_crosshair(fig)

            # Zoom inicial: SEMPRE 2 semanas
            x_start0, x_end0 = initial_range_last_two_weeks(df_plot, timeframe)

            # Render: Auto-Y + OHLC header interno (estilo Binance)
            st.components.v1.html(
                plotly_autoy_html(fig, height=chart_height, x_start=x_start0, x_end=x_end0),
                height=chart_height + 20,
                scrolling=False
            )

            st.markdown(
                "<div class='small-note'>Dica: arraste no gráfico (pan) e use scroll para zoom. "
                "O <b>Y</b> ajusta automaticamente ao período visível (estilo Binance). "
                "O topo mostra <b>OHLC</b> ao passar o mouse.</div>",
                unsafe_allow_html=True
            )

        # ------------------------------
        # RSI (aba separada)
        # ------------------------------
        with tab_rsi:
            if not show_rsi or "RSI" not in df_full_utc.columns:
                st.info("Ative RSI no menu lateral.")
            else:
                df_rsi = to_local_naive(df_full_utc)
                fr = go.Figure()
                fr.add_trace(go.Scatter(x=df_rsi["timestamp"], y=df_rsi["RSI"], mode="lines", name="RSI"))
                fr.add_hline(y=70, line_dash="dot", opacity=0.55)
                fr.add_hline(y=30, line_dash="dot", opacity=0.55)
                fr.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                fr.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                if show_crosshair:
                    apply_crosshair(fr)
                st.plotly_chart(fr, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

        # ------------------------------
        # MACD (aba separada)
        # ------------------------------
        with tab_macd:
            if not show_macd or "MACD" not in df_full_utc.columns:
                st.info("Ative MACD no menu lateral.")
            else:
                df_m = to_local_naive(df_full_utc)
                fm = go.Figure()
                fm.add_trace(go.Scatter(x=df_m["timestamp"], y=df_m["MACD"], mode="lines", name="MACD"))
                fm.add_trace(go.Scatter(x=df_m["timestamp"], y=df_m["SIGNAL"], mode="lines", name="Signal"))
                if "HIST" in df_m.columns:
                    fm.add_trace(go.Bar(x=df_m["timestamp"], y=df_m["HIST"], name="Hist", opacity=0.25))
                fm.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                fm.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                if show_crosshair:
                    apply_crosshair(fm)
                st.plotly_chart(fm, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

        # debug de erros de fonte
        if debug_mode and errors_map:
            st.markdown("**Debug (fontes):**")
            for k, v in errors_map.items():
                st.code(f"{k}: {v}", language="text")

st.info("✅ Modo híbrido ativo")


























