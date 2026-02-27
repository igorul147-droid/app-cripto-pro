import time
import json
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

# ==============================
# PAGE
# ==============================
st.set_page_config(layout="wide", page_title="Análise Cripto PRO+ - Premium")
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.1rem;}
      div[data-testid="stSidebar"] {border-right: 1px solid rgba(255,255,255,0.06);}
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
# HELPERS
# ==============================
TZ_LOCAL = "America/Sao_Paulo"

def request_json(url: str, params: dict, attempts: int = 3, base_sleep: float = 0.6):
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            if r.status_code in (418, 429) or 500 <= r.status_code <= 599:
                last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(base_sleep * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(base_sleep * (i + 1))
    raise last

def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "")

def fmt_price(p: float) -> str:
    return f"${p:,.6f}" if p < 1 else f"${p:,.2f}"

def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], unit="ms", utc=True)
    for c in ["open","high","low","close","volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["open","high","low","close"]).sort_values("timestamp").reset_index(drop=True)
    d["volume"] = d["volume"].fillna(0.0)
    return d

def to_local_naive(df_utc: pd.DataFrame) -> pd.DataFrame:
    d = df_utc.copy()
    d["timestamp"] = d["timestamp"].dt.tz_convert(TZ_LOCAL).dt.tz_localize(None)
    return d

def window_days_for_timeframe(tf: str) -> int:
    return {"1h": 2, "4h": 4, "1d": 7}.get(tf, 7)

def limit_for_timeframe(tf: str) -> int:
    # Binance max 1000
    return 1000

# ==============================
# BINANCE PAIRS (USDT only) - sem FDUSD e USDC
# ==============================
@st.cache_data(ttl=60 * 60)
def fetch_binance_usdt_spot_pairs() -> list[str]:
    endpoints = [
        "https://api.binance.com/api/v3/exchangeInfo",
        "https://data-api.binance.vision/api/v3/exchangeInfo",
        "https://api1.binance.com/api/v3/exchangeInfo",
        "https://api2.binance.com/api/v3/exchangeInfo",
    ]
    last_err = None
    for url in endpoints:
        try:
            j = request_json(url, {}, attempts=2, base_sleep=0.6)
            out = []
            for s in j.get("symbols", []):
                if s.get("status") != "TRADING":
                    continue
                if s.get("isSpotTradingAllowed") is not True:
                    continue
                if s.get("quoteAsset") != "USDT":
                    continue
                base = s.get("baseAsset")
                if not base:
                    continue
                out.append(f"{base}/USDT")
            out = sorted(list(dict.fromkeys(out)))
            return out
        except Exception as e:
            last_err = e

    st.session_state["binance_pairs_error"] = str(last_err) if last_err else "Falha desconhecida"
    return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT", "PEPE/USDT", "TURBO/USDT"]

# ==============================
# DATA (Binance OHLC)
# ==============================
@st.cache_data(ttl=120)
def fetch_binance_ohlcv(symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
    interval_map = {"1h": "1h", "4h": "4h", "1d": "1d"}
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval_map[timeframe], "limit": str(limit)}
    j = request_json(url, params)
    df = pd.DataFrame(j, columns=[
        "timestamp","open","high","low","close","volume",
        "closeTime","qav","numTrades","tbbav","tbqav","ignore"
    ])
    df = df[["timestamp","open","high","low","close","volume"]]
    return normalize_ohlcv(df)

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["MA7"] = d["close"].rolling(7).mean()
    d["MA25"] = d["close"].rolling(25).mean()
    d["MA99"] = d["close"].rolling(99).mean()
    d["VOL_MA"] = d["volume"].rolling(20).mean()
    return d

# ==============================
# PLOTLY AUTO-Y (Binance style) via HTML + JS
# ==============================
def plotly_autoy_html(fig: go.Figure, height: int = 850) -> str:
    fig_dict = fig.to_plotly_json()
    payload = json.dumps(fig_dict)

    # JS: ao mudar x-range (pan/zoom/rangeslider), recalcula y-range pelo low/high visíveis
    return f"""
    <div id="chart" style="width:100%;height:{height}px;"></div>
    <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
    <script>
      const fig = {payload};
      const gd = document.getElementById('chart');

      const config = {{
        scrollZoom: true,
        displaylogo: false,
        responsive: true,
        modeBarButtonsToRemove: ['lasso2d','select2d']
      }};

      function parseTime(t) {{
        // t pode vir como ISO string
        return new Date(t).getTime();
      }}

      function calcYRangeFromXRange(x0, x1) {{
        const data = fig.data || [];
        // assume 1º trace candlestick
        const cs = data.find(tr => tr.type === 'candlestick') || data[0];
        if (!cs || !cs.x || !cs.low || !cs.high) return null;

        const xs = cs.x;
        const lows = cs.low;
        const highs = cs.high;

        const start = parseTime(x0);
        const end = parseTime(x1);

        let lo = Infinity;
        let hi = -Infinity;

        for (let i = 0; i < xs.length; i++) {{
          const xt = parseTime(xs[i]);
          if (xt >= start && xt <= end) {{
            const l = lows[i];
            const h = highs[i];
            if (l < lo) lo = l;
            if (h > hi) hi = h;
          }}
        }}

        if (!isFinite(lo) || !isFinite(hi)) return null;

        const pad = (hi - lo) * 0.02; // 2% padding (estilo Binance)
        return [lo - pad, hi + pad];
      }}

      function applyAutoYFromLayout(layout) {{
        const xr = (layout.xaxis && layout.xaxis.range) ? layout.xaxis.range : null;
        if (!xr || xr.length < 2) return;

        const yr = calcYRangeFromXRange(xr[0], xr[1]);
        if (!yr) return;

        Plotly.relayout(gd, {{
          'yaxis.range': yr,
          'yaxis.autorange': false
        }});
      }}

      Plotly.newPlot(gd, fig.data, fig.layout, config).then(() => {{
        // AutoY inicial (se já tem range)
        applyAutoYFromLayout(fig.layout);

        gd.on('plotly_relayout', (e) => {{
          // pega range do x vindo do evento
          let x0 = e['xaxis.range[0]'];
          let x1 = e['xaxis.range[1]'];

          // se deu reset autoscale no x
          if (!x0 || !x1) {{
            const current = gd.layout && gd.layout.xaxis && gd.layout.xaxis.range;
            if (current && current.length === 2) {{
              x0 = current[0];
              x1 = current[1];
            }}
          }}

          if (x0 && x1) {{
            const yr = calcYRangeFromXRange(x0, x1);
            if (yr) {{
              Plotly.relayout(gd, {{
                'yaxis.range': yr,
                'yaxis.autorange': false
              }});
            }}
          }}
        }});
      }});
    </script>
    """

# ==============================
# SIDEBAR (CONTROLES)
# ==============================
with st.sidebar:
    st.header("⚙️ Controles")
    auto_refresh = st.toggle("🔄 Atualização automática", value=False)
    refresh_seconds = st.select_slider("Intervalo (segundos)", options=[30, 60, 120, 180], value=60)
    if auto_refresh:
        st_autorefresh(interval=refresh_seconds * 1000, key="refresh")

    st.divider()
    timeframe = st.selectbox("Prazo:", ["1h", "4h", "1d"], index=0)

# ==============================
# COINS (ALL BINANCE USDT)
# ==============================
ALL_USDT = fetch_binance_usdt_spot_pairs()

if "binance_pairs_error" in st.session_state:
    st.warning("⚠️ Binance bloqueou exchangeInfo agora. Usei lista reduzida temporária.")
    st.caption(st.session_state["binance_pairs_error"])

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    ALL_USDT,
    default=["BTC/USDT"] if "BTC/USDT" in ALL_USDT else [ALL_USDT[0]],
    max_selections=3
)

