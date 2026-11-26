/* The time lane: ONE time control for the run view, docked under the question tabs (docs/NAVIGATION.md Part B).
 *
 * WHY (Zach's pick round, 2026-11-24: docs/proposals/run-view-2026-11-24/, R2 "One timeline for the page", the AI pick
 * at 80 of 100, applied 2026-11-25): a video editor's page. One time control and one playhead line through every chart,
 * because every chart and the lane's ruler sit on the same x pixels (plots.js under `page.timeline`: a fixed y-axis
 * width and padding, and each chart's title in a left column exactly as wide as the lane's names column).
 *
 *   - the bar: to start, step back, play / pause, step forward, to end; the readout `t / tMax s`; `‹ ◆ Worst moment ›`
 *     (the worst moment of the shown runs, or the previous / next marked one); the zoomed span; Full range; the
 *     Angles deg / rad chips; the fold;
 *   - the ruler `[data-tc-ruler]`, the page's slider (role="slider", aria-valuenow = the committed time; ← → step,
 *     Shift ×10, Home / End, Space plays). Press and drag on it, or on any run's track: the time follows, live, snapped
 *     to the plot grid;
 *   - one track per run `[data-tc-lane-track]`, grouped as the situation chips are (a group row folds its tracks like a
 *     DAW folder track, and its eye toggles every run in it): eye, colour, whole name (ellipsized, whole in `title`), Δ,
 *     the run's error at the playhead, a band of its largest joint error over time on one scale for every run, and its
 *     moments `[data-tc-moment]`: ◆ worst, ▲ error rises (its first sample above half its own peak), × a broken limit
 *     (Situation.verdict). Click a moment to go there;
 *   - the zoom bar `[data-tc-zoom-bar]` over the whole motion, drawn as an overview of the shown runs' error: drag a
 *     range to zoom every chart, drag the window to pan, its edges to resize, the wheel to zoom; Full range or a
 *     double-click resets;
 *   - the line `[data-tc-line]` through every chart at the committed time, and a dashed one at an instant hovered on
 *     the lane (a hovered chart shows uPlot's own dashed cursor on every chart).
 *
 * The lane's height drags (its top edge) and it folds to its bar and ruler; the names column drags and the charts'
 * title column follows. All three are remembered (plots.js store/recall: localStorage inside try/catch). The
 * situation chips stay plots.js's state machinery (prefs, #run=, other scenario tabs); the lane's eyes call them.
 *
 * plots.js calls TrajCompareTimeline.create(page, hosts, kit) from buildPage; `kit` hands over the helpers it shares.
 */
