import streamlit as st
import pandas as pd
import ccxt
import plotly.graph_objs as go
from streamlit_autorefresh import st_autorefresh
import datetime
import requests
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="App Cripto PRO+")
st.title("🚀 Análise Cripto PRO+")

# =============================
# CONTROLES (mais estável no Cloud)
# =============================
auto_refresh = st.toggle("🔄 Atualização automática", value=False)
refresh_seconds = st.select_slider("Intervalo (segundos)", options=[60, 120, 180, 300], value=120)

if auto_refresh:
    st_autorefresh(interval=refresh_seconds * 1000, key="refresh")

# Seleção de moedas
moedas = st.multiselect(
    "Escolha até 3 criptos:",
    ["BTC/USDT", "ETH/USDT", "ADA/USDT", "DOGE/USDT", "PEPE/USDT", "TURBO/USDT", "NEIRO/USDT"],
    default=["BTC/USDT"],
    max_selections=3
)

timeframe = st.selectbox("Escolha o timeframe:", ["1d", "4h", "1h"])

indicadores = st.multiselect(
    "Indicadores:",
    ["SMA20", "RSI", "MACD", "Bollinger Bands"],
    default=["SMA20", "RSI", "MACD", "Bollinger Bands"]
)

# Meme coins
meme_coins = ["DOGE/USDT", "PEPE/USDT", "TURBO/USDT", "NEIRO/USDT"]

# =============================
# EXCHANGE (criado 1x e reutilizado)
# =============================
@st.cache_resource
def get_exchange():
    return ccxt.binance({"enableRateLimit": True})

exchange = get_exchange()

