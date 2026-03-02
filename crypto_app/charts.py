def plotly_autoy_html(fig: go.Figure, height: int, y_padding_ratio: float = 0.04) -> str:
    fig_dict = fig.to_plotly_json()
    payload = json.dumps(fig_dict, cls=PlotlyJSONEncoder)
    pad = float(y_padding_ratio)

    template = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
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
      if (v === null || v === undefined) return null;
      if (typeof v === 'number') return v;
      const d = new Date(v);
      const ms = d.getTime();
      return isNaN(ms) ? null : ms;
    }}

    function clampDtick(ymin, ymax) {{
      const rng = ymax - ymin;
      if (!isFinite(rng) || rng <= 0) return null;
      if (rng <= 25000) return 1000;
      if (rng <= 80000) return 5000;
      if (rng <= 200000) return 10000;
      return null;
    }}

    function autoYFromVisibleX(relayout) {{
      if (!ohlc.x || !ohlc.low || !ohlc.high) return;

      let x0 = relayout['xaxis.range[0]'];
      let x1 = relayout['xaxis.range[1]'];

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
      let ymax = -Infinity;

      for (let i = 0; i < ohlc.x.length; i++) {{
        const ms = toMs(ohlc.x[i]);
        if (!ms) continue;
        if (ms < ms0 || ms > ms1) continue;

        const lo = ohlc.low[i];
        const hi = ohlc.high[i];
        if (isNumber(lo) && lo < ymin) ymin = lo;
        if (isNumber(hi) && hi > ymax) ymax = hi;
      }}

      if (!isFinite(ymin) || !isFinite(ymax) || ymax <= ymin) return;

      const pad = (ymax - ymin) * {pad};
      const y0 = ymin - pad;
      const y1 = ymax + pad;

      const dtick = clampDtick(y0, y1);

      const upd = {{
        'yaxis.range': [y0, y1],
      }};

      if (dtick) {{
        upd['yaxis.dtick'] = dtick;
      }} else {{
        upd['yaxis.dtick'] = null;
      }}

      Plotly.relayout(gd, upd);
    }}

    Plotly.newPlot(gd, fig.data, fig.layout, fig.config).then(() => {{
      autoYFromVisibleX({{}});
    }});

    gd.on('plotly_relayout', (ev) => {{
      if (ev && (ev['yaxis.range[0]'] || ev['yaxis.range[1]'] || ev['yaxis.range'])) return;
      autoYFromVisibleX(ev || {{}});
    }});
  </script>
</body>
</html>
"""
    return template
