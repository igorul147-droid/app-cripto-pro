import time
import json
import requests
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

# ==============================
# PAGE
# ==============================
st.set_page_config(layout="wide", page_title="Análise Cripto PRO+")
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
st.title("🚀 Análise Cripto PRO+")

# ==============================
# SETTINGS
# ==============================
TZ_LOCAL = "America/Sao_Paulo"

# ==============================
# NETWORK (RETRY)
# ==============================
def request_json(url: str, params: dict, attempts: int = 3, base_sleep: float = 0.7):
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
# TIME HELPERS
# ==============================
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

# ==============================
# CORE HELPERS
# ==============================
def fmt_price(moeda: str, p: float, meme_coins: set[str]) -> str:
    return f"${p:,.6f}" if moeda in meme_coins else f"${p:,.2f}"

def symbol_compact(moeda: str) -> str:
    return moeda.replace("/", "")

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

def apply_time_window(df: pd.DataFrame, window_days: int) -> pd.DataFrame:
    if df.empty:
        return df
    end = df["timestamp"].max()
    start = end - pd.Timedelta(days=window_days)
    return df[df["timestamp"] >= start].copy()

def window_days_for_timeframe(tf: str) -> int:
    return {"1h": 2, "4h": 4, "1d": 7}.get(tf, 7)

def timeframe_freq(tf: str) -> str:
    return {"1h": "1H", "4h": "4H", "1d": "1D"}.get(tf, "1D")

# ==============================
# BINANCE: FULL USDT SPOT PAIRS (SEM FDUSD E USDC)
# ==============================
@st.cache_data(ttl=60 * 60)
def fetch_binance_usdt_spot_pairs() -> list[str]:
    """
    Lista de pares USDT Spot (TRADING + spot allowed).
    Sem FDUSD e USDC (por pedido).
    """
    endpoints = [
        "https://api.binance.com/api/v3/exchangeInfo",
        "https://data-api.binance.vision/api/v3/exchangeInfo",
        "https://api1.binance.com/api/v3/exchangeInfo",
        "https://api2.binance.com/api/v3/exchangeInfo",
        "https://api3.binance.com/api/v3/exchangeInfo",
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
                if quote != "USDT":
                    continue

                # Só por segurança — aqui não deve aparecer FDUSD/USDC pq é quote USDT
                if quote in ("FDUSD", "USDC"):
                    continue

                if base and quote:
                    out.append(f"{base}/{quote}")

            out = sorted(list(dict.fromkeys(out)))
            if out:
                return out
        except Exception as e:
            last_err = e

    st.session_state["binance_pairs_error"] = str(last_err) if last_err else "Falha desconhecida"
    # fallback mínimo
    return ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT", "PEPE/USDT", "TURBO/USDT"]

# ==============================
# BINANCE: OHLCV (PAGINADO) p/ HISTÓRICO MAIOR
# ==============================
def _binance_klines(symbol: str, interval: str, limit: int = 1000, endTime: int | None = None):
    """
    Klines com fallback de endpoints (resolve bloqueios do Streamlit Cloud).
    """
    endpoints = [
        "https://api.binance.com/api/v3/klines",
        "https://api1.binance.com/api/v3/klines",
        "https://api2.binance.com/api/v3/klines",
        "https://api3.binance.com/api/v3/klines",
        "https://data-api.binance.vision/api/v3/klines",
    ]

    params = {"symbol": symbol, "interval": interval, "limit": str(limit)}
    if endTime is not None:
        params["endTime"] = str(endTime)

    last_err = None
    for url in endpoints:
        try:
            return request_json(url, params=params, attempts=2, base_sleep=0.6)
        except Exception as e:
            last_err = e

    raise last_err

@st.cache_data(ttl=180)
def fetch_binance_ohlcv_paged(symbol: str, timeframe: str, candles_target: int = 4000) -> pd.DataFrame:
    """
    Binance permite até 1000 por request.
    Aqui buscamos até candles_target (ex: 4000) paginando pelo endTime.
    Isso te dá muito mais histórico pra arrastar pro passado mantendo candle bonito.
    """
    interval_map = {"1h": "1h", "4h": "4h", "1d": "1d"}
    interval = interval_map[timeframe]

    all_rows = []
    end_time = None  # ms
    remaining = int(candles_target)

    # evita loop infinito
    max_pages = int(np.ceil(candles_target / 1000)) + 3

    for _ in range(max_pages):
        batch_limit = 1000 if remaining > 1000 else max(200, remaining)
        j = _binance_klines(symbol, interval, limit=batch_limit, endTime=end_time)
        if not j:
            raise RuntimeError("Binance klines vazio (endpoint respondeu, mas veio sem candles).")

        # j é lista de listas
        # [ open_time, open, high, low, close, volume, close_time, ...]
        all_rows.extend(j)

        # próximo page: pega antes do primeiro candle desse lote
        first_open_time = int(j[0][0])
        end_time = first_open_time - 1

        remaining -= len(j)
        if remaining <= 0:
            break

        # se veio menos que pediu, acabou histórico
        if len(j) < batch_limit:
            break

        # respiro curto (evita 429)
        time.sleep(0.05)

    df = pd.DataFrame(all_rows, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore"
    ])
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
    df = normalize_ohlcv(df)
    return df

