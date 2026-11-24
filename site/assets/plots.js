// A small SVG time-series plot: lines, min/max bands, shaded time zones, horizontal rules, dots and a time cursor.
// It draws arrays the Python side computed; it computes no metric.
//
//   const p = plot(host, {x: [0, 4], y: [0, 3], yLabel: 'mm', series: [{x, y, cls: 'line-measured'}],
//                         zones: [{x0, x1, cls: 'zone-hi'}], rules: [{y: 1, cls: 'limit', label: '1 mm gate'}]});
//   p.cursor(1.2);

const NS = 'http://www.w3.org/2000/svg';

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) if (value !== undefined && value !== null) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

function niceTicks(lo, hi, count = 4) {
  const span = hi - lo || 1;
  const step0 = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => span / s <= count + 0.5) || 10 * magnitude;
  const ticks = [];
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9 * span; v += step) ticks.push(+v.toPrecision(12));
  return ticks;
}

function extent(series, rules, pad = 0.06) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of series) {
    for (const arr of [s.y, s.y0, s.y1]) {
      if (!arr) continue;
      for (const v of arr) if (v !== null && Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    }
  }
  for (const r of rules || []) if (Number.isFinite(r.y) && r.fit !== false) { lo = Math.min(lo, r.y); hi = Math.max(hi, r.y); }
  if (!Number.isFinite(lo)) return [0, 1];
  if (hi === lo) { hi += 1; lo -= 1; }
  const margin = (hi - lo) * pad;
  return [lo - margin, hi + margin];
}

export function plot(host, options) {
  // WHY the host's own width: a fixed viewBox scaled into a narrow card shrinks the axis text to unreadable
  const measured = Math.round(host.clientWidth || 0);
  const {width = measured >= 200 ? measured : 640, height = 170, series = [], zones = [], rules = [], dots = [], yLabel = '', title = '',
    yFormat = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : +v.toPrecision(3)).toString()} = options;
  const margin = {left: 42, right: 12, top: title ? 18 : 8, bottom: 22};
  const x = options.x || [0, 1];
  const y = options.y || extent(series, rules);
  const W = width - margin.left - margin.right;
  const H = height - margin.top - margin.bottom;
  const sx = (v) => margin.left + ((v - x[0]) / (x[1] - x[0] || 1)) * W;
  const sy = (v) => margin.top + (1 - (v - y[0]) / (y[1] - y[0] || 1)) * H;
  host.replaceChildren();
  const svg = el('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': options.aria || title || yLabel}, host);
  if (title) el('text', {x: margin.left, y: 11, class: 'plot-label'}, svg).textContent = title;
  const clipId = `clip${Math.random().toString(36).slice(2)}`;
  const clip = el('clipPath', {id: clipId}, el('defs', {}, svg));
  el('rect', {x: margin.left, y: margin.top, width: W, height: H}, clip);

  for (const z of zones) {
    const x0 = sx(Math.max(z.x0, x[0]));
    const x1 = sx(Math.min(z.x1, x[1]));
    el('rect', {x: x0, y: margin.top, width: Math.max(1, x1 - x0), height: H, class: z.cls}, svg);
  }
  const axis = el('g', {class: 'axis'}, svg);
  for (const v of niceTicks(y[0], y[1], 3)) {
    el('line', {x1: margin.left, x2: margin.left + W, y1: sy(v), y2: sy(v), class: 'gridline'}, axis);
    el('text', {x: margin.left - 6, y: sy(v) + 3, 'text-anchor': 'end'}, axis).textContent = yFormat(v);
  }
  for (const v of niceTicks(x[0], x[1], 5)) {
    el('text', {x: sx(v), y: margin.top + H + 15, 'text-anchor': 'middle'}, axis).textContent = `${+v.toPrecision(3)} s`;
  }
  if (yLabel) {
    el('text', {x: 4, y: margin.top + H / 2, transform: `rotate(-90 10 ${margin.top + H / 2})`, 'text-anchor': 'middle'},
      axis).textContent = yLabel;
  }
  const body = el('g', {'clip-path': `url(#${clipId})`}, svg);
  for (const s of series) {
    if (s.y0 && s.y1) {
      let d = '';
      s.x.forEach((xv, i) => { d += `${i ? 'L' : 'M'}${sx(xv).toFixed(1)},${sy(s.y1[i]).toFixed(1)}`; });
      for (let i = s.x.length - 1; i >= 0; i--) d += `L${sx(s.x[i]).toFixed(1)},${sy(s.y0[i]).toFixed(1)}`;
      el('path', {d: `${d}Z`, class: s.cls || 'band-measured'}, body);
      continue;
    }
    let d = '';
    let pen = false;
    s.x.forEach((xv, i) => {
      const v = s.y[i];
      if (v === null || !Number.isFinite(v)) { pen = false; return; }
      d += `${pen ? 'L' : 'M'}${sx(xv).toFixed(1)},${sy(v).toFixed(1)}`;
      pen = true;
    });
    el('path', {d, class: s.cls || 'line-measured'}, body);
  }
  for (const r of rules) {
    el('line', {x1: margin.left, x2: margin.left + W, y1: sy(r.y), y2: sy(r.y), class: r.cls || 'limit'}, svg);
    if (r.label) {
      el('text', {x: margin.left + W - 2, y: sy(r.y) - 4, 'text-anchor': 'end', class: r.labelCls || 'limit-label'}, svg)
        .textContent = r.label;
    }
  }
  for (const d of dots) {
    el('circle', {cx: sx(d.x), cy: sy(d.y), r: d.r || 3, class: d.cls || 'dot-hi'}, body);
    if (d.label) {
      const right = sx(d.x) > margin.left + 0.75 * W; // near the right edge: the label goes to the dot's left
      el('text', {x: sx(d.x) + (right ? -6 : 6), y: sy(d.y) - 6, 'text-anchor': right ? 'end' : 'start', class: 'plot-value'}, svg)
        .textContent = d.label;
    }
  }
  const cursor = el('line', {x1: 0, x2: 0, y1: margin.top, y2: margin.top + H, class: 'cursor', visibility: 'hidden'}, svg);
  const api = {
    svg,
    sx,
    sy,
    cursor(t) {
      if (t === null || t === undefined || t < x[0] || t > x[1]) { cursor.setAttribute('visibility', 'hidden'); return; }
      cursor.setAttribute('x1', sx(t));
      cursor.setAttribute('x2', sx(t));
      cursor.setAttribute('visibility', 'visible');
    },
    onSeek(callback) {
      svg.style.cursor = 'crosshair';
      svg.addEventListener('pointerdown', (event) => {
        const rect = svg.getBoundingClientRect();
        const px = ((event.clientX - rect.left) / rect.width) * width;
        const t = x[0] + ((px - margin.left) / W) * (x[1] - x[0]);
        if (t >= x[0] && t <= x[1]) callback(t);
      });
    },
  };
  return api;
}
