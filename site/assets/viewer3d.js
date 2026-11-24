// The 3D view: the UR5e drawn from MuJoCo's own geom poses, the measured arm solid and the target arm as a ghost.
//
//   const viewer = await createViewer(container);
//   viewer.setGeoms(render.geoms);                       // the model's capsules (type, size, body)
//   viewer.setArm('target', frames, t); viewer.setArm('measured', frames, t);
//   viewer.setPaths({target: [[x, y, z], ...], measured: [...]});
//   viewer.setTime(1.25);                                // every arm, path marker and overlay follows
//   viewer.setOverlay({build(ctx) {...; return {update(t) {...}, dispose() {...}}}, note: '...'});
//
// Nothing here computes kinematics: every pose is a geom_xpos / geom_xmat row the Python side got from
// mujoco.mj_kinematics. The geom-per-object drawing (MuJoCo is Z-up, so everything lives in a group rotated -90° about
// x; each object's matrix is set from geom_xpos + row-major geom_xmat) follows robotdescription.com's gallery viewer
// (github.com/zacharyyamaoka/robotdescription-website, site/gallery/mujoco.js, MIT), adapted.

const THREE_URL = 'https://cdn.jsdelivr.net/npm/three@0.186.1/+esm';
const ORBIT_URL = 'https://cdn.jsdelivr.net/npm/three@0.186.1/examples/jsm/controls/OrbitControls.js/+esm';
const GEOM = {PLANE: 0, SPHERE: 2, CAPSULE: 3, ELLIPSOID: 4, CYLINDER: 5, BOX: 6};

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
}

function frameIndex(times, t) {
  // the last frame at or before t (binary search)
  let lo = 0;
  let hi = times.length - 1;
  if (!times.length) return -1;
  if (t <= times[0]) return 0;
  if (t >= times[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) lo = mid; else hi = mid;
  }
  return lo;
}

