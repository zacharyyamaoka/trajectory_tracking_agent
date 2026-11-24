// A plain stick-and-capsule UR5e from forward-kinematics points (base, six link origins, tool point), Z up, mm in.
// Measured arm solid, target arm as a ghost. Pages add their own evidence into named layers.
// Rendering is on demand (no animation loop), so headless captures are deterministic.
// WHY a classic script taking THREE as an argument: a local ES module cannot be imported from file:// (CORS), so
// the page's inline module imports three.js from the CDN and hands it over; the page then also opens offline-ish
// from disk, not only over http.
(function () {
function armModule(THREE, OrbitControls) {

const RADII = [0.05, 0.045, 0.04, 0.034, 0.03, 0.028, 0.012]; // segment i: point i -> i+1 (m)
const MM = 0.001;
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const v3 = (p) => new THREE.Vector3(p[0] * MM, p[1] * MM, p[2] * MM);

function createArmView(container, opts = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  container.appendChild(renderer.domElement);
  renderer.domElement.style.display = "block";
  const overlay = document.createElement("div");
  overlay.className = "arm3d-labels";
  Object.assign(overlay.style, { position: "absolute", inset: "0", pointerEvents: "none", overflow: "hidden" });
  container.style.position = container.style.position || "relative";
  container.appendChild(overlay);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(opts.fov || 35, 1, 0.01, 50);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false;
  controls.addEventListener("change", () => render());

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a8a, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(1.5, -2, 3);
  scene.add(sun);

  // floor: a grid in the XY plane at z = 0 (the ruler's floor plane)
  const floor = new THREE.Group();
  scene.add(floor);
  const floorPlane = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 2.4), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.35, depthWrite: false }));
  floor.add(floorPlane);
  let grid = null;

  const unitCyl = new THREE.CylinderGeometry(1, 1, 1, 20, 1);
  const unitSph = new THREE.SphereGeometry(1, 20, 14);
  function makeArm(ghost) {
    const mats = RADII.map(() => new THREE.MeshStandardMaterial({ roughness: 0.6, metalness: 0.05, transparent: ghost, opacity: ghost ? 0.28 : 1, depthWrite: !ghost }));
    const segs = RADII.map((r, i) => new THREE.Mesh(unitCyl, mats[i]));
    const jmats = [0, 1, 2, 3, 4, 5].map(() => new THREE.MeshStandardMaterial({ roughness: 0.5, transparent: ghost, opacity: ghost ? 0.28 : 1, depthWrite: !ghost }));
    const joints = jmats.map((m) => new THREE.Mesh(unitSph, m));
    const g = new THREE.Group();
    segs.forEach((s) => g.add(s));
    joints.forEach((j) => g.add(j));
    scene.add(g);
    return { g, segs, joints, mats, jmats };
  }
  const measured = makeArm(false);
  const target = makeArm(true);
  const up = new THREE.Vector3(0, 1, 0);

  function pose(arm, pts) {
    for (let i = 0; i < 7; i++) {
      const a = v3(pts[i]), b = v3(pts[i + 1]);
      const d = b.clone().sub(a);
      const len = Math.max(1e-6, d.length());
      const s = arm.segs[i];
      s.position.copy(a).add(b).multiplyScalar(0.5);
      s.scale.set(RADII[i], len, RADII[i]);
      s.quaternion.setFromUnitVectors(up, d.normalize());
    }
    for (let j = 0; j < 6; j++) {
      const r = RADII[Math.min(j + 1, 5)] * 1.12;
      arm.joints[j].position.copy(v3(pts[j + 1]));
      arm.joints[j].scale.setScalar(r);
    }
  }

  const layers = {};
  function layer(name) {
    if (!layers[name]) { layers[name] = new THREE.Group(); scene.add(layers[name]); }
    return layers[name];
  }
  function clear(name) {
    const g = layer(name);
    for (const c of [...g.children]) { g.remove(c); c.geometry?.dispose?.(); }
    return g;
  }

  // helpers the pages use to draw evidence
  function line(points, color, { opacity = 1, dashed = false } = {}) {
    const geo = new THREE.BufferGeometry().setFromPoints(points.map(v3));
    const mat = dashed
      ? new THREE.LineDashedMaterial({ color, dashSize: 0.012, gapSize: 0.008, transparent: opacity < 1, opacity })
      : new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity });
    const l = new THREE.Line(geo, mat);
    if (dashed) l.computeLineDistances();
    return l;
  }
  function colorLine(points, colors) {
    const geo = new THREE.BufferGeometry().setFromPoints(points.map(v3));
    const col = new Float32Array(points.length * 3);
    colors.forEach((c, i) => { const cc = new THREE.Color(c); col.set([cc.r, cc.g, cc.b], i * 3); });
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    return new THREE.Line(geo, new THREE.LineBasicMaterial({ vertexColors: true }));
  }
  function segments(pairs, colors, { opacity = 1 } = {}) {
    const pos = new Float32Array(pairs.length * 6), col = new Float32Array(pairs.length * 6);
    pairs.forEach(([a, b], i) => {
      pos.set([a[0] * MM, a[1] * MM, a[2] * MM, b[0] * MM, b[1] * MM, b[2] * MM], i * 6);
      const c = new THREE.Color(Array.isArray(colors) ? colors[i] : colors);
      col.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6);
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    return new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: opacity < 1, opacity }));
  }
  function tube(points, colors, radiusMm = 3) {
    const curve = new THREE.CatmullRomCurve3(points.map(v3), false, "centripetal");
    const n = points.length - 1, radial = 8;
    const geo = new THREE.TubeGeometry(curve, n, radiusMm * MM, radial, false);
    const col = new Float32Array(geo.attributes.position.count * 3);
    for (let i = 0; i <= n; i++) {
      const c = new THREE.Color(colors[Math.min(i, colors.length - 1)]);
      for (let j = 0; j <= radial; j++) col.set([c.r, c.g, c.b], (i * (radial + 1) + j) * 3);
    }
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    return new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.7 }));
  }
  function sphere(p, radiusMm, color, { opacity = 1, wire = false } = {}) {
    const m = new THREE.Mesh(unitSph, new THREE.MeshStandardMaterial({ color, transparent: opacity < 1, opacity, wireframe: wire, depthWrite: opacity >= 1 }));
    m.position.copy(v3(p));
    m.scale.setScalar(radiusMm * MM);
    return m;
  }

  // HTML labels pinned to 3D points (crisp text, themed by CSS)
  let labels = [];
  function setLabels(list) { labels = list; overlay.innerHTML = list.map((l) => `<div class="lbl3d ${l.cls || ""}">${l.html}</div>`).join(""); }
  function placeLabels() {
    const w = renderer.domElement.clientWidth, h = renderer.domElement.clientHeight;
    [...overlay.children].forEach((el, i) => {
      const p = v3(labels[i].pos).project(camera);
      const vis = p.z < 1 && p.x > -1.2 && p.x < 1.2 && p.y > -1.2 && p.y < 1.2;
      el.style.display = vis ? "block" : "none";
      el.style.transform = `translate(${((p.x + 1) / 2) * w}px, ${((1 - p.y) / 2) * h}px) translate(${labels[i].dx ?? 8}px, ${labels[i].dy ?? -50}%)`;
    });
  }

  function applyTheme() {
    const ink = css("--measured"), ghost = css("--target"), line = css("--line"), bg = css("--surface-2");
    measured.mats.forEach((m) => m.color.set(ink === "#ecebe7" ? "#c9c8c4" : "#3a3c40"));
    measured.jmats.forEach((m) => m.color.set(ink === "#ecebe7" ? "#e8e7e2" : "#24262a"));
    target.mats.forEach((m) => m.color.set(ghost));
    target.jmats.forEach((m) => m.color.set(ghost));
    floorPlane.material.color.set(bg);
    if (grid) floor.remove(grid);
    grid = new THREE.GridHelper(2.4, 24, line, line);
    grid.rotation.x = Math.PI / 2;
    grid.material.transparent = true;
    grid.material.opacity = 0.7;
    floor.add(grid);
  }
  applyTheme();

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = w + "px";
    renderer.domElement.style.height = h + "px";
    camera.aspect = w / h;
    if (shiftFrac) camera.setViewOffset(w, h, -w * shiftFrac, 0, w, h); else camera.clearViewOffset();
    camera.updateProjectionMatrix();
    render();
  }
  new ResizeObserver(resize).observe(container);

  let shiftFrac = 0;
  /* move the picture right by a fraction of the width (room for an overlay card on the left) */
  function shift(f) { shiftFrac = f; resize(); }
  function render() {
    renderer.render(scene, camera);
    placeLabels();
  }

  /* frame a set of points (mm) from a three-quarter view */
  function fit(pointsMm, dir = [0.62, -0.7, 0.42], pad = 1.25) {
    const box = new THREE.Box3().setFromPoints(pointsMm.map(v3));
    const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() / 2;
    const aspect = container.clientWidth / Math.max(1, container.clientHeight) || camera.aspect;
    const vfov = (camera.fov * Math.PI) / 180, hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect * (1 - 2 * shiftFrac));
    const dist = (r * pad) / Math.sin(Math.min(vfov, hfov) / 2);
    const d = new THREE.Vector3(...dir).normalize().multiplyScalar(dist);
    controls.target.copy(c);
    camera.position.copy(c).add(d);
    controls.update();
    render();
  }
  function look(targetMm, fromMm) {
    controls.target.copy(v3(targetMm));
    camera.position.copy(v3(fromMm));
    controls.update();
    render();
  }

  return {
    THREE, scene, camera, renderer, controls, measured, target, floor,
    setPose(m, t) { pose(measured, m); if (t) pose(target, t); target.g.visible = !!t; },
    segColors(colors) { measured.mats.forEach((m, i) => m.color.set(colors ? colors[i] : css("--measured") === "#ecebe7" ? "#c9c8c4" : "#3a3c40")); },
    jointColors(colors) { measured.jmats.forEach((m, i) => m.color.set(colors ? colors[i] : css("--measured") === "#ecebe7" ? "#e8e7e2" : "#24262a")); },
    layer, clear, line, colorLine, segments, tube, sphere, setLabels, render, resize, look, fit, shift, applyTheme,
  };
}
return { createArmView, v3 };
}
window.ArmView = { create: (THREE, OrbitControls, container, opts) => armModule(THREE, OrbitControls).createArmView(container, opts) };
})();
