import time
import json
import requests
import numpy as np
import pandas as pd
import streamlit as st

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.utils import PlotlyJSONEncoder

from streamlit_autorefresh import st_autorefresh


# =========================================================
# PAGE / THEME
# =========================================================
st.set_page_config(layout="wide", page_title="Análise Cripto PRO+ — Premium (Binance-like)")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.1rem; padding-bottom: 2.3rem;}
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
      .pairhint {opacity:.78; font-size:.9rem; margin-top:-6px;}
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🚀 Análise Cripto PRO+ — Premium")


# =========================================================
# SETTINGS / CONSTANTS
# =========================================================
TZ_LOCAL = "America/Sao_Paulo"

BINANCE_EXCHANGEINFO_ENDPOINTS = [
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

# Excluir tickers que você não quer na lista (conforme pediu)
EXCLUDE_BASE = {"FDUSD", "USDC"}

TF_TO_BINANCE = {"1h": "1h", "4h": "4h", "1d": "1d"}

MEME_BASE = {"DOGE", "PEPE", "TURBO", "SHIB", "BONK", "FLOKI"}


# =========================================================
# SIDEBAR CONTROLS
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
    st.subheader("🕰️ Histórico (candles)")
    max_candles = st.slider("Quantos candles carregar (mais = mais histórico)", 300, 5000, 2000, 50)
    initial_view = st.slider("Candles visíveis ao abrir (zoom inicial)", 60, 800, 200, 10)

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
    y_log = st.toggle("Escala log (Y) — igual Binance", value=False)

    y_dtick_opt = st.selectbox(
        "Passo do eixo Y (opcional)",
        ["Auto", "10", "50", "100", "500", "1000", "5000", "10000"],
        index=0
    )

    chart_height = st.slider("Altura do gráfico", 620, 980, 840, 10)

    st.divider()
    debug_mode = st.toggle("🧪 Mostrar erros técnicos", value=False)


# =========================================================
# HELPERS
# =========================================================
def fmt_price(pair: str, p: float) -> str:
    base = pair.split("/")[0]
    return f"${p:,.6f}" if base in MEME_BASE else f"${p:,.2f}"

def fmt_compact(n: float) -> str:
    # 1234 -> 1.23K / 1.2M etc
    if n is None or not np.isfinite(n):
        return "-"
    a = abs(n)
    if a >= 1e12: return f"{n/1e12:.2f}T"
    if a >= 1e9:  return f"{n/1e9:.2f}B"
    if a >= 1e6:  return f"{n/1e6:.2f}M"
    if a >= 1e3:  return f"{n/1e3:.2f}K"
    return f"{n:.2f}"

def ensure_timestamp_utc(s: pd.Series) -> pd.Series:
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

def request_json_any(urls: list[str], params: dict, attempts_each: int = 2, base_sleep: float = 0.5, timeout: int = 18):
    headers = {"User-Agent": "Mozilla/5.0 (StreamlitApp)", "Accept": "application/json,text/plain,*/*"}
    last_err = None
    for url in urls:
        for i in range(attempts_each):
            try:
                r = requests.get(url, params=params, headers=headers, timeout=timeout)
                if r.status_code in (418, 429) or 500 <= r.status_code <= 599:
                    last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:220]}")
                    time.sleep(base_sleep * (i + 1))
                    continue
                r.raise_for_status()
                return r.json(), url
            except Exception as e:
                last_err = e
                time.sleep(base_sleep * (i + 1))
    raise last_err


# =========================================================
# BINANCE PAIRS (USDT SPOT) — NO FDUSD/USDC
# =========================================================
@st.cache_data(ttl=60 * 60)
def fetch_binance_usdt_spot_pairs() -> tuple[list[str], str | None]:
    try:
        j, _ = request_json_any(BINANCE_EXCHANGEINFO_ENDPOINTS, params={}, attempts_each=2, base_sleep=0.6, timeout=18)
        symbols = j.get("symbols", [])
        out = []
        for s in symbols:
            if s.get("status") != "TRADING":
                continue
            if s.get("isSpotTradingAllowed") is not True:
                continue
            if s.get("quoteAsset") != "USDT":
                continue
            base = s.get("baseAsset")
            if not base:
                continue
            if base in EXCLUDE_BASE:
                continue
            out.append(f"{base}/USDT")
        out = sorted(list(dict.fromkeys(out)))
        if not out:
            return (["BTC/USDT", "ETH/USDT", "SOL/USDT"], "Lista vazia da Binance.")
        return out, None
    except Exception as e:
        return (
            ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT", "PEPE/USDT", "SHIB/USDT", "TURBO/USDT"],
            str(e),
        )