# ==============================
# BYBIT (1º prioridade no híbrido)
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

# ==============================
# COINGECKO (fallback final) — OHLC endpoint
# ==============================
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

    # volume via market_chart
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

# ==============================
# DATASET HYBRID
# ==============================
def build_dataset_hybrid(moeda: str, timeframe: str, candles_target: int):
    sym = symbol_compact(moeda)   # BTCUSDT
    base = moeda.split("/")[0]    # BTC
    window_days = window_days_for_timeframe(timeframe)

    errors = {}

    # 1) Bybit (rápido)
    try:
        # bybit limit máximo comum é 1000
        bybit_limit = min(1000, max(300, candles_target))
        df = fetch_bybit_ohlcv(sym, timeframe, bybit_limit)
        return df, "Bybit (spot)", window_days, errors
    except Exception as e:
        errors["Bybit"] = str(e)[:260]

    # 2) Binance (histórico grande com paginação)
    try:
        df = fetch_binance_ohlcv_paged(sym, timeframe, candles_target=candles_target)
        return df, "Binance (spot)", window_days, errors
    except Exception as e:
        errors["Binance"] = str(e)[:260]

    # 3) CoinGecko OHLC (fallback)
    try:
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
# UI HELPERS
# ==============================
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
    # Y do preço: ticks de 1000 em 1000 (BTC e outras coins "grandes")
    fig.update_yaxes(dtick=1000, row=1, col=1)
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikethickness=1, spikecolor="rgba(255,255,255,0.35)")
    fig.update_yaxes(fixedrange=False, row=1, col=1)  # preço
    fig.update_yaxes(fixedrange=True, row=2, col=1)   # volume (opcional, pra não ficar “puxando”)

