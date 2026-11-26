/* traj_compare — plot grid engine.
 *
 * Consumes the JSON payload embedded by report.py and builds, per comparison
 * page: situation legend chips, section show/hide chips, a rad/deg unit
 * toggle (degrees by default), a reset-zoom button, and lazily-built uPlot
 * grids whose x zoom and cursor stay synchronized within a page.
 *
 * A per-page transport carries the shared time state. Every plot is a
 * scrubber: a press-and-drag on any plot (mouse, pen or a finger) commits the
 * time at every move, as does the page's one time control: the time lane
 * docked under the question tabs (timeline.js: transport, ruler, one track per
 * run, zoom bar), or without it the scrubbers under the 3D canvas and the
 * videos. The committed time drives the playhead on every plot (other tabs
 * too) and the one line through them, the video players (always seeked
 * together), the ruler, and the 3D truncation + robot pose. Hovering a plot
 * only previews that instant in the 3D viewer. x zoom is Shift-drag (uPlot's
 * box), Ctrl/⌘+wheel (a trackpad pinch) or the lane's zoom bar; Full range or
 * a double-click restores the full range (see attachTimeGestures).
 *
 * A "Camera" section stacks a real video and a selectable sim render in one
 * box (opacity slider, mix/difference blend, flicker toggle); those videos
 * join the page's video list, so the same transport drives them.
 *
 * Which plots, which situations, which 3D elements and which units are on is
 * *report-level* state, not page-level: pick a layout once and every scenario
 * tab you switch to shows the same one (see makePrefs / applyShared).
 */