var TrajCompareTimeline = (function () {
  'use strict';

  var TRACK_PX = 22;          // a run's track
  var GROUP_PX = 19;          // a group's row above its runs
  var VISIBLE_TRACKS = 6;     // WHY: about six tracks show by default, then the track list scrolls (R2's brief)
  var NAMES_PX = { fallback: 216, min: 110, max: 440, share: 0.4 };  // the names column; at most 40 % of the lane
  var LANE_MIN_PX = 120;
  var TICK_MIN_PX = 64;       // the ruler's labelled ticks are at least this far apart

  function icon(body, size) {
    var px = size || 14;
    return '<svg width="' + px + '" height="' + px + '" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' + body + '</svg>';
  }
  function chevron(path, size) {
    return icon('<path d="' + path + '" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" ' +
      'stroke-linejoin="round"/>', size);
  }
  var ICON = {
    start: icon('<rect x="4" y="5" width="2.4" height="14" rx="1"/><path d="M13 5.5v13L6.8 12z"/><path d="M20 5.5v13L13.8 12z"/>'),
    back: icon('<path d="M15 5.5v13L6 12z"/><rect x="16.6" y="5" width="2.4" height="14" rx="1"/>'),
    play: icon('<path d="M7.5 4.8v14.4L19.5 12z"/>'),
    pause: icon('<rect x="6.5" y="5" width="3.8" height="14" rx="1"/><rect x="13.7" y="5" width="3.8" height="14" rx="1"/>'),
    forward: icon('<rect x="5" y="5" width="2.4" height="14" rx="1"/><path d="M9 5.5v13L18 12z"/>'),
    end: icon('<path d="M4 5.5v13L10.2 12z"/><path d="M11 5.5v13L17.2 12z"/><rect x="17.6" y="5" width="2.4" height="14" rx="1"/>'),
    prev: chevron('M15.5 5l-7 7 7 7', 12),
    next: chevron('M8.5 5l7 7-7 7', 12),
    down: chevron('M6 9l6 6 6-6', 13),
    up: chevron('M6 15l6-6 6 6', 13),
    worst: icon('<path d="M12 3.5l8.5 8.5-8.5 8.5L3.5 12z"/>', 11),
  };
  // the stage's own eye (viewer3d.js), so the lane's run toggle reads as the same control
  var EYE_OPEN = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
    '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="2.6"/></svg>';
  var EYE_SHUT = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' +
    '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><line x1="4" y1="20" x2="20" y2="4"/></svg>';

  // A 1-2-5 step that leaves at least ``minPx`` between ticks.
  function niceStep(span, px, minPx) {
    var raw = span / Math.max(1, px / minPx);
    var power = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var mantissa = raw / power;
    return (mantissa <= 1 ? 1 : mantissa <= 2 ? 2 : mantissa <= 5 ? 5 : 10) * power;
  }
  function decimalsFor(step) { return Math.max(0, -Math.floor(Math.log(step) / Math.LN10 + 1e-9)); }

  // ``#rrggbb`` + an alpha as ``#rrggbbaa`` (what kit.ink takes); anything else comes back as it is
  function withAlpha(colour, alpha) {
    if (!/^#[0-9a-f]{6}$/i.test(colour || '')) return colour;
    return colour + ('0' + Math.round(alpha * 255).toString(16)).slice(-2);
  }

  function create(page, hosts, kit) {
    var el = kit.el;
    var transport = page.transport;
    var data = page.data;
    var grid = data.plot_t;
    var fullSpan = transport.tMax - transport.tMin;
    var sample = Infinity;
    for (var i = 1; i < grid.length; i++) sample = Math.min(sample, grid[i] - grid[i - 1]);
    if (!isFinite(sample)) sample = fullSpan || 1;
    var minSpan = Math.max(sample * 8, fullSpan * 0.01);   // the narrowest zoom
    var reference = kit.referenceTitle(data);

    var lane = { page: page };
    var geometry = { x0: null, width: null, chart: null, sheetX: 0, sheetY: 0, ok: false };
    var drawnKey = '';
    var queued = false;
    var laneHover = null;   // an instant hovered on the lane itself (the sheet's dashed line follows only this one)
    var paging = false;
    var folded = false;
    var laneHeight = null;
    var namesWidth = NAMES_PX.fallback;

    function committed() { return transport.t === null ? transport.tMax : transport.t; }
    function snap(time) { return grid[kit.nearestIndex(grid, time)]; }

    /* ---------------- each run's error band and moments ---------------- */

    var sits = data.situations;
    var runs = sits.filter(function (sit) { return sit.role !== 'target' && sit.has_data; });
    var envelope = {};   // run name -> its largest |reference − run| over every joint, per plot sample (radians)
    var peakAll = 0;
    runs.forEach(function (sit) {
      if (!sit.plot || !sit.plot.err_q) return;
      var values = kit.maxAbsOverJoints(sit.plot.err_q);
      envelope[sit.name] = values;
      values.forEach(function (value) { if (value !== null && value > peakAll) peakAll = value; });
    });

    // WHY these three (R2): "when was it worst?" is the page's first question; where a run's error starts to climb is
    // the cause to look at; a broken limit is the verdict's own evidence
    function momentsOf(sit) {
      var out = [];
      var values = envelope[sit.name];
      var worst = values ? kit.worstMoment(data, sit) : null;
      if (worst) {
        out.push({ kind: 'worst', t: worst.t, size: worst.size, joint: worst.joint });
        for (var index = 0; index < values.length && worst.size > 0; index++) {
          if (values[index] !== null && values[index] > worst.size / 2) {
            // a spike's first sample above half its peak IS the worst moment: one marker says both
            if (Math.abs(grid[index] - worst.t) > sample * 1.5) out.push({ kind: 'rise', t: grid[index], size: worst.size / 2 });
            break;
          }
        }
      }
      ['joint', 'tcp'].forEach(function (key) {  // robot_msgs.compare.check's violations, each at its own time
        var outcome = sit.verdict && sit.verdict[key];
        ((outcome && outcome.violations) || []).forEach(function (violation) {
          if (isFinite(violation.t)) out.push({ kind: 'limit', t: violation.t, violation: violation });
        });
      });
      return out;
    }

    function momentTitle(sit, moment) {
      var go = ' · click to go there';
      if (moment.kind === 'worst') {
        var where = page.parts.length > 1 ? page.parts[kit.partIndexOf(page, moment.joint)].name + ' · ' + moment.joint : moment.joint;
        return sit.title + ': worst moment, ' + kit.angleText(moment.size) + ' on ' + where + ' at t = ' + moment.t.toFixed(2) +
          ' s (the largest |' + reference + ' − run| over every joint)' + go;
      }
      if (moment.kind === 'rise') {
        return sit.title + ': its error rises, first above half its own peak (' + kit.angleText(moment.size) + ') at t = ' +
          moment.t.toFixed(2) + ' s' + go;
      }
      return sit.title + ': limit broken, ' + (moment.violation.phase ? moment.violation.phase + ' · ' : '') +
        kit.violationText(moment.violation) + go;
    }

    /* ---------------- DOM ---------------- */

    var root = el('section', 'tc-lane', hosts.column);
    root.setAttribute('data-tc-lane', '');
    root.setAttribute('aria-label', 'Time lane: one time control for every chart, the 3D view and the videos');
    var sizer = el('div', 'tc-lane-resize', root);
    sizer.setAttribute('data-tc-lane-resize', '');
    sizer.setAttribute('role', 'separator');
    sizer.setAttribute('aria-orientation', 'horizontal');
    sizer.title = 'drag to resize the time lane · double-click for the default height';

    var bar = el('div', 'tc-lane-bar', root);
    function tool(parent, html, title, onClick, extra) {
      var button = el('button', 'tc-tbtn tc-lane-tool' + (extra ? ' ' + extra : ''), parent);
      button.type = 'button';
      button.innerHTML = html;
      button.title = title;
      button.setAttribute('aria-label', title);
      button.onclick = onClick;
      return button;
    }
    var transportGroup = el('div', 'tc-lane-tools', bar);
    tool(transportGroup, ICON.start, 'to start', function () { transport.pause(); transport.setScrub(transport.tMin); });
    tool(transportGroup, ICON.back, 'step back one sample (← on the ruler)', function () { transport.stepBy(-1); });
    var playButton = tool(transportGroup, ICON.play, 'play / pause (Space on the ruler)', function () { transport.toggle(); }, 'tc-lane-play');
    playButton.setAttribute('data-tc-play', '');
    tool(transportGroup, ICON.forward, 'step forward one sample (→ on the ruler)', function () { transport.stepBy(1); });
    tool(transportGroup, ICON.end, 'to end', function () { transport.pause(); transport.setScrub(transport.tMax); });
    var readout = el('span', 'tc-time tc-lane-readout', bar);
    readout.setAttribute('data-tc-lane-readout', '');
    readout.title = 'the committed time / the end of the motion';

    var momentGroup = el('div', 'tc-lane-tools', bar);
    tool(momentGroup, ICON.prev, 'the previous marked moment of a shown run', function () { jumpMoment(-1); })
      .setAttribute('data-tc-jump', 'prev');
    var worstButton = tool(momentGroup, ICON.worst + '<span>Worst moment</span>', 'the worst moment of the shown runs',
      function () { jumpWorst(); }, 'tc-lane-worst');
    worstButton.setAttribute('data-tc-jump', 'worst');
    tool(momentGroup, ICON.next, 'the next marked moment of a shown run', function () { jumpMoment(1); })
      .setAttribute('data-tc-jump', 'next');

    el('span', 'tc-lane-spacer', bar);
    var viewText = el('span', 'tc-lane-view', bar);
    var fullButton = tool(bar, 'Full range', 'show the whole motion on every chart (a double-click on a chart or the zoom bar ' +
      'does too)', function () { reset(); }, 'tc-lane-full');
    fullButton.setAttribute('data-tc-zoom-reset', '');
    if (hosts.units) { hosts.units.classList.add('tc-lane-units'); bar.appendChild(hosts.units); }  // Angles: deg / rad
    var foldButton = tool(bar, ICON.down, '', function () { setFolded(!folded, true); }, 'tc-lane-fold');
    foldButton.setAttribute('data-tc-lane-fold', '');

    var body = el('div', 'tc-lane-body', root);
    // the legend row sits above the ruler, so the ruler touches the tracks and the lane's line runs from its grip down
    var legendRow = el('div', 'tc-lane-row tc-lane-legend-row', body);
    var legendHead = el('div', 'tc-lane-head', legendRow);
    el('span', 'tc-lane-label', legendHead, 'Runs');
    var countText = el('span', 'tc-lane-count', legendHead);
    countText.setAttribute('data-tc-lane-count', '');
    var legend = el('div', 'tc-lane-time tc-lane-legend', legendRow);

    var rulerRow = el('div', 'tc-lane-row tc-lane-ruler-row', body);
    var rulerHead = el('div', 'tc-lane-head', rulerRow);
    el('span', 'tc-lane-label', rulerHead, 'Time [s]');
    var nowLabel = el('span', 'tc-lane-now', rulerHead, 'error at t');
    nowLabel.title = 'each run\'s largest joint error at the committed time, max over joints of |' + reference + ' − run|';
    var ruler = el('div', 'tc-lane-time tc-lane-ruler', rulerRow);
    ruler.setAttribute('data-tc-ruler', '');
    ruler.setAttribute('role', 'slider');
    ruler.setAttribute('tabindex', '0');
    ruler.setAttribute('aria-label', 'Time');
    ruler.setAttribute('aria-valuemin', String(transport.tMin));
    ruler.setAttribute('aria-valuemax', String(transport.tMax));
    ruler.title = 'press and drag: move the time on every chart and the 3D · wheel: zoom · ← →: step · Space: play';
    var rulerCanvas = el('canvas', 'tc-lane-canvas', ruler);
    var grip = el('div', 'tc-lane-grip', ruler);
    grip.title = 'the time is outside the zoomed range: click to bring it into view';
    grip.addEventListener('pointerdown', function (event) {
      if (!grip.classList.contains('edge')) return;
      event.stopPropagation();
      event.preventDefault();
      var shown = view(), span = shown[1] - shown[0], time = committed();
      setView(time - span / 2, time + span / 2);
    });
    var gripTip = el('div', 'tc-lane-grip-tip', ruler);

    var tracks = el('div', 'tc-lane-tracks', body);
    tracks.setAttribute('data-tc-lane-tracks', '');

    var rangeRow = el('div', 'tc-lane-row tc-lane-range-row', body);
    var rangeHead = el('div', 'tc-lane-head', rangeRow);
    el('span', 'tc-lane-label', rangeHead, 'Zoom');
    var rangeHint = el('span', 'tc-lane-hint', rangeHead);
    var range = el('div', 'tc-lane-time tc-lane-range', rangeRow);
    range.setAttribute('data-tc-zoom-bar', '');
    range.title = 'the whole motion: drag a range to zoom every chart · drag the window to pan, its edges to resize · ' +
      'wheel: zoom · double-click: full range';
    var rangeCanvas = el('canvas', 'tc-lane-canvas', range);
    var rangeWindow = el('div', 'tc-lane-window', range);
    rangeWindow.setAttribute('data-tc-zoom-window', '');
    el('span', 'tc-lane-window-edge left', rangeWindow);
    el('span', 'tc-lane-window-edge right', rangeWindow);
    var rangeTick = el('div', 'tc-lane-range-tick', range);

    var laneLine = el('div', 'tc-lane-line', body);
    var laneGhost = el('div', 'tc-lane-line ghost', body);
    var namesHandle = el('div', 'tc-lane-names-resize', body);
    namesHandle.setAttribute('data-tc-lane-names-resize', '');
    namesHandle.setAttribute('role', 'separator');
    namesHandle.setAttribute('aria-orientation', 'vertical');
    namesHandle.title = 'drag: widen the names column (the charts\' title column follows) · double-click: default';

    // the ONE line through every chart, and the dashed one at an instant hovered on the lane
    var line = el('div', 'tc-line', hosts.sheet);
    line.setAttribute('data-tc-line', '');
    line.setAttribute('aria-hidden', 'true');
    var ghost = el('div', 'tc-line ghost', hosts.sheet);
    ghost.setAttribute('aria-hidden', 'true');

    /* ---------------- tracks ---------------- */

    var rows = [];
    var groupRows = [];
    function chipOf(list, name) { return list.filter(function (entry) { return entry.sit.name === name; })[0] || null; }

    function addTrack(sit, group) {
      var isTarget = sit.role === 'target';
      var row = el('div', 'tc-lane-row tc-lane-track', tracks);
      var head = el('div', 'tc-lane-head', row);
      var record = { sit: sit, el: row, group: group, moments: [] };
      if (!sit.has_data) {
        // not a track: there is nothing to scrub or hide, only the reason it is empty
        row.classList.add('nodata');
        row.setAttribute('data-tc-lane-nodata', sit.name);
        el('span', 'tc-lane-eye-gap', head);
        el('span', 'tc-lane-swatch', head).style.background = sit.color;
        var deadName = el('span', 'tc-lane-name', head, sit.title);
        deadName.title = sit.title + ' (no data' + (sit.note ? ' — ' + sit.note : '') + ')';
        el('div', 'tc-lane-time tc-lane-note', row, 'no data' + (sit.note ? ' — ' + sit.note : ''));
        rows.push(record);
        return;
      }
      row.setAttribute('data-tc-lane-track', sit.name);
      var chip = chipOf(page.sitChips, sit.name);
      var eye = el('button', 'tc-lane-eye', head);
      eye.type = 'button';
      eye.setAttribute('data-tc-lane-eye', '');
      eye.onclick = function () { if (chip) chip.apply(page.visible[sit.name] === false, true); };
      record.eye = eye;
      var swatch = el('span', 'tc-lane-swatch' + (isTarget ? ' dashed' : ''), head);
      swatch.style.background = sit.color;
      swatch.style.color = sit.color;
      // WHY two parts (Zach's rule: never truncate a name silently): under its group's row the group's prefix is the part
      // that may ellipsize; what tells the repeats apart always stays; the whole name is the title
      var name = el('span', 'tc-lane-name', head);
      var prefix = group && group.title && sit.title.indexOf(group.title) === 0 && sit.title.length > group.title.length ? group.title : '';
      el('span', 'tc-lane-name-pre', name, prefix || sit.title);
      if (prefix) el('span', 'tc-lane-name-post', name, sit.title.slice(prefix.length));
      name.title = sit.title + (sit.time_offset_s ? ' · errors taken with its clock shifted ' + sit.time_offset_s * 1000 + ' ms earlier' : '') +
        (isTarget ? ' · the reference every error is measured against' : '');
      var badge = kit.verdictBadge(sit);
      if (badge) head.appendChild(badge);
      if (!isTarget) {
        record.value = el('span', 'tc-lane-value', head);
        record.value.setAttribute('data-tc-lane-value', '');
        var errChip = chipOf(page.errChips, sit.name);
        if (errChip) {
          var delta = el('button', 'tc-lane-delta', head, 'Δ');
          delta.type = 'button';
          delta.setAttribute('data-tc-lane-delta', '');
          delta.title = 'Δ: draw ' + reference + ' − ' + sit.title + ' on every plot that has it (dotted)';
          delta.onclick = function () { errChip.apply(!page.errorOn[sit.name], true); paintSelection(); };
          record.delta = delta;
        } else {
          el('span', 'tc-lane-delta-gap', head);
        }
      }
      var time = el('div', 'tc-lane-time tc-lane-track-time', row);
      time.setAttribute('data-tc-lane-time', '');
      record.time = time;
      record.canvas = el('canvas', 'tc-lane-canvas', time);
      if (isTarget) el('span', 'tc-lane-note', time, 'the reference: every error is ' + reference + ' − run');
      record.moments = isTarget ? [] : momentsOf(sit);
      record.moments.forEach(function (moment) {
        var mark = el('button', 'tc-lane-mark ' + moment.kind, time);
        mark.type = 'button';
        mark.innerHTML = moment.kind === 'limit' ? '×' : '<i></i>';
        mark.style.color = sit.color;
        mark.setAttribute('data-tc-moment', moment.kind);
        mark.setAttribute('data-t', String(moment.t));
        mark.addEventListener('pointerdown', function (event) { event.stopPropagation(); });
        mark.onclick = function (event) {
          event.stopPropagation();
          jumpTo(moment.t);
        };
        moment.el = mark;
      });
      rows.push(record);
    }

    /* A group's row: like a DAW's folder track it folds its runs' tracks (remembered; a group none of whose runs is shown
       starts folded) and its eye shows or hides all of them. */
    function addGroup(group) {
      var row = el('div', 'tc-lane-row tc-lane-group', tracks);
      row.setAttribute('data-tc-lane-group', group.key);
      var head = el('div', 'tc-lane-head', row);
      var fold = el('button', 'tc-lane-group-fold', head);
      fold.type = 'button';
      var remembered = kit.recall('lane-group-folded:' + group.key, null);
      group.folded = remembered === null ? !group.sits.some(function (sit) { return page.visible[sit.name] !== false; }) : !!remembered;
      fold.onclick = function () {
        group.folded = !group.folded;
        kit.store('lane-group-folded:' + group.key, group.folded);
        paintSelection();
        setLaneHeight(laneHeight, false);
      };
      var eye = el('button', 'tc-lane-eye small', head);
      eye.type = 'button';
      eye.setAttribute('data-tc-lane-eye', '');
      eye.onclick = function () {
        var show = !group.sits.some(function (sit) { return page.visible[sit.name] !== false; });
        group.sits.forEach(function (sit) {
          var chip = chipOf(page.sitChips, sit.name);
          if (chip && (page.visible[sit.name] !== false) !== show) chip.apply(show, true);
        });
      };
      var label = el('span', 'tc-lane-group-name', head, group.title || 'Runs');
      label.title = group.title;
      var count = el('span', 'tc-lane-group-count', head);
      groupRows.push({ group: group, el: row, eye: eye, count: count, fold: fold });
    }

    (function buildTracks() {
      sits.filter(function (sit) { return sit.role === 'target'; }).forEach(function (sit) { addTrack(sit, null); });
      var groups = [], byKey = {};
      sits.forEach(function (sit) {
        if (sit.role === 'target') return;
        var key = sit.group || '';
        if (!byKey[key]) {
          // ``sits``: the runs with data (what the group's eye and count act on); ``all``: every row, no-data ones too
          byKey[key] = { key: key, title: sit.group_title || sit.group || '', sits: [], all: [] };
          groups.push(byKey[key]);
        }
        if (sit.has_data) byKey[key].sits.push(sit);
        byKey[key].all.push(sit);
      });
      var grouped = groups.length > 1;
      groups.forEach(function (group) {
        var row = grouped && group.sits.length;
        if (row) addGroup(group);
        group.all.forEach(function (sit) { addTrack(sit, row ? group : null); });
      });
    })();

    var anyLimit = rows.some(function (record) { return record.moments.some(function (moment) { return moment.kind === 'limit'; }); });
    (function buildLegend() {
      var band = el('span', 'tc-lane-key-item', legend);
      el('i', 'tc-lane-key band', band);
      var bandText = el('span', '', band);
      var worst = el('span', 'tc-lane-key-item', legend);
      el('i', 'tc-lane-key worst', worst);
      el('span', '', worst, 'worst moment');
      var rise = el('span', 'tc-lane-key-item', legend);
      el('i', 'tc-lane-key rise', rise);
      el('span', '', rise, 'error rises (first above half its peak)');
      if (anyLimit) {
        var limit = el('span', 'tc-lane-key-item', legend);
        el('i', 'tc-lane-key limit', limit, '×');
        el('span', '', limit, 'limit broken');
      }
      function paint() {
        bandText.textContent = 'largest joint error, max over joints of |' + reference + ' − run| [' +
          (kit.state.unit === 'deg' ? '°' : 'rad') + ']' + (peakAll ? ', one scale, top = ' + kit.angleText(peakAll) : '');
        legend.title = 'Each run\'s band: ' + bandText.textContent + '. ◆ its worst moment; ▲ where its error first passes ' +
          'half of its own peak' + (anyLimit ? '; × a limit it broke' : '') + '. Click a marker to go there.';
      }
      paint();
      page.unitRepaints.push(paint);
    })();

    /* ---------------- geometry: the charts' x pixels ---------------- */

    // the first chart drawn in the open tab: the lane measures its plotting area and draws on it
    function referenceChart() {
      var tab = kit.activeTab(page);
      if (!tab) return null;
      for (var index = 0; index < page.charts.length; index++) {
        var chart = page.charts[index];
        if (chart.u && tab.panel.contains(chart.card) && chart.card.offsetParent && chart.card.offsetWidth) return chart;
      }
      return null;
    }

    function view() {
      var chart = geometry.chart && geometry.chart.u ? geometry.chart : referenceChart();
      var scale = chart && chart.u.scales.x;
      if (scale && isFinite(scale.min) && scale.max > scale.min) return [scale.min, scale.max];
      var zoom = page.xZoom;
      if (zoom && isFinite(zoom.min) && isFinite(zoom.max) && zoom.max > zoom.min) return [zoom.min, zoom.max];
      return [transport.tMin, transport.tMax];
    }
    function isZoomed(shown) { return shown[1] - shown[0] < fullSpan - 1e-9; }

    function setNamesWidth(width, remember) {
      var room = root.clientWidth || hosts.column.clientWidth || 800;
      var widest = Math.max(NAMES_PX.min, Math.min(NAMES_PX.max, Math.round(room * NAMES_PX.share)));
      var wanted = width === null || width === undefined ? NAMES_PX.fallback : Number(width) || NAMES_PX.fallback;
      namesWidth = Math.round(Math.max(NAMES_PX.min, Math.min(widest, wanted)));
      page.el.style.setProperty('--tc-lane-names', namesWidth + 'px');
      if (remember) kit.store('lane-names-width', width === null ? null : namesWidth);
      var tab = kit.activeTab(page);
      if (tab) kit.resizeChartsIn(page, tab.panel);
      queue();
    }

    function measure() {
      var chart = referenceChart();
      var bodyBox = body.getBoundingClientRect();
      geometry.chart = chart;
      geometry.ok = !!chart;
      if (chart) {
        var over = chart.u.over.getBoundingClientRect();
        var sheetBox = hosts.sheet.getBoundingClientRect();
        geometry.x0 = over.left - bodyBox.left;
        geometry.width = over.width;
        geometry.sheetX = over.left - sheetBox.left;
        geometry.sheetY = over.top - sheetBox.top;
      } else if (geometry.x0 === null || !geometry.width) {
        // no chart in this tab: where a stacked chart's plot would start (its border, the title column, the y axis)
        geometry.x0 = 1 + namesWidth + kit.axisPx;
        geometry.width = Math.max(80, bodyBox.width - geometry.x0 - kit.padRightPx - 1);
      }
    }

    function sizeCanvas(canvas, width, height) {
      var ratio = window.devicePixelRatio || 1;
      var w = Math.max(1, Math.round(width * ratio)), h = Math.max(1, Math.round(height * ratio));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      var context = canvas.getContext('2d');
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      return context;
    }

    function drawRuler(shown) {
      var width = geometry.width, height = ruler.clientHeight || 26;
      var context = sizeCanvas(rulerCanvas, width, height);
      var span = shown[1] - shown[0];
      var step = niceStep(span, width, TICK_MIN_PX);
      var mantissa = step / Math.pow(10, Math.floor(Math.log(step) / Math.LN10));
      var minor = step / (Math.abs(mantissa - 2) < 1e-9 ? 4 : 5);
      var decimals = decimalsFor(step);
      context.lineWidth = 1;
      context.strokeStyle = kit.ink('#d3d2cc');
      context.beginPath();
      for (var t = Math.ceil(shown[0] / minor - 1e-9) * minor; t <= shown[1] + 1e-9; t += minor) {
        var x = Math.round((t - shown[0]) / span * width) + 0.5;
        context.moveTo(x, height - 4);
        context.lineTo(x, height);
      }
      context.stroke();
      context.strokeStyle = kit.ink('#a8a7a2');
      context.fillStyle = kit.ink('#6f6e69');
      context.font = '10.5px -apple-system, "Segoe UI", Roboto, sans-serif';
      context.beginPath();
      for (var major = Math.ceil(shown[0] / step - 1e-9) * step; major <= shown[1] + 1e-9; major += step) {
        var xm = Math.round((major - shown[0]) / span * width) + 0.5;
        context.moveTo(xm, height - 8);
        context.lineTo(xm, height);
        var label = (Math.abs(major) < 1e-12 ? 0 : major).toFixed(decimals);
        var textWidth = context.measureText(label).width;
        context.fillText(label, Math.max(1, Math.min(width - textWidth - 1, xm - textWidth / 2)), height - 11);
      }
      context.stroke();
    }

    function drawBand(record, shown) {
      var width = geometry.width, height = TRACK_PX - 1;
      var context = sizeCanvas(record.canvas, width, height);
      var values = envelope[record.sit.name];
      if (record.sit.role === 'target') {  // the reference: a dashed midline in its own grey
        context.strokeStyle = withAlpha(record.sit.color, 0.55);
        context.setLineDash([6, 4]);
        context.beginPath();
        context.moveTo(0, Math.round(height / 2) + 0.5);
        context.lineTo(width, Math.round(height / 2) + 0.5);
        context.stroke();
        return;
      }
      if (!values || !peakAll) return;
      var on = page.visible[record.sit.name] !== false;
      var colour = on ? record.sit.color : kit.ink('#b9b8b2');
      var span = shown[1] - shown[0];
      var lo = Math.max(0, kit.nearestIndex(grid, shown[0]) - 1), hi = Math.min(grid.length - 1, kit.nearestIndex(grid, shown[1]) + 1);
      var base = height - 2.5, room = height - 5;
      function trace(closed) {
        context.beginPath();
        var started = false, lastX = 0;
        for (var index = lo; index <= hi; index++) {
          var value = values[index];
          if (value === null || value === undefined) continue;
          var x = (grid[index] - shown[0]) / span * width, y = base - value / peakAll * room;
          if (!started) { context.moveTo(x, closed ? base : y); started = true; }
          context.lineTo(x, y);
          lastX = x;
        }
        if (closed && started) { context.lineTo(lastX, base); context.closePath(); }
        return started;
      }
      if (trace(true)) {
        context.fillStyle = withAlpha(colour, on ? 0.2 : 0.14);
        context.fill();
      }
      if (trace(false)) {
        context.strokeStyle = withAlpha(colour, on ? 0.9 : 0.5);
        context.lineWidth = 1.1;
        context.stroke();
      }
    }

    function placeMarks(record, shown) {
      var span = shown[1] - shown[0];
      record.moments.forEach(function (moment) {
        var x = (moment.t - shown[0]) / span * geometry.width;
        var inside = x >= -1 && x <= geometry.width + 1;
        moment.el.style.display = inside ? '' : 'none';
        if (inside) moment.el.style.left = x + 'px';
      });
    }

    function drawRange(shown) {
      var width = geometry.width, height = range.clientHeight || 22;
      var context = sizeCanvas(rangeCanvas, width, height);
      // the overview: the largest joint error of the shown runs, so the zoom bar is a map of where to look
      var on = runs.filter(function (sit) { return envelope[sit.name] && page.visible[sit.name] !== false; });
      if (on.length && peakAll) {
        var top = 0, largest = new Array(grid.length);
        for (var index = 0; index < grid.length; index++) {
          var best = null;
          for (var k = 0; k < on.length; k++) {
            var value = envelope[on[k].name][index];
            if (value !== null && (best === null || value > best)) best = value;
          }
          largest[index] = best;
          if (best !== null && best > top) top = best;
        }
        context.beginPath();
        context.moveTo(0, height - 2);
        for (var j = 0; j < grid.length; j++) {
          if (largest[j] === null) continue;
          context.lineTo((grid[j] - transport.tMin) / fullSpan * width, height - 2 - largest[j] / (top || 1) * (height - 6));
        }
        context.lineTo(width, height - 2);
        context.closePath();
        context.fillStyle = kit.ink('#52514e2b');
        context.fill();
      }
      var step = niceStep(fullSpan, width, 90);
      context.strokeStyle = kit.ink('#d3d2cc');
      context.beginPath();
      for (var t = Math.ceil(transport.tMin / step) * step; t <= transport.tMax + 1e-9; t += step) {
        var x = Math.round((t - transport.tMin) / fullSpan * width) + 0.5;
        context.moveTo(x, 0);
        context.lineTo(x, 4);
      }
      context.stroke();
      var left = (shown[0] - transport.tMin) / fullSpan * width, right = (shown[1] - transport.tMin) / fullSpan * width;
      rangeWindow.style.left = left + 'px';
      rangeWindow.style.width = Math.max(2, right - left) + 'px';
      rangeWindow.classList.toggle('full', !isZoomed(shown));
    }

    // what moves only when the geometry, the zoom, the unit, the fold or the selection does
    function drawStatic(shown) {
      root.style.setProperty('--tc-lane-x0', geometry.x0 + 'px');
      root.style.setProperty('--tc-lane-w', geometry.width + 'px');
      drawRuler(shown);
      rows.forEach(function (record) {
        if (!record.canvas) return;
        drawBand(record, shown);
        placeMarks(record, shown);
      });
      drawRange(shown);
      var zoomed = isZoomed(shown);
      viewText.textContent = zoomed ? 'Showing ' + shown[0].toFixed(2) + '–' + shown[1].toFixed(2) + ' s of ' + fullSpan.toFixed(2) + ' s' : '';
      viewText.title = zoomed ? 'every chart shows this part of the motion; Full range shows all of it' : '';
      fullButton.disabled = !zoomed;
      rangeHint.textContent = zoomed ? (shown[1] - shown[0]).toFixed(2) + ' s shown' : 'drag a range';
      namesHandle.style.left = (geometry.x0 - 7) + 'px';
    }

    /* ---------------- paint ---------------- */

    function xOf(time, shown) { return (time - shown[0]) / (shown[1] - shown[0]) * geometry.width; }

    // the lane's own vertical line (committed or hovered) from the ruler down through the tracks
    function placeLaneLine(node, x, fromY) {
      var bottom = folded ? rulerRow.offsetTop + rulerRow.offsetHeight : rangeRow.offsetTop;
      node.style.left = (geometry.x0 + x - 1) + 'px';
      node.style.top = fromY + 'px';
      node.style.height = Math.max(0, bottom - fromY) + 'px';
    }

    function paintTime(shown) {
      var time = committed();
      var inside = time >= shown[0] - 1e-9 && time <= shown[1] + 1e-9;
      // the line through the charts: the reference chart's own mapping, so it sits exactly where uPlot draws ``time``
      if (geometry.ok && inside) {
        line.style.display = '';
        line.style.left = (geometry.sheetX + geometry.chart.u.valToPos(time, 'x') - 1) + 'px';
        line.style.top = (geometry.sheetY - 8) + 'px';
      } else {
        line.style.display = 'none';
      }
      var x = xOf(time, shown);
      ruler.setAttribute('aria-valuenow', String(time));
      ruler.setAttribute('aria-valuetext', time.toFixed(2) + ' seconds');
      grip.classList.toggle('edge', !inside);
      gripTip.style.display = laneLine.style.display = inside ? '' : 'none';
      if (inside) {
        grip.textContent = time.toFixed(2);
        var gripWidth = grip.offsetWidth || 36;
        grip.style.left = Math.max(0, Math.min(geometry.width - gripWidth, x - gripWidth / 2)) + 'px';
        gripTip.style.left = x + 'px';
        placeLaneLine(laneLine, x, rulerRow.offsetTop + ruler.clientHeight - 6);
      } else {
        // outside the zoomed range the grip waits at that edge, pointing to the time (a click brings it into view)
        grip.textContent = time < shown[0] ? '‹ ' + time.toFixed(2) : time.toFixed(2) + ' ›';
        grip.style.left = (time < shown[0] ? 0 : Math.max(0, geometry.width - (grip.offsetWidth || 44))) + 'px';
      }
      rangeTick.style.left = ((time - transport.tMin) / fullSpan * geometry.width) + 'px';
      readout.textContent = time.toFixed(2) + ' / ' + transport.tMax.toFixed(2) + ' s';
      playButton.innerHTML = transport.playing ? ICON.pause : ICON.play;
      playButton.classList.toggle('on', transport.playing);
      paintValues(time);
      paintGhosts(shown);
    }

    function paintValues(time) {
      var index = kit.nearestIndex(grid, time);
      rows.forEach(function (record) {
        if (!record.value) return;
        var values = envelope[record.sit.name];
        var value = values ? values[index] : null;
        record.value.textContent = value === null || value === undefined ? '' : kit.angleText(value);
      });
    }

    function paintGhosts(shown) {
      var hover = transport.hoverT;
      var inLane = hover !== null && hover >= shown[0] && hover <= shown[1];
      laneGhost.style.display = inLane ? '' : 'none';
      if (inLane) placeLaneLine(laneGhost, xOf(hover, shown) + 0.5, rulerRow.offsetTop);
      // a hovered chart has uPlot's own dashed cursor on every chart; an instant hovered on the lane gets this one
      var inSheet = laneHover !== null && inLane && geometry.ok;
      ghost.style.display = inSheet ? '' : 'none';
      if (inSheet) {
        ghost.style.left = (geometry.sheetX + geometry.chart.u.valToPos(laneHover, 'x') - 0.5) + 'px';
        ghost.style.top = geometry.sheetY + 'px';
      }
    }

    function paint() {
      measure();
      var shown = view();
      var key = [geometry.x0, geometry.width, shown[0], shown[1], folded, kit.state.unit].join('|');
      if (key !== drawnKey) { drawnKey = key; drawStatic(shown); }
      paintTime(shown);
      // playing past a zoomed window pages the window along, as a video editor does
      if (transport.playing && !paging && isZoomed(shown)) {
        var time = committed();
        if (time > shown[1] || time < shown[0]) {
          paging = true;
          var span = shown[1] - shown[0];
          setView(time - span * 0.05, time + span * 0.95);
          paging = false;
        }
      }
    }

    function queue() {
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () { queued = false; paint(); });
    }

    function paintSelection() {
      var shownRuns = 0;
      rows.forEach(function (record) {
        if (!record.eye) return;
        var on = page.visible[record.sit.name] !== false;
        record.el.classList.toggle('off', !on);
        record.el.setAttribute('data-shown', on ? 'true' : 'false');
        record.eye.innerHTML = on ? EYE_OPEN : EYE_SHUT;
        record.eye.setAttribute('aria-pressed', on ? 'true' : 'false');
        record.eye.title = (on ? 'Hide ' : 'Show ') + record.sit.title + ' on every chart and in the 3D view';
        record.eye.setAttribute('aria-label', record.eye.title);
        if (record.delta) {
          var deltaOn = !!page.errorOn[record.sit.name];
          record.delta.classList.toggle('on', deltaOn);
          record.delta.setAttribute('aria-pressed', deltaOn ? 'true' : 'false');
        }
        if (record.sit.role !== 'target' && on) shownRuns += 1;
      });
      rows.forEach(function (record) { record.el.style.display = record.group && record.group.folded ? 'none' : ''; });
      groupRows.forEach(function (entry) {
        var group = entry.group;
        entry.el.classList.toggle('folded', !!group.folded);
        entry.fold.innerHTML = group.folded ? ICON.next : ICON.down;
        entry.fold.title = (group.folded ? 'Show the tracks of ' : 'Fold the tracks of ') + group.title;
        entry.fold.setAttribute('aria-label', entry.fold.title);
        entry.fold.setAttribute('aria-expanded', group.folded ? 'false' : 'true');
        var on = group.sits.filter(function (sit) { return page.visible[sit.name] !== false; }).length;
        entry.count.textContent = on + ' of ' + group.sits.length;
        entry.el.classList.toggle('off', on === 0);
        entry.eye.innerHTML = on ? EYE_OPEN : EYE_SHUT;
        entry.eye.setAttribute('aria-pressed', on ? 'true' : 'false');
        entry.eye.title = (on ? 'Hide every run of ' : 'Show every run of ') + group.title;
        entry.eye.setAttribute('aria-label', entry.eye.title);
      });
      countText.textContent = shownRuns + ' of ' + runs.length + ' shown';
      var worst = worstShown();
      worstButton.disabled = !worst;
      worstButton.title = worst ? 'go to the worst moment of the shown runs: ' + worst.record.sit.title + ', ' +
        kit.angleText(worst.moment.size) + ' on ' + worst.moment.joint + ' at t = ' + worst.moment.t.toFixed(2) + ' s'
        : 'no shown run has a joint error';
      worstButton.setAttribute('aria-label', worstButton.title);
      drawnKey = '';
      queue();
    }

    function paintTitles() {
      rows.forEach(function (record) {
        record.moments.forEach(function (moment) {
          moment.el.title = momentTitle(record.sit, moment);
          moment.el.setAttribute('aria-label', moment.el.title);
        });
      });
      paintSelection();
    }

    /* ---------------- moments ---------------- */

    function shownMoments() {
      var out = [];
      rows.forEach(function (record) {
        if (page.visible[record.sit.name] === false) return;
        record.moments.forEach(function (moment) { out.push({ record: record, moment: moment }); });
      });
      return out.sort(function (a, b) { return a.moment.t - b.moment.t; });
    }
    function worstShown() {
      var best = null;
      shownMoments().forEach(function (entry) {
        if (entry.moment.kind === 'worst' && (!best || entry.moment.size > best.moment.size)) best = entry;
      });
      return best;
    }
    function jumpTo(time) {
      transport.pause();
      transport.setScrub(time);
      var shown = view();
      if (isZoomed(shown) && (time < shown[0] || time > shown[1])) {
        var span = shown[1] - shown[0];
        setView(time - span / 2, time + span / 2);
      }
    }
    function jumpWorst() { var worst = worstShown(); if (worst) jumpTo(worst.moment.t); }
    function jumpMoment(direction) {
      var time = committed(), list = shownMoments(), half = sample / 2, pick = null;
      if (direction > 0) list.some(function (entry) { if (entry.moment.t > time + half) { pick = entry; return true; } return false; });
      else list.slice().reverse().some(function (entry) { if (entry.moment.t < time - half) { pick = entry; return true; } return false; });
      if (pick) jumpTo(pick.moment.t);
    }

    /* ---------------- zoom ---------------- */

    function setView(min, max) {
      if (!(max > min)) return;
      if (max - min < minSpan) { var middle = (min + max) / 2; min = middle - minSpan / 2; max = middle + minSpan / 2; }
      if (min < transport.tMin) { max += transport.tMin - min; min = transport.tMin; }
      if (max > transport.tMax) { min -= max - transport.tMax; max = transport.tMax; }
      min = Math.max(transport.tMin, min);
      if (max - min >= fullSpan - 1e-9) { reset(); return; }
      page.syncing = true;
      page.charts.forEach(function (chart) { if (chart.u) chart.u.setScale('x', { min: min, max: max }); });
      page.syncing = false;
      page.xZoom = { min: min, max: max };
      kit.restoreCursors(page);
      paint();
    }
    function reset() {
      kit.resetZoom(page);
      paint();
    }
    function onWheel(event, pointerTime) {
      event.preventDefault();
      var shown = view();
      if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        var shift = (shown[1] - shown[0]) * 0.12 * Math.sign(event.deltaX || event.deltaY);
        setView(shown[0] + shift, shown[1] + shift);
        return;
      }
      var factor = event.deltaY > 0 ? 1.25 : 0.8;
      setView(pointerTime - (pointerTime - shown[0]) * factor, pointerTime + (shown[1] - pointerTime) * factor);
    }

    /* ---------------- gestures ---------------- */

    function timeOnView(clientX, box) {
      var shown = view();
      var x = Math.max(0, Math.min(box.width, clientX - box.left));
      return shown[0] + x / box.width * (shown[1] - shown[0]);
    }

    function setLaneHover(time) {
      if (time === laneHover) return;
      laneHover = time;
      transport.setHover(time);  // the 3D previews that instant; the committed time stays
    }

    // press and drag on the ruler or a track: the time follows the pointer, live (snapped to the plot grid)
    function scrubSurface(surface) {
      surface.addEventListener('pointerdown', function (event) {
        if (event.button !== 0) return;
        event.preventDefault();
        var box = surface.getBoundingClientRect();
        var id = event.pointerId;
        transport.pause();
        setLaneHover(null);
        try { surface.setPointerCapture(id); } catch (error) {}
        document.body.classList.add('tc-scrubbing');
        transport.setScrub(snap(timeOnView(event.clientX, box)));
        if (surface === ruler) ruler.focus({ preventScroll: true });
        function move(moveEvent) {
          if (moveEvent.pointerId === id) transport.setScrub(snap(timeOnView(moveEvent.clientX, box)));
        }
        function up(upEvent) {
          if (upEvent.pointerId !== id) return;
          surface.removeEventListener('pointermove', move);
          surface.removeEventListener('pointerup', up);
          surface.removeEventListener('pointercancel', up);
          document.body.classList.remove('tc-scrubbing');
        }
        surface.addEventListener('pointermove', move);
        surface.addEventListener('pointerup', up);
        surface.addEventListener('pointercancel', up);
      });
      // a hover previews that instant in the 3D view and draws a dashed line through the charts
      surface.addEventListener('pointermove', function (event) {
        if (event.buttons || event.pointerType === 'touch') return;
        setLaneHover(snap(timeOnView(event.clientX, surface.getBoundingClientRect())));
      });
      surface.addEventListener('pointerleave', function () { setLaneHover(null); });
    }
    scrubSurface(ruler);
    rows.forEach(function (record) { if (record.time) scrubSurface(record.time); });

    ruler.addEventListener('wheel', function (event) {
      onWheel(event, timeOnView(event.clientX, ruler.getBoundingClientRect()));
    }, { passive: false });
    // the tracks list scrolls on a plain wheel (many runs do not fit); Ctrl / ⌘ / Alt + wheel zooms there
    tracks.addEventListener('wheel', function (event) {
      var surface = event.target.closest && event.target.closest('.tc-lane-track-time');
      if (!(event.ctrlKey || event.metaKey || event.altKey) || !surface) return;
      onWheel(event, timeOnView(event.clientX, surface.getBoundingClientRect()));
    }, { passive: false });

    function fullTimeAt(clientX) {
      var box = range.getBoundingClientRect();
      var x = Math.max(0, Math.min(box.width, clientX - box.left));
      return transport.tMin + x / box.width * fullSpan;
    }
    range.addEventListener('wheel', function (event) { onWheel(event, fullTimeAt(event.clientX)); }, { passive: false });
    range.addEventListener('dblclick', function () { reset(); });
    range.addEventListener('pointerdown', function (event) {
      if (event.button !== 0) return;
      event.preventDefault();
      var box = range.getBoundingClientRect();
      var shown = view();
      var zoomed = isZoomed(shown);
      var startX = event.clientX - box.left;
      var left = (shown[0] - transport.tMin) / fullSpan * box.width, right = (shown[1] - transport.tMin) / fullSpan * box.width;
      var mode = 'new';
      if (zoomed && Math.abs(startX - left) <= 6) mode = 'left';
      else if (zoomed && Math.abs(startX - right) <= 6) mode = 'right';
      else if (zoomed && startX > left && startX < right) mode = 'pan';
      var start = fullTimeAt(event.clientX);
      var moved = false;
      var id = event.pointerId;
      try { range.setPointerCapture(id); } catch (error) {}
      range.classList.add('dragging');
      function move(moveEvent) {
        if (moveEvent.pointerId !== id) return;
        if (Math.abs(moveEvent.clientX - box.left - startX) > 2) moved = true;
        if (!moved) return;
        var time = fullTimeAt(moveEvent.clientX);
        if (mode === 'pan') setView(shown[0] + time - start, shown[1] + time - start);
        else if (mode === 'left') setView(Math.min(time, shown[1] - minSpan), shown[1]);
        else if (mode === 'right') setView(shown[0], Math.max(time, shown[0] + minSpan));
        else setView(Math.min(start, time), Math.max(start, time));
      }
      function up(upEvent) {
        if (upEvent.pointerId !== id) return;
        range.removeEventListener('pointermove', move);
        range.removeEventListener('pointerup', up);
        range.removeEventListener('pointercancel', up);
        range.classList.remove('dragging');
        // a plain click while zoomed centres the window there
        if (!moved && zoomed) { var span = shown[1] - shown[0]; setView(start - span / 2, start + span / 2); }
      }
      range.addEventListener('pointermove', move);
      range.addEventListener('pointerup', up);
      range.addEventListener('pointercancel', up);
    });

    // the ruler is the page's slider: arrows step one sample (Shift: ten), Home / End, Space or k plays
    ruler.addEventListener('keydown', function (event) {
      var handled = true;
      if (event.key === 'ArrowLeft') transport.stepBy(event.shiftKey ? -10 : -1);
      else if (event.key === 'ArrowRight') transport.stepBy(event.shiftKey ? 10 : 1);
      else if (event.key === 'Home') { transport.pause(); transport.setScrub(transport.tMin); }
      else if (event.key === 'End') { transport.pause(); transport.setScrub(transport.tMax); }
      else if (event.key === ' ' || event.key === 'k') transport.toggle();
      else handled = false;
      if (handled) event.preventDefault();
    });

    /* ---------------- height, fold, names column ---------------- */

    function chromePx() {  // everything but the tracks
      return bar.offsetHeight + legendRow.offsetHeight + rulerRow.offsetHeight + rangeRow.offsetHeight + 4;
    }
    function listedPx() {
      var px = 0;
      rows.forEach(function (record) { if (!(record.group && record.group.folded)) px += TRACK_PX; });
      return px + groupRows.length * GROUP_PX;
    }
    function defaultPx() {
      // half a track more than fits says "it scrolls"
      return chromePx() + Math.min(listedPx(), VISIBLE_TRACKS * TRACK_PX + 2 * GROUP_PX + Math.round(TRACK_PX / 2));
    }
    function setLaneHeight(height, remember) {
      var tallest = Math.max(LANE_MIN_PX, Math.min(window.innerHeight - 160, chromePx() + listedPx()));
      var wanted = height === null || height === undefined ? defaultPx() : Number(height);
      var px = Math.round(Math.max(LANE_MIN_PX, Math.min(tallest, wanted)));
      laneHeight = height === null || height === undefined ? null : px;
      if (!folded) root.style.height = px + 'px';
      if (remember) kit.store('lane-height', laneHeight);
      drawnKey = '';
      queue();
    }
    function setFolded(value, remember) {
      folded = value;
      root.classList.toggle('folded', folded);
      if (folded) root.style.height = '';
      else setLaneHeight(laneHeight, false);
      foldButton.innerHTML = folded ? ICON.up : ICON.down;
      foldButton.title = folded ? 'Unfold the lane: the runs\' tracks and the zoom bar' : 'Fold the lane to its ruler: more room for the charts';
      foldButton.setAttribute('aria-label', foldButton.title);
      foldButton.setAttribute('aria-expanded', folded ? 'false' : 'true');
      if (remember) kit.store('lane-folded', folded);
      drawnKey = '';
      queue();
    }

    // a handle drag: ``onMove(startValue, dx, dy)`` while it moves, ``onDone()`` once released (it remembers the size)
    function dragHandle(handle, startValue, onMove, onDone) {
      handle.addEventListener('pointerdown', function (event) {
        if (event.button !== 0 || (handle === sizer && folded)) return;
        event.preventDefault();
        var start = { x: event.clientX, y: event.clientY }, id = event.pointerId;
        var from = startValue();
        handle.classList.add('dragging');
        try { handle.setPointerCapture(id); } catch (error) {}
        function move(moveEvent) { if (moveEvent.pointerId === id) onMove(from, moveEvent.clientX - start.x, moveEvent.clientY - start.y); }
        function up(upEvent) {
          if (upEvent.pointerId !== id) return;
          handle.classList.remove('dragging');
          handle.removeEventListener('pointermove', move);
          handle.removeEventListener('pointerup', up);
          handle.removeEventListener('pointercancel', up);
          onDone();
        }
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', up);
        handle.addEventListener('pointercancel', up);
      });
    }
    // the lane's top edge: up makes it taller
    dragHandle(sizer, function () { return root.offsetHeight; }, function (from, dx, dy) { setLaneHeight(from - dy, false); },
      function () { kit.store('lane-height', laneHeight); });
    sizer.addEventListener('dblclick', function () { setLaneHeight(null, true); });
    dragHandle(namesHandle, function () { return namesWidth; }, function (from, dx) { setNamesWidth(from + dx, false); },
      function () { kit.store('lane-names-width', namesWidth); });
    namesHandle.addEventListener('dblclick', function () { setNamesWidth(null, true); });

    /* ---------------- wiring ---------------- */

    setNamesWidth(kit.recall('lane-names-width', null), false);
    laneHeight = kit.recall('lane-height', null);
    setFolded(!!kit.recall('lane-folded', false), false);
    transport.onChange(function () { queue(); });
    page.unitRepaints.push(paintTitles);
    page.selectionRepaints.push(paintSelection);
    if (typeof ResizeObserver !== 'undefined') {
      var observer = new ResizeObserver(function () { drawnKey = ''; queue(); });
      observer.observe(hosts.sheet);
      observer.observe(root);
    }
    window.addEventListener('resize', function () {
      setNamesWidth(kit.recall('lane-names-width', null), false);
      if (!folded) setLaneHeight(laneHeight, false);
    });
    paintTitles();

    lane.el = root;
    lane.paint = paint;
    lane.queue = queue;
    lane.setView = setView;
    lane.reset = reset;
    lane.view = view;
    lane.jumpWorst = jumpWorst;
    lane.paintSelection = paintSelection;
    // the remembered sizes again (another scenario tab may have changed them)
    lane.applyShared = function () {
      setNamesWidth(kit.recall('lane-names-width', null), false);
      laneHeight = kit.recall('lane-height', null);
      setFolded(!!kit.recall('lane-folded', false), false);
    };
    return lane;
  }

  return { create: create };
})();
