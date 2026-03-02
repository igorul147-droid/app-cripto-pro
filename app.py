import time
import json
import math
import requests
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.utils import PlotlyJSONEncoder
from streamlit_autorefresh import st_autorefresh
 
# ==============================
# PAGE
# ==============================
st.set_page_config(layout="wide", page_title="Análise Cripto PRO — Premium")
 
st.markdown(
     """
     <style>
       .block container {padding top: 1.1rem;}
       div[data testid="stSidebar"] {border right: 1px solid rgba(255,255,255,0.06);}
       .stMetric {
         background: rgba(255,255,255,0.03);
         border: 1px solid rgba(255,255,255,0.06);
         padding: 14px;
         border radius: 14px;
       }
       .small note {opacity: .75; font size: 0.9rem;}
       .badge {
         display:inline block; padding:6px 10px; border radius:999px;
         border:1px solid rgba(255,255,255,0.12);
         background: rgba(255,255,255,0.04);
         font size: 0.9rem; opacity: 0.95;
         margin right: 8px;
       }
       code {font size: 0.9rem;}
       .muted {opacity: .8;}
     </style>
     """,
     unsafe_allow_html=True
 )
 
st.title("🚀 Análise Cripto PRO")
 
# ==============================
# SETTINGS / HELPERS
# ==============================
TZ_LOCAL = "America/Sao_Paulo"

def timeframe_freq(tf: str)  > str:
     return {"1h": "1H", "4h": "4H", "1d": "1D"}.get(tf, "1D")
 
def binance_interval(tf: str)  > str:
     return {"1h": "1h", "4h": "4h", "1d": "1d"}.get(tf, "1d")
 
def default_visible_candles(tf: str)  > int:
     # “abrir no máximo 2 semanas”
     # 1h: 14*24 = 336 | 4h: 14*6 = 84 | 1d: 14
     return {"1h": 336, "4h": 84, "1d": 14}.get(tf, 336)
 
def fmt_price(moeda: str, p: float, meme_coins: set[str])  > str:
     return f"${p:,.6f}" if moeda in meme_coins else f"${p:,.2f}"
 
def ensure_timestamp_utc(series: pd.Series)  > pd.Series:
     s = series
     if not pd.api.types.is_datetime64_any_dtype(s):
         s = pd.to_datetime(s, utc=True, errors="coerce")
     else:
         if getattr(s.dt, "tz", None) is None:
             s = s.dt.tz_localize("UTC")
         else:
             s = s.dt.tz_convert("UTC")
     return s
 
def to_local_naive(df: pd.DataFrame)  > pd.DataFrame:
     d = df.copy()
     d["timestamp"] = ensure_timestamp_utc(d["timestamp"]).dt.tz_convert(TZ_LOCAL).dt.tz_localize(None)
     return d
 
def normalize_ohlcv(df: pd.DataFrame)  > pd.DataFrame:
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
 
def symbol_compact(moeda: str)  > str:
     return moeda.replace("/", "")
 
def add_range_slider(fig):
     fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
 
def apply_crosshair(fig: go.Figure):
     # funciona tanto em subplots quanto figura simples
     fig.update_layout(hovermode="x unified", spikedistance= 1)
     fig.update_xaxes(
         showspikes=True, spikemode="across", spikesnap="cursor",
         spikethickness=1, spikecolor="rgba(255,255,255,0.35)",
     )
     fig.update_yaxes(
         showspikes=True, spikemode="across", spikesnap="cursor",
         spikethickness=1, spikecolor="rgba(255,255,255,0.25)",
     )
 
def compute_dtick_for_range(ymin: float, ymax: float)  > float | None:
     rng = float(ymax   ymin)
     if rng <= 0 or not np.isfinite(rng):
         return None
     # tenta ficar “de 1k em 1k” quando faz sentido
     if rng <= 25000:
         return 1000.0
     if rng <= 80000:
         return 5000.0
     if rng <= 200000:
         return 10000.0
     return None
 
# ==============================
# NETWORK (RETRY)
# ==============================
def request_json(url: str, params: dict, attempts: int = 3, base_sleep: float = 0.8):
     headers = {
         "User Agent": "Mozilla/5.0 (StreamlitApp)",
         "Accept": "application/json,text/plain,*/*",
     }
     last_err = None
     for i in range(attempts):
         try:
             r = requests.get(url, params=params, headers=headers, timeout=25)
             if r.status_code in (418, 429) or 500 <= r.status_code <= 599:
                 last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:250]}")
                 time.sleep(base_sleep * (i  1))
                 continue
             r.raise_for_status()
             return r.json()
         except Exception as e:
             last_err = e
             time.sleep(base_sleep * (i  1))
     raise last_err
 