# =========================================================
# BINANCE OHLCV (PAGINATED) — BIG HISTORY
# =========================================================
@st.cache_data(ttl=120)
def fetch_binance_ohlcv_paginated(symbol: str, timeframe: str, limit_total: int) -> pd.DataFrame:
    interval = TF_TO_BINANCE.get(timeframe, "1h")
    limit_total = int(max(50, min(limit_total, 5000)))

    frames = []
    remaining = limit_total
    end_time = None  # ms
    safety_loops = 0

    while remaining > 0 and safety_loops < 10:
        batch = min(1000, remaining)
        params = {"symbol": symbol, "interval": interval, "limit": str(batch)}
        if end_time is not None:
            params["endTime"] = str(end_time)

        j, _ = request_json_any(BINANCE_KLINES_ENDPOINTS, params=params, attempts_each=2, base_sleep=0.4, timeout=18)
        if not isinstance(j, list) or len(j) == 0:
            break

        df = pd.DataFrame(j, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore"
        ])
        df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = normalize_ohlcv(df)
        if df.empty:
            break

        frames.append(df)

        first_ts = df["timestamp"].min()
        end_time = int(first_ts.value / 1_000_000) - 1  # ns -> ms - 1ms

        remaining -= len(df)
        safety_loops += 1
        time.sleep(0.05)

    if not frames:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    big = pd.concat(frames, ignore_index=True)
    big = big.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
    return big


# =========================================================
# DATASET (BINANCE ONLY = "IDÊNTICO")
# =========================================================
def build_dataset(pair: str, timeframe: str, candles: int) -> tuple[pd.DataFrame, str, dict]:
    errors = {}
    sym = pair.replace("/", "")
    try:
        df = fetch_binance_ohlcv_paginated(sym, timeframe, candles)
        if df.empty:
            raise RuntimeError("Binance retornou vazio.")
        return df, "Binance (spot)", errors
    except Exception as e:
        errors["Binance"] = str(e)[:260]
        raise RuntimeError("Falha geral de dados", errors)


# =========================================================
# CROSSHAIR (Plotly spikes)
# =========================================================
def apply_crosshair(fig: go.Figure):
    fig.update_layout(hovermode="x unified", spikedistance=-1)
    fig.update_xaxes(
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikecolor="rgba(255,255,255,0.35)",
    )
    fig.update_yaxes(
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikecolor="rgba(255,255,255,0.25)",
    )


# =========================================================
# AUTO-Y (Binance feel) via HTML component (pan/zoom => auto y)
# Supports LOG too.
# =========================================================
def plotly_autoy_html(fig: go.Figure, height: int) -> str:
    fig_json = json.dumps(fig.to_plotly_json(), cls=PlotlyJSONEncoder)

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
  <style>
    html, body {{
      margin: 0; padding: 0;
      background: transparent;
      overflow: hidden;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Helvetica, Arial;
    }}
    #chart {{ width: 100%; height: {height}px; }}
  </style>
</head>
<body>
  <div id="chart"></div>

  <script>
    const fig = {fig_json};
    const gd = document.getElementById('chart');

    Plotly.newPlot(gd, fig.data, fig.layout, fig.config).then(() => {{

      function toMs(x) {{
        if (typeof x === 'number') return x;
        const d = new Date(x);
        const t = d.getTime();
        return isNaN(t) ? null : t;
      }}

      function getVisibleXRange() {{
        const full = gd._fullLayout;
        if (!full || !full.xaxis) return null;
        const r = full.xaxis.range;
        if (r && r.length === 2) {{
          const a = toMs(r[0]);
          const b = toMs(r[1]);
          if (a != null && b != null) return [Math.min(a,b), Math.max(a,b)];
        }}
        return null;
      }}

      function computeYFromVisibleX() {{
        const xr = getVisibleXRange();
        if (!xr) return null;

        const xmin = xr[0], xmax = xr[1];
        let ymin = Infinity, ymax = -Infinity;
        let found = 0;

        for (const tr of gd.data) {{
          if (!tr || tr.type !== 'candlestick') continue;
          const xs = tr.x || [];
          const lows = tr.low || [];
          const highs = tr.high || [];
          const n = Math.min(xs.length, lows.length, highs.length);

          for (let i = 0; i < n; i++) {{
            const t = toMs(xs[i]);
            if (t == null) continue;
            if (t < xmin || t > xmax) continue;

            const lo = Number(lows[i]);
            const hi = Number(highs[i]);
            if (!isFinite(lo) || !isFinite(hi)) continue;

            ymin = Math.min(ymin, lo);
            ymax = Math.max(ymax, hi);
            found++;
          }}
        }}

        if (found < 5 || !isFinite(ymin) || !isFinite(ymax)) return null;

        const full = gd._fullLayout;
        const isLog = full && full.yaxis && full.yaxis.type === 'log';

        if (!isLog) {{
          const span = Math.max(1e-9, ymax - ymin);
          const pad = span * 0.08;
          return [ymin - pad, ymax + pad];
        }}

        // LOG: usa range em log10
        ymin = Math.max(ymin, 1e-12);
        ymax = Math.max(ymax, ymin * 1.000001);

        const logMin = Math.log10(ymin);
        const logMax = Math.log10(ymax);
        const spanL = Math.max(1e-9, logMax - logMin);
        const padL = spanL * 0.10;
        return [Math.pow(10, logMin - padL), Math.pow(10, logMax + padL)];
      }}

      let raf = null;

      function scheduleAutoY() {{
        if (raf) cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => {{
          const yr = computeYFromVisibleX();
          if (!yr) return;
          Plotly.relayout(gd, {{ 'yaxis.range': yr }});
        }});
      }}

      // primeira vez
      scheduleAutoY();

      gd.on('plotly_relayout', (ev) => {{
        const keys = Object.keys(ev || {{}}).join('|');
        if (
          keys.includes('xaxis.range') ||
          keys.includes('xaxis.autorange') ||
          keys.includes('xaxis.rangeslider') ||
          keys.includes('xaxis.range[0]') ||
          keys.includes('xaxis.range[1]')
        ) {{
          scheduleAutoY();
        }}
      }});
    }});
  </script>
