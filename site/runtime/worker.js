// The in-browser runtime: CPython (Pyodide) + MuJoCo (official WASM) in a module Web Worker, so the page stays
// responsive while the real pipeline runs.
//
//   const worker = new Worker(new URL('./runtime/worker.js', import.meta.url), {type: 'module'});
//   worker.postMessage({id, call: 'run', kwargs: {...}})   ->  {id, result} | {id, error}
//   status lines arrive as {status: '...'} and Python's stdout as {stdout: '...'}
//
// What runs here: the wheels in ../wheels (robot_msgs, robot_controllers, this repo's package; built from each
// repo's committed HEAD by tools/build_site.py, installed with micropip, no network dependency resolution), driven
// by ./pipeline.py. `import mujoco` resolves to ./mujoco_shim.py: the only non-original code, a thin layer over
// MuJoCo's own WASM build (see its docstring). Versions are pinned in ./manifest.json.

const here = (path) => new URL(path, import.meta.url).href;
const post = (message) => self.postMessage(message);
const status = (text) => post({status: text});

async function fetchText(path) {
  const response = await fetch(here(path));
  if (!response.ok) throw new Error(`could not fetch ${path} (${response.status})`);
  return response.text();
}

async function boot() {
  const started = performance.now();
  const manifest = JSON.parse(await fetchText('./manifest.json'));
  status(`loading Python ${manifest.pyodide} and MuJoCo ${manifest.mujoco_wasm}…`);
  const [{loadPyodide}, mujocoModule] = await Promise.all([
    import(`${manifest.pyodide_url}pyodide.mjs`),
    import(manifest.mujoco_url),
  ]);
  const [pyodide, mujoco] = await Promise.all([
    loadPyodide({indexURL: manifest.pyodide_url, stdout: (line) => post({stdout: line})}),
    mujocoModule.default(),
  ]);
  status('loading numpy…');
  await pyodide.loadPackage(['numpy', 'micropip']);
  pyodide.registerJsModule('_mujoco_js', mujoco);
  const [shim, fields, pipeline] = await Promise.all([
    fetchText('./mujoco_shim.py'), fetchText('./mujoco_fields.json'), fetchText('./pipeline.py'),
  ]);
  pyodide.FS.mkdirTree('/home/pyodide/runtime/mujoco');
  pyodide.FS.writeFile('/home/pyodide/runtime/mujoco/__init__.py', shim);
  pyodide.FS.writeFile('/home/pyodide/runtime/mujoco/mujoco_fields.json', fields);
  pyodide.FS.writeFile('/home/pyodide/runtime/pipeline.py', pipeline);
  status('installing robot_msgs and robot_controllers…');
  const micropip = pyodide.pyimport('micropip');
  for (const wheel of manifest.wheels) {
    await micropip.install.callKwargs(here(`../wheels/${wheel.file}`), {deps: false});
  }
  // The one platform gap besides MuJoCo: CPython on Emscripten has no per-thread CPU clock, and robot_controllers'
  // host loop times each tick with time.thread_time_ns. In this single-threaded worker the thread's clock is the
  // worker's monotonic clock, so it is aliased to perf_counter_ns. It changes no physics: it is the "compute_s"
  // the loop reports, and the send time only when a run sets include_compute (the parity run does not).
  // The repo files the ruler reads relative to its repo root (the dev tapes, station.json, every solution folder),
  // written at the same paths relative to the installed package, so dataset.py and population.py run unmodified.
  status('loading the dev tasks and the solutions…');
  const repoRoot = pyodide.runPython(
    'from trajectory_tracking_agent.ruler.dataset import REPO_ROOT\nstr(REPO_ROOT)');
  await Promise.all(manifest.repo_files.map(async ({path}) => {
    const response = await fetch(here(`../data/repo/${path}`));
    if (!response.ok) throw new Error(`could not fetch ${path} (${response.status})`);
    const target = `${repoRoot}/${path}`;
    pyodide.FS.mkdirTree(target.slice(0, target.lastIndexOf('/')));
    pyodide.FS.writeFile(target, new Uint8Array(await response.arrayBuffer()));
  }));
  pyodide.runPython(`
import sys, time
if not hasattr(time, "thread_time_ns"):
    time.thread_time_ns = time.perf_counter_ns
    time.thread_time = time.perf_counter
sys.path.insert(0, "/home/pyodide/runtime")
import mujoco, pipeline
`);
  const bootSeconds = (performance.now() - started) / 1000;
  status(`ready (${bootSeconds.toFixed(1)} s)`);
  return {pyodide, bootSeconds, manifest};
}

const ready = boot().catch((error) => {
  post({status: `failed: ${error.message}`, fatal: String(error.stack || error)});
  throw error;
});

self.onmessage = async (event) => {
  const {id, call, kwargs = {}, exec} = event.data;
  try {
    const {pyodide, bootSeconds} = await ready;
    if (exec !== undefined) {  // a console for debugging: run Python here, get its last expression's repr back
      post({id, result: {repr: String(pyodide.runPython(`repr(eval(compile(${JSON.stringify(exec)}, '<page>', 'eval')))`))}});
      return;
    }
    const fn = pyodide.globals.get('pipeline')[call];
    if (!fn) throw new Error(`pipeline has no ${call}`);
    const started = performance.now();
    const raw = fn.callKwargs(kwargs);
    // JSON over the boundary: plain lists and floats, exactly as Python's json writes them (repr round-trips)
    const json = pyodide.globals.get('pipeline').dumps(raw);
    raw.destroy?.();
    const result = JSON.parse(json);
    result.browser = {boot_s: bootSeconds, call_s: (performance.now() - started) / 1000};
    post({id, result});
  } catch (error) {
    post({id, error: String(error.message || error)});
  }
};