export async function createViewer(container) {
  const [THREE, {OrbitControls}] = await Promise.all([import(THREE_URL), import(ORBIT_URL)]);
  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, preserveDrawingBuffer: true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 50);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;

  const world = new THREE.Group(); // MuJoCo coordinates (Z-up) inside
  world.rotation.x = -Math.PI / 2;
  scene.add(world);
  const hemi = new THREE.HemisphereLight(0xffffff, 0x8a8f96, 1.9);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(2, 4, 3);
  scene.add(sun);

  const floorGroup = new THREE.Group();
  world.add(floorGroup);
  let grid = null;
  let floorDisc = null;

  function buildFloor() {
    if (grid) { floorGroup.remove(grid); grid.geometry.dispose(); }
    if (floorDisc) { floorGroup.remove(floorDisc); floorDisc.geometry.dispose(); }
    const dark = matchMedia('(prefers-color-scheme: dark)').matches;
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 256;
    const g = canvas.getContext('2d');
    const fade = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    const ink = dark ? '120,130,145' : '90,100,115';
    fade.addColorStop(0, `rgba(${ink},0.16)`);
    fade.addColorStop(0.55, `rgba(${ink},0.07)`);
    fade.addColorStop(1, `rgba(${ink},0)`);
    g.fillStyle = fade;
    g.fillRect(0, 0, 256, 256);
    const texture = new THREE.CanvasTexture(canvas);
    floorDisc = new THREE.Mesh(new THREE.PlaneGeometry(3, 3),
      new THREE.MeshBasicMaterial({map: texture, transparent: true, depthWrite: false}));
    floorDisc.position.z = -0.0015;
    floorGroup.add(floorDisc);
    grid = new THREE.GridHelper(2.4, 24, dark ? 0x3a4049 : 0xc9ccc9, dark ? 0x2a2f36 : 0xdfe1de);
    grid.material.transparent = true;
    grid.material.opacity = 0.7;
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -0.001;
    floorGroup.add(grid);
  }
  buildFloor();

  const state = {
    geoms: null,
    arms: {},           // name -> {objects: [...], frames, times}
    paths: {},          // name -> THREE.Line
    markers: {},        // name -> sphere at the current tool point
    overlay: null,      // {update(t), dispose()}
    time: 0,
    dirty: true,
  };

  function material(kind) {
    if (kind === 'target') {
      return new THREE.MeshStandardMaterial({color: new THREE.Color(css('--target')), transparent: true, opacity: 0.2,
        depthWrite: false, roughness: 0.9});
    }
    return new THREE.MeshStandardMaterial({color: armColor(), roughness: 0.5, metalness: 0.05});
  }

  function armColor() {
    // the measured arm: the accent, lightened toward the surface so a metre of it doesn't shout
    return new THREE.Color(css('--accent')).lerp(new THREE.Color(css('--surface')), 0.35);
  }

  // WHY a wider ghost: the target and the measured arm differ by millimetres, so a same-size ghost hides inside the
  // solid arm; drawn 1.35x as thick it reads as a glass sleeve, and any real offset still shows
  const GHOST_THICKNESS = 1.35;

  function geomGeometry(type, size, thickness = 1) {
    switch (type) {
      case GEOM.CAPSULE: return new THREE.CapsuleGeometry(thickness * size[0], 2 * size[1], 8, 20).rotateX(Math.PI / 2);
      case GEOM.CYLINDER: return new THREE.CylinderGeometry(thickness * size[0], thickness * size[0], 2 * size[1], 24).rotateX(Math.PI / 2);
      case GEOM.SPHERE: return new THREE.SphereGeometry(thickness * size[0], 20, 14);
      case GEOM.BOX: return new THREE.BoxGeometry(2 * size[0], 2 * size[1], 2 * size[2]);
      default: return null;
    }
  }

  function makeArm(name) {
    const old = state.arms[name];
    if (old) for (const object of old.objects) { world.remove(object); object.geometry?.dispose(); }
    const objects = [];
    const {type, size, body} = state.geoms;
    for (let g = 0; g < type.length; g++) {
      const geometry = geomGeometry(type[g], size[g], name === 'target' ? GHOST_THICKNESS : 1);
      if (!geometry) { objects.push(null); continue; }
      const mesh = new THREE.Mesh(geometry, material(name));
      mesh.matrixAutoUpdate = false;
      mesh.userData = {body: body[g], baseColor: mesh.material.color.clone(), kind: name};
      mesh.renderOrder = name === 'target' ? 2 : 1;
      world.add(mesh);
      objects.push(mesh);
    }
    state.arms[name] = {objects, frames: null, times: []};
  }

  const matrix = new THREE.Matrix4();
  function poseArm(name, t) {
    const arm = state.arms[name];
    if (!arm || !arm.frames) return;
    const k = frameIndex(arm.times, t);
    if (k < 0) return;
    const pos = arm.frames.geom_xpos[k];
    const rot = arm.frames.geom_xmat[k];
    arm.objects.forEach((object, g) => {
      if (!object) return;
      const p = pos[g];
      const m = rot[g];
      matrix.set(m[0], m[1], m[2], p[0], m[3], m[4], m[5], p[1], m[6], m[7], m[8], p[2], 0, 0, 0, 1);
      object.matrix.copy(matrix);
    });
    const marker = state.markers[name];
    if (marker) {
      const tool = arm.frames.tool[k];
      marker.position.set(tool[0], tool[1], tool[2]);
    }
  }

  function line(points, color, {dashed = false, width = 1, opacity = 1} = {}) {
    const geometry = new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(p[0], p[1], p[2])));
    const mat = dashed
      ? new THREE.LineDashedMaterial({color, dashSize: 0.012, gapSize: 0.008, transparent: opacity < 1, opacity})
      : new THREE.LineBasicMaterial({color, linewidth: width, transparent: opacity < 1, opacity});
    // WHY no depth test: a path or an explanation is what the view is for; drawn over the arm, never hidden in it
    mat.depthTest = false;
    const object = new THREE.Line(geometry, mat);
    object.renderOrder = 5;
    if (dashed) object.computeLineDistances();
    return object;
  }

  function sphere(radius, color, opacity = 1) {
    return new THREE.Mesh(new THREE.SphereGeometry(radius, 18, 12),
      new THREE.MeshBasicMaterial({color, transparent: opacity < 1, opacity, depthTest: opacity >= 1}));
  }

  function label(text, color) {
    // a camera-facing text sprite (canvas texture): for the few numbers an explanation pins in space
    const canvas = document.createElement('canvas');
    const scale = 2;
    const ctx = canvas.getContext('2d');
    ctx.font = `${13 * scale}px system-ui, sans-serif`;
    const width = Math.ceil(ctx.measureText(text).width) + 14 * scale;
    canvas.width = width;
    canvas.height = 24 * scale;
    ctx.font = `${13 * scale}px system-ui, sans-serif`;
    ctx.fillStyle = css('--surface');
    ctx.globalAlpha = 0.9;
    ctx.beginPath();
    ctx.roundRect(0, 0, canvas.width, canvas.height, 6 * scale);
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.fillStyle = color;
    ctx.textBaseline = 'middle';
    ctx.fillText(text, 7 * scale, canvas.height / 2);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture, depthTest: false, transparent: true}));
    const h = 0.045;
    sprite.scale.set(h * canvas.width / canvas.height, h, 1);
    sprite.renderOrder = 10;
    return sprite;
  }

  function disposeTree(object) {
    object.traverse((child) => {
      child.geometry?.dispose();
      const mats = Array.isArray(child.material) ? child.material : [child.material];
      for (const mat of mats) { mat?.map?.dispose(); mat?.dispose(); }
    });
  }

  function resize() {
    const {clientWidth: w, clientHeight: h} = container;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    state.dirty = true;
  }
  new ResizeObserver(resize).observe(container);

  function fit(points, {minRadius = 0.5, scale = 1.12} = {}) {
    // look at the work: every point given (the arm's body origins over the clip, the tool path) and the base, from a
    // three-quarter view on the side the arm works (three is Y-up: MuJoCo (x, y, z) -> three (x, z, -y))
    const box = new THREE.Box3();
    if (minRadius >= 0.5) box.expandByPoint(new THREE.Vector3(0, 0, 0)); // the whole arm: keep the base in view
    for (const p of points) box.expandByPoint(new THREE.Vector3(p[0], p[2], -p[1]));
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(minRadius, box.getSize(new THREE.Vector3()).length() / 2);
    const fov = (Math.min(camera.fov, camera.fov * camera.aspect) * Math.PI) / 360;
    const distance = (radius / Math.sin(fov)) * scale;
    const side = Math.atan2(center.z, center.x); // the arm's working side, seen from 50° around and a little above
    const azimuth = side + (50 * Math.PI) / 180;
    const direction = new THREE.Vector3(Math.cos(azimuth), 0.45, Math.sin(azimuth)).normalize();
    camera.position.copy(center).addScaledVector(direction, distance);
    controls.target.copy(center);
    controls.update();
    state.dirty = true;
  }

  function tick() {
    if (controls.update()) state.dirty = true;
    if (state.dirty) {
      renderer.render(scene, camera);
      state.dirty = false;
    }
    requestAnimationFrame(tick);
  }
  controls.addEventListener('change', () => { state.dirty = true; });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    buildFloor();
    for (const [name, arm] of Object.entries(state.arms)) {
      for (const object of arm.objects) {
        if (!object) continue;
        object.material.color.copy(name === 'target' ? new THREE.Color(css('--target')) : armColor());
        object.userData.baseColor = object.material.color.clone();
      }
    }
    state.dirty = true;
  });
  resize();
  requestAnimationFrame(tick);

  const viewer = {
    THREE,
    world,
    css,
    frameIndex,
    canvas: renderer.domElement,
    get time() { return state.time; },
    setGeoms(geoms) {
      state.geoms = geoms;
      makeArm('target');
      makeArm('measured');
      for (const name of ['target', 'measured']) {
        state.markers[name]?.removeFromParent();
        state.markers[name] = sphere(0.009, new THREE.Color(css(name === 'target' ? '--target' : '--accent')));
        state.markers[name].material.depthTest = false;
        state.markers[name].renderOrder = 6;
        state.markers[name].visible = false;
        world.add(state.markers[name]);
      }
    },
    setArm(name, frames, times) {
      const arm = state.arms[name];
      arm.frames = frames;
      arm.times = times || [];
      const visible = Boolean(frames);
      for (const object of arm.objects) if (object) object.visible = visible;
      state.markers[name].visible = visible;
      poseArm(name, state.time);
      state.dirty = true;
    },
    setPaths(paths) {
      for (const [name, object] of Object.entries(state.paths)) { world.remove(object); disposeTree(object); }
      state.paths = {};
      if (paths.target) {
        state.paths.target = line(paths.target, new THREE.Color(css('--target')), {dashed: true});
        world.add(state.paths.target);
      }
      if (paths.measured) {
        state.paths.measured = line(paths.measured, new THREE.Color(css('--accent')), {opacity: 0.85});
        world.add(state.paths.measured);
      }
      state.dirty = true;
    },
    fit,
    setTime(t) {
      state.time = t;
      poseArm('target', t);
      poseArm('measured', t);
      state.overlay?.update?.(t);
      state.dirty = true;
    },
    setOverlay(spec) {
      if (state.overlay) {
        state.overlay.dispose?.();
        if (state.overlay.group) { world.remove(state.overlay.group); disposeTree(state.overlay.group); }
      }
      this.tint(null);
      state.overlay = null;
      const note = container.querySelector('.overlay-note');
      if (note) note.textContent = spec?.note || '';
      if (spec?.build) {
        const group = new THREE.Group();
        group.renderOrder = 7;
        world.add(group);
        const ctx = {THREE, group, world, css, line, sphere, label, frameIndex, viewer};
        state.overlay = {group, ...(spec.build(ctx) || {})};
        // an explanation draws over the arm (see line()): every material in it skips the depth test
        group.traverse((child) => {
          const mats = Array.isArray(child.material) ? child.material : [child.material];
          for (const mat of mats) if (mat) mat.depthTest = false;
          child.renderOrder = 7;
        });
        state.overlay.update?.(state.time);
      }
      state.dirty = true;
    },
    see(through) {
      // the explanations that live at the tool make the arm glassy, so the path and the errors read through it
      for (const [name, arm] of Object.entries(state.arms)) {
        for (const object of arm.objects) {
          if (!object) continue;
          const solid = name === 'measured';
          object.material.transparent = !solid || through;
          object.material.opacity = solid ? (through ? 0.5 : 1) : (through ? 0.12 : 0.2);
          object.material.depthWrite = solid && !through;
          object.material.needsUpdate = true;
        }
      }
      state.dirty = true;
    },
    tint(byBody, armName = 'measured') {
      // byBody: {bodyIndex: css colour or THREE.Color} tints those links of the arm; null restores every link
      const arm = state.arms[armName];
      if (!arm) return;
      for (const object of arm.objects) {
        if (!object) continue;
        const color = byBody?.[object.userData.body];
        object.material.color.copy(color ? new THREE.Color(color) : object.userData.baseColor);
        if (object.material.emissive) object.material.emissive.set(color ? new THREE.Color(color).multiplyScalar(0.25) : 0x000000);
      }
      state.dirty = true;
    },

    render() { renderer.render(scene, camera); },
  };
  return viewer;
}