# ==============================
# PLOTLY AUTO-Y (igual Binance) via HTML+JS
# ==============================
def plotly_autoy_html(fig, height=840):

    fig_dict = fig.to_plotly_json()
    payload = json.dumps(fig_dict, cls=PlotlyJSONEncoder)

    html = """
<div id="plotly_autoy" style="width:100%;height:""" + str(height) + """px;"></div>

<script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
<script>
(function () {

  const fig = """ + payload + """;
  const gd = document.getElementById('plotly_autoy');

  Plotly.newPlot(gd, fig.data, fig.layout, fig.config).then(() => {
    autoY();
  });

  let t = null;

  gd.on('plotly_relayout', (ev) => {

    const touchedX =
      ev['xaxis.range[0]'] ||
      ev['xaxis.range[1]'] ||
      ev['xaxis.autorange'] ||
      ev['xaxis.range'];

    if (!touchedX) return;

    clearTimeout(t);
    t = setTimeout(autoY, 60);
  });

  function parseDate(v) {
    if (!v) return null;
    const d = new Date(v);
    if (!isNaN(d.getTime())) return d.getTime();
    return null;
  }

  function getXRangeMs() {
    const xr = gd.layout?.xaxis?.range;
    if (xr && xr.length === 2) {
      const a = parseDate(xr[0]);
      const b = parseDate(xr[1]);
      if (a !== null && b !== null)
        return [Math.min(a,b), Math.max(a,b)];
    }
    return null;
  }

  function autoY() {

    let xr = getXRangeMs();
    if (!xr) {
      Plotly.relayout(gd, {'yaxis.autorange': true});
      return;
    }

    const x0 = xr[0];
    const x1 = xr[1];

    let ymin = Infinity;
    let ymax = -Infinity;

    for (const tr of gd.data) {

      if (tr.yaxis && tr.yaxis !== 'y') continue;
      if (tr.name && String(tr.name).toLowerCase().includes('volume')) continue;

      const xs = tr.x || [];

      if (tr.type === 'candlestick') {
        const lows = tr.low || [];
        const highs = tr.high || [];

        for (let i = 0; i < xs.length; i++) {
          const xi = parseDate(xs[i]);
          if (xi === null) continue;
          if (xi < x0 || xi > x1) continue;

          const lo = Number(lows[i]);
          const hi = Number(highs[i]);

          if (lo < ymin) ymin = lo;
          if (hi > ymax) ymax = hi;
        }
      }
      else {
        const ys = tr.y || [];

        for (let i = 0; i < xs.length; i++) {
          const xi = parseDate(xs[i]);
          if (xi === null) continue;
          if (xi < x0 || xi > x1) continue;

          const yi = Number(ys[i]);
          if (!isFinite(yi)) continue;

          if (yi < ymin) ymin = yi;
          if (yi > ymax) ymax = yi;
        }
      }
    }

    if (!isFinite(ymin) || !isFinite(ymax)) {
      Plotly.relayout(gd, {'yaxis.autorange': true});
      return;
    }

    const pad = (ymax - ymin) * 0.03;
    Plotly.relayout(gd, {
      'yaxis.autorange': false,
      'yaxis.range': [ymin - pad, ymax + pad]
    });
  }

})();
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
    candles_target = st.slider("Quantos candles carregar (mais = mais histórico)", 1000, 8000, 4000, 500)

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
    chart_height = st.slider("Altura do gráfico", 620, 980, 860, 10)

    st.divider()
    debug_mode = st.toggle("🧪 Debug (mostrar erros das fontes)", value=False)

# ==============================
# COINS LIST (Binance USDT)
# ==============================
ALL_USDT = fetch_binance_usdt_spot_pairs()

if "binance_pairs_error" in st.session_state:
    st.warning("⚠️ Não consegui carregar a lista completa da Binance agora. Usei lista reduzida temporária.")
    if debug_mode:
        st.code(st.session_state["binance_pairs_error"])

# meme coins (pra formatar casas)
meme_coins = {m for m in ALL_USDT if m.split("/")[0] in {"DOGE", "PEPE", "TURBO", "SHIB"}}

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    ALL_USDT,
    default=["BTC/USDT"] if "BTC/USDT" in ALL_USDT else [ALL_USDT[0]],
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
        if moeda in meme_coins:
            st.warning("🧪 Meme coin — alta volatilidade")

        try:
            df_full_utc, source, window_days, errors = build_dataset_hybrid(moeda, timeframe, candles_target=candles_target)
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

        # indicadores em UTC
        df_full_utc = add_indicators(df_full_utc, show_ma, show_bb, show_rsi, show_macd, show_vol_ma, vol_ma_period)

        # janela inicial (só pra abrir bonito, mas você pode arrastar pro passado)
        df_view_utc = apply_time_window(df_full_utc, window_days)

        # plot em horário Brasil
        df_plot = to_local_naive(df_full_utc)
        df_plot_view = to_local_naive(df_view_utc)

        ultimo = float(df_full_utc["close"].iloc[-1])
        first = float(df_view_utc["close"].iloc[0]) if len(df_view_utc) else float(df_full_utc["close"].iloc[0])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

        st.caption(f"📡 Fonte: **{source}**")
        st.markdown(
            f"<span class='badge'>Timeframe: <b>{timeframe}</b></span>"
            f"<span class='badge'>Janela inicial: <b>{window_days} dias</b></span>"
            f"<span class='badge'>Candles carregados: <b>{len(df_full_utc)}</b></span>"
            f"<span class='badge'>TZ: <b>{TZ_LOCAL}</b></span>",
            unsafe_allow_html=True
        )

        k1, k2, k3 = st.columns([1.6, 1, 1])
        k1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo, meme_coins), f"{var_pct:.2f}%")
        k2.metric("📈 Máxima (janela)", fmt_price(moeda, float(df_view_utc["high"].max()), meme_coins))
        k3.metric("📉 Mínima (janela)", fmt_price(moeda, float(df_view_utc["low"].min()), meme_coins))

        # ======================
        # CHART (AUTO-Y estilo Binance)
        # ======================
       with tab_chart:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.82, 0.18],
        vertical_spacing=0.02,
        row_titles=["Preço", "Volume"]
    )

    # ======================
    # Candles
    # ======================
    fig.add_trace(
        go.Candlestick(
            x=df_plot["timestamp"],
            open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"],
            increasing_line_color="#00C896",
            decreasing_line_color="#FF4B4B",
            increasing_fillcolor="rgba(0,200,150,0.88)",
            decreasing_fillcolor="rgba(255,75,75,0.88)",
            whiskerwidth=0.7,
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

    # ======================
    # MAs
    # ======================
    if show_ma and "MA7" in df_plot.columns:
        fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA7"], mode="lines", opacity=0.9, name="MA7"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA25"], mode="lines", opacity=0.9, name="MA25"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA99"], mode="lines", opacity=0.9, name="MA99"), row=1, col=1)

    # ======================
    # Bollinger
    # ======================
    if show_bb and "BB_UP" in df_plot.columns:
        fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_UP"], mode="lines", opacity=0.55, name="BB Upper"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_MID"], mode="lines", opacity=0.55, name="BB Mid"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_LOW"], mode="lines", opacity=0.55, name="BB Lower"), row=1, col=1)

    # ======================
    # Volume
    # ======================
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

    # ======================
    # Layout
    # ======================
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))

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
        apply_crosshair(fig)

    # ✅ Range inicial no X = janela atual (zoomado), MAS mantendo histórico todo carregado
    start0 = df_plot_view["timestamp"].min()
    end0 = df_plot_view["timestamp"].max()
    if pd.notna(start0) and pd.notna(end0):
        fig.update_xaxes(range=[start0, end0])

    # ✅ Render com Auto-Y (o Y vai seguir o range X visível)
    st.components.v1.html(
        plotly_autoy_html(fig, height=chart_height),
        height=chart_height + 30,
        scrolling=False
    )
    st.markdown(
        "<div class='small-note'>Dica: arraste no gráfico (pan) e use scroll para zoom. O Y se ajusta automaticamente ao X visível.</div>",
        unsafe_allow_html=True
    )

# ======================
# RSI (aba separada)
# ======================
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
        add_range_buttons(fr)
        if show_crosshair:
            apply_crosshair(fr)

        # ✅ Aqui era o erro: você estava renderizando "fig"
        st.plotly_chart(fr, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

# ======================
# MACD (aba separada)
# ======================
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
        add_range_buttons(fm)
        if show_crosshair:
            apply_crosshair(fm)

        st.plotly_chart(fm, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

st.info("✅ Modo híbrido ativo")























