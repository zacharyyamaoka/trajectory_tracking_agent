/* Shared plumbing for the five proposals: the fixture, the ruler's labels, formatting, the solution picker,
   the guide strip (manual walkthrough) and the inputs footer. No proposal-specific drawing lives here.
   WHY outputs only (Zach, 2026-11-24): every view reads the target, the measured joint states, the applied
   torques, the deployment and the ruler; never a controller's internals, so any solution renders the same way. */
(function () {
  const F = window.FIXTURE;
  if (!F) { document.body.textContent = "Missing ../_data/fixture.js"; return; }

  const pop = F.population.slice().sort((a, b) => a.rank - b.rank);
  const traced = pop.filter((s) => F.traces[s.id]);  // the solutions whose featured-task run ships in full
  const byId = Object.fromEntries(pop.map((s) => [s.id, s]));

  function mask(intervals, n) {
    const m = new Uint8Array(n);
    for (const [a, b] of intervals) for (let i = a; i <= b; i++) m[i] = 1;
    return m;
  }

  /* number formatting: significant figures, never scientific; mm values keep their unit */
  function sig(v, n = 3) {
    if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
    if (v === 0) return "0";
    const a = Math.abs(v);
    const d = Math.max(0, n - 1 - Math.floor(Math.log10(a)));
    return v.toFixed(Math.min(d, 6));
  }
  const fmt = {
    mm: (v) => `${sig(v, 3)} mm`,
    pct: (v) => `${v < 0.01 && v > 0 ? sig(v, 2) : v.toFixed(v >= 10 ? 1 : 2)} %`,
    ms: (v) => `${Math.abs(v) < 0.05 ? "0.0" : v.toFixed(1)} ms`,
    deg: (v) => `${sig(v, 3)}°`,
    s: (v) => `${v.toFixed(2)} s`,
    int: (v) => v.toLocaleString("en-US"),
    sig,
  };

  const T = F.thresholds;
  /* the ruler, in plain words with the code id beside it (OBJECTIVES §4) */
  const OBJECTIVE = {
    id: "tool_track_rms_mm", label: "Tool tracking error", short: "tracking error", unit: "mm RMS",
    how: "RMS distance between the measured and the target tool point at the same instant, over the moving samples; the objective is the median over dev tasks. Lower is better.",
  };
  const GATES = [
    { id: "completed", label: "Completed", short: "completed",
      rule: "no crash or NaN, reaches the end and settles",
      value: (k) => k.completed, show: (k) => (k.completed ? "finished, settled" : "did not settle") },
    { id: "stop_error_max_mm", label: "Stop error", short: "stop error",
      rule: `≤ ${T.stop_error_max_mm} mm at every stop (mean of its last ${T.stop_tail_s} s)`,
      value: (k) => k.stop_error_max_mm, show: (k) => `${sig(k.stop_error_max_mm, 3)} mm`, limit: T.stop_error_max_mm, unit: "mm" },
    { id: "saturation_share_pct", label: "Torque saturation", short: "saturation",
      rule: `≤ ${T.saturation_share_pct} % of physics samples (4 kHz) with any joint ≥ ${Math.round(T.sat_fraction * 100)} % of its torque cap`,
      value: (k) => k.saturation_share_pct, show: (k) => fmt.pct(k.saturation_share_pct), limit: T.saturation_share_pct, unit: "%" },
    { id: "limit_violations", label: "Joint limits", short: "limits",
      rule: `0 physics samples (4 kHz) outside a position limit or above ${T.vel_margin} × a velocity limit`,
      value: (k) => k.limit_violations, show: (k) => `${fmt.int(k.limit_violations)} samples` },
    { id: "floor_clearance", label: "Floor clearance", short: "floor",
      rule: "0 physics samples (4 kHz) with the tool point or any link origin below the floor",
      value: (k) => k.floor_clearance, show: (k) => `${fmt.int(k.floor_clearance)} samples` },
  ];
  const DIAGNOSTICS = [
    { id: "tool_lag_ms", label: "Tool lag", show: (k) => fmt.ms(k.tool_lag_ms),
      how: "how late the measured motion runs behind the target (joint velocities cross-correlated, refined on position RMS)" },
    { id: "joint_track_rms_deg", label: "Joint tracking (worst joint)", show: (k) => fmt.deg(k.joint_track_rms_deg),
      how: "RMS joint angle error over the moving samples, the worst of the six joints" },
    { id: "energy_j", label: "Motor energy", show: (k) => `${k.energy_j.toFixed(1)} J`,
      how: "positive mechanical work: the sum over joints of torque × velocity where it is positive, integrated over time" },
  ];

  const Kit = {
    F, pop, traced, byId, mask, failingId: F.featured_failing, bestId: traced[0].id, fmt, sig, OBJECTIVE, GATES, DIAGNOSTICS,
    trace: (id) => F.traces[id],
    best: () => pop.find((s) => s.admissible) || null,
    time: (tr, i) => tr.t0 + i * tr.dt,
    /* the decimated sample nearest full-rate index i */
    near: (tr, i) => Math.min(tr.idx.length - 1, Math.max(0, Math.round(i / tr.every))),
    failed: (tr) => GATES.filter((g) => !tr.gates[g.id]),
    css: (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim(),
  };

  /* sequential colour for an error fraction 0..1 (css tokens --err-0..4) */
  Kit.errColor = function (f) {
    const stops = [0, 1, 2, 3, 4].map((i) => Kit.css(`--err-${i}`));
    const x = Math.max(0, Math.min(1, f)) * 4;
    const i = Math.min(3, Math.floor(x));
    return mix(stops[i], stops[i + 1], x - i);
  };
  function hex(c) {
    c = c.replace("#", "");
    if (c.length === 3) c = c.split("").map((x) => x + x).join("");
    return [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16));
  }
  function mix(a, b, t) {
    const A = hex(a), B = hex(b);
    return "#" + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join("");
  }
  Kit.mix = mix;

  /* ── state in the URL hash: #s=<solution>&step=<n>&... so every state is linkable and screenshot-able ── */
  Kit.hash = function () {
    const out = {};
    for (const part of location.hash.replace(/^#/, "").split("&")) {
      if (!part) continue;
      const [k, v] = part.split("=");
      out[decodeURIComponent(k)] = decodeURIComponent(v || "");
    }
    return out;
  };

  /* ── theme toggle ── */
  Kit.theme = function (btn, onChange) {
    const root = document.documentElement;
    const h = Kit.hash();
    if (h.theme) root.dataset.theme = h.theme;
    const label = () => {
      const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      btn.textContent = dark ? "☀ Light" : "☾ Dark";
      return dark;
    };
    label();
    btn.addEventListener("click", () => {
      const dark = label();
      root.dataset.theme = dark ? "light" : "dark";
      label();
      onChange && onChange();
    });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { label(); onChange && onChange(); });
  };

  /* ── solution picker ── */
  Kit.picker = function (el, current, onPick) {
    el.innerHTML = `<span class="lbl">Solution</span>` + traced.map((s) =>
      `<button class="chip" data-sol="${s.id}" aria-pressed="${s.id === current}" title="rank ${s.rank} · ${s.admissible ? "admissible" : "not admissible"}">` +
      `<span class="dot ${s.admissible ? "" : "bad"}"></span><span class="rk">#${s.rank}</span>${s.id}</button>`).join("");
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-sol]");
      if (b) onPick(b.dataset.sol, true);
    });
    return (id) => el.querySelectorAll("[data-sol]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sol === id)));
  };

  /* ── guide strip: Back / Next / step chips / caption; drives the same states as the direct controls ── */
  Kit.guide = function (el, steps, apply) {
    let cur = -1;
    el.innerHTML = `<span class="gt">Guide</span><button class="iconbtn" data-g="back" aria-label="Previous step">← Back</button>` +
      `<span class="steps">${steps.map((s, i) => `<button data-g="${i}" title="${s.label}">${i + 1}</button>`).join("")}</span>` +
      `<button class="iconbtn" data-g="next" aria-label="Next step">Next →</button><span class="cap" aria-live="polite"></span>`;
    const cap = el.querySelector(".cap");
    function show(i, run = true) {
      cur = i;
      el.querySelectorAll(".steps button").forEach((b, j) => (j === i ? b.setAttribute("aria-current", "step") : b.removeAttribute("aria-current")));
      document.querySelectorAll(".guide-target").forEach((n) => n.classList.remove("guide-target"));
      if (i < 0) { cap.innerHTML = "Step through the view, or click any score directly."; return; }
      const s = steps[i];
      cap.innerHTML = `<b>${i + 1}. ${s.label}</b>${s.caption}`;
      if (run) apply(s);
      const t = s.target && document.querySelector(s.target);
      if (t) {
        t.classList.add("guide-target");
        const b = t.getBoundingClientRect();
        if (b.top < 0 || b.bottom > innerHeight) t.scrollIntoView({ block: b.height > innerHeight * 0.7 ? "start" : "center" });
      }
    }
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-g]");
      if (!b) return;
      const g = b.dataset.g;
      if (g === "back") show(Math.max(0, cur - 1));
      else if (g === "next") show(Math.min(steps.length - 1, cur + 1));
      else show(+g);
    });
    return {
      show,
      /* a direct control moved the view: light the step whose state matches, or none */
      sync(match) {
        const i = steps.findIndex(match);
        show(i, false);
      },
      get current() { return cur; },
    };
  };

  /* ── inputs footer ── */
  Kit.footer = function (el, { reads, generalises, extra = "" }) {
    const tr = F.traces[traced[0].id];
    el.innerHTML = `
      <div><h3>This view reads (black-box outputs only)</h3><ul>${F.inputs.filter(([k]) => reads.includes(k)).map(([k, v]) => `<li><b>${k}</b>: ${v}</li>`).join("")}</ul>
        <p style="margin:6px 0 0">Never read: ${F.not_used}. Any solution renders through the same view.</p></div>
      <div><h3>How it generalises</h3><p style="margin:0">${generalises}</p></div>
      <div><h3>Data shown</h3><p style="margin:0">${F.deployment_title} · ${F.dataset} · ${pop.length} solutions from <span class="src">ledger.jsonl</span> (${F.ledger_rows} rows) and <span class="src">solutions/*/scorecard.json</span>. Traces: task <code>${F.featured_task}</code> for ${traced.map((s) => s.id).join(", ")}, from <span class="src">${tr.source}</span> and its siblings. Metrics and gates: ${F.ruler_source}.</p>
        <p style="margin:6px 0 0">Samples are drawn on the target's 100 Hz grid; saturation, limits and floor are scored on every 4 kHz physics sample, so their counts are quoted from the scorecard and the 100 Hz flags only show where.</p>${extra}</div>`;
  };

  window.Kit = Kit;
})();