var TrajCompare = (function () {
  'use strict';

  // ── ink: the dark theme's colour of a light one (traj_compare._theme.dark_colour, role "other", ported; a test holds
  // the port equal to it and this block identical in plots.js and dataset.js). WHY: the stylesheets go dark by
  // themselves (their generated dark block); a canvas (uPlot axes, the three.js scene, the SVG charts) is painted
  // with colours from code, so its few neutral ones go through here. Data colours come back unchanged.
  function themeIsDark() {
    var pinned = document.documentElement.getAttribute('data-theme');
    if (pinned === 'dark') return true;
    if (pinned === 'light') return false;
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }
  function darkInk(colour) {
    var digits = String(colour).replace('#', '');
    if (digits.length === 3 || digits.length === 4) digits = digits.split('').map(function (ch) { return ch + ch; }).join('');
    var rgb = [0, 2, 4].map(function (i) { return parseInt(digits.slice(i, i + 2), 16); });
    var lin = rgb.map(function (c) { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); });
    var f = function (t) { return t > 0.008856 ? Math.pow(t, 1 / 3) : 7.787 * t + 16 / 116; };
    var x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047;
    var y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
    var z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883;
    var L = 116 * f(y) - 16, a = 500 * (f(x) - f(y)), b = 200 * (f(y) - f(z));
    if (Math.hypot(a, b) >= 15 && L <= 70) return colour;
    var mapped = L >= 94 ? 10 + (L - 94) : 18 + (94 - L) * 77 / 91;
    var inv = function (t) { return t * t * t > 0.008856 ? t * t * t : (t - 16 / 116) / 7.787; };
    for (var step = 0; step <= 20; step++) {
      var scale = 1 - step / 20, fy = (mapped + 16) / 116;
      var X = 0.95047 * inv(fy + 0.7 * a * scale / 500), Y = inv(fy), Z = 1.08883 * inv(fy - 0.7 * b * scale / 200);
      var out = [3.2406 * X - 1.5372 * Y - 0.4986 * Z, -0.9689 * X + 1.8758 * Y + 0.0415 * Z, 0.0557 * X - 0.2040 * Y + 1.0570 * Z];
      if (out.some(function (v) { return v < -1e-4 || v > 1 + 1e-4; })) continue;
      var hex = out.map(function (v) {
        v = Math.min(1, Math.max(0, v));
        v = v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
        return ('0' + Math.round(v * 255).toString(16)).slice(-2);
      }).join('');
      return hex === rgb.map(function (v) { return ('0' + v.toString(16)).slice(-2); }).join('') ? colour : '#' + hex + digits.slice(6, 8);
    }
    return colour;
  }
  function ink(colour) { return themeIsDark() ? darkInk(colour) : colour; }
  // ── ink end


  var RAD2DEG = 180 / Math.PI;

  // kind -> {angle: uses the global rad/deg toggle, scale: fixed multiplier}
  var KINDS = {
    angle: { angle: true, rad: 'rad', deg: '°' },
    angle_rate: { angle: true, rad: 'rad/s', deg: '°/s' },
    angle_acc: { angle: true, rad: 'rad/s²', deg: '°/s²' },
    m: { label: 'm' },
    mm: { label: 'mm', scale: 1000 },
    ms: { label: 'ms', scale: 1000 },
    m_s: { label: 'm/s' },
    m_s2: { label: 'm/s²' },
    Nm: { label: 'N·m' },
    A: { label: 'A' },
    pct: { label: '%' },
    pct_s: { label: '%/s' },
    pct_s2: { label: '%/s²' },
    // a recorded channel (NAVIGATION.md C1): drawn as recorded, its unit the caller's own text (spec.unit)
    raw: { label: '' },
  };

  var PLOT_HEIGHT = 150;
  // Under the time lane (``page.timeline``) every chart stacks full width, its title in a left column as wide as the
  // lane's names column, with a FIXED y-axis width and padding [top, right, bottom, left]: every plotting area then starts
  // and ends at the same x as the lane's ruler, which is what lets one playhead line run through all of them.
  var LANE_AXIS_PX = 56;
  var LANE_PAD = [10, 16, 0, 0];

  var state = {
    unit: 'deg',
    pages: [],
    groups: [],
    reportPages: [],
    activePage: 0,
    prefs: null,   // report-level view configuration shared by every page
  };

  function store(key, value) {
    try { localStorage.setItem('traj-compare:' + key, JSON.stringify(value)); } catch (e) {}
  }
  function recall(key, fallback) {
    try {
      var raw = localStorage.getItem('traj-compare:' + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) { return fallback; }
  }

  /* One view configuration for the whole report, so switching scenario tabs
     keeps the plots/situations/3D elements you chose. Held in memory (the
     part that must work) and mirrored to localStorage (best effort — a
     file:// page may refuse it). A pref nobody has touched reads back null,
     which lets each page fall back to its own default. */
  function makePrefs(namespace) {
    var cache = {};
    return {
      get: function (key, fallback) {
        if (!(key in cache)) cache[key] = recall(namespace + ':' + key, null);
        return cache[key] === null ? fallback : cache[key];
      },
      set: function (key, value) {
        cache[key] = value;
        store(namespace + ':' + key, value);
      },
    };
  }

  function el(tag, className, parent, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }

  function unitLabel(kind) {
    var meta = KINDS[kind];
    return meta.angle ? (state.unit === 'deg' ? meta.deg : meta.rad) : meta.label;
  }

  function convert(kind, values) {
    var meta = KINDS[kind];
    var factor = meta.angle ? (state.unit === 'deg' ? RAD2DEG : 1) : (meta.scale || 1);
    if (factor === 1) return values;
    var out = new Array(values.length);
    for (var i = 0; i < values.length; i++) {
      out[i] = values[i] === null ? null : values[i] * factor;
    }
    return out;
  }

  /* ---------------- transport: the page's shared time state ---------------- */

  function makeTransport(page) {
    var grid = page.data.plot_t;
    var transport = {
      tMin: grid[0],
      tMax: grid[grid.length - 1],
      t: null,       // committed scrub time; null = end (everything shown)
      hoverT: null,  // transient preview while hovering a plot
      playing: false,
      listeners: [],
      bars: [],
    };

    transport.eff = function () {
      if (transport.hoverT !== null) return transport.hoverT;
      if (transport.t !== null) return transport.t;
      return transport.tMax;
    };

    transport.onChange = function (listener) { transport.listeners.push(listener); };

    function emit(kind) {
      transport.listeners.forEach(function (listener) { listener(kind); });
      transport.bars.forEach(function (bar) { bar.paint(); });
    }

    transport.setHover = function (time) {
      if (time === transport.hoverT) return;
      transport.hoverT = time;
      emit('hover');
    };

    transport.setScrub = function (time, fromCursor) {
      transport.t = Math.min(transport.tMax, Math.max(transport.tMin, time));
      if (!fromCursor) paintCursors(page, transport.t);
      queueVideoSeek(page, transport.t);
      emit('scrub');
    };

    transport.stepBy = function (samples) {
      transport.pause();
      var current = transport.eff();
      var index = nearestIndex(grid, current) + samples;
      index = Math.min(grid.length - 1, Math.max(0, index));
      transport.setScrub(grid[index]);
    };

    var lastTick = 0;
    function tick(now) {
      if (!transport.playing) return;
      var dt = Math.min(0.1, (now - lastTick) / 1000);
      lastTick = now;
      var next = followVideos(page, transport.t === null ? transport.tMin : transport.t, dt, now);
      if (next >= transport.tMax) {
        transport.setScrub(transport.tMax);
        transport.pause();
        return;
      }
      transport.t = next;
      paintCursors(page, next);
      emit('scrub');
      requestAnimationFrame(tick);
    }

    // The videos start from the tick, once each one sits on the clock.
    transport.play = function () {
      if (transport.playing) return;
      if (transport.t === null || transport.t >= transport.tMax - 1e-9) {
        transport.t = transport.tMin;
      }
      transport.playing = true;
      lastTick = performance.now();
      emit('play');
      requestAnimationFrame(tick);
    };

    // Nothing changed when we were already paused, and emitting anyway
    // repainted the bars — which wrote the *stale* time straight back into
    // the slider the user was dragging. Pausing is a no-op when paused.
    // A paused page shows exactly the cursor's frame: the videos ran on for
    // up to a display frame after the last tick, so they are put back on it.
    transport.pause = function () {
      if (!transport.playing) return;
      transport.playing = false;
      pauseVideos(page);
      if (transport.t !== null) queueVideoSeek(page, transport.t);
      emit('pause');
    };

    transport.toggle = function () {
      if (transport.playing) transport.pause(); else transport.play();
    };

    return transport;
  }

  function nearestIndex(sorted, value) {
    var lo = 0, hi = sorted.length - 1;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (sorted[mid] < value) lo = mid + 1; else hi = mid;
    }
    if (lo > 0 && Math.abs(sorted[lo - 1] - value) < Math.abs(sorted[lo] - value)) return lo - 1;
    return lo;
  }

  function paintCursors(page, time) {
    page.cursorDriven = true;
    page.charts.forEach(function (chart) {
      if (!chart.u) return;
      var left = chart.u.valToPos(time, 'x');
      chart.u.setCursor({ left: left, top: 8 });
    });
    page.cursorDriven = false;
  }

  /* One video follows the trajectory clock. ``entry.t0`` (camera overlays
     only; 0 for a plain situation video) is the trajectory time shown at
     video time 0, so the video position is t - t0. */
  function seekEntry(entry, time) {
    var video = entry.el;
    if (!video.duration) return;
    video.currentTime = Math.min(video.duration - 0.001, Math.max(0, time - (entry.t0 || 0)));
  }

  function seekVideos(page, time) {
    page.videos.forEach(function (entry) { seekEntry(entry, time); });
  }

  /* A drag fires input events far faster than a decoder can honour seeks, and
     ten <video> elements re-seeking per event stalls the whole page. Coalesce
     to one seek per frame — the last position asked for is the only one that
     matters. */
  function queueVideoSeek(page, time) {
    page.pendingSeek = { time: time };
    if (page.seekQueued) return;
    page.seekQueued = true;
    requestAnimationFrame(function () {
      page.seekQueued = false;
      var pending = page.pendingSeek;
      if (pending) seekVideos(page, pending.time);
    });
  }

  function pauseVideos(page) {
    page.videos.forEach(function (entry) {
      entry.el.pause();
      entry.el.playbackRate = 1;
    });
  }

  /* Playback: the clock follows the videos, never the other way round.

     WHY: a seek lands on the keyframe before its target and decodes forward
     from it, 150-500 ms in the rack's mp4s (a keyframe every 8.3 s). The old
     loop advanced a wall clock and re-seeked any video 0.12 s off it, so a
     seek still in flight was restarted every tick: the picture froze on its
     last frame until the clock crossed a keyframe while the plot cursor ran
     on (measured 2026-10-21 on the rack sensors report: no frame presented
     for the first 3.2 s of play), and a video that did keep up was left up
     to 0.12 s off the cursor. Now the clock holds while any video is seeking
     or starved, every video is put exactly on it before it plays, and then
     the first playing video IS the clock: the cursor is the time of the
     frame it has on screen. The others follow it by playbackRate, seeking
     only when they are far off. "On screen" is the frame the compositor
     PRESENTED (requestVideoFrameCallback, which runs just before this
     frame's animation callbacks), not currentTime: currentTime wandered 1-2
     frames off the picture, and with four 720p decoders a follower's
     currentTime sat on the clock while its picture ran two frames late
     (67 ms, headless Chrome, 2026-10-21). A
     video whose recording does not cover the time is parked on its
     first/last frame instead of playing ahead of it. */
  var PLAY_ALIGN_S = 0.015;   // a video this close to the clock may start playing
  var PLAY_RESEEK_S = 0.25;   // a follower further off than this is re-seeked
  var PLAY_NUDGE_GAIN = 2.0;  // rate = 1 - gain * drift: ~0.5 s to converge
  var PLAY_NUDGE_LIMIT = 0.25;

  function videoPlayable(page, entry) {
    return entry.el.duration > 0 && !entry.el.error && page.visible[entry.sit.name] !== false;
  }

  function videoCovers(entry, time) {
    var position = time - (entry.t0 || 0);
    return position >= 0 && position < entry.el.duration - 0.05;
  }

  function watchPresented(entry) {
    if (entry.watching || !entry.el.requestVideoFrameCallback) return;
    entry.watching = true;
    var onFrame = function (now, meta) {
      entry.presented = { media: meta.mediaTime, now: now };
      entry.el.requestVideoFrameCallback(onFrame);
    };
    entry.el.requestVideoFrameCallback(onFrame);
  }

  // Video time of the picture on screen at ``now``: the last presented frame,
  // run on at the playback rate since (capped), else currentTime.
  function shownTime(entry, now) {
    var shown = entry.presented;
    if (!shown || entry.el.paused) return entry.el.currentTime;
    return shown.media + Math.min(0.1, Math.max(0, (now - shown.now) / 1000)) * entry.el.playbackRate;
  }

  function followVideos(page, time, dt, now) {
    var active = [];
    page.videos.forEach(function (entry) {
      if (!videoPlayable(page, entry)) return;
      if (videoCovers(entry, time)) { active.push(entry); return; }
      entry.el.pause();
      var parked = Math.min(entry.el.duration - 0.001, Math.max(0, time - (entry.t0 || 0)));
      if (!entry.el.seeking && Math.abs(entry.el.currentTime - parked) > 0.001) entry.el.currentTime = parked;
    });
    if (!active.length) return time + dt;
    function target(entry) { return time - (entry.t0 || 0); }
    var waiting = active.some(function (entry) {
      return entry.el.seeking || (!entry.el.paused && entry.el.readyState < 3);
    });
    if (waiting) {
      active.forEach(function (entry) { entry.el.pause(); });
      return time;
    }
    var stopped = active.some(function (entry) { return entry.el.paused; });
    if (stopped) {
      var off = active.filter(function (entry) {
        return Math.abs(entry.el.currentTime - target(entry)) > PLAY_ALIGN_S;
      });
      active.forEach(function (entry) { entry.el.pause(); });
      if (off.length) {
        off.forEach(function (entry) { entry.el.currentTime = target(entry); });
        return time;
      }
      active.forEach(function (entry) {
        watchPresented(entry);
        entry.presented = null;  // the paused frame's presentation says nothing about playback
        entry.el.playbackRate = 1;
        entry.el.play().catch(function () {});
      });
      return time;
    }
    var clock = active[0];
    var next = shownTime(clock, now) + (clock.t0 || 0);
    active.slice(1).forEach(function (entry) {
      var drift = shownTime(entry, now) + (entry.t0 || 0) - next;
      if (Math.abs(drift) > PLAY_RESEEK_S) {
        entry.el.currentTime = next - (entry.t0 || 0);
        return;
      }
      entry.el.playbackRate = 1 - Math.max(-PLAY_NUDGE_LIMIT, Math.min(PLAY_NUDGE_LIMIT, PLAY_NUDGE_GAIN * drift));
    });
    return next;
  }

  /* Scrubber bar: one under the 3D canvas, one under the videos. Every bar of
     a page stays in sync through the transport. None under the time lane: WHY (Zach's pick round 2026-11-24, R2) the
     lane is the page's one time control, and a second slider would be a second one to keep in step. */
  function buildTransportBar(page, parent) {
    var transport = page.transport;
    if (!transport || page.oneTimeline) return null;
    var bar = el('div', 'tc-transport', parent);
    var handle = { selfDriving: false };

    function iconButton(label, title, onClick) {
      var button = el('button', 'tc-tbtn', bar, label);
      button.title = title;
      button.onclick = onClick;
      return button;
    }

    iconButton('⏮', 'to start', function () { transport.pause(); transport.setScrub(transport.tMin); });
    iconButton('◀', 'step back', function () { transport.stepBy(-1); });
    var playButton = iconButton('▶', 'play / pause', function () { transport.toggle(); });
    iconButton('▶', 'step forward', function () { transport.stepBy(1); });
    iconButton('⏭', 'to end', function () { transport.pause(); transport.setScrub(transport.tMax); });

    var slider = document.createElement('input');
    slider.type = 'range';
    slider.className = 'tc-scrub';
    slider.min = transport.tMin;
    slider.max = transport.tMax;
    slider.step = (transport.tMax - transport.tMin) / 2000;
    slider.value = transport.tMax;
    slider.title = 'drag to scrub · click the track to jump · arrow keys step';
    bar.appendChild(slider);
    slider.addEventListener('input', function () {
      // Read before anything can repaint us, and refuse to be repainted for
      // the duration: writing slider.value mid-drag cancels the drag.
      var time = parseFloat(slider.value);
      handle.selfDriving = true;
      transport.pause();
      transport.setScrub(time);
      handle.selfDriving = false;
    });

    var readout = el('span', 'tc-time', bar);

    handle.paint = function () {
      var time = transport.t === null ? transport.tMax : transport.t;
      if (!handle.selfDriving) slider.value = time;
      readout.textContent = time.toFixed(2) + ' / ' + transport.tMax.toFixed(2) + ' s';
      playButton.textContent = transport.playing ? '⏸' : '▶';
    };
    transport.bars.push(handle);
    handle.paint();
    return bar;
  }

  /* ---------------- chart registry + x-sync ---------------- */

  function makeChart(page, card, spec) {
    var titleEl = el('div', 'ptitle', card);
    var chartEl = el('div', '', card);

    var chart = {
      page: page, card: card, spec: spec, titleEl: titleEl, chartEl: chartEl, u: null,
    };

    // A series is drawn while its situation is on and, on a torque card, while its component is on too.
    function seriesShown(entry) {
      if (page.visible[entry.sit.name] === false) return false;
      return !entry.component || page.torqueOn[entry.component] !== false;
    }

    function seriesOpts() {
      var opts = [{}];
      spec.series.forEach(function (entry) {
        if (entry.style) {
          // a torque-breakdown trace: its component decides colour, width, dash and fill
          var styled = {
            label: entry.style.label,
            stroke: entry.style.stroke,
            width: entry.style.width,
            dash: entry.style.dash,
            points: { show: false },
            show: seriesShown(entry),
          };
          if (entry.style.fill) {
            styled.fill = entry.style.fill;
            // WHY a function: uPlot reads ``fillTo || default``, so a literal 0 would fall back to the default
            styled.fillTo = function () { return 0; };
          }
          opts.push(styled);
          return;
        }
        if (entry.error) {
          opts.push({
            label: 'Δ ' + entry.sit.title,
            stroke: entry.sit.color,
            width: 1.2,
            dash: [2, 3],
            points: { show: false },
            show: !!page.errorOn[entry.sit.name],
          });
          return;
        }
        opts.push({
          label: entry.sit.title,
          stroke: entry.sit.color,
          width: entry.sit.role === 'target' ? 1.4 : 1.7,
          dash: entry.sit.role === 'target' ? [7, 4] : undefined,
          points: { show: false },
          show: page.visible[entry.sit.name] !== false,
        });
      });
      return opts;
    }

    function data() {
      var columns = [page.data.plot_t];
      spec.series.forEach(function (entry) {
        columns.push(convert(spec.kind, entry.values));
      });
      return columns;
    }

    // WHY 160 (2026-11-19, parts): a hand's finger row puts 3-4 joints side by side beside the stage
    function width() {
      if (page.oneTimeline) return Math.max(80, chartEl.clientWidth);  // the plot column beside the title column
      return Math.max(160, card.clientWidth - 18);
    }

    // ``spec.unit`` (a channel's own unit text) wins over the kind's; an empty unit draws no brackets (C1)
    function unitText() {
      return spec.unit !== undefined ? spec.unit : unitLabel(spec.kind);
    }

    function paintTitle() {
      var unit = unitText();
      titleEl.innerHTML = '';
      titleEl.appendChild(document.createTextNode(spec.title + (unit ? ' ' : '')));
      if (unit) el('span', 'unit', titleEl, '[' + unit + ']');
      if (spec.note) el('span', 'pnote', titleEl, ' · ' + spec.note);
      // WHY always (Zach's rule: never truncate a name silently): the title ellipsizes, the hover has it whole
      titleEl.title = spec.title + (unit ? ' [' + unit + ']' : '') + (spec.note ? ' · ' + spec.note : '');
    }

    chart.build = function () {
      paintTitle();
      if (spec.situation && page.visible[spec.situation] === false) card.style.display = 'none';
      var opts = {
        width: width(),
        height: PLOT_HEIGHT,
        series: seriesOpts(),
        scales: { x: { time: false } },
        legend: { show: false },
        cursor: {
          drag: { x: true, y: false },
          points: { size: 6 },
          sync: { key: 'tc-page-' + page.index },
        },
        axes: [
          { stroke: ink('#8a8983'), grid: { stroke: ink('#e6e5e0'), width: 0.5 }, ticks: { stroke: ink('#c9c8c2') }, size: 28 },
          { stroke: ink('#8a8983'), grid: { stroke: ink('#e6e5e0'), width: 0.5 }, ticks: { stroke: ink('#c9c8c2') },
            size: page.oneTimeline ? LANE_AXIS_PX : 44 },
        ],
        padding: page.oneTimeline ? LANE_PAD : undefined,
        hooks: {
          setScale: [function (u, key) {
            if (key === 'x' && chart.paintPlayhead) chart.paintPlayhead();  // the playhead rides every zoom
            if (key === 'x' && page.timeline) page.timeline.queue();       // and so do the lane and its line
            if (key !== 'x' || !u._tcReady || page.syncing) return;
            var scale = u.scales.x;
            page.syncing = true;
            page.charts.forEach(function (other) {
              if (other.u && other.u !== u) other.u.setScale('x', { min: scale.min, max: scale.max });
            });
            page.xZoom = { min: scale.min, max: scale.max };
            page.syncing = false;
            restoreCursors(page);
          }],
          setCursor: [function (u) {
            // hover preview for the 3D view; ignore our own programmatic sets
            if (page.cursorDriven || !page.transport) return;
            // WHY only with a pointer over a plot, and not while one drags (measured 2026-11-25): a chart built when
            // its tab first shows joins the cursor sync at its last sample, and that "hover" parked the 3D at the end
            // of the run on every first open of a tab; during a drag the committed time is what the 3D shows
            if (!page.hoverChart || page.scrubbing) return;
            var index = u.cursor.idx;
            page.transport.setHover(index == null ? null : page.data.plot_t[index]);
          }],
          ready: [function (u) { u._tcReady = true; }],
        },
      };
      chart.u = new uPlot(opts, data(), chartEl);
      if (page.xZoom) chart.u.setScale('x', page.xZoom);
      attachTimeGestures(page, chart);
    };

    chart.refreshUnits = function () {
      if (!chart.u) return;
      var keep = page.xZoom;
      chart.u._tcReady = false;
      chart.u.setData(data(), true);
      if (keep) chart.u.setScale('x', keep);
      chart.u._tcReady = true;
      paintTitle();
    };

    // A run's own trace and its Δ curve toggle independently — that is what
    // lets you hide target + measured and read the error off a y axis that
    // has rescaled to the error alone. A card that belongs to one run (the
    // torque breakdown: ``spec.situation``) is hidden whole with its run.
    chart.setSituation = function (name, show) {
      if (!chart.u) return;
      if (spec.situation === name) {
        var wasHidden = card.style.display === 'none';
        card.style.display = show ? '' : 'none';
        if (show && wasHidden) chart.resize();  // built or last sized while hidden
      }
      spec.series.forEach(function (entry, index) {
        if (entry.sit.name === name && !entry.error) chart.u.setSeries(index + 1, { show: show && seriesShown(entry) });
      });
    };

    // One torque component (target, commanded, feedforward, feedback, applied) on or off on this card.
    chart.setComponent = function (component) {
      if (!chart.u) return;
      spec.series.forEach(function (entry, index) {
        if (entry.component === component) chart.u.setSeries(index + 1, { show: seriesShown(entry) });
      });
    };

    chart.setError = function (name, show) {
      if (!chart.u) return;
      spec.series.forEach(function (entry, index) {
        if (entry.sit.name === name && entry.error) chart.u.setSeries(index + 1, { show: show });
      });
    };

    chart.hasError = function (name) {
      return spec.series.some(function (entry) {
        return entry.error && entry.sit.name === name;
      });
    };

    chart.resetZoom = function () {
      if (!chart.u) return;
      chart.u._tcReady = false;
      chart.u.setScale('x', { min: page.transport ? page.transport.tMin : null, max: page.transport ? page.transport.tMax : null });
      chart.u._tcReady = true;
    };

    // A hidden card (its tab, part or run not shown) keeps its size; it is sized when it shows (activateTab).
    chart.resize = function () {
      if (chart.u && card.clientWidth) chart.u.setSize({ width: width(), height: PLOT_HEIGHT });
      if (chart.paintPlayhead) {
        chart.paintPlayhead();
        restoreCursors(page);  // uPlot keeps its cursor at a pixel through a resize
      }
      if (page.timeline) page.timeline.queue();  // the lane re-measures the shared x pixels
    };

    chart.build();
    page.charts.push(chart);
    return chart;
  }

  /* ---------------- every plot is a scrubber ----------------

     WHY (Zach, Daily Note 2026-11-24): "a important thing is that as you drag the time on any of the figures it syncs
     across all of the other ones". The run-view round's five proposals (docs/proposals/run-view-2026-11-24/) all
     shared this one mechanism (R1, "every figure is a scrubber"); the page layout around it stays Zach's pick.

     - The playhead ``[data-tc-playhead]`` is the COMMITTED time (transport.t; the end of the run when none): a solid
       line in the page's ink with a grip on top, on every plot. uPlot's own dashed cursor is the hover preview, put
       back on the committed time when the pointer leaves, so its dots read the values there.
     - A plain press-and-drag on a plot commits the time at every move (pointer events: mouse, pen and a finger;
       ``touch-action: pan-y`` keeps a vertical swipe scrolling the page), snapped to the shared plot grid. The
       transport does the rest: every other plot, the 3D pose, the videos and the slider follow while the pointer moves.
     - Hover is kept from before (decided 2026-11-25, as R1 did): a pointer over a plot without a press previews that
       instant in the 3D only; the playheads and the slider stay on the committed time, and leaving the plot puts the
       3D back. A drag never previews: while it runs the 3D shows the committed time.
     - x zoom moves off the plain drag: Shift-drag draws uPlot's zoom box (untouched), Ctrl/⌘+wheel (a trackpad pinch
       is Ctrl+wheel in Chrome) zooms around the pointer, Reset zoom or a double-click restores the full range. A plain
       wheel is left alone: a tab is a column of plots, so the pointer is nearly always over one and the wheel must keep
       scrolling the page.
     - A page without a transport (a report page's charts) keeps uPlot's plain-drag zoom. */

  var WHEEL_ZOOM_PER_PX = 1.0015;  // a 100 px wheel notch zooms by 1.16x; a pinch's small deltas zoom smoothly
  var MIN_ZOOM_SAMPLES = 4;        // the narrowest wheel zoom spans this many display samples

  function committedTime(page) {
    var transport = page.transport;
    return transport.t === null ? transport.tMax : transport.t;
  }

  function paintPlayheads(page) {
    page.charts.forEach(function (chart) { if (chart.paintPlayhead) chart.paintPlayhead(); });
  }

  // Full range on every plot: the lane's Full range, the Reset zoom chip (no lane), a double-click on the zoom bar
  function resetZoom(page) {
    page.xZoom = null;
    page.charts.forEach(function (chart) { chart.resetZoom(); });
    restoreCursors(page);
  }

  // uPlot hides its cursor when the mouse leaves a plot and keeps it at a pixel through a zoom: a frame later (uPlot
  // commits a new scale after setScale returns), unless a pointer hovers or drags a plot, put it on the committed time.
  function restoreCursors(page) {
    if (!page.transport || page.cursorRestoreQueued) return;
    page.cursorRestoreQueued = true;
    requestAnimationFrame(function () {
      page.cursorRestoreQueued = false;
      if (!page.hoverChart && !page.scrubbing && page.transport.t !== null) paintCursors(page, page.transport.t);
    });
  }

  function attachTimeGestures(page, chart) {
    var u = chart.u;
    var over = u.over;
    var transport = page.transport;
    if (!transport) return;
    over.classList.add('tc-scrubbable');
    var mark = el('div', 'tc-playhead', over);
    mark.setAttribute('data-tc-playhead', '');
    el('div', 'tc-playhead-grip', mark);
    chart.paintPlayhead = function () {
      var x = u.valToPos(committedTime(page), 'x');
      var show = isFinite(x) && x >= -0.5 && x <= over.clientWidth + 0.5;
      mark.style.display = show ? '' : 'none';
      if (show) mark.style.left = x + 'px';
    };
    chart.paintPlayhead();

    over.addEventListener('pointerenter', function (event) {
      if (event.pointerType !== 'touch') page.hoverChart = chart;
    });
    over.addEventListener('pointerleave', function () {
      if (page.hoverChart !== chart) return;
      page.hoverChart = null;
      transport.setHover(null);
    });
    over.addEventListener('mouseleave', function () { restoreCursors(page); });

    // WHY the pointer's own clientX (R3, measured 2026-11-24): a mouse event's x is whole pixels, a pointer event's
    // keeps the fraction; on a narrow plot one pixel is more than a sample
    function timeAt(clientX) {
      var box = over.getBoundingClientRect();
      var x = Math.max(0, Math.min(box.width, clientX - box.left));
      var grid = page.data.plot_t;
      return grid[nearestIndex(grid, u.posToVal(x, 'x'))];
    }
    // Capture on uPlot's wrapper runs before anything on the plot. Cancelling the pointerdown also cancels the
    // mousedown / mousemove / mouseup the browser would derive from it, so uPlot never starts its zoom box for a plain
    // press, and its hover cursor stays where paintCursors puts it (the committed time) while the drag runs.
    over.parentNode.addEventListener('pointerdown', function (event) {
      if (!over.contains(event.target) || event.button !== 0 || event.shiftKey) return;  // Shift: uPlot's zoom box
      event.preventDefault();
      event.stopPropagation();
      var id = event.pointerId;
      var startX = event.clientX, startY = event.clientY;
      // A finger commits once it moves sideways, or on a tap; a swipe that starts on a plot and goes up or down
      // scrolls the page (the browser then cancels the pointer) and leaves the time alone.
      var waiting = event.pointerType === 'touch';
      try { over.setPointerCapture(id); } catch (error) {}
      function commit(clientX) {
        if (page.scrubbing !== chart) {
          transport.pause();
          page.scrubbing = chart;
          transport.setHover(null);
          document.body.classList.add('tc-scrubbing');
        }
        transport.setScrub(timeAt(clientX));
      }
      if (!waiting) commit(event.clientX);
      function move(moveEvent) {
        if (moveEvent.pointerId !== id) return;
        if (waiting) {
          var dx = Math.abs(moveEvent.clientX - startX), dy = Math.abs(moveEvent.clientY - startY);
          if (dx < 4 || dx < dy) return;
          waiting = false;
        }
        commit(moveEvent.clientX);
      }
      function end(endEvent) {
        if (endEvent.pointerId !== id) return;
        if (waiting && endEvent.type === 'pointerup') commit(endEvent.clientX);  // a tap
        over.removeEventListener('pointermove', move);
        over.removeEventListener('pointerup', end);
        over.removeEventListener('pointercancel', end);
        if (page.scrubbing === chart) page.scrubbing = null;
        document.body.classList.remove('tc-scrubbing');
      }
      over.addEventListener('pointermove', move);
      over.addEventListener('pointerup', end);
      over.addEventListener('pointercancel', end);
    }, true);

    over.addEventListener('wheel', function (event) {
      if (!event.ctrlKey && !event.metaKey) return;  // a plain wheel scrolls the page
      event.preventDefault();
      var box = over.getBoundingClientRect();
      var pointer = u.posToVal(Math.max(0, Math.min(box.width, event.clientX - box.left)), 'x');
      var min = u.scales.x.min, max = u.scales.x.max;
      var pixels = event.deltaY * (event.deltaMode === 1 ? 33 : event.deltaMode === 2 ? box.height : 1);
      var factor = Math.min(2, Math.max(0.5, Math.pow(WHEEL_ZOOM_PER_PX, pixels)));
      var lo = Math.max(transport.tMin, pointer - (pointer - min) * factor);
      var hi = Math.min(transport.tMax, pointer + (max - pointer) * factor);
      var grid = page.data.plot_t;
      var narrowest = grid.length > 1 ? MIN_ZOOM_SAMPLES * (grid[grid.length - 1] - grid[0]) / (grid.length - 1) : 0;
      if (hi - lo < narrowest || (lo === min && hi === max)) return;
      u.setScale('x', { min: lo, max: hi });
    }, { passive: false });
  }

  /* ---------------- sections ---------------- */

  function sitsWith(page, field) {
    return page.data.situations.filter(function (sit) {
      return sit.plot && sit.plot[field];
    });
  }

  /* What an error is measured against: the run sitting in ``target`` (sim vs real has no
     target, so the report names whichever run is the reference). */
  function referenceTitle(data) {
    return data.reference_title || 'Target';
  }

  /* How the page names the reference in running text. WHY (arm_motion_bench, 2026-11-20): in a sim → real pair the
     reference is the sim run (Comparison.reference_kind "run"), and its τ is that run's applied torque; calling it
     "target" named a different signal. A target reference keeps "target". */
  function isRunReference(data) {
    return data.reference_kind === 'run';
  }
  function referenceWord(data) {
    return isRunReference(data) ? referenceTitle(data) : 'the target';
  }

  /* Difference on the display grid, reference - value (target - run, the ROS 2
     convention robot_msgs.compare uses): both columns are already resampled
     onto plot_t, and a null on either side (outside a run's own recorded
     span) stays a null so the gap survives instead of becoming a fake zero. */
  function difference(values, reference) {
    var out = new Array(values.length);
    for (var index = 0; index < values.length; index++) {
      var value = values[index], base = reference[index];
      out[index] = (value === null || base === null) ? null : base - value;
    }
    return out;
  }

  /* Append one Δ-to-target series per measured run to a chart's series list.
     ``precomputed`` lets a channel hand over an error the analysis already
     computed on the native grid (q does: err_q); everything else differences
     the display columns. */
  function withErrors(series, precomputed) {
    var target = null;
    series.forEach(function (entry) {
      if (entry.sit.role === 'target') target = entry;
    });
    var out = series.slice();
    series.forEach(function (entry) {
      if (entry.sit.role === 'target') return;
      var values = precomputed ? precomputed(entry.sit) : (target && difference(entry.values, target.values));
      if (values) out.push({ sit: entry.sit, values: values, error: true });
    });
    return out;
  }

  /* ---------------- parts: an arm or a hand at a time ----------------
     Zach 2026-11-19, traj compare view feedback: "split the arm and the hand into separate concerns, and each
     arm separately ... Arm can have between 1 - 7 motors, Hand can have 1 - N motors (perhaps you group by
     finger)". ``data.parts`` (tabs.normalize_parts) names them — the viewer never guesses membership from joint
     names. A per-joint section draws the selected part only, built the first time it shows: an arm one row per
     joint, a hand one row per finger with that finger's joints as columns. */

  function partsOf(data) {
    if (Array.isArray(data.parts) && data.parts.length) return data.parts;
    return [{ name: 'All joints', groups: [{ name: '', joints: data.joint_names.slice() }] }];
  }

  function jointsWord(count) {
    return count + (count === 1 ? ' joint' : ' joints');
  }

  function partJoints(part) {
    var joints = [];
    part.groups.forEach(function (group) { joints = joints.concat(group.joints); });
    return joints;
  }

  // What the part selector says: "Left hand · 16 joints" (NAVIGATION.md Part B).
  function partLabel(part) {
    return part.name + ' · ' + jointsWord(partJoints(part).length);
  }

  function partIndexOf(page, joint) {
    for (var index = 0; index < page.parts.length; index++) {
      if (partJoints(page.parts[index]).indexOf(joint) !== -1) return index;
    }
    return 0;
  }

  /* One block per part under a per-joint section. ``buildJoint(page, host, jointName, dof)`` appends that joint's
     card(s) to ``host``; ``beforePart(block, part)`` draws what a part block opens with (the torque budget). */
  function partView(page, section, body, buildJoint, beforePart) {
    var dofOf = {};
    page.data.joint_names.forEach(function (name, dof) { dofOf[name] = dof; });
    var view = { section: section, blocks: [] };
    page.parts.forEach(function (part) {
      view.blocks.push({ el: el('div', 'tc-part-block', body), part: part, built: false });
    });
    view.build = function (index) {
      var entry = view.blocks[index];
      if (!entry || entry.built) return;
      entry.built = true;
      if (beforePart) beforePart(entry.el, entry.part);
      entry.part.groups.forEach(function (group) {
        if (!group.name) {  // an arm: one row per joint
          group.joints.forEach(function (joint) {
            var row = el('div', 'tc-joint-row', entry.el);
            row.setAttribute('data-tc-joint', joint);
            buildJoint(page, row, joint, dofOf[joint]);
            if (row.children.length > 1) row.classList.add('multi');
          });
          return;
        }
        // a hand: one row per finger, that finger's joints as columns
        var finger = el('div', 'tc-finger-row', entry.el);
        finger.setAttribute('data-tc-finger', group.name);
        el('div', 'tc-finger-label', finger, group.name + ' · ' + jointsWord(group.joints.length));
        var columns = el('div', 'tc-finger-cols', finger);
        group.joints.forEach(function (joint) {
          var column = el('div', 'tc-finger-col', columns);
          column.setAttribute('data-tc-joint', joint);
          buildJoint(page, column, joint, dofOf[joint]);
        });
      });
      observeGrid(page, entry.el);
    };
    page.partViews.push(view);
    syncPartView(page, view);
    return view;
  }

  // Show the selected part's block; build it only once a reader can see it (a shown section on the active tab).
  function syncPartView(page, view) {
    view.blocks.forEach(function (entry, index) { entry.el.style.display = index === page.part ? '' : 'none'; });
    var section = view.section;
    if (section.on && section.tab && section.tab.id === page.activeTab) view.build(page.part);
  }

  function jointSectionBuilder(field, kind, titleSuffix) {
    return function (page, body, section) {
      var sits = sitsWith(page, field);
      partView(page, section, body, function (page, host, jointName, dof) {
        var series = sits.map(function (sit) {
          return { sit: sit, values: sit.plot[field][dof] };
        });
        if (!series.length) return;
        // q has a native-grid error channel already; reuse it so the overlay
        // and the Joint error section can never disagree.
        var precomputed = field !== 'q' ? null : function (sit) {
          return sit.plot.err_q ? sit.plot.err_q[dof] : null;
        };
        makeChart(page, el('div', 'tc-plotcard', host),
          { title: jointName + ': ' + titleSuffix, kind: kind,
            series: withErrors(series, precomputed) });
      });
    };
  }

  /* ---------------- channels: every other recorded signal ----------------
     docs/NAVIGATION.md C1 (the arm_motion_bench agent's gaps 1 and 2): contact force, winding temperature, a
     collision residual. One section per channel (``data.channels``, analysis.py), one plot per column, titled by the
     signal, its column and its unit ("Contact force, x [N]"); every situation that recorded it in its run colour,
     the target dashed as everywhere else. WHY drawn as recorded (truthful rendering): a channel nobody described
     keeps its own name and no unit, never dropped or renamed, and no unit draws no "[]". */

  function channelSits(data, channel) {
    return data.situations.filter(function (sit) {
      return sit.has_data && sit.channels && sit.channels[channel.name];
    });
  }

  function channelPlotTitle(channel, column) {
    return channel.ndim === 1 ? channel.title : channel.title + ', ' + channel.columns[column];
  }

  function channelSectionBuilder(channel) {
    return function (page, body) {
      var sits = channelSits(page.data, channel);
      var grid = el('div', 'tc-grid tc-channel-grid', body);
      var count = channel.ndim === 1 ? 1 : channel.columns.length;
      for (var column = 0; column < count; column++) {
        var card = el('div', 'tc-plotcard', grid);
        card.setAttribute('data-tc-channel-column', channel.ndim === 1 ? 'value' : channel.columns[column]);
        makeChart(page, card, {
          title: channelPlotTitle(channel, column), kind: 'raw', unit: channel.unit,
          series: sits.map(function (sit) { return { sit: sit, values: sit.channels[channel.name][column] }; }),
        });
      }
      observeGrid(page, grid);
    };
  }

  function channelHint(channel, data) {
    var who = channelSits(data, channel).map(function (sit) { return sit.title; });
    var hint = 'recorded by ' + who.join(', ');
    if (channel.per_joint) hint += '; one plot per joint';
    if (!channel.described) hint += '; not described, so drawn under its recorded name';
    return hint;
  }

  /* ---------------- torque breakdown ----------------
     Zach, 2026-11-19: "target torque, the commanded torque (what you send to the FOC controller) and the
     actual torque ... of the command torque some portion of that is coming from Feedforward, and some
     portion of that is coming from feedback." One card per joint × run with all five torques, one
     component legend for the whole section, and the Torque budget table first (CONTRACT.md). */

  // WHY fixed component colours (Zach 2026-11-19, torque breakdown): feedforward and feedback read the same on
  // every card and in Rerun (rerun_export FEEDFORWARD_COLOR / FEEDBACK_COLOR); commanded and applied wear the run's
  // colour (commanded thickest, applied thin), the target is grey and dashed like every target trace.
  var TORQUE_FEEDFORWARD = '#3b82f6';
  var TORQUE_FEEDBACK = '#f97316';
  var TORQUE_FEEDBACK_FILL = 'rgba(249, 115, 22, 0.12)';
  var TORQUE_TARGET = ink('#8a8983');

  // Legend order. ``key`` is the payload plot key (the target's τ is its own ``tau``; a run's ``tau`` is applied).
  var TORQUE_COMPONENTS = [
    { id: 'target', key: 'tau', label: 'Target', hint: 'the torque the reference needs (inverse dynamics of the target)' },
    { id: 'commanded', key: 'tau_cmd', label: 'Commanded', hint: 'what the controller sends to the FOC current loop (moteus control_torque) = feedforward + feedback; run colour, thickest' },
    { id: 'feedforward', key: 'tau_ff', label: 'Feedforward', hint: 'the model-based part of the command' },
    { id: 'feedback', key: 'tau_fb', label: 'Feedback', hint: 'the error-correcting part of the command (kp·e + kd·ė + ki∫e), filled to zero' },
    { id: 'applied', key: 'tau', label: 'Applied', hint: 'the torque actually delivered at that instant (moteus reply torque); run colour, thin' },
  ];
  // Draw order on a card: the filled feedback underneath, the target's dashes on top of the thick command.
  var TORQUE_DRAW_ORDER = ['feedback', 'feedforward', 'applied', 'commanded', 'target'];
  var TORQUE_DERIVED = {
    tau_cmd: 'commanded = FF + FB (derived)',
    tau_ff: 'feedforward = commanded − FB (derived)',
    tau_fb: 'feedback = commanded − FF (derived)',
  };

  function hasTorqueBreakdown(sit) {
    return !!(sit.has_data && sit.plot && sit.role !== 'target' &&
      (sit.plot.tau_cmd || sit.plot.tau_ff || sit.plot.tau_fb));
  }

  function withAlpha(color, alphaHex) {
    return /^#[0-9a-f]{6}$/i.test(color) ? color + alphaHex : color;
  }

  function torqueStyle(component, sit) {
    var name = component.charAt(0).toUpperCase() + component.slice(1);
    if (component === 'target') return { label: sit.title + ' τ', stroke: TORQUE_TARGET, width: 1.3, dash: [7, 4] };
    if (component === 'commanded') return { label: name, stroke: sit.color, width: 2.4 };
    if (component === 'feedforward') return { label: name, stroke: TORQUE_FEEDFORWARD, width: 1.4 };
    if (component === 'feedback') return { label: name, stroke: TORQUE_FEEDBACK, width: 1.2, fill: TORQUE_FEEDBACK_FILL };
    return { label: name, stroke: withAlpha(sit.color, 'bf'), width: 0.9 };
  }

  // ``joints``: the part's joints (default every joint); ``partName`` names the part in the title.
  function torqueBudgetTable(data, joints, partName) {
    function nm(value) { return value === null || value === undefined ? '—' : value.toFixed(3); }
    function percent(value) { return value === null || value === undefined ? '—' : (value * 100).toFixed(1) + ' %'; }
    var reference = referenceTitle(data);
    var columns = [
      ['FB share', 'fb_share', percent], ['Commanded RMS', 'cmd_rms', nm], ['FF RMS', 'ff_rms', nm],
      ['FB RMS', 'fb_rms', nm], ['Applied RMS', 'applied_rms', nm], [reference + ' − commanded RMS', 'target_minus_cmd_rms', nm],
      ['Commanded − applied RMS', 'cmd_minus_applied_rms', nm], ['Peak |commanded|', 'cmd_peak', nm],
    ];
    var budgets = [];
    data.situations.forEach(function (sit) {
      if (!sit.torque_budget) return;
      (joints || data.joint_names).forEach(function (jointName) {
        if (sit.torque_budget[jointName]) budgets.push([sit, jointName, sit.torque_budget[jointName]]);
      });
    });
    // WHY drop all-empty columns (Zach 2026-11-19, torque breakdown): a rig that logs only feedforward + applied
    // (no control_torque) would otherwise show a table of dashes; what was not recorded is said once, not per cell.
    columns = columns.filter(function (column) {
      return budgets.some(function (budget) { return budget[2][column[1]] !== null && budget[2][column[1]] !== undefined; });
    });
    var rows = budgets.map(function (budget) {
      return {
        cells: [budget[0].title, budget[1]].concat(columns.map(function (column) { return column[2](budget[2][column[1]]); })),
        tone: '',
      };
    });
    var missing = ['commanded', 'feedforward', 'feedback'].filter(function (name, index) {
      var key = ['cmd_rms', 'ff_rms', 'fb_rms'][index];
      return !budgets.some(function (budget) { return budget[2][key] !== null && budget[2][key] !== undefined; });
    });
    return {
      title: 'Torque budget per run and joint, N·m' + (partName ? ' — ' + partName : ''),
      description: 'FB share = Σ|feedback| / (Σ|feedforward| + Σ|feedback|) over the run\'s own samples: how much of the ' +
        'command the feedback had to supply (0 % = the feedforward did all of it). RMS values use each run\'s own samples. ' +
        reference + ' − commanded is lined up like every other error (time offset honoured, never extrapolated); ' +
        'commanded − applied is the drive gap (saturation, current-loop lag, torque-constant error). Torques in N·m.' +
        (missing.length ? ' Not recorded by any run: ' + missing.join(', ') + ' torque.' : ''),
      columns: ['Run', 'Joint'].concat(columns.map(function (column) { return column[0]; })),
      rows: rows,
    };
  }

  /* One chip per component present on the page; a chip toggles that component on every card (report-level pref). */
  function torqueLegend(page, body, runs, present) {
    var runReference = isRunReference(page.data);
    var legend = el('div', 'tc-torque-legend', body);
    el('span', 'grouplabel', legend, 'Components');
    var runColors = runs.map(function (sit) { return sit.color; });
    var runPaint = runColors.length > 1 ? 'linear-gradient(90deg, ' + runColors.join(', ') + ')' : (runColors[0] || ink('#52514e'));
    TORQUE_COMPONENTS.forEach(function (component) {
      if (!present[component.id]) return;
      var chip = el('button', 'chip', legend);
      var swatch = el('span', 'swatch torque-' + component.id, chip);
      if (component.id === 'target') { swatch.className += ' dashed'; swatch.style.color = TORQUE_TARGET; }
      else if (component.id === 'feedforward') swatch.style.background = TORQUE_FEEDFORWARD;
      else if (component.id === 'feedback') swatch.style.color = TORQUE_FEEDBACK;
      else swatch.style.background = runPaint;
      var reference = component.id === 'target' && runReference;
      chip.appendChild(document.createTextNode(reference ? referenceTitle(page.data) + ' τ (applied)' : component.label));
      chip.title = reference ? 'the applied torque of ' + referenceTitle(page.data) + ', the run this pair is measured against'
        : component.hint;
      function apply(show, remember) {
        page.torqueOn[component.id] = show;
        chip.className = 'chip ' + (show ? 'on' : 'off');
        if (remember) state.prefs.set('torque:' + component.id, show);
        page.charts.forEach(function (chart) { if (chart.setComponent) chart.setComponent(component.id); });
      }
      page.torqueChips.push({ id: component.id, apply: apply });
      chip.onclick = function () { apply(page.torqueOn[component.id] === false, true); };
      apply(state.prefs.get('torque:' + component.id, true), false);
    });
    el('span', 'tc-torque-note', legend, 'commanded and applied wear the run\'s colour');
  }

  function torqueBreakdownBuilder(page, body, section) {
    var data = page.data;
    var runs = data.situations.filter(hasTorqueBreakdown);
    if (!runs.length) {
      buildTable(body, torqueBudgetTable(data), true).classList.add('embedded', 'tc-torque-budget');
      el('div', 'tc-empty', body, 'No measured run has a commanded, feedforward or feedback torque.');
      return;
    }
    var target = data.situations.filter(function (sit) {
      return sit.role === 'target' && sit.has_data && sit.plot && sit.plot.tau;
    })[0] || null;
    var present = { target: !!target };
    runs.forEach(function (sit) {
      TORQUE_COMPONENTS.forEach(function (component) {
        if (component.id !== 'target' && sit.plot[component.key]) present[component.id] = true;
      });
    });
    torqueLegend(page, body, runs, present);

    // WHY the budget per part (Zach 2026-11-19, parts): 46 motors × 4 runs is a 184-row table; the selected
    // arm or hand's rows sit above its own cards instead.
    var named = page.parts.length > 1;
    partView(page, section, body, function (page, host, jointName, dof) {
      runs.forEach(function (sit) {
        var series = [];
        TORQUE_DRAW_ORDER.forEach(function (id) {
          var owner = id === 'target' ? target : sit;
          var key = TORQUE_COMPONENTS.filter(function (component) { return component.id === id; })[0].key;
          if (!owner || !owner.plot[key]) return;
          series.push({ sit: owner, component: id, values: owner.plot[key][dof], style: torqueStyle(id, owner) });
        });
        // WHY say "derived" on the card (CONTRACT.md): a component computed from the other two is not a recording
        var derived = (sit.derived || []).filter(function (key) { return TORQUE_DERIVED[key]; })
          .map(function (key) { return TORQUE_DERIVED[key]; });
        var card = el('div', 'tc-plotcard', host);
        card.dataset.situation = sit.name;
        makeChart(page, card, {
          title: jointName + ' · ' + sit.title + ': torque breakdown', kind: 'Nm', series: series,
          situation: sit.name, note: derived.join(' · '),
        });
      });
    }, function (block, part) {
      var budget = buildTable(block, torqueBudgetTable(data, partJoints(part), named ? part.name : ''), true);
      budget.classList.add('embedded', 'tc-torque-budget');
    });
  }

  // The frame fk / poses describe (Comparison.tcp_frame): "TCP", "L2 tip", ...
  function frameName(page) {
    return page.data.tcp_frame || 'TCP';
  }

  function tcpPoseBuilder(page, body) {
    var grid = el('div', 'tc-grid', body);
    var frame = frameName(page);
    // WHY the axis named in full (Zach 2026-11-19, traj compare view feedback: titles "super descriptive")
    [['x', frame + ' position x (world)', 'm'], ['y', frame + ' position y (world)', 'm'],
     ['z', frame + ' position z (world)', 'm'],
     ['rx', frame + ' rotation rx (extrinsic xyz, unwrapped)', 'angle'],
     ['ry', frame + ' rotation ry (extrinsic xyz, unwrapped)', 'angle'],
     ['rz', frame + ' rotation rz (extrinsic xyz, unwrapped)', 'angle']]
      .forEach(function (row) {
        var series = sitsWith(page, row[0]).map(function (sit) {
          return { sit: sit, values: sit.plot[row[0]] };
        });
        if (!series.length) return;
        makeChart(page, el('div', 'tc-plotcard', grid),
          { title: row[1], kind: row[2], series: withErrors(series) });
      });
    observeGrid(page, grid);
  }

  function tcpErrBuilder(page, body) {
    var grid = el('div', 'tc-grid', body);
    var frame = frameName(page);
    var minus = referenceTitle(page.data) + ' − run';
    // Combined magnitudes, then the path split (off the path vs behind along it),
    // then each world axis on its own (rotation as a rotation vector, not RPY).
    // Every error is target - run, as robot_msgs.compare computes it.
    [['xyz_mag', frame + ' position error |Δp|, |' + minus + '|', 'mm'],
     ['rot_mag', frame + ' rotation error angle, ' + minus, 'angle'],
     ['cross_track', frame + ' cross-track error, distance off ' + referenceWord(page.data) + "'s path", 'mm'],
     ['lag', frame + ' lag along the path, + = run behind ' + referenceWord(page.data), 'mm'],
     ['contour', frame + ' contour error, exact distance to ' + referenceWord(page.data) + "'s path", 'mm'],
     ['lag_time', frame + ' lag time, + = run behind ' + referenceWord(page.data), 'ms']]
      .concat((page.data.error_axes || []).map(function (label, index) {
        // WHY a field of its own per axis: err_axes is one list per axis, not one channel
        return ['err_axes:' + index, frame + ' position error along ' + label + ', ' + minus, 'mm'];
      }))
      .concat([
     ['err_x', frame + ' position error x (world), ' + minus, 'mm'],
     ['err_y', frame + ' position error y (world), ' + minus, 'mm'],
     ['err_z', frame + ' position error z (world), ' + minus, 'mm'],
     ['err_rx', frame + ' rotation error about x (world rotation vector), ' + minus, 'angle'],
     ['err_ry', frame + ' rotation error about y (world rotation vector), ' + minus, 'angle'],
     ['err_rz', frame + ' rotation error about z (world rotation vector), ' + minus, 'angle']]).forEach(function (row) {
      var axis = row[0].indexOf('err_axes:') === 0 ? Number(row[0].slice(9)) : null;
      var field = axis === null ? row[0] : 'err_axes';
      var series = sitsWith(page, field).map(function (sit) {
        return { sit: sit, values: axis === null ? sit.plot[field] : sit.plot[field][axis] };
      });
      if (!series.length) return;
      makeChart(page, el('div', 'tc-plotcard', grid),
        { title: row[1], kind: row[2], series: series });
    });
    observeGrid(page, grid);
  }

  function jointErrBuilder(page, body, section) {
    var sits = sitsWith(page, 'err_q');
    var minus = referenceTitle(page.data) + ' − run';
    partView(page, section, body, function (page, host, jointName, dof) {
      if (!sits.length) return;
      makeChart(page, el('div', 'tc-plotcard', host), {
        title: jointName + ': joint error, ' + minus, kind: 'angle',
        series: sits.map(function (sit) { return { sit: sit, values: sit.plot.err_q[dof] }; }),
      });
    });
  }

  function pathBuilder(page, body) {
    var frame = frameName(page);
    var whose = page.data.pct_reference === 'target' ? 'the target' : 'its own';
    // labels: [the value, its rate, its acceleration] (Zach 2026-11-19: every title names signal and unit)
    var channels = [
      { key: 'pct', labels: ['% of ' + whose + ' path length completed', 'path speed, % of the path per s',
                             'path acceleration, % of the path per s²'], kinds: ['pct', 'pct_s', 'pct_s2'] },
      { key: 'xyz', labels: [frame + ' distance travelled along its path', frame + ' speed along its path',
                             frame + ' acceleration along its path'], kinds: ['m', 'm_s', 'm_s2'] },
      { key: 'rpy', labels: [frame + ' rotation accumulated along its path', frame + ' rotation rate',
                             frame + ' rotation acceleration'], kinds: ['angle', 'angle_rate', 'angle_acc'] },
    ];
    page.data.vec_labels.forEach(function (label, index) {
      channels.push({ key: 'vec' + index, labels: [frame + ' signed displacement along ' + label,
        frame + ' speed along ' + label, frame + ' acceleration along ' + label], kinds: ['m', 'm_s', 'm_s2'] });
    });
    var grid = el('div', 'tc-grid pathgrid', body);
    grid.style.setProperty('--path-cols', String(channels.length));
    [['', 0], ['_d', 1], ['_dd', 2]].forEach(function (level) {
      channels.forEach(function (channel) {
        var field = channel.key + level[0];
        var series = sitsWith(page, field).map(function (sit) {
          return { sit: sit, values: sit.plot[field] };
        });
        if (!series.length) return;
        makeChart(page, el('div', 'tc-plotcard', grid),
          { title: channel.labels[level[1]], kind: channel.kinds[level[1]],
            series: withErrors(series) });
      });
    });
    observeGrid(page, grid);
  }

  function videosBuilder(page, body) {
    var grid = el('div', 'tc-videogrid', body);
    page.data.situations.forEach(function (sit) {
      if (!sit.video) return;
      var card = el('div', 'tc-videocard', grid);
      card.dataset.situation = sit.name;
      var label = el('div', 'vlabel', card);
      var swatch = el('span', 'swatch', label);
      swatch.style.background = sit.color;
      label.appendChild(document.createTextNode(sit.title));
      var video = document.createElement('video');
      video.src = sit.video;
      video.muted = true;
      video.playsInline = true;
      video.preload = 'auto';
      card.appendChild(video);
      video.addEventListener('click', function () {
        if (page.transport) page.transport.toggle();
      });
      page.videos.push({ sit: sit, el: video, card: card, t0: sit.video_start_s || 0 });
      if (page.visible[sit.name] === false) card.style.display = 'none';
    });
    // One transport for every video on the page — the videos are frames of
    // the same run, so they are never scrubbed or played independently.
    if (page.transport) buildTransportBar(page, body);
    el('div', 'tc-videonote', body,
      (page.oneTimeline ? 'The time lane drives' : 'One scrubber drives') + ' every video, the plot cursors and the 3D view ' +
      'together; clicking a video plays/pauses them all.');
  }

  /* ---------------- camera overlay: real video + sim render ---------------- */

  var FLICKER_PERIOD_MS = 250;  // real <-> sim swap, i.e. a 2 Hz blink

  function overlayLayer(stack, className) {
    var video = el('video', className, stack);
    video.muted = true;
    video.playsInline = true;
    video.preload = 'auto';
    return { el: video, path: '', failed: false };
  }

  function overlaySetSource(layer, path) {
    layer.path = path || '';
    layer.failed = !path;
    if (path) {
      layer.el.src = path;
    } else {
      layer.el.removeAttribute('src');
      layer.el.load();
    }
  }

  function overlayControl(parent, labelText) {
    var group = el('label', 'tc-ovl-ctl', parent);
    el('span', 'ctl-label', group, labelText);
    return group;
  }

  function buildOverlayCard(page, parent, overlay) {
    var key = 'overlay:' + overlay.name + ':';
    var card = el('div', 'tc-overlaycard', parent);
    card.dataset.overlay = overlay.name;
    var heading = el('div', 'vlabel', card, overlay.name);
    if (overlay.note) el('span', 'vnote', heading, ' — ' + overlay.note);

    // Real sits underneath at full opacity; only the sim layer carries the
    // slider. WHY: fading both layers lets the black box show through and
    // darkens the middle of the slider, and a single opacity makes 0 and 1
    // exactly "only real" / "only sim" — which is the comparison being made.
    var stack = el('div', 'tc-ovl-stack', card);
    var real = overlayLayer(stack, 'tc-ovl-real');
    var sim = overlayLayer(stack, 'tc-ovl-sim');
    var missing = el('div', 'tc-ovl-missing', stack);
    var user = { opacity: 0.5, sim: overlay.sims[0].label, blend: 'normal', flicker: false };
    var flickerPhase = false;
    var flickerTimer = null;

    var controls = el('div', 'tc-ovl-controls', card);
    var opacityGroup = overlayControl(controls, 'Real ◀ ▶ Sim');
    var slider = el('input', 'tc-ovl-opacity', opacityGroup);
    slider.type = 'range';
    slider.min = 0; slider.max = 1; slider.step = 0.01;
    var opacityOut = el('output', '', opacityGroup);
    var simGroup = overlayControl(controls, 'Sim');
    var simSelect = el('select', 'tc-ovl-simsel', simGroup);
    overlay.sims.forEach(function (entry) {
      var option = el('option', '', simSelect, entry.label);
      option.value = entry.label;
    });
    simSelect.disabled = overlay.sims.length < 2;
    var blendGroup = overlayControl(controls, 'Blend');
    var blendSelect = el('select', 'tc-ovl-blendsel', blendGroup);
    [['normal', 'Mix (normal)'], ['difference', 'Difference']].forEach(function (pair) {
      var option = el('option', '', blendSelect, pair[1]);
      option.value = pair[0];
    });
    var flickerChip = el('button', 'chip tc-ovl-flicker', controls, 'Flicker');
    flickerChip.title = 'alternate real and sim at 2 Hz for a blink comparison';

    function simPath(label) {
      for (var i = 0; i < overlay.sims.length; i++) {
        if (overlay.sims[i].label === label) return overlay.sims[i].video;
      }
      return overlay.sims[0].video;
    }

    function paint() {
      var flicker = user.flicker;
      sim.el.style.opacity = flicker ? (flickerPhase ? 1 : 0) : user.opacity;
      // the blend only reads sensibly against a steady layer, so a blink is plain
      sim.el.style.mixBlendMode = (user.blend === 'difference' && !flicker) ? 'difference' : 'normal';
      slider.value = user.opacity;
      slider.disabled = flicker;
      opacityOut.textContent = user.opacity.toFixed(2);
      simSelect.value = user.sim;
      blendSelect.value = user.blend;
      flickerChip.className = 'chip tc-ovl-flicker ' + (flicker ? 'on' : 'off');
      card.dataset.flickerPhase = flicker ? (flickerPhase ? 'sim' : 'real') : '';
      var lines = [];
      if (real.failed) lines.push('no video — real: ' + (real.path || '(no path)'));
      if (sim.failed) lines.push('no video — sim: ' + (sim.path || '(no path)'));
      missing.textContent = lines.join('\n');
      missing.style.display = lines.length ? '' : 'none';
      card.classList.toggle('missing', real.failed);
      real.el.style.visibility = real.failed ? 'hidden' : '';
      sim.el.style.visibility = sim.failed ? 'hidden' : '';
    }

    function setFlicker(on) {
      user.flicker = on;
      if (flickerTimer !== null) { clearInterval(flickerTimer); flickerTimer = null; }
      flickerPhase = false;
      if (on) {
        flickerTimer = setInterval(function () {
          flickerPhase = !flickerPhase;
          paint();
        }, FLICKER_PERIOD_MS);
      }
    }

    // The overlay videos join the page's video list, so seek/play/drag
    // coalescing is the Videos section's own code, not a copy of it.
    var realEntry = { sit: { name: 'overlay:' + overlay.name + ':real' }, el: real.el, card: card, t0: overlay.t0_s };
    var simEntry = { sit: { name: 'overlay:' + overlay.name + ':sim' }, el: sim.el, card: card, t0: overlay.t0_s };
    page.videos.push(realEntry, simEntry);

    function catchUp(layer, entry) {
      var transport = page.transport;
      if (!transport) return;
      // while playing, the transport's tick starts it once it sits on the clock
      seekEntry(entry, transport.t === null ? transport.tMax : transport.t);
    }
    [[real, realEntry], [sim, simEntry]].forEach(function (pair) {
      var layer = pair[0], entry = pair[1];
      layer.el.addEventListener('error', function () { layer.failed = true; paint(); });
      layer.el.addEventListener('loadedmetadata', function () {
        layer.failed = false;
        // one box, one aspect: the real stream decides it
        if (layer === real && layer.el.videoWidth) {
          stack.style.aspectRatio = layer.el.videoWidth + ' / ' + layer.el.videoHeight;
        }
        paint();
        catchUp(layer, entry);
      });
    });
    stack.addEventListener('click', function () {
      if (page.transport) page.transport.toggle();
    });

    slider.addEventListener('input', function () {
      user.opacity = parseFloat(slider.value);
      state.prefs.set(key + 'opacity', user.opacity);
      paint();
    });
    simSelect.addEventListener('change', function () {
      user.sim = simSelect.value;
      state.prefs.set(key + 'sim', user.sim);
      overlaySetSource(sim, simPath(user.sim));
      paint();
    });
    blendSelect.addEventListener('change', function () {
      user.blend = blendSelect.value;
      state.prefs.set(key + 'blend', user.blend);
      paint();
    });
    flickerChip.onclick = function () {
      setFlicker(!user.flicker);
      state.prefs.set(key + 'flicker', user.flicker);
      paint();
    };

    // Pull report-level choices (made on another scenario tab, or remembered
    // from last time) into this card; the sim source reloads only on a change.
    function applyShared() {
      user.opacity = Number(state.prefs.get(key + 'opacity', 0.5));
      user.blend = state.prefs.get(key + 'blend', 'normal') === 'difference' ? 'difference' : 'normal';
      var wantSim = state.prefs.get(key + 'sim', overlay.sims[0].label);
      var known = overlay.sims.some(function (entry) { return entry.label === wantSim; });
      if (!known) wantSim = overlay.sims[0].label;
      var simChanged = wantSim !== user.sim || !sim.path;
      user.sim = wantSim;
      var wantFlicker = !!state.prefs.get(key + 'flicker', false);
      if (wantFlicker !== user.flicker) setFlicker(wantFlicker);
      if (simChanged) overlaySetSource(sim, simPath(user.sim));
      paint();
    }

    overlaySetSource(real, overlay.real_video);
    page.overlayCards.push({ overlay: overlay, applyShared: applyShared });
    applyShared();
  }

  function cameraBuilder(page, body) {
    var grid = el('div', 'tc-overlaygrid', body);
    page.data.overlays.forEach(function (overlay) { buildOverlayCard(page, grid, overlay); });
    if (page.transport) buildTransportBar(page, body);
    el('div', 'tc-videonote', body,
      'The real stream is the base layer; the slider fades the sim render over it ' +
      '(Difference shows where they disagree). The ' + (page.oneTimeline ? 'time lane' : 'scrubber') + ' drives both, offset by t0.');
  }

  function viewer3dBuilder(page, body) {
    var wrap = el('div', '', body);
    page.viewer3d = Viewer3D.create(page, wrap, { height: stageCanvasHeight });
  }

  // WHY (Zach 2026-11-19, keep the 3D always visible): in the stage the canvas and its scrubber fit one screen.
  function stageCanvasHeight(width) {
    return Math.max(220, Math.min(540, width * 0.8, window.innerHeight - 230));
  }

  function observeGrid(page, grid) {
    if (typeof ResizeObserver === 'undefined') return;
    var pending = false;
    var observer = new ResizeObserver(function () {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () {
        pending = false;
        page.charts.forEach(function (chart) {
          if (grid.contains(chart.card)) chart.resize();
        });
      });
    });
    observer.observe(grid);
  }

  /* ---------------- page assembly ---------------- */

  function sectionStartsOn(data, id, fallback) {
    if (!Array.isArray(data.default_sections)) return fallback;
    return data.default_sections.indexOf(id) !== -1;
  }

  // ``units`` appends the bracketed unit(s), read at paint time so the rad/deg toggle repaints it.
  function inUnit(kind) {
    return function () { return ' [' + unitLabel(kind) + ']'; };
  }

  /* WHY the long labels (Zach 2026-11-19, traj compare view feedback: titles "super descriptive"): each names the
     signal, its sign convention and unit — "Joint angle q [°]", never "Joint q". Section ids stay as they were:
     callers pass them in ``default_sections``. */
  function sectionDefs(data) {
    var reference = referenceTitle(data);
    var frame = data.tcp_frame || 'TCP';
    var defs = [
      { id: 'joint-q', label: 'Joint angle q', units: inUnit('angle'), on: sectionStartsOn(data, 'joint-q', true), build: jointSectionBuilder('q', 'angle', 'joint angle q') },
      { id: 'joint-qd', label: 'Joint speed q̇', units: inUnit('angle_rate'), on: sectionStartsOn(data, 'joint-qd', false), build: jointSectionBuilder('qd', 'angle_rate', 'joint speed q̇') },
      { id: 'joint-qdd', label: 'Joint acceleration q̈', units: inUnit('angle_acc'), on: sectionStartsOn(data, 'joint-qdd', false), build: jointSectionBuilder('qdd', 'angle_acc', 'joint acceleration q̈') },
    ];
    if (data.has_tau) {
      defs.push({ id: 'joint-tau', label: 'Motor / joint τ, applied torque', units: inUnit('Nm'), on: sectionStartsOn(data, 'joint-tau', false), build: jointSectionBuilder('tau', 'Nm', 'applied torque τ') });
    }
    if (data.has_current) {
      defs.push({ id: 'joint-current', label: 'Motor current i', units: inUnit('A'), on: sectionStartsOn(data, 'joint-current', false), build: jointSectionBuilder('current', 'A', 'motor current i') });
    }
    if (data.has_torque_breakdown) {
      // on by default (CONTRACT.md): the split of the command is the question a breakdown is recorded to answer
      defs.push({ id: 'joint-torque', label: 'Torque breakdown: ' + (isRunReference(data) ? reference + ' (applied)' : 'target') +
        ', commanded = feedforward + feedback, applied', units: inUnit('Nm'), on: sectionStartsOn(data, 'joint-torque', true), build: torqueBreakdownBuilder });
    }
    var anyErr = data.situations.some(function (sit) { return sit.plot && sit.plot.err_q; });
    if (anyErr) {
      defs.push({ id: 'joint-err', label: 'Joint error, ' + reference + ' − run', units: inUnit('angle'), on: sectionStartsOn(data, 'joint-err', false), build: jointErrBuilder });
    }
    if (data.has_cartesian) {
      defs.push({ id: 'tcp-pose', label: frame + ' pose, world frame', units: function () { return ' [m, ' + unitLabel('angle') + ']'; }, on: sectionStartsOn(data, 'tcp-pose', false), build: tcpPoseBuilder });
      var anyMag = data.situations.some(function (sit) { return sit.plot && sit.plot.xyz_mag; });
      if (anyMag) defs.push({ id: 'tcp-err', label: frame + ' error, ' + reference + ' − run', units: function () { return ' [mm, ' + unitLabel('angle') + ', ms]'; }, on: sectionStartsOn(data, 'tcp-err', true), build: tcpErrBuilder });
      defs.push({ id: 'path', label: 'Path progress: distance, speed and acceleration along the path', units: function () { return ' [%, m, ' + unitLabel('angle') + ']'; }, on: sectionStartsOn(data, 'path', true), build: pathBuilder });
    }
    if (data.has_overlay) {
      defs.push({ id: 'camera', label: 'Camera overlay: real video under the sim render', on: sectionStartsOn(data, 'camera', true), build: cameraBuilder });
    }
    if (data.has_video) {
      defs.push({ id: 'videos', label: 'Videos, one per run, played together', on: sectionStartsOn(data, 'videos', true), build: videosBuilder });
    }
    if (data.has_cartesian) {
      defs.push({ id: 'viewer3d', label: '3D view: robot and ' + frame + ' paths', on: sectionStartsOn(data, 'viewer3d', true), build: viewer3dBuilder });
    }
    // WHY always on (NAVIGATION.md C1): the channels tab exists to show them; ``default_sections`` names the fixed
    // sections only, so it never hides a channel
    (data.channels || []).forEach(function (channel) {
      var units = channel.unit ? function () { return ' [' + channel.unit + ']'; } : null;
      defs.push({ id: channel.section, label: channel.title, units: units, on: true, build: channelSectionBuilder(channel) });
    });
    return defs;
  }

  function sectionTitle(def) {
    return def.label + (def.units ? def.units() : '');
  }

  // The stage pins these beside the question tabs, 3D first (NAVIGATION.md Part B).
  var STAGE_SECTIONS = ['viewer3d', 'camera', 'videos'];

  // Sections whose plots carry the optional Δ-to-target overlay.
  var DELTA_SECTIONS = ['joint-q', 'joint-qd', 'joint-qdd', 'joint-tau', 'joint-current', 'tcp-pose', 'path'];

  function sectionHint(id, data, page) {
    var timeControl = page && page.oneTimeline ? 'the time lane' : 'the scrubber';
    var channel = (data.channels || []).filter(function (entry) { return entry.section === id; })[0];
    if (channel) return channelHint(channel, data);
    var hint = '';
    if (id === 'path') {
      var reference = data.pct_reference === 'target' ? 'target path length' : 'own path length';
      hint = '% is of ' + reference + '; Vec is signed progress along the labeled direction';
    }
    if (id === 'tcp-err') {
      hint = (data.tcp_frame || 'TCP') + ' frame, error = ' + referenceTitle(data) + ' − run at the run\'s own sample times; ' +
        'axis errors are world-frame, rotation as a world-axis rotation vector; ' +
        'lag is + when the run is behind ' + referenceWord(data) + '; contour is the exact distance to the reference path, ' +
        'lag time the time offset to its nearest point' +
        (data.error_axes && data.error_axes.length
          ? '; error · <axis> is the position error projected on ' + data.error_axes.join(' / ') : '');
    }
    if (id === 'tcp-pose') hint = (data.tcp_frame || 'TCP') + ' frame';
    if (id === 'joint-torque') {
      hint = 'commanded = feedforward + feedback is what goes to the FOC current loop; applied is what the drive delivered; ' +
        'the component chips toggle a torque on every card';
    }
    if (id === 'videos') hint = 'always played together, seeked by ' + timeControl;
    if (id === 'camera') hint = 'real video under the sim render; both follow ' + timeControl;
    if (id === 'viewer3d') {
      hint = 'drag any plot or ' + (page && page.oneTimeline ? 'the time lane' : 'the slider below') +
        ' to move the time everywhere; hovering a plot previews that instant here';
    }
    // tau and current are optional on the target; no target trace, no Δ to draw
    var needs = { 'joint-tau': 'tau', 'joint-current': 'current' }[id];
    var hasTarget = data.situations.some(function (sit) {
      return sit.role === 'target' && sit.plot && (!needs || sit.plot[needs]);
    });
    if (hasTarget && DELTA_SECTIONS.indexOf(id) !== -1) {
      hint += (hint ? ' · ' : '') +
        'Error (' + referenceTitle(data) + ' − run) draws a dotted Δ here; hide target + measured to read it on its own axis';
    }
    return hint;
  }

  function buildTable(parent, table, compact) {
    var block = el('section', 'tc-tableblock' + (compact ? ' compact' : ''), parent);
    if (table.title) el('h3', '', block, table.title);
    if (table.description) el('p', 'tc-table-desc', block, table.description);
    var scroll = el('div', 'tc-table-scroll', block);
    var tableEl = el('table', 'tc-metrics', scroll);
    var head = el('thead', '', tableEl);
    var headRow = el('tr', '', head);
    table.columns.forEach(function (column) { el('th', '', headRow, column); });
    var body = el('tbody', '', tableEl);
    table.rows.forEach(function (row) {
      var tr = el('tr', row.tone ? 'tone-' + row.tone : '', body);
      row.cells.forEach(function (cell, index) {
        var tag = index === 0 ? 'th' : 'td';
        // A verdict column reads green when SUCCESSFUL and red only for a violation.
        var verdict = index > 0 && table.columns[index].indexOf('Verdict') === 0 && cell !== '—';
        el(tag, verdict ? 'verdict ' + (cell === 'SUCCESSFUL' ? 'ok' : 'bad') : '', tr, cell);
      });
    });
    return block;
  }

  function buildMetricCards(parent, metrics) {
    if (!metrics || !metrics.length) return;
    var grid = el('div', 'tc-metriccards', parent);
    metrics.forEach(function (metric) {
      var card = el('div', 'tc-metriccard tone-' + (metric.tone || 'neutral'), grid);
      el('div', 'label', card, metric.label);
      el('div', 'value', card, metric.value);
      if (metric.detail) el('div', 'detail', card, metric.detail);
    });
  }

  function buildBarChart(parent, chart) {
    var section = el('section', 'tc-summary-chart', parent);
    el('h3', '', section, chart.title);
    if (chart.description) el('p', 'tc-table-desc', section, chart.description);
    var values = [];
    chart.series.forEach(function (series) {
      series.values.forEach(function (value) { if (value !== null) values.push(value); });
    });
    var maximum = values.length ? Math.max.apply(null, values) : 1;
    if (!(maximum > 0)) maximum = 1;
    // report.py's SITUATION_PALETTE: a bar chart with more than five series no longer wraps to blue
    var colors = ['#2a78d6', '#eb6834', '#2f9e44', '#8e5bd1', '#c22f6e', '#17a2b8', '#a67c00', '#6b7a8f',
      '#d17c7b', '#336a3a', '#7d4b8b', '#974811', '#f356b8', '#ac28ab', '#b81b36', '#9d86da'];
    chart.categories.forEach(function (category, categoryIndex) {
      var group = el('div', 'tc-bar-group', section);
      el('div', 'tc-bar-category', group, category);
      chart.series.forEach(function (series, seriesIndex) {
        var row = el('div', 'tc-bar-row', group);
        el('div', 'tc-bar-label', row, series.name);
        var track = el('div', 'tc-bar-track', row);
        var value = series.values[categoryIndex];
        var fill = el('span', 'tc-bar-fill', track);
        fill.style.background = series.color || colors[seriesIndex % colors.length];
        fill.style.width = value === null ? '0' : Math.max(1, value / maximum * 100) + '%';
        var formatted = value === null ? '—' : value.toFixed(chart.decimals);
        el('div', 'tc-bar-value', row, formatted + (chart.unit ? ' ' + chart.unit : ''));
      });
    });
  }

  function buildInsightCards(parent, insights) {
    if (!insights || !insights.length) return;
    var grid = el('div', 'tc-insights', parent);
    insights.forEach(function (insight) {
      var card = el('article', 'tc-insight tone-' + (insight.tone || 'neutral'), grid);
      el('h3', '', card, insight.title);
      el('p', 'finding', card, insight.finding);
      if (insight.evidence && insight.evidence.length) {
        var list = el('ul', 'evidence', card);
        insight.evidence.forEach(function (item) { el('li', '', list, item); });
      }
      if (insight.recommendation) {
        var recommendation = el('p', 'recommendation', card);
        el('strong', '', recommendation, 'Recommendation: ');
        recommendation.appendChild(document.createTextNode(insight.recommendation));
      }
    });
  }

  function buildReportPage(page) {
    var data = page.data;
    el('h2', 'tc-page-title', page.el, data.title);
    if (data.description) el('p', 'tc-report-desc', page.el, data.description);
    buildMetricCards(page.el, data.metrics);
    data.charts.forEach(function (chart) { buildBarChart(page.el, chart); });
    data.tables.forEach(function (table) { buildTable(page.el, table, false); });
    (data.images || []).forEach(function (image) { buildFigure(page.el, image); });
    buildInsightCards(page.el, data.insights);
  }

  function buildFigure(parent, image) {
    var figure = el('figure', 'tc-figure', parent);
    el('h3', '', figure, image.title);
    var img = el('img', '', figure);
    img.src = image.src;
    img.alt = image.title;
    if (image.width_px) img.style.width = image.width_px + 'px';
    if (image.caption) el('figcaption', '', figure, image.caption);
  }

  /* ---- Open in Rerun ------------------------------------------------------------------------
     The .rrd beside this report is the same data in Rerun (WHY: Tracking-Run Data — data-ui vs
     Rerun, 2026-10-26: the viewer is one projection, Rerun the other). Served by
     ``python -m traj_compare.serve`` the primary button starts the pinned viewer through the
     server; from file:// or a plain static server there is nothing to start it, so it copies the
     command instead. Either way the command stays on screen. */
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; },
        function () { return copyTextFallback(text); });
    }
    return Promise.resolve(copyTextFallback(text));
  }

  function copyTextFallback(text) {
    var area = el('textarea', '', document.body, text);
    area.style.cssText = 'position:fixed;left:-9999px;top:0';
    area.select();
    var done = false;
    try { done = document.execCommand('copy'); } catch (error) { done = false; }
    document.body.removeChild(area);
    return done;
  }

  /* Parquet / MCAP beside the page (WHY: prior-art item 10, 2026-11-10: PlotJuggler, Foxglove, LeRobot
     and pandas read them; the same payload as the plots). Plain download links, no launcher. */
  function addExportLinks(row, exports) {
    [['parquet', 'Download Parquet', 'tidy rows: comparison, situation, reference, channel, column, t, value'],
     ['mcap', 'Download MCAP', 'one JSON topic per situation and channel, for PlotJuggler / Foxglove']
    ].forEach(function (item) {
      if (!exports[item[0]]) return;
      var link = el('a', 'tc-rerun-btn', row, item[1]);
      link.href = exports[item[0]];
      link.setAttribute('download', '');
      link.title = item[2];
    });
  }

  function buildExportsBar(root, exports) {
    var bar = el('div', 'tc-rerun', root);
    addExportLinks(el('div', 'tc-rerun-row', bar), exports);
  }

  function buildRerunBar(root, info, exports) {
    var served = location.protocol === 'http:' || location.protocol === 'https:';
    var rrdUrl = new URL(info.rrd, location.href);
    var bar = el('div', 'tc-rerun', root);
    var row = el('div', 'tc-rerun-row', bar);
    // Named layouts (rerun_export.LAYOUTS): the first is the one embedded in the .rrd (the user's preference);
    // choosing another opens its .rbl beside the .rrd. WHY a choice here: Zach, 2026-11-11 — named layouts
    // ("evo", "questions") so each person keeps their own preference.
    var layouts = info.layouts || [];
    var chosen = layouts[0] || null;
    var picker = null;
    if (layouts.length > 1) {
      var pick = el('label', 'tc-rerun-layout', row, 'Layout ');
      picker = el('select', 'tc-rerun-select', pick);
      layouts.forEach(function (layout) {
        var option = el('option', '', picker, layout.title || layout.name);
        option.value = layout.name;
      });
    }
    var open = el('button', 'tc-rerun-open', row, 'Open in Rerun');
    var copy = el('button', 'tc-rerun-btn', row, 'Copy command');
    var download = el('a', 'tc-rerun-btn', row, 'Download .rrd');
    download.href = info.rrd;
    download.setAttribute('download', '');
    if (exports) addExportLinks(row, exports);
    if (served) {
      var web = el('a', 'tc-rerun-btn', row, 'Rerun in browser');
      web.href = 'https://app.rerun.io/version/' + info.sdk + '/index.html?url=' +
        encodeURIComponent(rrdUrl.href);
      web.target = '_blank';
      web.rel = 'noopener';
      web.title = 'the web viewer fetches the .rrd from this server; it needs the serve command';
    }
    var status = el('span', 'tc-rerun-status', row);
    var command = el('code', 'tc-rerun-cmd', bar, chosen ? chosen.command : info.command);
    if (picker) {
      picker.onchange = function () {
        chosen = layouts.filter(function (layout) { return layout.name === picker.value; })[0] || layouts[0];
        command.textContent = chosen.command;
        say('');
      };
    }
    command.title = 'Rerun ' + info.sdk + ' (an .rrd needs a viewer at least as new as its SDK)';

    function say(text, bad) {
      status.textContent = text;
      status.classList.toggle('bad', !!bad);
    }
    function copyCommand(prefix) {
      return Promise.resolve(copyText(chosen ? chosen.command : info.command)).then(function (ok) {
        say(ok ? prefix + 'command copied — paste it in a terminal' : prefix + 'copy failed — select the command below');
      });
    }
    copy.onclick = function () { copyCommand(''); };
    open.onclick = function () {
      if (!served) { copyCommand('No launcher on file:// — '); return; }
      say('Opening Rerun…');
      // The endpoint wants a path relative to the served root, not to this page.
      var relative = decodeURIComponent(rrdUrl.pathname.replace(/^\//, ''));
      var query = '?rrd=' + encodeURIComponent(relative) + (chosen ? '&layout=' + encodeURIComponent(chosen.name) : '');
      fetch(location.origin + '/__rerun/open' + query, { method: 'POST' })
        .then(function (response) {
          return response.text().then(function (text) {
            var body = null;
            try { body = JSON.parse(text); } catch (error) { body = null; }
            if (body && body.ok) { say('Opening Rerun… (the window can take a few seconds)'); return; }
            if (body && body.error) { say(body.error, true); return; }
            // Not our server: a plain static server answers 404/405/501 for the POST.
            return copyCommand('No launcher on this server — ');
          });
        }, function () { return copyCommand('No launcher reachable — '); });
    };
  }

  /* ---------------- verdicts + ISO 9283 (robot_msgs.compare.check / aggregate) ---------------- */

  // WHY degrees (Zach's rule: degrees at the display edge, never a milli-radian): a verdict's error and limit are SI, so a joint
  // position, a rotation and an angular rate read in °, °/s, °/s²; a TCP distance in mm. A metric this does not know prints
  // its SI number with no unit rather than a wrong one.
  function formatLimit(metric, value) {
    var magnitude = Math.abs(value);
    var number = function (x, unit) { return Number(x.toPrecision(3)) + unit; };
    var head = metric.split('/')[0];
    if (head === 'velocities' || metric === 'angular_velocity') return number(magnitude * RAD2DEG, '°/s');
    if (head === 'accelerations') return number(magnitude * RAD2DEG, '°/s²');
    if (head === 'positions' || ['rotation', 'rx', 'ry', 'rz'].indexOf(metric) >= 0) return number(magnitude * RAD2DEG, '°');
    if (metric === 'linear_velocity') return number(magnitude * 1000, ' mm/s');
    if (['position', 'x', 'y', 'z', 'lag', 'cross_track', 'contour'].indexOf(metric) >= 0) return number(magnitude * 1000, ' mm');
    if (metric === 'lag_time') return number(magnitude * 1000, ' ms');
    if (head === 'effort') return number(magnitude, ' N·m');
    return number(magnitude, '');
  }

  function violationText(violation) {
    return violation.metric + ': ' + formatLimit(violation.metric, violation.error) + ' > ' +
      formatLimit(violation.metric, violation.limit) + ' at t = ' + violation.t.toFixed(2) + ' s';
  }

  function outcomeText(outcome) {
    if (outcome.violations && outcome.violations.length) return violationText(outcome.violations[0]);
    return outcome.error_code === 0 ? 'every tolerance met' : (outcome.error_string || outcome.code_name);
  }

  var VERDICT_GROUPS = [['joint', 'joints'], ['tcp', 'TCP']];

  /* One calm badge per run: green "pass", else the failed phase; the first violation is its hover. */
  function verdictBadge(sit) {
    if (!sit.verdict) return null;
    var failed = null, lines = [];
    VERDICT_GROUPS.forEach(function (group) {
      var outcome = sit.verdict[group[0]];
      if (!outcome) return;
      if (outcome.error_code !== 0 && !failed) failed = outcome;
      lines.push(group[1] + ': ' + outcomeText(outcome));
    });
    if (!lines.length) return null;
    var badge = document.createElement('span');
    badge.className = 'verdict-badge ' + (failed ? 'bad' : 'ok');
    badge.textContent = failed ? '✗ ' + failed.code_name.split('_')[0].toLowerCase() : '✓ pass';
    badge.title = lines.join('\n');
    return badge;
  }

  function buildVerdictDetails(parent, data) {
    var judged = data.situations.filter(function (sit) { return sit.verdict; });
    if (!judged.length) return;
    var failing = judged.filter(function (sit) {
      return VERDICT_GROUPS.some(function (group) {
        return sit.verdict[group[0]] && sit.verdict[group[0]].error_code !== 0;
      });
    }).length;
    var details = el('details', 'tc-verdicts', parent);
    el('summary', '', details, 'Verdicts (ROS 2 tolerances) — ' + (judged.length - failing) + ' of ' +
      judged.length + ' pass; first violation, margins and anything unchecked');
    var scroll = el('div', 'tc-table-scroll', details);
    var table = el('table', 'tc-metrics', scroll);
    var headRow = el('tr', '', el('thead', '', table));
    ['Run', 'Frame', 'Verdict', 'First violation per limit', 'Tightest margin', 'Unchecked']
      .forEach(function (name) { el('th', '', headRow, name); });
    var body = el('tbody', '', table);
    judged.forEach(function (sit) {
      VERDICT_GROUPS.forEach(function (group) {
        var outcome = sit.verdict[group[0]];
        if (!outcome) return;
        var tr = el('tr', '', body);
        el('th', '', tr, sit.title);
        el('td', '', tr, group[1]);
        el('td', 'verdict ' + (outcome.error_code === 0 ? 'ok' : 'bad'), tr, outcome.code_name);
        var cell = el('td', 'wrap', tr);
        if (outcome.violations.length) {
          outcome.violations.forEach(function (violation) {
            el('div', '', cell, violation.phase + ' · ' + violationText(violation));
          });
        } else {
          cell.textContent = '—';
        }
        var keys = Object.keys(outcome.margins || {});
        var tight = null;
        keys.forEach(function (key) {
          if (tight === null || outcome.margins[key] < outcome.margins[tight]) tight = key;
        });
        el('td', '', tr, tight === null ? '—' :
          tight + ' ' + (outcome.margins[tight] < 0 ? '−' : '+') + formatLimit(tight.split('/').slice(1).join('/'), outcome.margins[tight]));
        el('td', 'wrap', tr, (outcome.unchecked && outcome.unchecked.length) ? outcome.unchecked.join('; ') : '—');
      });
    });
  }

  function significant(value) {
    return String(Number(value.toPrecision(3)));
  }

  function buildAggregateCards(page, parent, data) {
    var groups = Object.keys(data.aggregates || {});
    if (!groups.length) return;
    var host = el('div', 'tc-aggregates', parent);
    groups.forEach(function (group) {
      var info = data.aggregates[group];
      var card = el('section', 'tc-aggregate', host);
      el('h3', '', card, 'Accuracy vs repeatability (ISO 9283) — ' + group);
      el('p', 'tc-table-desc', card,
        info.runs.length + ' runs (' + info.titles.join(', ') + ') against ' + referenceTitle(data) + '. ' +
        'AT: how far the average of the runs sits from the reference — a systematic bias a feed-forward could remove. ' +
        'RT: how widely the runs scatter around their own average (mean + 3σ of the distance to it) — only a better ' +
        'controller or a steadier plant reduces it.');
      var scroll = el('div', 'tc-table-scroll', card);
      var table = el('table', 'tc-metrics', scroll);
      var headRow = el('tr', '', el('thead', '', table));
      ['', 'AT — accuracy (max |reference − mean|)', 'RT — repeatability (max of mean + 3σ)']
        .forEach(function (name) { el('th', '', headRow, name); });
      var body = el('tbody', '', table);
      var rows = [];
      if (info.joint) {
        data.joint_names.forEach(function (jointName) {
          var key = 'positions/' + jointName;
          var accuracy = info.joint.accuracy[key], spread = info.joint.repeatability[key];
          if (accuracy && spread) rows.push({ label: jointName, kind: 'angle', at: accuracy.max_abs, rt: spread.max });
        });
      }
      if (info.tcp && info.tcp.accuracy.position && info.tcp.repeatability.position) {
        rows.push({ label: frameName(page) + ' position', kind: 'mm',
                    at: info.tcp.accuracy.position.max_abs, rt: info.tcp.repeatability.position.max });
      }
      function show(row, value) {
        if (value === null || value === undefined) return '—';
        if (row.kind === 'mm') return significant(value * 1000) + ' mm';
        return state.unit === 'deg' ? significant(value * RAD2DEG) + '°' : significant(value) + ' rad';
      }
      function paint() {
        body.innerHTML = '';
        rows.forEach(function (row) {
          var tr = el('tr', '', body);
          el('th', '', tr, row.label);
          el('td', '', tr, show(row, row.at));
          el('td', '', tr, show(row, row.rt));
        });
      }
      paint();
      page.unitRepaints.push(paint);
    });
  }

  /* ---------------- the run view: the stage beside the question tabs ----------------
     docs/NAVIGATION.md Part B (frozen 2026-11-19). Zach, daily note 2026-11-19 (traj compare view feedback):
     "100% we need to do the tabbed model", keep the 3D always showing, and standalone and Rerun "should be the
     exact same thing" — so the tabs, their titles, headings and sections come from the payload (tabs.py), never
     from this file. The Summary / Insights / scenario tabs (#tc-tabs) stay the page level above. */

  var STAGE_MIN_PX = 280;
  var STAGE_FOLDED_PX = 34;
  var PANELS_MIN_PX = 380;
  var PER_JOINT_SECTIONS = ['joint-q', 'joint-qd', 'joint-qdd', 'joint-tau', 'joint-current', 'joint-torque', 'joint-err'];

  function tabFromHash() {
    var match = /(?:^#|&)tab=([^&]+)/.exec(location.hash || '');
    if (!match) return null;
    try { return decodeURIComponent(match[1]); } catch (error) { return match[1]; }
  }

  function writeHash(id) {
    var run = /(?:^#|&)(run=[^&]+)/.exec(location.hash || '');  // a #run= deep link stays in the address
    try { history.replaceState(null, '', '#tab=' + encodeURIComponent(id) + (run ? '&' + run[1] : '')); } catch (error) {}
  }

  // ``report.html#run=<label>`` (a run's name or title, any case; with ``#tab=<id>&run=<label>`` too) opens the page
  // with only that run shown beside its reference, and is not remembered: the next plain visit shows the runs as left.
  // An unknown label changes nothing. WHY (TTA ask, 2026-11-24): a Model × Dataset cell links one solution's run of a
  // task, and the task's report holds every solution.
  function runFromHash() {
    var match = /(?:^#|&)run=([^&]+)/.exec(location.hash || '');
    if (!match) return null;
    try { return decodeURIComponent(match[1]); } catch (error) { return match[1]; }
  }
  function focusedRun(data) {
    var wanted = runFromHash();
    if (!wanted || !data || !data.situations) return null;
    wanted = wanted.toLowerCase();
    var hit = data.situations.filter(function (sit) {
      return sit.role !== 'target' && (String(sit.name).toLowerCase() === wanted || String(sit.title || '').toLowerCase() === wanted);
    })[0];
    return hit ? hit.name : null;
  }
  function sitWanted(page, sit) {
    var focus = focusedRun(page.data);
    if (focus) return sit.role === 'target' || sit.name === focus;
    return state.prefs.get('sit:' + sit.name, true);
  }

  function resizeChartsIn(page, host) {
    if (!host) return;
    page.charts.forEach(function (chart) { if (host.contains(chart.card)) chart.resize(); });
  }

  function activeTab(page) {
    return (page.tabs || []).filter(function (tab) { return tab.id === page.activeTab; })[0] || null;
  }

  function angleText(value) {
    return state.unit === 'deg' ? significant(value * RAD2DEG) + '°' : significant(value) + ' rad';
  }

  // The 3D view renders only while a reader can see it: its page active, the stage unfolded.
  function paintStage(page) {
    if (page.viewer3d) page.viewer3d.setActive(page.el.classList.contains('active') && !page.stageFolded);
  }

  function setStageWidth(page, width) {
    var stage = page.stage;
    var room = stage.workspace.clientWidth;
    // WHY 30 %: at 1440 px the six question titles still fit on one line beside it
    var fallback = Math.min(560, Math.max(320, Math.round(room * 0.3)));
    var widest = Math.max(STAGE_MIN_PX, room - PANELS_MIN_PX);
    page.stageWidth = Math.round(Math.min(widest, Math.max(STAGE_MIN_PX, Number(width) || fallback)));
    stage.el.style.width = (page.stageFolded ? STAGE_FOLDED_PX : page.stageWidth) + 'px';
  }

  function setStageFolded(page, folded, remember) {
    var stage = page.stage;
    page.stageFolded = folded;
    stage.el.classList.toggle('folded', folded);
    stage.fold.textContent = folded ? '›' : '‹';
    stage.fold.title = folded ? 'Unfold the stage: 3D view and videos' : 'Fold the stage away: more room for the plots';
    stage.fold.setAttribute('aria-label', stage.fold.title);
    stage.fold.setAttribute('aria-expanded', folded ? 'false' : 'true');
    setStageWidth(page, page.stageWidth);
    if (remember) store('stage-folded', folded);
    paintStage(page);
    var tab = activeTab(page);
    if (tab) resizeChartsIn(page, tab.panel);
  }

  /* The stage: the 3D view (its scrubber under it) over the camera overlay / videos, pinned left of the tabs so
     the time cursor, the 3D pose and every plot stay in view together. Its edge drags (width remembered), it
     folds away (remembered), and below 900 px it stacks above the tabs (style.css). */
  function buildStage(page, workspace, sections) {
    var stageEl = el('aside', 'tc-stage', workspace);
    stageEl.setAttribute('data-tc-stage', '');
    stageEl.setAttribute('aria-label', 'Stage: 3D view and videos');
    var head = el('div', 'tc-stage-head', stageEl);
    var names = { viewer3d: '3D view', camera: 'Camera', videos: 'Videos' };
    var title = el('span', 'tc-stage-title', head, sections.map(function (section) { return names[section.def.id]; }).join(' · '));
    title.title = 'always visible: ' + (page.oneTimeline ? 'the time lane' : 'the scrubber') +
      ' drives the 3D pose, the videos and the cursor on every plot';
    var fold = el('button', 'tc-stage-fold', head);
    fold.setAttribute('data-tc-stage-fold', '');
    var scroll = el('div', 'tc-stage-scroll', stageEl);
    var handle = el('div', 'tc-stage-resize', stageEl);
    handle.setAttribute('data-tc-stage-resize', '');
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-orientation', 'vertical');
    handle.title = 'drag to resize the stage · double-click for the default width';
    page.stage = { el: stageEl, fold: fold, handle: handle, workspace: workspace };
    page.stageWidth = recall('stage-width', null);
    setStageFolded(page, !!recall('stage-folded', false), false);
    fold.onclick = function () { setStageFolded(page, !page.stageFolded, true); };

    handle.addEventListener('pointerdown', function (event) {
      if (page.stageFolded || event.button !== 0) return;
      event.preventDefault();
      var startX = event.clientX;
      var startWidth = page.stageWidth;
      handle.classList.add('dragging');
      try { handle.setPointerCapture(event.pointerId); } catch (error) {}
      function move(moveEvent) { setStageWidth(page, startWidth + moveEvent.clientX - startX); }
      function up() {
        handle.classList.remove('dragging');
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
        store('stage-width', page.stageWidth);
      }
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    });
    handle.addEventListener('dblclick', function () {
      store('stage-width', null);
      setStageWidth(page, null);
    });

    sections.forEach(function (section) {
      section.on = true;  // WHY always (Zach 2026-11-19): the 3D stays visible; folding is the one way to hide it
      buildSectionShell(page, section, scroll);
    });
  }

  function buildSectionShell(page, section, host) {
    section.el = el('div', 'tc-section', host);
    section.el.setAttribute('data-tc-section', section.def.id);
    var heading = el('h3', '', section.el);
    var title = el('span', 'tc-section-title', heading);
    var hint = sectionHint(section.def.id, page.data, page);
    if (hint) el('span', 'hint', heading, ' — ' + hint);
    function paint() { title.textContent = sectionTitle(section.def); }
    paint();
    page.unitRepaints.push(paint);
    section.body = el('div', '', section.el);
  }

  function paintSection(page, section) {
    if (section.chip) {
      section.chip.className = 'chip ' + (section.on ? 'on' : 'off');
      section.chip.setAttribute('aria-pressed', section.on ? 'true' : 'false');
    }
    if (!section.el) return;  // its tab has not been opened yet
    section.el.style.display = section.on ? '' : 'none';
    var wasBuilt = section.built;
    if (section.on && !section.built) {
      section.built = true;
      section.def.build(page, section.body, section);
    }
    if (section.on && wasBuilt) {
      page.partViews.forEach(function (view) { if (view.section === section) syncPartView(page, view); });
      resizeChartsIn(page, section.el);
    }
    if (section.def.id === 'viewer3d') paintStage(page);
  }

  function setSection(page, section, on, remember) {
    section.on = on;
    // WHY a new key (2026-11-19): "section:<id>" choices were made to shorten one long page; in tabs they would
    // hide a tab's plots for no reason, so the tabbed view starts from each section's own default
    if (remember) state.prefs.set('tabsection:' + section.def.id, on);
    paintSection(page, section);
  }

  /* ---- parts: ranking, selector ---- */

  function paintPartButtons(page) {
    page.partButtons.forEach(function (button) {
      var on = button.getAttribute('data-tc-part') === String(page.part);
      button.setAttribute('aria-selected', on ? 'true' : 'false');
      button.className = 'chip tc-part' + (on ? ' on' : '');
    });
  }

  function showPart(page, index) {
    page.part = index;
    paintPartButtons(page);
    page.partViews.forEach(function (view) { syncPartView(page, view); });
    var tab = activeTab(page);
    if (tab) resizeChartsIn(page, tab.panel);
    if (page.transport && page.transport.t !== null) paintCursors(page, page.transport.t);
  }

  function buildPartBar(page, panel) {
    if (page.parts.length < 2) return;
    var bar = el('div', 'tc-partbar', panel);
    bar.setAttribute('role', 'tablist');
    bar.setAttribute('aria-label', 'Part of the robot');
    el('span', 'grouplabel', bar, 'Part');
    page.parts.forEach(function (part, index) {
      var button = el('button', 'chip tc-part', bar, partLabel(part));
      button.setAttribute('data-tc-part', String(index));
      button.setAttribute('role', 'tab');
      var fingers = part.groups.filter(function (group) { return group.name; });
      button.title = part.name + ': ' + (fingers.length
        ? fingers.map(function (group) { return group.name + ' (' + group.joints.length + ')'; }).join(', ')
        : partJoints(part).join(', '));
      button.onclick = function () { showPart(page, index); };
      page.partButtons.push(button);
    });
    paintPartButtons(page);
  }

  /* One number per joint, worst run first: ``error`` the RMS joint error (target − run), ``fbshare`` the share of
     the command the feedback supplied. */
  function rankingRows(page, metric, everyRun) {
    var data = page.data;
    var partOf = {};
    page.parts.forEach(function (part) {
      partJoints(part).forEach(function (joint) { partOf[joint] = part.name; });
    });
    // WHY the shown runs (bug (b), 2026-11-25): each bar names its worst run; a hidden run must not be it
    var runs = data.situations.filter(function (sit) {
      return sit.role !== 'target' && sit.has_data && (everyRun || page.visible[sit.name] !== false);
    });
    var rows = [];
    data.joint_names.forEach(function (joint, dof) {
      var worst = null;
      runs.forEach(function (sit) {
        var value = null;
        if (metric === 'error') {
          var stats = sit.error_metrics && sit.error_metrics['positions/' + joint];
          value = stats ? stats.rms : null;
        } else {
          var budget = sit.torque_budget && sit.torque_budget[joint];
          value = budget ? budget.fb_share : null;
        }
        if (value === null || value === undefined || !isFinite(value)) return;
        if (!worst || value > worst.value) worst = { value: value, run: sit };
      });
      if (worst) rows.push({ joint: joint, dof: dof, part: partOf[joint] || '', value: worst.value, run: worst.run });
    });
    rows.sort(function (a, b) { return b.value - a.value || a.dof - b.dof; });
    return rows;
  }

  function buildRanking(page, panel, metric) {
    var data = page.data;
    if (data.joint_names.length < 2) return;
    var all = rankingRows(page, metric, true);
    if (all.length < 2) return;
    var box = el('section', 'tc-rank', panel);
    box.setAttribute('data-tc-rank', '');
    var title = el('h4', 'tc-rank-title', box);
    var hint = el('span', 'hint', box, metric === 'error'
      ? 'the RMS over each run’s own samples; each bar is its worst shown run · click a bar to show that joint’s plot'
      : 'Σ|feedback| / (Σ|feedforward| + Σ|feedback|) over the run; each bar is its worst shown run · click a bar to show that joint’s plots');
    hint.className = 'tc-rank-hint';
    var bars = el('div', 'tc-rank-bars' + (all.length > 8 ? ' many' : ''), box);
    var named = page.parts.length > 1;
    var paints = [];
    function valueText(value) {
      return metric === 'error' ? angleText(value) : (value * 100).toFixed(1) + ' %';
    }
    // the bars over the shown runs: rebuilt when a run is shown or hidden (the order can change)
    function fill() {
      bars.innerHTML = '';
      paints = [];
      var rows = rankingRows(page, metric, false);
      box.style.display = rows.length ? '' : 'none';
      if (!rows.length) return;
      var maximum = rows[0].value > 0 ? rows[0].value : 1;
      rows.forEach(function (row) {
        var label = named ? row.part + ' · ' + row.joint : row.joint;
        var bar = el('button', 'tc-rank-bar', bars);
        bar.setAttribute('data-tc-rank-bar', '');
        bar.setAttribute('data-joint', row.joint);
        el('span', 'tc-rank-label', bar, label);
        var fillEl = el('span', 'tc-rank-fill', el('span', 'tc-rank-track', bar));
        fillEl.style.width = Math.max(1, row.value / maximum * 100) + '%';
        var value = el('span', 'tc-rank-value', bar);
        paints.push(function () {
          var text = valueText(row.value);
          value.textContent = text;
          var detail = label + ': ' + text + ' (' + row.run.title + ')';
          bar.title = detail + ' · click to show its plot';
          bar.setAttribute('aria-label', detail);
        });
        bar.onclick = function () { revealJoint(page, row.joint); };
      });
    }
    function paint() {
      title.textContent = metric === 'error'
        ? 'RMS joint error, ' + referenceTitle(data) + ' − run [' + unitLabel('angle') + '], worst joint first'
        : 'Feedback share of the commanded torque [%], highest first';
      paints.forEach(function (paintBar) { paintBar(); });
    }
    fill();
    paint();
    page.unitRepaints.push(paint);
    page.selectionRepaints.push(function () { fill(); paint(); });
  }

  // A ranking bar: show the joint's part, scroll to its first plot in this tab, and outline it for a moment.
  function revealJoint(page, joint) {
    showPart(page, partIndexOf(page, joint));
    var tab = activeTab(page);
    if (!tab) return;
    var target = null;
    tab.panel.querySelectorAll('[data-tc-joint]').forEach(function (node) {
      if (!target && node.getAttribute('data-tc-joint') === joint && node.offsetParent !== null) target = node;
    });
    if (!target) return;
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    target.classList.remove('tc-flash');
    void target.offsetWidth;  // restart the outline when the same bar is clicked twice
    target.classList.add('tc-flash');
    setTimeout(function () { target.classList.remove('tc-flash'); }, 1600);
  }

  /* ---- the track tab: one calm answer, then the statistics ---- */

  function meanJointRms(data, sit) {
    var values = [];
    data.joint_names.forEach(function (joint) {
      var stats = sit.error_metrics && sit.error_metrics['positions/' + joint];
      if (stats && isFinite(stats.rms)) values.push(stats.rms);
    });
    return values.length ? values.reduce(function (sum, value) { return sum + value; }, 0) / values.length : null;
  }

  // The largest |target − run| over every joint and display sample: where and when the run was worst.
  function worstMoment(data, sit) {
    var errors = sit.plot && sit.plot.err_q;
    if (!errors) return null;
    var worst = null;
    errors.forEach(function (column, dof) {
      (column || []).forEach(function (value, index) {
        if (value === null || value === undefined) return;
        var size = Math.abs(value);
        if (!worst || size > worst.size) worst = { size: size, joint: data.joint_names[dof], t: data.plot_t[index] };
      });
    });
    return worst;
  }

  function maxAbsOverJoints(errors) {
    var length = errors.length && errors[0] ? errors[0].length : 0;
    var out = new Array(length);
    for (var index = 0; index < length; index++) {
      var worst = null;
      for (var dof = 0; dof < errors.length; dof++) {
        var value = errors[dof] ? errors[dof][index] : null;
        if (value === null || value === undefined) continue;
        if (worst === null || Math.abs(value) > worst) worst = Math.abs(value);
      }
      out[index] = worst;
    }
    return out;
  }

  function buildAnswer(page, panel) {
    var data = page.data;
    var every = data.situations.filter(function (sit) {
      return sit.role !== 'target' && sit.has_data && sit.error_metrics;
    }).map(function (sit) {
      return { sit: sit, mean: meanJointRms(data, sit) };
    }).filter(function (entry) { return entry.mean !== null; });
    if (!every.length) return;
    var named = page.parts.length > 1;
    var box = el('section', 'tc-answer', panel);
    var lead = el('p', 'tc-answer-lead', box);
    var detail = el('p', 'tc-answer-detail', box);
    var momentText = el('span', '', detail);
    var moment = null;
    var go = null;
    if (page.transport) {
      go = el('button', 'chip', detail);
      go.title = 'moves the time there: the 3D pose, the videos and the playhead on every plot';
      go.onclick = function () {
        if (!moment) return;
        page.transport.pause();
        page.transport.setScrub(moment.t);
      };
    }
    // WHY over the shown runs only (the run-view round's bug (b), 2026-11-24): the answer ranked every run in the
    // payload, so with a situation chip off (or #run= focusing one run) it named a run the page did not show
    function paint() {
      var runs = every.filter(function (entry) { return page.visible[entry.sit.name] !== false; });
      runs.sort(function (a, b) { return b.mean - a.mean; });
      var worst = runs[0], best = runs[runs.length - 1];
      moment = worst ? worstMoment(data, worst.sit) : null;
      detail.style.display = moment ? '' : 'none';
      if (go && moment) go.textContent = 'Go to t = ' + moment.t.toFixed(2) + ' s';
      if (!worst) {
        lead.textContent = 'No run is shown: turn one on with the situation chips.';
        return;
      }
      var minus = referenceTitle(data) + ' − run';
      lead.textContent = runs.length > 1
        ? 'Worst run: ' + worst.sit.title + ', mean joint RMS error ' + angleText(worst.mean) + ' (' + minus +
          '); best: ' + best.sit.title + ', ' + angleText(best.mean) + '.'
        : worst.sit.title + ': mean joint RMS error ' + angleText(worst.mean) + ' (' + minus + ') over ' +
          jointsWord(data.joint_names.length) + '.';
      if (!moment) return;
      var where = named ? page.parts[partIndexOf(page, moment.joint)].name + ' · ' + moment.joint : moment.joint;
      momentText.textContent = 'Its worst moment: ' + angleText(moment.size) + ' on ' + where + ' at t = ' +
        moment.t.toFixed(2) + ' s. ';
    }
    paint();
    page.unitRepaints.push(paint);
    page.selectionRepaints.push(paint);
  }

  // "When was it worst?" over time: the largest joint error at each instant, and the tool's position error.
  function buildWorstOverTime(page, panel) {
    var minus = referenceTitle(page.data) + ' − run';
    var grid = el('div', 'tc-grid tc-track-grid', panel);
    var joint = sitsWith(page, 'err_q');
    if (joint.length) {
      makeChart(page, el('div', 'tc-plotcard', grid), {
        title: 'Largest joint error at each instant, max over joints of |' + minus + '|', kind: 'angle',
        series: joint.map(function (sit) { return { sit: sit, values: maxAbsOverJoints(sit.plot.err_q) }; }),
      });
    }
    var tool = sitsWith(page, 'xyz_mag');
    if (tool.length) {
      makeChart(page, el('div', 'tc-plotcard', grid), {
        title: frameName(page) + ' position error |Δp|, |' + minus + '|', kind: 'mm',
        series: tool.map(function (sit) { return { sit: sit, values: sit.plot.xyz_mag }; }),
      });
    }
    if (grid.children.length) observeGrid(page, grid); else grid.remove();
  }

  function buildDomainSummary(parent, data) {
    var summary = data.meta && data.meta.summary;
    if (!summary) return;
    var summaryCard = el('section', 'tc-summary', parent);
    el('h3', '', summaryCard, summary.title || 'Performance summary');
    if (summary.facts && summary.facts.length) {
      var facts = el('div', 'tc-facts', summaryCard);
      summary.facts.forEach(function (fact) {
        var item = el('div', 'tc-fact', facts);
        el('span', 'label', item, fact.label);
        el('strong', '', item, String(fact.value));
      });
    }
    if (summary.columns && summary.rows) {
      var tableWrap = el('div', 'tc-summary-table-wrap', summaryCard);
      var table = el('table', 'tc-summary-table', tableWrap);
      var head = el('thead', '', table);
      var headRow = el('tr', '', head);
      summary.columns.forEach(function (column) {
        el('th', '', headRow, column.label + (column.unit ? ' (' + column.unit + ')' : ''));
      });
      var body = el('tbody', '', table);
      summary.rows.forEach(function (row) {
        var tr = el('tr', '', body);
        summary.columns.forEach(function (column) {
          var value = row[column.key];
          el('td', '', tr, value === undefined || value === null ? '—' : String(value));
        });
      });
    }
  }

  // track: the answer, the statistics, when it was worst, verdicts, ISO 9283, the caller's own summary.
  function buildTrackPanel(page, panel) {
    var data = page.data;
    buildAnswer(page, panel);
    // WHY first under the lane (R2, measured 2026-11-24 on 17 runs): stacked full width under a long statistics table,
    // both "when was it worst" charts fell below the first screen
    if (page.oneTimeline) buildWorstOverTime(page, panel);
    if (data.stats_mask) {
      // Comparison.stats_mask: every error statistic is over these samples; the plots still draw every sample
      el('p', 'tc-desc tc-stats-mask', panel, 'Error statistics are over ' + data.stats_mask.n + ' of ' + data.stats_mask.of +
        ' samples' + (data.stats_mask.label ? ' (' + data.stats_mask.label + ')' : '') + '; the plots draw every sample.')
        .setAttribute('data-tc-stats-mask', '');
    }
    if (data.statistics) buildTable(panel, data.statistics, true);
    if (!page.oneTimeline) buildWorstOverTime(page, panel);
    buildVerdictDetails(panel, data);
    buildAggregateCards(page, panel, data);
    buildDomainSummary(panel, data);
  }

  /* ---- tabs ---- */

  // A tab's panel is drawn the first time it opens, so its charts are sized to a visible panel.
  function buildPanel(page, tab) {
    tab.built = true;
    var panel = tab.panel;
    if (tab.id === 'track') buildTrackPanel(page, panel);
    var ids = tab.sections.map(function (section) { return section.def.id; });
    var notes = [];
    if (page.derived.fd && ids.some(function (id) { return id === 'joint-qd' || id === 'joint-qdd'; })) notes.push(page.derived.fd);
    if (page.derived.torque && ids.indexOf('joint-torque') !== -1) notes.push(page.derived.torque);
    if (notes.length) el('div', 'tc-derived', panel, notes.join(' · '));
    var toggles = tab.sections.filter(function (section) { return section.toggle; });
    if (toggles.length) {
      var chips = el('div', 'tc-panel-chips', panel);
      el('span', 'grouplabel', chips, 'Plots in this tab');
      toggles.forEach(function (section) {
        section.chip = el('button', 'chip', chips);
        var paintChip = function () { section.chip.textContent = sectionTitle(section.def); };
        paintChip();
        page.unitRepaints.push(paintChip);
        section.chip.onclick = function () { setSection(page, section, !section.on, true); };
      });
    }
    if (tab.id === 'joints') buildRanking(page, panel, 'error');
    if (tab.id === 'torque') buildRanking(page, panel, 'fbshare');
    if (ids.some(function (id) { return PER_JOINT_SECTIONS.indexOf(id) !== -1; })) buildPartBar(page, panel);
    tab.sections.forEach(function (section) { buildSectionShell(page, section, panel); });
    tab.sections.forEach(function (section) { paintSection(page, section); });
  }

  function activateTab(page, id, fromUser) {
    var tab = page.tabs.filter(function (candidate) { return candidate.id === id; })[0] || page.tabs[0];
    if (!tab) return;
    page.activeTab = tab.id;
    page.tabs.forEach(function (other) {
      var on = other === tab;
      other.button.setAttribute('aria-selected', on ? 'true' : 'false');
      other.button.tabIndex = on ? 0 : -1;
      other.panel.hidden = !on;
    });
    // a tab switch ends any hover preview: no pointer is on this tab's plots yet (the bug (a) fix's other half: the 3D
    // stays on the committed time when a tab's charts are first built)
    page.hoverChart = null;
    if (page.transport) page.transport.setHover(null);
    if (!tab.built) buildPanel(page, tab);
    page.partViews.forEach(function (view) { syncPartView(page, view); });
    // WHY (measured 2026-11-19): a chart drawn or last sized while its panel was hidden keeps that width; size every
    // chart of the shown panel to it, and put the shared time cursor on the newly drawn ones
    resizeChartsIn(page, tab.panel);
    if (page.transport && page.transport.t !== null) paintCursors(page, page.transport.t);
    if (page.transport) {
      paintPlayheads(page);
      // and again once uPlot has committed the new charts: their cursor joins the sync at the run's last sample
      // after this returns, which left the value dots of a freshly opened tab on the end of the run
      restoreCursors(page);
    }
    if (page.timeline) page.timeline.queue();
    if (fromUser) {
      state.prefs.set('tab', tab.id);
      writeHash(tab.id);
    }
  }

  function buildTabStrip(page, strip, column, tabs, byId) {
    strip.setAttribute('data-tc-tabs', '');
    strip.setAttribute('role', 'tablist');
    strip.setAttribute('aria-label', 'Questions about this run');
    page.tabs = tabs.map(function (tab) {
      var record = { id: tab.id, title: tab.title, heading: tab.heading, built: false, sections: [] };
      record.button = el('button', 'tc-qtab', strip, tab.title);
      record.button.setAttribute('data-tc-tab', tab.id);
      record.button.setAttribute('role', 'tab');
      record.button.title = tab.heading;
      record.button.onclick = function () { activateTab(page, tab.id, true); };
      record.panel = el('section', 'tc-panel', column);
      record.panel.setAttribute('data-tc-panel', tab.id);
      record.panel.setAttribute('role', 'tabpanel');
      record.panel.setAttribute('aria-label', tab.title);
      record.panel.hidden = true;
      el('h3', 'tc-tab-heading', record.panel, tab.heading).setAttribute('data-tc-tab-heading', '');
      (tab.sections || []).forEach(function (id) {
        var section = byId[id];
        if (!section || section.tab || STAGE_SECTIONS.indexOf(id) !== -1) return;
        section.tab = record;
        record.sections.push(section);
      });
      // A lone section is the tab's content: always on, no chip. Several start as the caller asked
      // (default_sections) or as last toggled, and never all off.
      var lone = record.sections.length < 2;
      record.sections.forEach(function (section) {
        section.toggle = !lone;
        section.on = lone ? true : !!state.prefs.get('tabsection:' + section.def.id, section.defaultOn);
      });
      if (!lone && !record.sections.some(function (section) { return section.on; })) record.sections[0].on = true;
      return record;
    });
    strip.addEventListener('keydown', function (event) {
      var index = page.tabs.map(function (tab) { return tab.id; }).indexOf(page.activeTab);
      var next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: page.tabs.length - 1 }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      var tab = page.tabs[(next + page.tabs.length) % page.tabs.length];
      activateTab(page, tab.id, true);
      tab.button.focus();
    });
  }

  function buildPage(page) {
    var data = page.data;
    var root = page.el;

    if (data.plot_t) {
      page.transport = makeTransport(page);
      page.transport.onChange(function (kind) { if (kind !== 'hover') paintPlayheads(page); });
    }
    // One timeline for the page (docs/NAVIGATION.md Part B; Zach's pick round 2026-11-24, R2): the time lane under the
    // tabs is the page's one time control. A page without timeline.js (an older shared assets folder) keeps the stage's
    // scrubber.
    page.oneTimeline = !!(page.transport && window.TrajCompareTimeline);
    if (page.oneTimeline) root.classList.add('tc-timeline');
    page.unitRepaints = [];
    page.selectionRepaints = [];  // what names runs repaints when a run is shown or hidden (setSituationVisible)
    page.parts = partsOf(data);
    page.part = 0;
    page.partViews = [];
    page.partButtons = [];

    el('h2', 'tc-page-title', root, data.title);
    if (data.description) el('p', 'tc-desc', root, data.description);
    if (data.rerun) buildRerunBar(root, data.rerun, data.exports);
    else if (data.exports) buildExportsBar(root, data.exports);

    page.sections = sectionDefs(data).map(function (def) {
      return { def: def, on: false, defaultOn: def.on, toggle: false, tab: null, built: false, chip: null, el: null, body: null };
    });
    var byId = {};
    page.sections.forEach(function (section) { byId[section.def.id] = section; });
    var tabs = Array.isArray(data.tabs) && data.tabs.length ? data.tabs : [{
      // a payload from before the question tabs: one panel with every plot section
      id: 'plots', title: data.title, heading: '',
      sections: page.sections.map(function (section) { return section.def.id; }),
    }];

    var workspace = el('div', 'tc-workspace', root);
    var stageSections = STAGE_SECTIONS.map(function (id) { return byId[id]; }).filter(Boolean);
    if (stageSections.length) buildStage(page, workspace, stageSections);
    var column = el('div', 'tc-qcol', workspace);
    var head = el('div', 'tc-qhead', column);
    // the sheet holds the tabs' panels and, under the lane, the one playhead line through their charts
    var sheet = el('div', 'tc-sheet', column);
    buildTabStrip(page, el('nav', 'tc-qtabs', head), sheet, tabs, byId);
    // Under the lane these chips are hidden (style.css) and stay the state machinery: the lane's tracks call them, and
    // so do the prefs of another scenario tab and ``#run=``. The Angles chips move into the lane's bar.
    var controls = el('div', 'tc-controls', head);

    // Situation chips are grouped semantically instead of becoming one long,
    // permutation-heavy list. Visibility is keyed by situation name across
    // the report, so hiding "Real" on one scenario hides it on all of them.
    var situationGroups = [];
    var situationGroupsByName = {};
    data.situations.forEach(function (sit) {
      var name = sit.group || 'situations';
      if (!situationGroupsByName[name]) {
        situationGroupsByName[name] = {
          name: name,
          title: sit.group_title || 'Situations',
          situations: [],
        };
        situationGroups.push(situationGroupsByName[name]);
      }
      situationGroupsByName[name].situations.push(sit);
    });
    var situationsHost = el('div', 'tc-situation-groups', controls);
    situationGroups.forEach(function (definition) {
      var situationGroup = el('div', 'group situation-group', situationsHost);
      el('span', 'grouplabel', situationGroup, definition.title);
      definition.situations.forEach(function (sit) {
        if (!sit.has_data) {
          var dead = el('span', 'chip nodata', situationGroup);
          var swatchOff = el('span', 'swatch', dead);
          swatchOff.style.background = sit.color;
          dead.appendChild(document.createTextNode(sit.title + ' '));
          el('span', 'note', dead, '(no data' + (sit.note ? ' — ' + sit.note : '') + ')');
          return;
        }
        var chip = el('button', 'chip on', situationGroup);
        var swatch = el('span', 'swatch' + (sit.role === 'target' ? ' dashed' : ''), chip);
        swatch.style.background = sit.color;
        swatch.style.color = sit.color;
        chip.appendChild(document.createTextNode(sit.title));
        var badge = verdictBadge(sit);
        if (badge) chip.appendChild(badge);
        if (sit.time_offset_s) {
          // the run's clock is shifted back by this much in every error below (Situation.time_offset_s)
          var shift = el('span', 'verdict-badge shift', chip, 'clock −' + Number((sit.time_offset_s * 1000).toPrecision(3)) + ' ms');
          shift.title = 'errors are taken with this run shifted ' + sit.time_offset_s * 1000 + ' ms earlier (time_offset_s)';
        }

        function apply(show, remember) {
          page.visible[sit.name] = show;
          chip.className = 'chip ' + (show ? 'on' : 'off');
          if (remember) state.prefs.set('sit:' + sit.name, show);
          setSituationVisible(page, sit.name, show);
        }
        page.sitChips.push({ sit: sit, apply: apply });
        chip.onclick = function () { apply(page.visible[sit.name] === false, true); };
        apply(sitWanted(page, sit), false);
      });
    });

    // Δ-to-target chips: one per measured run, off by default. Independent of
    // the run's own chip, so the useful move — hide target *and* measured,
    // leave Δ — is two clicks and the y axis rescales to the error.
    var hasTarget = data.situations.some(function (sit) {
      return sit.role === 'target' && sit.plot;
    });
    var errorCandidates = !hasTarget ? [] : data.situations.filter(function (sit) {
      return sit.has_data && sit.role !== 'target' && sit.plot;
    });
    if (errorCandidates.length) {
      var errorGroup = el('div', 'group', controls);
      el('span', 'grouplabel', errorGroup, isRunReference(data) ? 'Error vs ' + referenceTitle(data) : 'Error vs target');
      errorGroup.title = 'overlay each measured run minus ' + referenceWord(data) + ' on every plot';
      errorCandidates.forEach(function (sit) {
        var chip = el('button', 'chip', errorGroup);
        var swatch = el('span', 'swatch dotted', chip);
        swatch.style.background = sit.color;
        swatch.style.color = sit.color;
        chip.appendChild(document.createTextNode('Δ ' + sit.title));

        function apply(show, remember) {
          page.errorOn[sit.name] = show;
          chip.className = 'chip ' + (show ? 'on' : 'off');
          if (remember) state.prefs.set('err:' + sit.name, show);
          page.charts.forEach(function (chart) { chart.setError(sit.name, show); });
          if (page.timeline) page.timeline.paintSelection();
        }
        page.errChips.push({ sit: sit, apply: apply });
        chip.onclick = function () { apply(!page.errorOn[sit.name], true); };
        apply(state.prefs.get('err:' + sit.name, false), false);
      });
    }

    // unit toggle + reset zoom
    var unitGroup = el('div', 'group', controls);
    el('span', 'grouplabel', unitGroup, 'Angles');
    var degChip = el('button', 'chip', unitGroup, 'deg');
    var radChip = el('button', 'chip', unitGroup, 'rad');
    function paintUnits() {
      degChip.className = 'chip ' + (state.unit === 'deg' ? 'on' : 'off');
      radChip.className = 'chip ' + (state.unit === 'rad' ? 'on' : 'off');
      page.unitRepaints.forEach(function (repaint) { repaint(); });
    }
    function setUnit(unit) {
      if (state.unit === unit) return;
      state.unit = unit;
      store('unit', unit);
      state.pages.forEach(function (other) {
        other.charts.forEach(function (chart) { chart.refreshUnits(); });
        if (other.paintUnits) other.paintUnits();
      });
    }
    degChip.onclick = function () { setUnit('deg'); };
    radChip.onclick = function () { setUnit('rad'); };
    page.paintUnits = paintUnits;
    paintUnits();

    var zoomGroup = el('div', 'group', controls);
    el('span', 'grouplabel', zoomGroup, 'Zoom');
    var resetButton = el('button', 'chip', zoomGroup, 'Reset zoom');
    resetButton.title = 'restore the full time range on every plot (double-clicking a plot works too)';
    resetButton.onclick = function () { resetZoom(page); };
    if (page.transport) {
      // WHY said on the page: a plain drag zoomed before 2026-11-25; it moves the time now
      var zoomHint = el('span', 'tc-zoom-hint', zoomGroup, 'Shift-drag or Ctrl+wheel a plot');
      zoomHint.title = 'Shift-drag a plot to zoom its time range on every plot, or Ctrl/⌘+wheel (a trackpad pinch) to ' +
        'zoom around the pointer; a plain drag moves the time';
    }

    // derived-channel footnotes, shown in the tab whose plots they qualify: qd / qdd by finite differences; a torque
    // from the other two of commanded / feedforward / feedback (TORQUE_DERIVED), which is arithmetic
    function derivedNote(test) {
      return data.situations
        .map(function (sit) {
          var keys = (sit.derived || []).filter(test);
          return keys.length ? sit.title + ': ' + keys.join(', ') : null;
        })
        .filter(function (bit) { return bit; });
    }
    // the time lane, docked under the tabs column: transport, ruler, one track per run, zoom bar (timeline.js)
    if (page.oneTimeline) {
      page.timeline = TrajCompareTimeline.create(page, { column: column, sheet: sheet, units: unitGroup }, {
        el: el, store: store, recall: recall, ink: ink, state: state, nearestIndex: nearestIndex, worstMoment: worstMoment,
        maxAbsOverJoints: maxAbsOverJoints, angleText: angleText, referenceTitle: referenceTitle, partIndexOf: partIndexOf,
        violationText: violationText, verdictBadge: verdictBadge, activeTab: activeTab, resizeChartsIn: resizeChartsIn,
        restoreCursors: restoreCursors, resetZoom: resetZoom, axisPx: LANE_AXIS_PX, padRightPx: LANE_PAD[1],
      });
    }

    var derivedBits = derivedNote(function (key) { return !TORQUE_DERIVED[key]; });
    var torqueBits = derivedNote(function (key) { return !!TORQUE_DERIVED[key]; });
    page.derived = {
      fd: derivedBits.length ? 'Finite-difference derived — ' + derivedBits.join(' · ') : '',
      torque: torqueBits.length ? 'Derived from the other two (tau_cmd = tau_ff + tau_fb) — ' + torqueBits.join(' · ') : '',
    };

    // the stage is drawn after the chips, so the 3D view and the videos start with the runs they left on
    stageSections.forEach(function (section) { paintSection(page, section); });
    activateTab(page, tabFromHash() || state.prefs.get('tab', null), false);

    page.paintSections = function () {
      page.sections.forEach(function (section) { paintSection(page, section); });
    };

    /* Pull in choices made on another scenario tab. Pages are built lazily,
       so this is what keeps an already-built page in step. */
    page.applyShared = function () {
      page.sections.forEach(function (section) {
        if (!section.toggle) return;
        var want = !!state.prefs.get('tabsection:' + section.def.id, section.defaultOn);
        if (want !== section.on) setSection(page, section, want, false);
      });
      page.sitChips.forEach(function (entry) {
        var want = sitWanted(page, entry.sit);
        if (want !== (page.visible[entry.sit.name] !== false)) entry.apply(want, false);
      });
      page.errChips.forEach(function (entry) {
        var want = state.prefs.get('err:' + entry.sit.name, false);
        if (want !== !!page.errorOn[entry.sit.name]) entry.apply(want, false);
      });
      page.torqueChips.forEach(function (entry) {
        var want = state.prefs.get('torque:' + entry.id, true);
        if (want !== (page.torqueOn[entry.id] !== false)) entry.apply(want, false);
      });
      page.overlayCards.forEach(function (card) { card.applyShared(); });
      if (page.viewer3d && page.viewer3d.applyShared) page.viewer3d.applyShared();
      if (page.stage) {
        page.stageWidth = recall('stage-width', page.stageWidth);
        setStageFolded(page, !!recall('stage-folded', false), false);
      }
      if (page.timeline) page.timeline.applyShared();
      var wanted = state.prefs.get('tab', null);
      if (wanted && wanted !== page.activeTab) activateTab(page, wanted, false);
    };
  }

  function setSituationVisible(page, name, show) {
    page.charts.forEach(function (chart) { chart.setSituation(name, show); });
    (page.selectionRepaints || []).forEach(function (repaint) { repaint(); });
    if (page.viewer3d) page.viewer3d.setSituationVisible(name, show);
    page.videos.forEach(function (entry) {
      if (entry.sit.name === name) {
        entry.card.style.display = show ? '' : 'none';
        if (!show) entry.el.pause();
        else if (page.transport && page.transport.playing) entry.el.play().catch(function () {});
      }
    });
  }

  /* ---------------- boot ---------------- */

  function paintPrimaryTabs(activeGroup, activeReport) {
    state.groups.forEach(function (group) {
      group.tab.classList.toggle('active', group.name === activeGroup);
    });
    state.reportPages.forEach(function (page) {
      page.tab.classList.toggle('active', page.data.name === activeReport);
    });
  }

  function paintSubtabs(group) {
    var nav = document.getElementById('tc-subtabs');
    nav.innerHTML = '';
    if (!group || group.pages.length < 2) {
      nav.style.display = 'none';
      return;
    }
    nav.style.display = '';
    group.pages.forEach(function (page) {
      nav.appendChild(page.tab);
      page.tab.classList.toggle('active', page.index === group.activeIndex);
    });
  }

  function activatePage(index) {
    state.activePage = index;
    var selected = state.pages[index];
    var group = selected.group;
    group.activeIndex = index;
    paintPrimaryTabs(group.name, null);
    paintSubtabs(group);
    state.reportPages.forEach(function (page) { page.el.classList.remove('active'); });
    state.pages.forEach(function (page, pageIndex) {
      var active = pageIndex === index;
      page.el.classList.toggle('active', active);
      page.tab.classList.toggle('active', active);
      if (active && !page.builtPage) {
        page.builtPage = true;
        buildPage(page);
      } else if (active && page.applyShared) {
        page.applyShared();
      }
      if (active && page.tabs) {
        var shown = activeTab(page);
        if (shown) resizeChartsIn(page, shown.panel);
      }
      if (page.viewer3d) page.viewer3d.setActive(active && !page.stageFolded);
      if (!active && page.transport) page.transport.pause();
    });
  }

  function activateReportPage(index) {
    var selected = state.reportPages[index];
    paintPrimaryTabs(null, selected.data.name);
    paintSubtabs(null);
    state.pages.forEach(function (page) {
      page.el.classList.remove('active');
      page.tab.classList.remove('active');
      if (page.transport) page.transport.pause();
      if (page.viewer3d) page.viewer3d.setActive(false);
    });
    state.reportPages.forEach(function (page, pageIndex) {
      var active = pageIndex === index;
      page.el.classList.toggle('active', active);
      if (active && !page.builtPage) {
        page.builtPage = true;
        buildReportPage(page);
      }
    });
  }

  function boot() {
    var payload = JSON.parse(document.getElementById('traj-compare-data').textContent);
    // Robot link meshes are stored once per report; links carry an index.
    var meshLibrary = payload.mesh_library || [];
    payload.comparisons.forEach(function (data) {
      // the target's grey in the page's theme; every run's colour is a data colour and stays
      (data.situations || []).forEach(function (sit) { if (sit.role === 'target' && sit.color) sit.color = ink(sit.color); });
      (data.robots || []).forEach(function (model) {
        model.links.forEach(function (link) {
          if (typeof link.tris === 'number') link.tris = meshLibrary[link.tris];
        });
      });
    });
    state.unit = recall('unit', 'deg');
    state.prefs = makePrefs(payload.title || 'report');

    var nav = document.getElementById('tc-tabs');
    var main = document.getElementById('tc-main');
    var groupsByName = {};

    state.pages = payload.comparisons.map(function (data, index) {
      var page = {
        index: index,
        data: data,
        el: el('section', 'tc-page', main),
        tab: null,
        charts: [],
        sections: [],
        sitChips: [],
        errChips: [],
        errorOn: {},   // situation name -> its Δ-to-target curve is drawn
        torqueChips: [],
        torqueOn: {},  // torque component (target, commanded, ...) -> drawn on every breakdown card
        videos: [],
        overlayCards: [],
        visible: {},
        syncing: false,
        cursorDriven: false,
        seekQueued: false,
        pendingSeek: null,
        xZoom: null,
        hoverChart: null,   // the chart a mouse or pen is over (only then does a hover preview the 3D)
        scrubbing: null,    // the chart a press-and-drag is moving the time on
        cursorRestoreQueued: false,
        builtPage: false,
        viewer3d: null,
        transport: null,
        group: null,
      };
      page.el.id = 'page-' + data.name;
      page.tab = el('button', '', null, data.tab_title || data.title);
      page.tab.onclick = function () { activatePage(index); };
      var groupName = data.group || data.name;
      if (!groupsByName[groupName]) {
        groupsByName[groupName] = {
          name: groupName,
          title: data.group_title || data.title,
          pages: [],
          activeIndex: index,
          tab: null,
        };
      }
      page.group = groupsByName[groupName];
      page.group.pages.push(page);
      return page;
    });

    state.groups = [];
    payload.comparisons.forEach(function (data) {
      var group = groupsByName[data.group || data.name];
      if (state.groups.indexOf(group) !== -1) return;
      group.tab = el('button', '', nav, group.title);
      group.tab.onclick = function () { activatePage(group.activeIndex); };
      state.groups.push(group);
    });

    state.reportPages = (payload.report_pages || []).map(function (data, index) {
      var page = {
        data: data,
        el: el('section', 'tc-page tc-report-page', main),
        tab: el('button', '', nav, data.title),
        builtPage: false,
      };
      page.el.id = 'report-page-' + data.name;
      page.tab.onclick = function () { activateReportPage(index); };
      return page;
    });
    if (state.groups.length + state.reportPages.length < 2) nav.style.display = 'none';

    // ``report.html#tab=<id>`` opens that question tab (NAVIGATION.md Part B), also when the hash changes later
    window.addEventListener('hashchange', function () {
      var id = tabFromHash();
      var page = state.pages[state.activePage];
      if (id && page && page.builtPage && page.tabs && page.el.classList.contains('active')) activateTab(page, id, false);
      if (page && page.builtPage && page.sitChips) {
        page.sitChips.forEach(function (entry) {
          var want = sitWanted(page, entry.sit);
          if (want !== (page.visible[entry.sit.name] !== false)) entry.apply(want, false);
        });
      }
    });

    activatePage(0);
  }

  /* The dataset view (dataset.py) draws a Summary ReportPage with this same renderer. */
  function renderReportPage(parent, data) {
    buildReportPage({ el: parent, data: data });
  }

  return {
    boot: boot,
    ink: ink,
    renderReportPage: renderReportPage,
    state: state,
    buildTransportBar: buildTransportBar,
    prefs: function () { return state.prefs; },
  };
})();