</body>
</html>
"""
    return html


# =========================================================
# COINS PICKER (SEARCH + MULTISELECT)
# =========================================================
ALL_USDT, pairs_err = fetch_binance_usdt_spot_pairs()

if pairs_err:
    st.warning(
        "⚠️ Não consegui carregar a lista completa da Binance agora (cloud pode bloquear/limitar). "
        "Usei uma lista reduzida temporária. Clique em ‘Atualizar agora’ depois."
    )
    if debug_mode:
        st.code(pairs_err)

search = st.text_input("Buscar moeda (ex: BTC, PEPE, SOL):", value="", placeholder="Digite o ticker…").strip().upper()
filtered = ALL_USDT
if search:
    filtered = [p for p in ALL_USDT if search in p.split("/")[0]]

if not filtered:
    filtered = ["BTC/USDT"]

default_pair = "BTC/USDT" if "BTC/USDT" in filtered else filtered[0]

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    filtered,
    default=[default_pair],
    max_selections=3
)

meme_coins = {p for p in ALL_USDT if p.split("/")[0] in MEME_BASE}


# =========================================================
# TABS
# =========================================================
tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])


# =========================================================
# MAIN
# =========================================================
for pair in moedas:
    base = pair.split("/")[0]

    with st.expander(f"Detalhes de {pair}", expanded=True):
        if base in MEME_BASE:
            st.warning("🧪 Meme coin — volatilidade alta")

        # Data
        try:
            df_full_utc, source, errors = build_dataset(pair, timeframe, max_candles)
        except Exception as e:
            err_map = None
            if isinstance(e.args, tuple) and len(e.args) >= 2 and isinstance(e.args[1], dict):
                err_map = e.args[1]
            st.error(f"Não foi possível obter dados para {pair}.")
            st.caption(f"Detalhe técnico: {type(e).__name__}")
            if debug_mode and err_map:
                st.markdown("**Erros por fonte:**")
                for k, v in err_map.items():
                    st.code(f"{k}: {v}", language="text")
            continue

        if df_full_utc.empty or len(df_full_utc) < 80:
            st.warning("Poucos dados para renderizar. Tente outro prazo.")
            st.caption(f"Fonte: {source}")
            continue

        # Indicators
        df_full_utc = add_indicators(df_full_utc)
        df_plot = to_local_naive(df_full_utc)

        # Stats / Header OHLC (último candle)
        last = df_full_utc.iloc[-1]
        prev = df_full_utc.iloc[-2] if len(df_full_utc) >= 2 else last

        o = float(last["open"])
        h = float(last["high"])
        l = float(last["low"])
        c = float(last["close"])
        c_prev = float(prev["close"])
        vol = float(last["volume"])

        var_pct = ((c - c_prev) / c_prev) * 100 if c_prev else 0.0
        approx_quote_vol = vol * c  # aprox em USDT

        st.caption(f"📡 Fonte: **{source}**")
        st.markdown(
            f"<span class='badge'>Prazo: <b>{timeframe}</b></span>"
            f"<span class='badge'>Candles: <b>{len(df_full_utc)}</b></span>"
            f"<span class='badge'>TZ: <b>{TZ_LOCAL}</b></span>",
            unsafe_allow_html=True
        )

        # Header estilo Binance (OHLC + var)
        a1, a2, a3, a4, a5, a6 = st.columns([1.1, 1.1, 1.1, 1.1, 1.2, 1.4])
        a1.metric("Abertura", fmt_price(pair, o))
        a2.metric("Máximo", fmt_price(pair, h))
        a3.metric("Mínimo", fmt_price(pair, l))
        a4.metric("Fechamento", fmt_price(pair, c))
        a5.metric("Variação", f"{var_pct:.2f}%")
        a6.metric("Volume", f"{fmt_compact(vol)} ({base})  •  {fmt_compact(approx_quote_vol)} (USDT)")

        # =================================================
        # CHART
        # =================================================
        with tab_chart:
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.82, 0.18],
                vertical_spacing=0.02,
                row_titles=["Preço", "Volume"]
            )

            # Candles
            fig.add_trace(
                go.Candlestick(
                    x=df_plot["timestamp"],
                    open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"],
                    increasing_line_color="#00C896",
                    decreasing_line_color="#FF4B4B",
                    increasing_fillcolor="rgba(0,200,150,0.92)",
                    decreasing_fillcolor="rgba(255,75,75,0.92)",
                    whiskerwidth=0.65,
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
                fig.add_hline(y=c, line_dash="dot", opacity=0.55, row=1, col=1)

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

            # Volume colors
            if volume_colored:
                vol_colors = ["#00C896" if cl >= op else "#FF4B4B" for op, cl in zip(df_plot["open"], df_plot["close"])]
            else:
                vol_colors = "rgba(255,255,255,0.22)"

            fig.add_trace(
                go.Bar(
                    x=df_plot["timestamp"],
                    y=df_plot["volume"],
                    marker_color=vol_colors,
                    opacity=0.18 if clean_volume else 0.42,
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
                        opacity=0.80,
                        name="Vol MA",
                        hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Vol MA: %{y}<extra></extra>"
                    ),
                    row=2, col=1
                )

            # Layout feel
            fig.update_layout(
                template="plotly_dark",
                height=chart_height,
                margin=dict(l=10, r=10, t=8, b=10),
                dragmode="pan",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                hovermode="x unified",
                uirevision=f"{pair}-{timeframe}",  # mantém estado
            )
            fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
            fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)")

            # Only rangeslider (no rangeselector -> sem quadradinhos brancos)
            fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))

            # Crosshair
            if show_crosshair:
                apply_crosshair(fig)

            # LOG scale (Binance)
            if y_log:
                fig.update_yaxes(type="log", row=1, col=1)

            # Y dtick (opcional, tipo "1k em 1k") — ignora em LOG
            if (not y_log) and y_dtick_opt != "Auto":
                try:
                    dt = float(y_dtick_opt)
                    fig.update_yaxes(dtick=dt, row=1, col=1)
                except Exception:
                    pass

            # Zoom inicial: mostra "initial_view" candles do final, mas histórico inteiro carregado
            n = min(int(initial_view), len(df_plot))
            if n >= 10:
                x_start = df_plot["timestamp"].iloc[-n]
                x_end = df_plot["timestamp"].iloc[-1]
                fig.update_xaxes(range=[x_start, x_end], row=1, col=1)

            # Config
            fig.update_layout(
                modebar_remove=["lasso2d", "select2d"]
            )
            fig_config = {
                "scrollZoom": True,
                "displaylogo": False,
                "responsive": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"],
            }

            # Render com Auto-Y (Binance-like)
            st.components.v1.html(
                plotly_autoy_html(fig, height=chart_height),
                height=chart_height + 30,
                scrolling=False
            )

            st.markdown(
                "<div class='small-note'>Dica: arraste (pan) e use scroll para zoom. O eixo Y ajusta automaticamente ao trecho visível (estilo Binance).</div>",
                unsafe_allow_html=True
            )

        # =================================================
        # RSI
        # =================================================
        with tab_rsi:
            if not show_rsi or "RSI" not in df_full_utc.columns:
                st.info("Ative RSI no menu lateral.")
            else:
                df_rsi = to_local_naive(df_full_utc)
                fr = go.Figure()
                fr.add_trace(go.Scatter(x=df_rsi["timestamp"], y=df_rsi["RSI"], mode="lines", name="RSI"))
                fr.add_hline(y=70, line_dash="dot", opacity=0.55)
                fr.add_hline(y=30, line_dash="dot", opacity=0.55)
                fr.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=8, b=10))
                fr.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                if show_crosshair:
                    apply_crosshair(fr)
                st.plotly_chart(fr, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

        # =================================================
        # MACD
        # =================================================
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
                fm.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=8, b=10))
                fm.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
                if show_crosshair:
                    apply_crosshair(fm)
                st.plotly_chart(fm, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

st.info("✅ Modo híbrido ativo")

























