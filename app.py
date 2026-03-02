import time

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

from crypto_app.charts import apply_crosshair, plotly_autoy_html
from crypto_app.data import fetch_binance_usdt_spot_pairs, symbol_compact, fetch_binance_klines
from crypto_app.realtime import RealtimeStore
from crypto_app.utils import (
    TZ_LOCAL,
    add_indicators,
    compute_dtick_for_range,
    default_visible_candles,
    fmt_price,
    to_local_naive,
)

st.set_page_config(layout="wide", page_title="Análise Cripto PRO+")

st.html("""
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
</style>
""")

st.title("🚀 Análise Cripto PRO+")

with st.sidebar:
    st.header("⚙️ Controles")

    ui_refresh_on = st.toggle("🔄 Refresh UI (1s)", value=True)
    if ui_refresh_on:
        st_autorefresh(interval=1000, key="ui_refresh")

    st.divider()
    st.caption("Modo PRO: candle 1m ao vivo via WebSocket + Time & Trades.")

    candles_to_load = st.slider("Histórico inicial (candles 1m)", 300, 5000, 1200, 100)
    candles_visible = st.slider(
        "Zoom inicial (candles)",
        50,
        min(1200, candles_to_load),
        min(default_visible_candles("1h"), candles_to_load),
        10,
    )

    st.divider()
    st.subheader("📌 Indicadores")
    show_ma = st.toggle("MA 7/25/99", value=True)
    show_bb = st.toggle("Bollinger (20, 2)", value=False)
    show_rsi = st.toggle("RSI (14)", value=True)
    show_macd = st.toggle("MACD (12/26/9)", value=True)

    st.divider()
    st.subheader("📼 Tape")
    show_tape = st.toggle("Mostrar Time & Trades", value=True)
    tape_size = st.slider("Trades visíveis", 20, 300, 80, 10)

    st.divider()
    st.subheader("🎛️ Aparência")
    show_crosshair = st.toggle("Crosshair", value=True)
    chart_height = st.slider("Altura do gráfico", 620, 980, 860, 10)

ALL_USDT = fetch_binance_usdt_spot_pairs()
if not ALL_USDT:
    st.error("Não há pares disponíveis para carregar no momento.")
    st.stop()

search = st.text_input("Digite o ticker…", placeholder="Ex: BTC, PEPE, SOL").strip().upper()
filtered = [m for m in ALL_USDT if m.startswith(search + "/") or m.split("/")[0].startswith(search)] if search else ALL_USDT

if "selected_pairs" not in st.session_state:
    st.session_state["selected_pairs"] = ["BTC/USDT"] if "BTC/USDT" in ALL_USDT else [ALL_USDT[0]]

selected_now = [x for x in st.session_state["selected_pairs"] if x in ALL_USDT]
options = selected_now + [x for x in filtered if x not in selected_now]

moedas = st.multiselect("Escolha até 3 criptos:", options=options, max_selections=3, key="selected_pairs")

if not moedas:
    st.info("Selecione ao menos 1 moeda.")
    st.stop()

if "rt_stores" not in st.session_state:
    st.session_state["rt_stores"] = {}

rt_stores: dict = st.session_state["rt_stores"]

# remove stores não selecionadas
wanted = {symbol_compact(m) for m in moedas}
for sym in list(rt_stores.keys()):
    if sym not in wanted:
        try:
            rt_stores[sym].stop()
        except Exception:
            pass
        rt_stores.pop(sym, None)

# cria stores faltantes
for moeda in moedas:
    sym = symbol_compact(moeda)
    if sym not in rt_stores:
        base_df = fetch_binance_klines(sym, interval="1m", limit=int(candles_to_load))
        rt = RealtimeStore(sym, base_df_ohlcv=base_df, max_trades=300)
        rt.start()
        rt_stores[sym] = rt

col_main, col_side = st.columns([3.5, 1.2], gap="large")