# =============================
# FUNÇÃO DE DADOS (BINANCE + FALLBACK) com CACHE
# =============================
@st.cache_data(ttl=60)
def fetch_ohlcv_safe(symbol, timeframe="1d"):
    # 1) Binance (principal)
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df, "Binance"
    except Exception:
        pass

    # 2) CoinGecko (fallback)
    try:
        coin_id = symbol.split("/")[0].lower()
        days_map = {"1d": 90, "4h": 30, "1h": 7}
        days = days_map.get(timeframe, 90)

        url = "https://api.coingecko.com/api/v3/coins/{}/market_chart".format(coin_id)
        params = {"vs_currency": "usd", "days": days}

        headers = {"User-Agent": "Mozilla/5.0 (StreamlitApp)"}
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()

        df = pd.DataFrame(data['prices'], columns=['timestamp', 'close'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['open'] = df['close']
        df['high'] = df['close']
        df['low'] = df['close']
        df['volume'] = 0

        return df, "CoinGecko"
    except Exception:
        return None, None

# =============================
# LOOP PRINCIPAL
# =============================
for moeda in moedas:
    # expanded=False para evitar bug/instabilidade com refresh + plotly no Cloud
    with st.expander(f"Detalhes de {moeda}", expanded=False):

        if moeda in meme_coins:
            st.warning("🧪 Meme coin — alta volatilidade")

        df_full, source = fetch_ohlcv_safe(moeda, timeframe)

        if df_full is None:
            st.error(f"Não foi possível obter dados para {moeda}.")
            continue

        st.info(f"Dados obtidos de: {source}")

        now = datetime.datetime.now()
        df_mes = df_full[
            (df_full['timestamp'].dt.month == now.month) &
            (df_full['timestamp'].dt.year == now.year)
        ].copy()

        if df_mes.empty:
            st.warning(f"Não há dados para {moeda} no mês atual.")
            continue

        # =============================
        # ESTATÍSTICAS DO PERÍODO
        # =============================
        preco_inicial = df_mes['close'].iloc[0]
        preco_final = df_mes['close'].iloc[-1]
        variacao_pct = ((preco_final - preco_inicial) / preco_inicial) * 100
        variacao_cor = "green" if variacao_pct >= 0 else "red"

        max_periodo = df_mes['high'].max()
        min_periodo = df_mes['low'].min()
        ultimo_preco = df_mes['close'].iloc[-1]

        st.metric(
            label=f"💰 Preço atual {moeda}",
            value=f"${ultimo_preco:,.2f}",
            delta=f"{variacao_pct:.2f}%"
        )

        st.markdown(
            f"### 📊 Variação do período: "
            f"<span style='color:{variacao_cor}'>{variacao_pct:.2f}%</span>",
            unsafe_allow_html=True
        )

        if moeda in meme_coins:
            st.write(f"🔼 Máxima: {max_periodo:.6f}")
            st.write(f"🔽 Mínima: {min_periodo:.6f}")
        else:
            st.write(f"🔼 Máxima: {max_periodo:.2f}")
            st.write(f"🔽 Mínima: {min_periodo:.2f}")

        # =============================
        # INDICADORES
        # =============================
        ultimo_rsi = None

        if "SMA20" in indicadores:
            df_mes['SMA20'] = df_mes['close'].rolling(20).mean()

        if "RSI" in indicadores:
            delta = df_mes['close'].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss
            df_mes['RSI'] = 100 - (100 / (1 + rs))

            ultimo_rsi = df_mes['RSI'].iloc[-1]
            if pd.notna(ultimo_rsi):
                if ultimo_rsi > 70:
                    st.warning(f"⚠ RSI em Sobrecompra ({ultimo_rsi:.2f})")
                elif ultimo_rsi < 30:
                    st.warning(f"⚠ RSI em Sobrevenda ({ultimo_rsi:.2f})")

        if "Bollinger Bands" in indicadores:
            df_mes['BB_middle'] = df_mes['close'].rolling(20).mean()
            df_mes['BB_std'] = df_mes['close'].rolling(20).std()
            df_mes['BB_upper'] = df_mes['BB_middle'] + 2 * df_mes['BB_std']
            df_mes['BB_lower'] = df_mes['BB_middle'] - 2 * df_mes['BB_std']

        if "MACD" in indicadores:
            ema12 = df_mes['close'].ewm(span=12, adjust=False).mean()
            ema26 = df_mes['close'].ewm(span=26, adjust=False).mean()
            df_mes['MACD'] = ema12 - ema26
            df_mes['MACD_signal'] = df_mes['MACD'].ewm(span=9, adjust=False).mean()

        # =============================
        # SINAIS AUTOMÁTICOS
        # =============================
        if ("RSI" in indicadores) and ("MACD" in indicadores) and (ultimo_rsi is not None) and pd.notna(ultimo_rsi):
            if ultimo_rsi < 30 and df_mes['MACD'].iloc[-1] > df_mes['MACD_signal'].iloc[-1]:
                st.success("🟢 Sinal de COMPRA confirmado")
            elif ultimo_rsi > 70 and df_mes['MACD'].iloc[-1] < df_mes['MACD_signal'].iloc[-1]:
                st.error("🔴 Sinal de VENDA confirmado")

        # =============================
        # SUBPLOTS
        # =============================
        rows_count = 2
        row_heights = [0.65, 0.15]
        row_titles_list = ["Preço", "Volume"]

        if "RSI" in indicadores:
            rows_count += 1
            row_heights.append(0.1)
            row_titles_list.append("RSI")

        if "MACD" in indicadores:
            rows_count += 1
            row_heights.append(0.1)
            row_titles_list.append("MACD")

        fig = make_subplots(
            rows=rows_count,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.02,
            row_titles=row_titles_list,
            row_heights=row_heights
        )

        # Candlestick
        fig.add_trace(go.Candlestick(
            x=df_mes['timestamp'],
            open=df_mes['open'],
            high=df_mes['high'],
            low=df_mes['low'],
            close=df_mes['close'],
            increasing_line_color='#0ECB81',
            decreasing_line_color='#F6465D',
            name="Preço"
        ), row=1, col=1)

        # Linha preço atual
        fig.add_hline(
            y=ultimo_preco,
            line_dash="dot",
            line_color="rgba(255,255,255,0.4)",
            row=1,
            col=1
        )

        # Volume colorido
        volume_colors = [
            '#0ECB81' if c >= o else '#F6465D'
            for o, c in zip(df_mes['open'], df_mes['close'])
        ]

        fig.add_trace(go.Bar(
            x=df_mes['timestamp'],
            y=df_mes['volume'],
            marker_color=volume_colors,
            name="Volume"
        ), row=2, col=1)

        fig.update_layout(
            title=f"{moeda} - Análise PRO+",
            template="plotly_dark",
            height=720,
            hovermode="x unified",
            xaxis_rangeslider_visible=False
        )

        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Últimos preços")

        if moeda in meme_coins:
            st.dataframe(
                df_mes[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
                .round(6).tail(10)
            )
        else:
            st.dataframe(df_mes.tail(10))

if auto_refresh:
    st.info(f"🔄 Atualização automática a cada {refresh_seconds} segundos.")
else:
    st.info("🔄 Atualização automática desativada (ligue no toggle acima).")