# ==============================
# BINANCE SYMBOL LIST (USDT only, remove USDC/FDUSD)
# ==============================
@st.cache_data(ttl=60 * 60)
def fetch_binance_usdt_spot_pairs()  > list[str]:
     endpoints = [
         "https://api.binance.com/api/v3/exchangeInfo",
         "https://api1.binance.com/api/v3/exchangeInfo",
         "https://api2.binance.com/api/v3/exchangeInfo",
         "https://api3.binance.com/api/v3/exchangeInfo",
         "https://data api.binance.vision/api/v3/exchangeInfo",
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
 
                 # Só USDT. (já remove FDUSD/USDC automaticamente)
                 if quote != "USDT":
                     continue
                 if not base:
                     continue
 
                 out.append(f"{base}/{quote}")
 
             out = sorted(list(dict.fromkeys(out)))
             if out:
                 return out
         except Exception as e:
             last_err = e
 
     st.session_state["binance_pairs_error"] = str(last_err) if last_err else "Falha desconhecida"
     return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT", "PEPE/USDT", "TURBO/USDT"]
 
# ==============================
# DATA: BINANCE OHLCV WITH PAGINATION (HUGE HISTORY)
# ==============================
@st.cache_data(ttl=120)
def fetch_binance_ohlcv_paged(symbol: str, interval: str, total_limit: int)  > pd.DataFrame:
     """
     total_limit pode ser > 1000.
     Estratégia: puxa blocos de 1000 usando endTime e vai voltando.
     """
     url_candidates = [
         "https://api.binance.com/api/v3/klines",
         "https://api1.binance.com/api/v3/klines",
         "https://api2.binance.com/api/v3/klines",
         "https://api3.binance.com/api/v3/klines",
         "https://data api.binance.vision/api/v3/klines",
     ]
 
     limit_step = 1000
     remaining = int(total_limit)
     end_time_ms = None  # None = mais recente
     chunks: list[pd.DataFrame] = []
     last_err = None
 
     while remaining > 0:
         step = min(limit_step, remaining)
         params = {"symbol": symbol, "interval": interval, "limit": str(step)}
         if end_time_ms is not None:
             params["endTime"] = str(end_time_ms)
 
         got = False
         for url in url_candidates:
             try:
                 j = request_json(url, params=params, attempts=2, base_sleep=0.5)
                 if not j:
                     raise RuntimeError("Binance klines vazio")
 
                 df = pd.DataFrame(j, columns=[
                     "timestamp", "open", "high", "low", "close", "volume",
                     "closeTime", "qav", "numTrades", "tbbav", "tbqav", "ignore"
                 ])
                 df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
                 df = df[["timestamp", "open", "high", "low", "close", "volume"]]
                 df = normalize_ohlcv(df)
                 if df.empty:
                     raise RuntimeError("Binance klines normalizado vazio")
 
                 chunks.append(df)
                 # próximo bloco: termina 1ms antes do primeiro candle desse bloco
                 end_time_ms = int(df["timestamp"].min().value // 10**6)   1
 
                 remaining  = step
                 got = True
                 break
             except Exception as e:
                 last_err = e
 
         if not got:
             raise RuntimeError(f"Falha ao paginar Binance: {last_err}")
 
         # proteção: se começar a repetir timestamps, para
         if len(chunks) >= 2:
             if chunks[ 1]["timestamp"].max() >= chunks[ 2]["timestamp"].min():
                 break
 
     out = pd.concat(chunks, axis=0).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
     return out
 
# ==============================
# FALLBACK: BYBIT (if Binance totally blocked)
# ==============================
@st.cache_data(ttl=120)
def fetch_bybit_ohlcv(symbol: str, timeframe: str, limit: int)  > pd.DataFrame:
     interval_map = {"1h": "60", "4h": "240", "1d": "D"}
     url = "https://api.bybit.com/v5/market/kline"
     params = {
         "category": "spot",
         "symbol": symbol,
         "interval": interval_map[timeframe],
         "limit": str(min(limit, 1000)),
     }
     j = request_json(url, params=params)
     if str(j.get("retCode")) != "0":
         raise RuntimeError(f"Bybit retCode={j.get('retCode')} msg={j.get('retMsg')}")
     rows = j["result"]["list"]
     df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"])
     df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
     df = df[["timestamp", "open", "high", "low", "close", "volume"]]
     return normalize_ohlcv(df)
 
# ==============================
# INDICATORS
# ==============================
def add_indicators(df: pd.DataFrame, show_ma: bool, show_bb: bool, show_rsi: bool, show_macd: bool,
                    show_vol_ma: bool, vol_ma_period: int)  > pd.DataFrame:
     d = df.copy()
 
     if show_ma:
         d["MA7"] = d["close"].rolling(7).mean()
         d["MA25"] = d["close"].rolling(25).mean()
         d["MA99"] = d["close"].rolling(99).mean()
 
     if show_bb:
         mid = d["close"].rolling(20).mean()
         std = d["close"].rolling(20).std()
         d["BB_MID"] = mid
         d["BB_UP"] = mid  2 * std
         d["BB_LOW"] = mid   2 * std
 
     if show_rsi:
         delta = d["close"].diff()
         gain = delta.clip(lower=0)
         loss =  delta.clip(upper=0)
         avg_gain = gain.rolling(14).mean()
         avg_loss = loss.rolling(14).mean()
         rs = avg_gain / avg_loss
         d["RSI"] = 100   (100 / (1  rs))
 
     if show_macd:
         ema12 = d["close"].ewm(span=12, adjust=False).mean()
         ema26 = d["close"].ewm(span=26, adjust=False).mean()
         d["MACD"] = ema12   ema26
         d["SIGNAL"] = d["MACD"].ewm(span=9, adjust=False).mean()
         d["HIST"] = d["MACD"]   d["SIGNAL"]
 
     if show_vol_ma:
         d["VOL_MA"] = d["volume"].rolling(vol_ma_period).mean()
 
     return d
 
# ==============================
# PLOTLY AUTO Y HTML (BINANCE LIKE)
# ==============================
def plotly_autoy_html(fig: go.Figure, height: int, y_padding_ratio: float = 0.04)  > str:
     """
     Renderiza Plotly em HTML com:
       listeners para relayout (zoom/pan no X)
       recalcula Y baseado nos candles visíveis no X (low/high)
       ajusta dtick para ficar “bonito” (ex: 1k em 1k quando dá)
     """
     fig_dict = fig.to_plotly_json()
     payload = json.dumps(fig_dict, cls=PlotlyJSONEncoder)
 
     # JS sem f string “quebrando” com chaves: usa format apenas no final
     template = """
 <!doctype html>
 <html>
 <head>
   <meta charset="utf 8"/>
   <script src="https://cdn.plot.ly/plotly 2.30.0.min.js"></script>
   <style>
     html, body {{ margin:0; padding:0; background: transparent; }}
     #chart {{ width:100%; height:{height}px; }}
   </style>
 </head>
 <body>
   <div id="chart"></div>
   <script>
     const fig = {payload};
     const gd = document.getElementById('chart');
 
     function isNumber(x) {{
       return typeof x === 'number' && isFinite(x);
     }}
 
     // pega arrays de OHLC
     function getOHLC(fig) {{
       let x=null, low=null, high=null;
       for (const t of fig.data) {{
         if (t.type === 'candlestick' || t.type === 'ohlc') {{
           x = t.x; low = t.low; high = t.high;
           break;
         }}
       }}
       return {{x, low, high}};
     }}
 
     const ohlc = getOHLC(fig);
 
     function toMs(v) {{
       // Plotly manda datas como string ISO, ou Date, ou número
       if (v === null || v === undefined) return null;
       if (typeof v === 'number') return v;
       const d = new Date(v);
       const ms = d.getTime();
       return isNaN(ms) ? null : ms;
     }}
 
     function clampDtick(ymin, ymax) {{
       const rng = ymax   ymin;
       if (!isFinite(rng) || rng <= 0) return null;
       if (rng <= 25000) return 1000;
       if (rng <= 80000) return 5000;
       if (rng <= 200000) return 10000;
       return null;
     }}
 
     function autoYFromVisibleX(relayout) {{
       if (!ohlc.x || !ohlc.low || !ohlc.high) return;
 
       // tenta detectar range atual do X
       let x0 = relayout['xaxis.range[0]'];
       let x1 = relayout['xaxis.range[1]'];
 
       // se não veio, tenta pegar do layout atual
       if (!x0 || !x1) {{
         const xr = gd.layout?.xaxis?.range;
         if (xr && xr.length === 2) {{
           x0 = xr[0]; x1 = xr[1];
         }}
       }}
 
       const ms0 = toMs(x0);
       const ms1 = toMs(x1);
       if (!ms0 || !ms1) return;
 
       let ymin = Infinity;
       let ymax =  Infinity;
 
       // varre pontos no range (simples e robusto)
       for (let i = 0; i < ohlc.x.length; i) {{
         const ms = toMs(ohlc.x[i]);
         if (!ms) continue;
         if (ms < ms0 || ms > ms1) continue;
 
         const lo = ohlc.low[i];
         const hi = ohlc.high[i];
         if (isNumber(lo) && lo < ymin) ymin = lo;
         if (isNumber(hi) && hi > ymax) ymax = hi;
       }}
 
       if (!isFinite(ymin) || !isFinite(ymax) || ymax <= ymin) return;
 
       const pad = (ymax   ymin) * {pad};
       const y0 = ymin   pad;
       const y1 = ymax  pad;
 
       const dtick = clampDtick(y0, y1);
 
       const upd = {{
         'yaxis.range': [y0, y1],
       }};
 
       if (dtick) {{
         upd['yaxis.dtick'] = dtick;
       }} else {{
         upd['yaxis.dtick'] = null;
       }}
 
       // aplica sem re trigger infinito
       Plotly.relayout(gd, upd);
     }}
 
     // render inicial
     Plotly.newPlot(gd, fig.data, fig.layout, fig.config).then(() => {{
       // ajusta Y logo no load, baseado no X inicial
       autoYFromVisibleX({{}});
     }});
 
     // toda vez que mover/zoomer no X, recalcula Y
     gd.on('plotly_relayout', (ev) => {{
       // ignora relayout que foi só do Y (pra não loopar)
       if (ev && (ev['yaxis.range[0]'] || ev['yaxis.range[1]'] || ev['yaxis.range'])) return;
       autoYFromVisibleX(ev || {{}});
     }});
   </script>
 </body>
 </html>
 """
     return template.format(height=height, payload=payload, pad=float(y_padding_ratio))
 
# ==============================
# SIDEBAR CONTROLS
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
     st.subheader("🕓 Histórico (candles)")
 
     candles_to_load = st.slider(
         "Quantos candles carregar (mais = mais histórico)",
         min_value=300, max_value=5000, value=2000, step=100
     )
 
     visible_default = default_visible_candles(timeframe)
     candles_visible = st.slider(
         "Candles visíveis ao abrir (zoom inicial)",
         min_value=50, max_value=min(1200, candles_to_load),
         value=min(visible_default, candles_to_load),
         step=10
     )
 
     st.caption("Dica: arraste o gráfico pra voltar no tempo. O Y acompanha o X (auto).")
 
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
     chart_height = st.slider("Altura do gráfico", 620, 980, 860, 10)
 
     st.divider()
     debug_mode = st.toggle("🧪 Debug (mostrar erros)", value=False)
 
# ==============================
# COINS LIST  SEARCH
# ==============================
 ALL_USDT = fetch_binance_usdt_spot_pairs()
 
 if "binance_pairs_error" in st.session_state:
     st.warning(
         "⚠️ Não consegui carregar a lista completa da Binance agora. Usei uma lista reduzida temporária. "
         "Tente ‘Atualizar agora’ depois."
     )
     if st.sidebar.toggle("🧪 Debug lista Binance", value=False):
         st.sidebar.code(st.session_state["binance_pairs_error"])
 
 # meme coins (só pra formatação)
 meme_coins = {m for m in ALL_USDT if m.split("/")[0] in {"DOGE", "PEPE", "TURBO", "SHIB", "FLOKI", "BONK"}}
 
 search = st.text_input("Digite o ticker…", placeholder="Ex: BTC, PEPE, SOL").strip().upper()
 
 if search:
     filtered = [m for m in ALL_USDT if m.startswith(search  "/") or m.split("/")[0].startswith(search)]
 else:
     filtered = ALL_USDT
 
 # garante que a seleção atual não “suma” se o filtro esconder
 if "selected_pairs" not in st.session_state:
     st.session_state["selected_pairs"] = ["BTC/USDT"] if "BTC/USDT" in ALL_USDT else [ALL_USDT[0]]
 
 # opções finais: mantém selecionadas no topo  resto filtrado
 selected_now = [x for x in st.session_state["selected_pairs"] if x in ALL_USDT]
 options = selected_now  [x for x in filtered if x not in selected_now]
 
 moedas = st.multiselect(
     "Escolha até 3 criptos:",
     options=options,
     default=selected_now[:3] if selected_now else [options[0]],
     max_selections=3,
     key="selected_pairs",
 )
 
 # ==============================
 # DATASET BUILD (prefer Binance; fallback Bybit)
 # ==============================
 def build_dataset(moeda: str, timeframe: str, candles_to_load: int):
     sym = symbol_compact(moeda)  # BTCUSDT
     interval = binance_interval(timeframe)
     errors = {}
 
     # 1) Binance paginado (principal)
     try:
         df = fetch_binance_ohlcv_paged(sym, interval, candles_to_load)
         return df, "Binance (spot)", errors
     except Exception as e:
         errors["Binance"] = str(e)[:260]
 
     # 2) Bybit simples (fallback)
     try:
         df = fetch_bybit_ohlcv(sym, timeframe, min(candles_to_load, 1000))
         return df, "Bybit (spot)", errors
     except Exception as e:
         errors["Bybit"] = str(e)[:260]
 
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
             df_full_utc, source, errors = build_dataset(moeda, timeframe, candles_to_load)
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
 
         if df_full_utc.empty or len(df_full_utc) < 50:
             st.warning("Poucos dados para renderizar. Tente outro prazo.")
             st.caption(f"Fonte: {source}")
             if debug_mode and errors:
                 st.code(str(errors), language="text")
             continue
 
         # indicadores em UTC
         df_full_utc = add_indicators(
             df_full_utc,
             show_ma=show_ma, show_bb=show_bb, show_rsi=show_rsi, show_macd=show_macd,
             show_vol_ma=show_vol_ma, vol_ma_period=vol_ma_period
         )
 
         # versão local pro plot
         df_plot = to_local_naive(df_full_utc)
 
         # define janela inicial por "candles_visible"
         df_plot_view = df_plot.tail(int(candles_visible)).copy()
         if df_plot_view.empty:
             df_plot_view = df_plot.tail(200).copy()
 
         ultimo = float(df_full_utc["close"].iloc[ 1])
         first = float(df_full_utc["close"].iloc[ min(len(df_full_utc), int(candles_visible))])
         var_pct = ((ultimo   first) / first) * 100 if first else 0.0
 
         st.caption(f"📡 Fonte: **{source}**")
         st.markdown(
             f"<span class='badge'>Prazo: <b>{timeframe}</b></span>"
             f"<span class='badge'>Histórico carregado: <b>{len(df_plot)} candles</b></span>"
             f"<span class='badge'>Zoom inicial: <b>{len(df_plot_view)} candles</b></span>"
             f"<span class='badge'>TZ: <b>{TZ_LOCAL}</b></span>",
             unsafe_allow_html=True
         )
 
         k1, k2, k3 = st.columns([1.6, 1, 1])
         k1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo, meme_coins), f"{var_pct:.2f}%")
         k2.metric("📈 Máxima (zoom inicial)", fmt_price(moeda, float(df_full_utc["high"].tail(len(df_plot_view)).max()), meme_coins))
         k3.metric("📉 Mínima (zoom inicial)", fmt_price(moeda, float(df_full_utc["low"].tail(len(df_plot_view)).min()), meme_coins))
 
         # ======================
         # CHART (AUTO Y HTML)
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
                     whiskerwidth=0.7,
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
                 fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA7"], mode="lines", opacity=0.95, name="MA7"), row=1, col=1)
                 fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA25"], mode="lines", opacity=0.95, name="MA25"), row=1, col=1)
                 fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA99"], mode="lines", opacity=0.95, name="MA99"), row=1, col=1)
 
             # BB
             if show_bb and "BB_UP" in df_plot.columns:
                 fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_UP"], mode="lines", opacity=0.5, name="BB Upper"), row=1, col=1)
                 fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_MID"], mode="lines", opacity=0.5, name="BB Mid"), row=1, col=1)
                 fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_LOW"], mode="lines", opacity=0.5, name="BB Lower"), row=1, col=1)
 
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
                         opacity=0.8,
                         name="Vol MA",
                         hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Vol MA: %{y}<extra></extra>"
                     ),
                     row=2, col=1
                 )
 
             # layout
             add_range_slider(fig)
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
 
             # “abre” no zoom inicial (2 semanas, por padrão)
             start0 = df_plot_view["timestamp"].min()
             end0 = df_plot_view["timestamp"].max()
             if pd.notna(start0) and pd.notna(end0):
                 fig.update_xaxes(range=[start0, end0], row=1, col=1)
                 fig.update_xaxes(range=[start0, end0], row=2, col=1)
 
                 # y inicial já bem “colado” (antes do JS assumir)
                 ymin = float(df_plot_view["low"].min())
                 ymax = float(df_plot_view["high"].max())
                 pad = (ymax   ymin) * 0.04 if ymax > ymin else (ymax * 0.02)
                 y0, y1 = ymin   pad, ymax  pad
                 dtick = compute_dtick_for_range(y0, y1)
                 fig.update_yaxes(range=[y0, y1], dtick=dtick, row=1, col=1)
 
             # Render AUTO Y (Binance like)
             html = plotly_autoy_html(fig, height=chart_height, y_padding_ratio=0.035)
             st.components.v1.html(html, height=chart_height  40, scrolling=False)
             st.markdown(
                 "<div class='small note'>Dica: arraste (pan) e use scroll para zoom. O <b>Y acompanha automaticamente</b> o trecho visível no X.</div>",
                 unsafe_allow_html=True
             )
 
         # ======================
         # RSI (SEPARADO)
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
                 add_range_slider(fr)
                 fr.update_xaxes(range=[start0, end0] if pd.notna(start0) and pd.notna(end0) else None)
                 if show_crosshair:
                     apply_crosshair(fr)
                 st.plotly_chart(fr, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})
 
         # ======================
         # MACD (SEPARADO)
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
                 add_range_slider(fm)
                 fm.update_xaxes(range=[start0, end0] if pd.notna(start0) and pd.notna(end0) else None)
                 if show_crosshair:
                     apply_crosshair(fm)
                 st.plotly_chart(fm, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})
 
 st.info("✅ Modo híbrido ativo")
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
 
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

