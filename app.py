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
      .muted {opacity: .8;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🚀 Análise Cripto PRO+ — Premium")

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
filtered = [m for m in ALL_USDT if m.startswith(search + "/") or m.split("/")[0].startswith(search)] if search else ALL_USDT

if "selected_pairs" not in st.session_state:
    st.session_state["selected_pairs"] = ["BTC/USDT"] if "BTC/USDT" in ALL_USDT else [ALL_USDT[0]]

selected_now = [x for x in st.session_state["selected_pairs"] if x in ALL_USDT]
options = selected_now + [x for x in filtered if x not in selected_now]

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

        ultimo = float(df_full_utc["close"].iloc[-1])
        first = float(df_full_utc["close"].iloc[-min(len(df_full_utc), int(candles_visible))])
        var_pct = ((ultimo - first) / first) * 100 if first else 0.0

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
                pad = (ymax - ymin) * 0.04 if ymax > ymin else (ymax * 0.02)
                y0, y1 = ymin - pad, ymax + pad
                dtick = compute_dtick_for_range(y0, y1)
                fig.update_yaxes(range=[y0, y1], dtick=dtick, row=1, col=1)

            html = plotly_autoy_html(fig, height=chart_height, y_padding_ratio=0.035)
            st.components.v1.html(html, height=chart_height + 40, scrolling=False)
            st.markdown(
                "<div class='small-note'>Dica: arraste (pan) e use scroll para zoom. O <b>Y acompanha automaticamente</b> o trecho visível no X.</div>",
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
