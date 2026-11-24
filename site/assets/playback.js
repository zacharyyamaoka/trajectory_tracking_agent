// Saved runs, played back: loads site/data/playback/ (written by tools/build_site.py from the run records `tta
// evaluate` saved) and decodes it into the arrays the page draws. Nothing is simulated or scored here.
//
//   const index = await loadIndex();
//   const run = await loadRun(index, 'p5s-pass3', 'workspace-dev-001');
//   run.metrics.tool_track_rms_mm      // the ruler's own number, from the record
//   run.tool[i], run.frames.measured.pos[i][geom]   // what is drawn, computed natively at build time
//
// The format (read_playback in tools/build_site.py is the same decoder in Python; `shoot` checks the two agree):
// gzip(magic "TTAPLAY1" + uint32 LE header length + header JSON + arrays). Each array is integers, each column
// contiguous, as its first difference along time, in the narrowest signed int, its bytes split into planes (low
// first); value = (running sum + the task file's integers of `base`) x step.

const ROOT = new URL('../data/playback/', import.meta.url);
const MAGIC = 'TTAPLAY1';
const cache = new Map();

async function bytes(path) {
  const response = await fetch(new URL(path, ROOT));
  if (!response.ok) throw new Error(`could not load ${path} (${response.status})`);
  const raw = new Uint8Array(await response.arrayBuffer());
  // a server that sends the file with Content-Encoding: gzip has already inflated it
  if (raw[0] !== 0x1f || raw[1] !== 0x8b) return raw;
  const stream = new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function unpack(payload, spec) {
  const size = Number(spec.dtype.slice(1)) / 8;
  const count = spec.shape.reduce((a, b) => a * b, 1);
  const planes = payload.subarray(spec.offset, spec.offset + spec.bytes);
  const view = new DataView(new ArrayBuffer(count * size));
  for (let k = 0; k < count; k++) for (let b = 0; b < size; b++) view.setUint8(k * size + b, planes[b * count + k]);
  const read = size === 1 ? (k) => view.getInt8(k) : size === 2 ? (k) => view.getInt16(2 * k, true) : (k) => view.getInt32(4 * k, true);
  const rows = spec.shape[0];
  const columns = count / rows;
  const ints = new Float64Array(count); // row-major (N, columns); exact: every running sum is an integer < 2^53
  for (let c = 0; c < columns; c++) {
    let sum = 0;
    for (let i = 0; i < rows; i++) { sum += read(c * rows + i); ints[i * columns + c] = sum; }
  }
  return ints;
}

async function load(path, base) {
  const data = await bytes(path);
  if (new TextDecoder().decode(data.subarray(0, 8)) !== MAGIC) throw new Error(`${path} is not a playback file`);
  const length = new DataView(data.buffer, data.byteOffset + 8, 4).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(data.subarray(12, 12 + length)));
  const payload = data.subarray(12 + length);
  const ints = {};
  const arrays = {};
  for (const [name, spec] of Object.entries(header.arrays)) {
    const values = unpack(payload, spec);
    if (spec.base) { const b = base[spec.base]; for (let k = 0; k < values.length; k++) values[k] += b[k]; }
    ints[name] = values;
    arrays[name] = {values: Float64Array.from(values, (v) => v * spec.step), shape: spec.shape};
  }
  return {header, arrays, ints};
}

function rows({values, shape}, missing = null) {
  // (N, ...) as nested plain arrays: what the plots and the viewer index; a row with no measurement is null
  if (shape.length === 1) return Array.from(values, (v, i) => (missing?.[i] ? null : v));
  const width = values.length / shape[0];
  const out = [];
  for (let i = 0; i < shape[0]; i++) {
    if (missing?.[i]) { out.push(null); continue; }
    const row = Array.from(values.subarray(i * width, (i + 1) * width));
    if (shape.length === 3) {
      const inner = shape[2];
      out.push(Array.from({length: shape[1]}, (_, g) => row.slice(g * inner, (g + 1) * inner)));
    } else out.push(row);
  }
  return out;
}

export async function loadIndex() {
  const response = await fetch(new URL('index.json', ROOT));
  if (!response.ok) throw new Error(`could not load the playback index (${response.status})`);
  return response.json();
}

async function loadTask(index, taskId) {
  const key = `task:${taskId}`;
  if (!cache.has(key)) {
    const row = index.tasks.find((t) => t.id === taskId);
    if (!row) throw new Error(`task ${taskId} does not ship`);
    cache.set(key, load(row.file).then((file) => ({...file, row})));
  }
  return cache.get(key);
}

export async function loadRun(index, solutionId, taskId) {
  const solution = index.solutions.find((s) => s.id === solutionId);
  const entry = solution?.tasks[taskId];
  if (!entry) throw new Error(`${solutionId} on ${taskId} does not ship`);
  const task = await loadTask(index, taskId);
  const key = `run:${solutionId}:${taskId}`;
  if (!cache.has(key)) cache.set(key, load(entry.file, task.ints));
  const file = await cache.get(key);
  const h = file.header;
  const missing = new Uint8Array(h.samples);
  for (const [a, b] of h.missing) missing.fill(1, a, b + 1);
  const ta = task.arrays;
  const a = file.arrays;
  return {
    solution: solutionId,
    task: taskId,
    kind: task.header.kind,
    duration_s: task.header.duration_s,
    scored: solution.scored,
    meta: solution,
    dep: index.deployment,    // the joint names, caps, limits and the ruler's constants
    point_names: index.point_names,
    metrics: h.metrics,       // the ruler's numbers, as the record holds them
    gates: h.gates,
    notes: h.notes,
    explain: h.explain,       // computed natively at build time (tools/build_site.py _explain)
    stops: task.header.stops,
    fit_box: task.header.fit_box,
    t: rows(ta.t),
    moving: rows(ta.moving).map(Boolean),
    q_target: rows(ta.q_target),
    tool_target: rows(ta.tool_target),
    q: rows(a.q, missing),
    qd: rows(a.qd, missing),
    tau: rows(a.tau, missing),
    tool: rows(a.tool, missing),
    error_mm: rows(a.error_mm, missing),
    lowest: rows(a.lowest, missing),
    frames: {
      target: {pos: rows(ta.geom_pos), quat: rows(ta.geom_quat), tool: rows(ta.tool_target)},
      measured: {pos: rows(a.geom_pos, missing), quat: rows(a.geom_quat, missing), tool: rows(a.tool, missing)},
    },
  };
}

export function shippedTasks(index, solutionId) {
  const solution = index.solutions.find((s) => s.id === solutionId);
  return solution ? index.tasks.filter((t) => t.id in solution.tasks) : [];
}