from crypto_app.charts import add_range_slider, apply_crosshair, plotly_autoy_html
from crypto_app.data import (
    binance_interval,
    fetch_binance_ohlcv_paged,
    fetch_binance_usdt_spot_pairs,
    fetch_bybit_ohlcv,
    symbol_compact,
)
from crypto_app.utils import (
    TZ_LOCAL,
    add_indicators,
    compute_dtick_for_range,
    default_visible_candles,
    fmt_price,
    to_local_naive,
)

st.set_page_config(layout="wide", page_title="Análise Cripto PRO — Premium")

st.markdown(
    """
    <style>
      .block container {padding top: 1.1rem;}
      div[data testid="stSidebar"] {border right: 1px solid rgba(255,255,255,0.06);}
      .stMetric {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
        padding: 14px;
        border radius: 14px;
      }
      .small note {opacity: .75; font size: 0.9rem;}
      .badge {
        display:inline block; padding:6px 10px; border radius:999px;
        border:1px solid rgba(255,255,255,0.12);
        background: rgba(255,255,255,0.04);
        font size: 0.9rem; opacity: 0.95;
        margin right: 8px;
      }
      code {font size: 0.9rem;}
      .muted {opacity: .8;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🚀 Análise Cripto PRO — Premium")

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
    st.subheader("🕓 Histórico (candles)")

    candles_to_load = st.slider(
        "Quantos candles carregar (mais = mais histórico)", min_value=300, max_value=5000, value=2000, step=100
    )

    visible_default = default_visible_candles(timeframe)
    candles_visible = st.slider(
        "Candles visíveis ao abrir (zoom inicial)",
        min_value=50,
        max_value=min(1200, candles_to_load),
        value=min(visible_default, candles_to_load),
        step=10,
    )

    st.caption("Dica: arraste o gráfico pra voltar no tempo. O Y acompanha o X (auto).")

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
    chart_height = st.slider("Altura do gráfico", 620, 980, 860, 10)

    st.divider()
    debug_mode = st.toggle("🧪 Debug (mostrar erros)", value=False)

ALL_USDT = fetch_binance_usdt_spot_pairs()
if not ALL_USDT:
    st.error("Não há pares disponíveis para carregar no momento. Tente novamente em instantes.")
    st.stop()

if "binance_pairs_error" in st.session_state:
    st.warning(
        "⚠️ Não consegui carregar a lista completa da Binance agora. Usei uma lista reduzida temporária. "
        "Tente ‘Atualizar agora’ depois."
    )
    if st.sidebar.toggle("🧪 Debug lista Binance", value=False):
        st.sidebar.code(st.session_state["binance_pairs_error"])

meme_coins = {m for m in ALL_USDT if m.split("/")[0] in {"DOGE", "PEPE", "TURBO", "SHIB", "FLOKI", "BONK"}}

search = st.text_input("Digite o ticker…", placeholder="Ex: BTC, PEPE, SOL").strip().upper()
filtered = [m for m in ALL_USDT if m.startswith(search  "/") or m.split("/")[0].startswith(search)] if search else ALL_USDT

if "selected_pairs" not in st.session_state:
    st.session_state["selected_pairs"] = ["BTC/USDT"] if "BTC/USDT" in ALL_USDT else [ALL_USDT[0]]

selected_now = [x for x in st.session_state["selected_pairs"] if x in ALL_USDT]
options = selected_now  [x for x in filtered if x not in selected_now]

moedas = st.multiselect(
    "Escolha até 3 criptos:",
    options=options,
    default=selected_now[:3] if selected_now else [options[0]],
    max_selections=3,
    key="selected_pairs",
)


def build_dataset(moeda: str, timeframe: str, candles_to_load: int):
    sym = symbol_compact(moeda)
    interval = binance_interval(timeframe)
    errors = {}

    try:
        df = fetch_binance_ohlcv_paged(sym, interval, candles_to_load)
        return df, "Binance (spot)", errors
    except Exception as err:
        errors["Binance"] = str(err)[:260]

    try:
        df = fetch_bybit_ohlcv(sym, timeframe, min(candles_to_load, 1000))
        return df, "Bybit (spot)", errors
    except Exception as err:
        errors["Bybit"] = str(err)[:260]

    raise RuntimeError("Falha geral de dados", errors)


tab_chart, tab_rsi, tab_macd = st.tabs(["📈 Gráfico", "📉 RSI", "📊 MACD"])

for moeda in moedas:
    with st.expander(f"Detalhes de {moeda}", expanded=True):
        if moeda in meme_coins:
            st.warning("🧪 Meme coin — alta volatilidade")

        try:
            df_full_utc, source, errors = build_dataset(moeda, timeframe, candles_to_load)
        except Exception as err:
            err_map = None
            if isinstance(err.args, tuple) and len(err.args) >= 2 and isinstance(err.args[1], dict):
                err_map = err.args[1]
            st.error(f"Não foi possível obter dados para {moeda}.")
            st.caption(f"Detalhe técnico: {type(err).__name__}")
            if debug_mode and err_map:
                st.markdown("**Erros por fonte:**")
                for k, v in err_map.items():
                    st.code(f"{k}: {v}", language="text")
            continue

        if df_full_utc.empty or len(df_full_utc) < 50:
            st.warning("Poucos dados para renderizar. Tente outro prazo.")
            st.caption(f"Fonte: {source}")
            if debug_mode and errors:
                st.code(str(errors), language="text")
            continue

        df_full_utc = add_indicators(
            df_full_utc,
            show_ma=show_ma,
            show_bb=show_bb,
            show_rsi=show_rsi,
            show_macd=show_macd,
            show_vol_ma=show_vol_ma,
            vol_ma_period=vol_ma_period,
        )
        df_plot = to_local_naive(df_full_utc)
        df_plot_view = df_plot.tail(int(candles_visible)).copy()
        if df_plot_view.empty:
            df_plot_view = df_plot.tail(200).copy()

        ultimo = float(df_full_utc["close"].iloc[ 1])
        first = float(df_full_utc["close"].iloc[ min(len(df_full_utc), int(candles_visible))])
        var_pct = ((ultimo   first) / first) * 100 if first else 0.0

        st.caption(f"📡 Fonte: **{source}**")
        st.markdown(
            f"<span class='badge'>Prazo: <b>{timeframe}</b></span>"
            f"<span class='badge'>Histórico carregado: <b>{len(df_plot)} candles</b></span>"
            f"<span class='badge'>Zoom inicial: <b>{len(df_plot_view)} candles</b></span>"
            f"<span class='badge'>TZ: <b>{TZ_LOCAL}</b></span>",
            unsafe_allow_html=True,
        )

        k1, k2, k3 = st.columns([1.6, 1, 1])
        k1.metric(f"💰 Preço atual {moeda}", fmt_price(moeda, ultimo, meme_coins), f"{var_pct:.2f}%")
        k2.metric("📈 Máxima (zoom inicial)", fmt_price(moeda, float(df_full_utc["high"].tail(len(df_plot_view)).max()), meme_coins))
        k3.metric("📉 Mínima (zoom inicial)", fmt_price(moeda, float(df_full_utc["low"].tail(len(df_plot_view)).min()), meme_coins))

        with tab_chart:
            fig = make_subplots(
                rows=2,
                cols=1,
                shared_xaxes=True,
                row_heights=[0.82, 0.18],
                vertical_spacing=0.02,
                row_titles=["Preço", "Volume"],
            )

            fig.add_trace(
                go.Candlestick(
                    x=df_plot["timestamp"],
                    open=df_plot["open"],
                    high=df_plot["high"],
                    low=df_plot["low"],
                    close=df_plot["close"],
                    name=moeda,
                    increasing_line_color="#00C896",
                    decreasing_line_color="#FF4B4B",
                    increasing_fillcolor="#00C896",
                    decreasing_fillcolor="#FF4B4B",
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

            if show_price_line:
                fig.add_hline(y=ultimo, line_dash="dot", opacity=0.5, row=1, col=1)

            if show_ma and "MA7" in df_plot.columns:
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA7"], mode="lines", opacity=0.95, name="MA7"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA25"], mode="lines", opacity=0.95, name="MA25"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA99"], mode="lines", opacity=0.95, name="MA99"), row=1, col=1)

            if show_bb and "BB_UP" in df_plot.columns:
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_UP"], mode="lines", opacity=0.5, name="BB Upper"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_MID"], mode="lines", opacity=0.5, name="BB Mid"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_LOW"], mode="lines", opacity=0.5, name="BB Lower"), row=1, col=1)

            vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df_plot["open"], df_plot["close"])] if volume_colored else "rgba(255,255,255,0.22)"

            fig.add_trace(
                go.Bar(
                    x=df_plot["timestamp"],
                    y=df_plot["volume"],
                    marker_color=vol_colors,
                    opacity=0.18 if clean_volume else 0.42,
                    name="Volume",
                    showlegend=True,
                    hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Volume: %{y}<extra></extra>",
                ),
                row=2,
                col=1,
            )

            if show_vol_ma and "VOL_MA" in df_plot.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df_plot["timestamp"],
                        y=df_plot["VOL_MA"],
                        mode="lines",
                        opacity=0.8,
                        name="Vol MA",
                        hovertemplate="<b>%{x|%d/%m/%Y %H:%M}</b><br>Vol MA: %{y}<extra></extra>",
                    ),
                    row=2,
                    col=1,
                )

            add_range_slider(fig)
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

            start0 = df_plot_view["timestamp"].min()
            end0 = df_plot_view["timestamp"].max()
            if pd.notna(start0) and pd.notna(end0):
                fig.update_xaxes(range=[start0, end0], row=1, col=1)
                fig.update_xaxes(range=[start0, end0], row=2, col=1)

                ymin = float(df_plot_view["low"].min())
                ymax = float(df_plot_view["high"].max())
                pad = (ymax   ymin) * 0.04 if ymax > ymin else (ymax * 0.02)
                y0, y1 = ymin   pad, ymax  pad
                dtick = compute_dtick_for_range(y0, y1)
                fig.update_yaxes(range=[y0, y1], dtick=dtick, row=1, col=1)

            html = plotly_autoy_html(fig, height=chart_height, y_padding_ratio=0.035)
            st.components.v1.html(html, height=chart_height  40, scrolling=False)
            st.markdown(
                "<div class='small note'>Dica: arraste (pan) e use scroll para zoom. O <b>Y acompanha automaticamente</b> o trecho visível no X.</div>",
                unsafe_allow_html=True,
            )

        with tab_rsi:
            if not show_rsi or "RSI" not in df_plot.columns:
                st.info("Ative RSI no menu lateral.")
            else:
                fr = go.Figure()
                fr.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["RSI"], mode="lines", name="RSI"))
                fr.add_hline(y=70, line_dash="dot", opacity=0.55)
                fr.add_hline(y=30, line_dash="dot", opacity=0.55)
                fr.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10))
                add_range_slider(fr)
                fr.update_xaxes(range=[start0, end0] if pd.notna(start0) and pd.notna(end0) else None)
                if show_crosshair:
                    apply_crosshair(fr)
                st.plotly_chart(fr, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

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
                add_range_slider(fm)
                fm.update_xaxes(range=[start0, end0] if pd.notna(start0) and pd.notna(end0) else None)
                if show_crosshair:
                    apply_crosshair(fm)
                st.plotly_chart(fm, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})

st.info("✅ Modo híbrido ativo")