# ==============================
# MAIN
# ==============================
for moeda in moedas:
    sym = symbol_compact(moeda)
    window_days = window_days_for_timeframe(timeframe)
    limit = limit_for_timeframe(timeframe)

    with st.expander(f"Detalhes de {moeda}", expanded=True):
        df_utc = fetch_binance_ohlcv(sym, timeframe, limit=limit)
        df_utc = add_indicators(df_utc)
        df = to_local_naive(df_utc)

        # Janela inicial (2d/4d/7d) — só pra começar “bonito”
        end = df["timestamp"].max()
        start = end - pd.Timedelta(days=window_days)

        ultimo = float(df_utc["close"].iloc[-1])
        st.markdown(
            f"<span class='badge'>Timeframe: <b>{timeframe}</b></span>"
            f"<span class='badge'>Janela inicial: <b>{window_days} dias</b></span>"
            f"<span class='badge'>Candles carregados: <b>{len(df)}</b></span>",
            unsafe_allow_html=True
        )
        st.metric(f"💰 Preço atual {moeda}", fmt_price(ultimo))

        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.82, 0.18],
            vertical_spacing=0.03,
            row_titles=["Preço", "Volume"]
        )

        fig.add_trace(
            go.Candlestick(
                x=df["timestamp"],
                open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                increasing_line_color="#00C896",
                decreasing_line_color="#FF4B4B",
                name="Preço",
            ),
            row=1, col=1
        )

        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["MA7"], mode="lines", name="MA7", opacity=0.9), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["MA25"], mode="lines", name="MA25", opacity=0.9), row=1, col=1)
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["MA99"], mode="lines", name="MA99", opacity=0.9), row=1, col=1)

        vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df["open"], df["close"])]
        fig.add_trace(
            go.Bar(x=df["timestamp"], y=df["volume"], marker_color=vol_colors, opacity=0.22, name="Volume"),
            row=2, col=1
        )
        fig.add_trace(go.Scatter(x=df["timestamp"], y=df["VOL_MA"], mode="lines", name="Vol MA", opacity=0.7), row=2, col=1)

        fig.update_layout(
            template="plotly_dark",
            height=860,
            margin=dict(l=10, r=10, t=10, b=10),
            dragmode="pan",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )

        # X começa no range da janela (igual Binance: abre "zoomado" e você arrasta pro passado)
        fig.update_xaxes(
            range=[start, end],
            rangeslider=dict(visible=True, thickness=0.06),
            gridcolor="rgba(255,255,255,0.06)",
        )
        fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)")

        # Render com Auto-Y estilo Binance
        html = plotly_autoy_html(fig, height=860)
        st.components.v1.html(html, height=880, scrolling=False)

        st.markdown("<div class='small-note'>Dica: arraste no gráfico (pan) e use scroll para zoom. O Y vai se ajustar automaticamente ao X visível.</div>", unsafe_allow_html=True)

st.info("✅ Modo híbrido ativo")
