for moeda in moedas:
    sym = symbol_compact(moeda)
    rt = rt_stores[sym]
    df_full_utc, trades, meta = rt.snapshot()

    if df_full_utc.empty:
        st.warning(f"Aguardando dados WS para {moeda}…")
        continue

    df_full_utc = add_indicators(
        df_full_utc,
        show_ma=show_ma,
        show_bb=show_bb,
        show_rsi=show_rsi,
        show_macd=show_macd,
        show_vol_ma=True,
        vol_ma_period=20,
    )

    df_plot = to_local_naive(df_full_utc)
    df_plot_view = df_plot.tail(int(candles_visible)).copy() if len(df_plot) >= 10 else df_plot.copy()

    ultimo = float(df_full_utc["close"].iloc[-1])
    first = float(df_full_utc["close"].iloc[-min(len(df_full_utc), int(candles_visible))])
    var_pct = ((ultimo - first) / first) * 100 if first else 0.0

    with col_main:
        st.markdown(
            f"<span class='badge'>🪙 <b>{moeda}</b></span>"
            f"<span class='badge'>TF: <b>1m</b></span>"
            f"<span class='badge'>Hist: <b>{len(df_plot)}</b></span>"
            f"<span class='badge'>TZ: <b>{TZ_LOCAL}</b></span>",
            unsafe_allow_html=True,
        )

        k1, k2, k3 = st.columns([1.6, 1, 1])
        k1.metric(f"💰 Preço {moeda}", fmt_price(moeda, ultimo, set()), f"{var_pct:.2f}%")
        k2.metric("📈 Máxima (zoom)", f"{float(df_full_utc['high'].tail(len(df_plot_view)).max()):,.2f}")
        k3.metric("📉 Mínima (zoom)", f"{float(df_full_utc['low'].tail(len(df_plot_view)).min()):,.2f}")

        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            row_heights=[0.82, 0.18],
            vertical_spacing=0.02,
        )

        fig.add_trace(
            go.Candlestick(
                x=df_plot["timestamp"],
                open=df_plot["open"],
                high=df_plot["high"],
                low=df_plot["low"],
                close=df_plot["close"],
                name=moeda,
                whiskerwidth=0.3,
                increasing=dict(line=dict(width=1.2), fillcolor="#00C896"),
                decreasing=dict(line=dict(width=1.2), fillcolor="#FF4B4B"),
                showlegend=True,
            ),
            row=1,
            col=1,
        )

        if show_ma and "MA7" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA7"], mode="lines", opacity=0.9, name="MA7"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA25"], mode="lines", opacity=0.9, name="MA25"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["MA99"], mode="lines", opacity=0.9, name="MA99"), row=1, col=1)

        if show_bb and "BB_UP" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_UP"], mode="lines", opacity=0.35, name="BB Upper"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_MID"], mode="lines", opacity=0.35, name="BB Mid"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["BB_LOW"], mode="lines", opacity=0.35, name="BB Lower"), row=1, col=1)

        vol_colors = ["#00C896" if c >= o else "#FF4B4B" for o, c in zip(df_plot["open"], df_plot["close"])]
        fig.add_trace(
            go.Bar(
                x=df_plot["timestamp"],
                y=df_plot["volume"],
                marker_color=vol_colors,
                opacity=0.28,
                name="Volume",
                showlegend=True,
            ),
            row=2,
            col=1,
        )
        if "VOL_MA" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["VOL_MA"], mode="lines", opacity=0.7, name="Vol MA"), row=2, col=1)

        fig.update_layout(
            template="plotly_dark",
            height=chart_height,
            margin=dict(l=10, r=10, t=10, b=10),
            dragmode="pan",
            hovermode="x unified",
            xaxis_rangeslider_visible=False,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.06)", zeroline=False)
        fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.06)", zeroline=False, side="right")

        if show_crosshair:
            apply_crosshair(fig)

        start0 = df_plot_view["timestamp"].min()
        end0 = df_plot_view["timestamp"].max()
        if pd.notna(start0) and pd.notna(end0):
            fig.update_xaxes(range=[start0, end0], row=1, col=1)
            fig.update_xaxes(range=[start0, end0], row=2, col=1)

            ymin = float(df_plot_view["low"].min())
            ymax = float(df_plot_view["high"].max())
            pad = (ymax - ymin) * 0.04 if ymax > ymin else (ymax * 0.02)
            y0, y1 = ymin - pad, ymax + pad
            dtick = compute_dtick_for_range(y0, y1)
            fig.update_yaxes(range=[y0, y1], dtick=dtick, row=1, col=1)

        html = plotly_autoy_html(fig, height=chart_height, y_padding_ratio=0.035)
        st.components.v1.html(html, height=chart_height + 40, scrolling=False)

        age = time.time() - float(meta.get("last_update_ts") or time.time())
        ws_err = meta.get("last_ws_error")
        if ws_err:
            st.warning(f"WS status: {ws_err}")
        else:
            st.caption(f"WS ok • atualização ~{age:.1f}s atrás")

    with col_side:
        if show_tape:
            st.subheader("📼 Time & Trades")
            if trades:
                tdf = pd.DataFrame(trades).head(int(tape_size))
                tdf["hora"] = tdf["time"].dt.tz_convert(TZ_LOCAL).dt.strftime("%H:%M:%S")
                tdf["lado"] = tdf["is_maker"].map(lambda x: "SELL" if x else "BUY")
                tdf = tdf[["hora", "lado", "price", "qty"]]
                st.dataframe(tdf, use_container_width=True, height=520)
            else:
                st.info("Aguardando trades…")
