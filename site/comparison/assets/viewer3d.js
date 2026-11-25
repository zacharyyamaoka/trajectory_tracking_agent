/* traj_compare — 3D path viewer (three.js, z-up).
 *
 * Per situation, one row: a bulk visibility eye plus a full-word multi-select
 * of what to draw for that run — path line, sampled points, pose frames,
 * z-vectors, its robot model, and (candidates only) difference arrows to the
 * target's same-time pose and rotation arcs between the candidate z-axis and
 * the target's. The model is one more item in that dropdown because it is one
 * more view of the same trajectory, drawn in the same color: target vs sim vs
 * real rigs overlay each other.
 *
 * Time-aware: the page transport (scrubber under the canvas, plot hover)
 * limits drawing to samples <= t — solid up to t over a faint full-path
 * ghost — and poses each visible model at that instant.
 *
 * Orientation gizmo: three.js' own ViewHelper (examples/jsm/helpers), drawn
 * bottom-right; click an axis ball to fly to that view.
 */

var Viewer3D = (function () {
  'use strict';

  var CANVAS_HEIGHT = 540;
  // a neutral scene colour in the page's theme (TrajCompare.ink, plots.js: unchanged on the light page)
  function inkNumber(value) {
    var tc = window.TrajCompare;
    if (!tc || !tc.ink) return value;
    return parseInt(tc.ink('#' + ('00000' + value.toString(16)).slice(-6)).slice(1, 7), 16);
  }
  var GIZMO_SIZE = 128;   // ViewHelper's fixed `dim`
  var ARC_STEPS = 10;

  var EYE_OPEN =
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
    '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="2.6"/></svg>';
  var EYE_CLOSED =
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
    '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><line x1="4" y1="20" x2="20" y2="4"/></svg>';

  // all:  offered for every situation (otherwise: candidates only, since it
  //       is measured against the target)
  // robot: offered only when this situation carries a model
  var ELEMENTS = [
    { id: 'path', label: 'Path line', all: true, on: true },
    { id: 'points', label: 'Points', all: true, on: true },
    { id: 'robot', label: 'Robot / URDF', all: true, on: true, robot: true },
    { id: 'frames', label: 'Pose frames', all: true, on: false },
    { id: 'zvec', label: 'Z vectors', all: true, on: false },
    { id: 'diff', label: 'Arrows → target', all: false, on: true },
    { id: 'zarc', label: 'Z rotation arcs', all: false, on: false },
  ];

  /* An element's words on this page. WHY (arm_motion_bench, 2026-11-20): in a sim → real pair the arrows point at the
     sim run (Comparison.reference_kind "run"), so they say so instead of "target". */
  function elementLabel(element, page) {
    var data = page && page.data;
    if (element.id === 'diff' && data && data.reference_kind === 'run') return 'Arrows → ' + data.reference_title;
    return element.label;
  }

  function availableElements(sit) {
    return ELEMENTS.filter(function (element) {
      if (element.robot) return !!sit.robot_track;
      return element.all || sit.three.tp;
    });
  }

  function el(tag, className, parent, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }

  function countLeq(sorted, value) {
    var lo = 0, hi = sorted.length;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (sorted[mid] <= value) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  function zAxisOf(quat) { // [w,x,y,z] -> rotated +Z column
    var w = quat[0], x = quat[1], y = quat[2], z = quat[3];
    return [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)];
  }

  function columnsOf(quat) { // x,y,z axis columns of R
    var w = quat[0], x = quat[1], y = quat[2], z = quat[3];
    return [
      [1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)],
      [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)],
      [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)],
    ];
  }

  function decodeTris(b64) {
    var raw = atob(b64);
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return new Float32Array(bytes.buffer);
  }

  /* ``options.height(width)``: the canvas height for a canvas box ``width`` px wide (default CANVAS_HEIGHT).
     WHY (Zach 2026-11-19, traj compare view feedback: keep the 3D always visible): in the run view's stage the
     canvas sits in a pane a third of the page wide, where a fixed 540 px would push the scrubber off screen. */
  function create(page, container, options) {
    var prefs = TrajCompare.prefs();
    var heightFor = (options && options.height) || function () { return CANVAS_HEIGHT; };
    var canvasHeight = CANVAS_HEIGHT;
    var situations = page.data.situations.filter(function (sit) { return sit.three; });
    if (!situations.length) {
      el('div', 'tc-empty', container, 'no cartesian data to draw');
      return { setSituationVisible: function () {}, setActive: function () {} };
    }

    var wrap = el('div', 'tc-3dwrap', container);
    var canvasBox = el('div', 'tc-3dcanvasbox', wrap);
    var canvas = document.createElement('canvas');
    canvasBox.appendChild(canvas);
    var panel = el('div', 'tc-3dpanel', wrap);

    var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.autoClear = false;
    var scene = new THREE.Scene();
    scene.background = new THREE.Color(inkNumber(0xfcfcfb));
    var camera = new THREE.PerspectiveCamera(50, 1.6, 0.005, 200);
    camera.up.set(0, 0, 1);

    var grid = new THREE.GridHelper(2, 20, inkNumber(0xd0cfc9), inkNumber(0xe6e5e0));
    grid.rotation.x = Math.PI / 2; // robotics z-up: grid on the XY plane
    scene.add(grid);
    scene.add(new THREE.AxesHelper(0.15));

    var dirty = true;
    var active = false;

    /* ---------------- bounds + camera ---------------- */

    var bounds = new THREE.Box3();
    situations.forEach(function (sit) {
      sit.three.p.forEach(function (point) {
        bounds.expandByPoint(new THREE.Vector3(point[0], point[1], point[2]));
      });
      // Robot links sweep well beyond the TCP paths; sample their track so
      // the default fit shows the whole arm, not a cropped torso.
      var track = sit.robot_track;
      if (track) {
        [0, track.p.length - 1, track.p.length >> 1].forEach(function (sample) {
          track.p[sample].forEach(function (link) {
            bounds.expandByPoint(new THREE.Vector3(link[0], link[1], link[2]));
          });
        });
      }
    });
    if ((page.data.robots || []).length) bounds.expandByPoint(new THREE.Vector3(0, 0, 0));
    var span = bounds.getSize(new THREE.Vector3()).length() || 1.0;
    var center = bounds.getCenter(new THREE.Vector3());

    var view = { theta: -Math.PI / 4, phi: Math.PI / 3.2, radius: span * 1.05, target: center.clone() };

    function applyCamera() {
      var sinPhi = Math.sin(view.phi);
      camera.position.set(
        view.target.x + view.radius * sinPhi * Math.cos(view.theta),
        view.target.y + view.radius * sinPhi * Math.sin(view.theta),
        view.target.z + view.radius * Math.cos(view.phi)
      );
      camera.lookAt(view.target);
      dirty = true;
    }

    function fitView() {
      view.target.copy(center);
      view.radius = Math.max(span * 1.05, 0.2);
      view.theta = -Math.PI / 4;
      view.phi = Math.PI / 3.2;
      applyCamera();
    }

    /* ---------------- orientation gizmo (three.js ViewHelper) ---------------- */

    // Upstream owns the widget: drawing, hit testing, and the fly-to
    // animation. It drives the camera directly, so after every animation step
    // the spherical orbit state is read back off the camera — otherwise the
    // next drag would snap back to wherever the orbit thought it was.
    var viewHelper = new THREE.ViewHelper(camera, canvas);
    viewHelper.setLabels ? viewHelper.setLabels('X', 'Y', 'Z') : null;

    function syncViewFromCamera() {
      var offset = camera.position.clone().sub(view.target);
      view.radius = Math.max(offset.length(), 1e-6);
      view.theta = Math.atan2(offset.y, offset.x);
      view.phi = Math.min(Math.PI - 0.03,
        Math.max(0.03, Math.acos(offset.z / view.radius)));
    }

    function inGizmo(px, py) {
      var width = canvas.clientWidth || 800;
      return px >= width - GIZMO_SIZE && px <= width
        && py >= canvasHeight - GIZMO_SIZE && py <= canvasHeight;
    }

    /* ---------------- pointer: orbit / pan / gizmo ---------------- */

    var dragging = null;
    canvas.addEventListener('contextmenu', function (event) { event.preventDefault(); });
    canvas.addEventListener('pointerdown', function (event) {
      var box = canvas.getBoundingClientRect();
      var px = event.clientX - box.left, py = event.clientY - box.top;
      if (inGizmo(px, py)) {
        dragging = { mode: 'gizmo', x: event.clientX, y: event.clientY };
        return;
      }
      canvas.setPointerCapture(event.pointerId);
      dragging = {
        mode: (event.button === 2 || event.shiftKey || event.ctrlKey) ? 'pan' : 'orbit',
        x: event.clientX, y: event.clientY,
      };
    });
    canvas.addEventListener('pointermove', function (event) {
      var box = canvas.getBoundingClientRect();
      canvas.style.cursor = inGizmo(event.clientX - box.left, event.clientY - box.top)
        ? 'pointer' : '';
      if (!dragging || dragging.mode === 'gizmo') return;
      var dx = event.clientX - dragging.x;
      var dy = event.clientY - dragging.y;
      dragging.x = event.clientX;
      dragging.y = event.clientY;
      if (dragging.mode === 'orbit') {
        view.theta -= dx * 0.006;
        view.phi = Math.min(Math.PI - 0.03, Math.max(0.03, view.phi - dy * 0.006));
      } else {
        var right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
        var up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
        var scale = view.radius * 0.0016;
        view.target.addScaledVector(right, -dx * scale).addScaledVector(up, dy * scale);
      }
      applyCamera();
    });
    canvas.addEventListener('pointerup', function (event) {
      if (dragging && dragging.mode === 'gizmo') {
        var moved = Math.abs(event.clientX - dragging.x) + Math.abs(event.clientY - dragging.y);
        if (moved < 5) {
          viewHelper.center.copy(view.target);
          if (viewHelper.handleClick(event)) dirty = true;
        }
      }
      dragging = null;
    });
    canvas.addEventListener('wheel', function (event) {
      event.preventDefault();
      view.radius = Math.min(span * 12, Math.max(span * 0.05, view.radius * Math.exp(event.deltaY * 0.0012)));
      applyCamera();
    }, { passive: false });
    canvas.addEventListener('dblclick', function (event) {
      var box = canvas.getBoundingClientRect();
      if (!inGizmo(event.clientX - box.left, event.clientY - box.top)) fitView();
    });

    /* ---------------- per-situation geometry ---------------- */

    // What is drawn for a situation is remembered under its *name*, so the
    // same choice comes back on every scenario tab (see plots.js prefs).
    function elementKey(sit, id) { return '3d:' + sit.name + ':' + id; }
    function eyeKey(sit) { return '3deye:' + sit.name; }

    var sitStates = situations.map(function (sit) {
      var group = new THREE.Group();
      scene.add(group);
      var enabled = {};
      availableElements(sit).forEach(function (element) {
        enabled[element.id] = prefs.get(elementKey(sit, element.id), element.on);
      });
      return {
        sit: sit,
        group: group,
        eyeOn: prefs.get(eyeKey(sit), true),
        globalOn: page.visible[sit.name] !== false,
        enabled: enabled,
        objects: {},
        timeLists: {},   // element id -> sorted per-unit sample times (for truncation)
        markerDisposables: [],
        row: null,
        eyeBtn: null,
        boxes: {},       // element id -> its checkbox in the dropdown
        paintButton: null,
      };
    });

    var density = 20;
    var markerSize = Math.max(0.01, Math.min(0.25, span * 0.05));

    function markerIndices(count) {
      var indices = [];
      var stride = Math.max(1, Math.floor(count / density));
      for (var i = 0; i < count; i += stride) indices.push(i);
      if (indices[indices.length - 1] !== count - 1) indices.push(count - 1);
      return indices;
    }

    function segmentsObject(positions, colors, material) {
      var geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(positions), 3));
      if (colors) {
        geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(colors), 3));
      }
      return new THREE.LineSegments(geometry, material);
    }

    function buildStatic(state) {
      var three = state.sit.three;
      var flat = new Float32Array(three.p.length * 3);
      three.p.forEach(function (point, index) {
        flat[index * 3] = point[0]; flat[index * 3 + 1] = point[1]; flat[index * 3 + 2] = point[2];
      });
      var attribute = new THREE.BufferAttribute(flat, 3);
      var dashed = state.sit.role === 'target';

      function lineMaterial(opacity) {
        var options = { color: state.sit.color };
        if (opacity < 1) { options.transparent = true; options.opacity = opacity; }
        return dashed
          ? new THREE.LineDashedMaterial(Object.assign(options, {
              dashSize: span * 0.016, gapSize: span * 0.010 }))
          : new THREE.LineBasicMaterial(options);
      }

      // Faint full-path ghost stays complete while the solid line is
      // truncated to the transport time, so scrubbing keeps its context.
      var ghostGeometry = new THREE.BufferGeometry();
      ghostGeometry.setAttribute('position', attribute);
      var ghost = new THREE.Line(ghostGeometry, lineMaterial(0.18));
      if (dashed) ghost.computeLineDistances();

      var solidGeometry = new THREE.BufferGeometry();
      solidGeometry.setAttribute('position', attribute);
      var solid = new THREE.Line(solidGeometry, lineMaterial(1));
      if (dashed) solid.computeLineDistances();

      var pathGroup = new THREE.Group();
      pathGroup.add(ghost);
      pathGroup.add(solid);
      state.objects.path = pathGroup;
      state.solidPathGeometry = solidGeometry;
      state.group.add(pathGroup);
    }

    function disposeMarkers(state) {
      state.markerDisposables.forEach(function (object) {
        state.group.remove(object);
        object.traverse(function (child) {
          if (child.geometry) child.geometry.dispose();
          if (child.material && child.material.map) child.material.map.dispose();
          if (child.material) child.material.dispose();
        });
      });
      state.markerDisposables = [];
    }

    function buildMarkers(state) {
      disposeMarkers(state);
      var three = state.sit.three;
      var indices = markerIndices(three.p.length);
      var times = indices.map(function (i) { return three.t[i]; });
      var color = new THREE.Color(state.sit.color);
      var length = markerSize;

      state.timeLists = { points: times, frames: times, zvec: times, diff: [], zarc: times };

      var pointsFlat = [];
      indices.forEach(function (i) { pointsFlat.push(three.p[i][0], three.p[i][1], three.p[i][2]); });
      var pointsGeometry = new THREE.BufferGeometry();
      pointsGeometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pointsFlat), 3));
      var points = new THREE.Points(pointsGeometry, new THREE.PointsMaterial({
        color: color, size: Math.max(3, length * 55), sizeAttenuation: false,
      }));
      state.objects.points = points;

      var framePositions = [], frameColors = [];
      var zPositions = [];
      var axisColors = [new THREE.Color(0xd23b3b), new THREE.Color(0x2f9e44), new THREE.Color(0x2a66d6)];
      indices.forEach(function (i) {
        var p = three.p[i];
        var columns = columnsOf(three.quat[i]);
        for (var axis = 0; axis < 3; axis++) {
          framePositions.push(p[0], p[1], p[2],
            p[0] + columns[axis][0] * length, p[1] + columns[axis][1] * length, p[2] + columns[axis][2] * length);
          for (var vertex = 0; vertex < 2; vertex++) {
            frameColors.push(axisColors[axis].r, axisColors[axis].g, axisColors[axis].b);
          }
        }
        zPositions.push(p[0], p[1], p[2],
          p[0] + columns[2][0] * length, p[1] + columns[2][1] * length, p[2] + columns[2][2] * length);
      });
      state.objects.frames = segmentsObject(framePositions, frameColors,
        new THREE.LineBasicMaterial({ vertexColors: true }));
      state.objects.zvec = segmentsObject(zPositions, null, new THREE.LineBasicMaterial({ color: color }));

      if (three.tp) {
        var arrowPositions = [];
        var arrowCones = [];
        var arrowTimes = [];
        indices.forEach(function (i) {
          var from = three.p[i], to = three.tp[i];
          if (to[0] === null) return;  // past the target's span: no target pose, no arrow
          var dx = to[0] - from[0], dy = to[1] - from[1], dz = to[2] - from[2];
          var distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
          if (distance < 1e-6) return;
          arrowPositions.push(from[0], from[1], from[2], to[0], to[1], to[2]);
          arrowCones.push({ to: to, direction: [dx / distance, dy / distance, dz / distance], distance: distance });
          arrowTimes.push(three.t[i]);
        });
        state.timeLists.diff = arrowTimes;
        var arrowGroup = new THREE.Group();
        var arrowLines = segmentsObject(arrowPositions, null, new THREE.LineBasicMaterial({ color: color }));
        arrowGroup.add(arrowLines);
        var cones = null;
        if (arrowCones.length) {
          var coneHeight = Math.min(length * 0.5, span * 0.02);
          var coneGeometry = new THREE.ConeGeometry(coneHeight * 0.35, coneHeight, 6);
          cones = new THREE.InstancedMesh(coneGeometry,
            new THREE.MeshBasicMaterial({ color: color }), arrowCones.length);
          var matrix = new THREE.Matrix4();
          var quaternion = new THREE.Quaternion();
          var yUp = new THREE.Vector3(0, 1, 0);
          arrowCones.forEach(function (cone, index) {
            var direction = new THREE.Vector3(cone.direction[0], cone.direction[1], cone.direction[2]);
            quaternion.setFromUnitVectors(yUp, direction);
            var height = Math.min(coneHeight, cone.distance * 0.5);
            var scale = height / coneHeight;
            matrix.compose(
              new THREE.Vector3(
                cone.to[0] - direction.x * height / 2,
                cone.to[1] - direction.y * height / 2,
                cone.to[2] - direction.z * height / 2),
              quaternion,
              new THREE.Vector3(scale, scale, scale));
            cones.setMatrixAt(index, matrix);
          });
          cones.instanceMatrix.needsUpdate = true;
          arrowGroup.add(cones);
        }
        state.objects.diff = arrowGroup;
        state.arrowLines = arrowLines;
        state.arrowCones = cones;
        state.arrowTotal = arrowCones.length;

        var arcPositions = [];
        var ownPositions = [];
        var ghostPositions = [];
        var arcTimes = [];
        indices.forEach(function (i) {
          var p = three.p[i];
          var own = zAxisOf(three.quat[i]);
          if (three.tquat[i][0] === null) return;  // outside the target's span
          arcTimes.push(three.t[i]);
          var goal = zAxisOf(three.tquat[i]);
          // Both fan edges are part of the arc object, so the rotation gap
          // reads on its own without also enabling the Z column.
          ownPositions.push(p[0], p[1], p[2],
            p[0] + own[0] * length, p[1] + own[1] * length, p[2] + own[2] * length);
          ghostPositions.push(p[0], p[1], p[2],
            p[0] + goal[0] * length, p[1] + goal[1] * length, p[2] + goal[2] * length);
          var previous = null;
          for (var step = 0; step <= ARC_STEPS; step++) {
            var f = step / ARC_STEPS;
            var vx = own[0] * (1 - f) + goal[0] * f;
            var vy = own[1] * (1 - f) + goal[1] * f;
            var vz = own[2] * (1 - f) + goal[2] * f;
            var norm = Math.sqrt(vx * vx + vy * vy + vz * vz) || 1;
            var point = [p[0] + vx / norm * length, p[1] + vy / norm * length, p[2] + vz / norm * length];
            if (previous) arcPositions.push(previous[0], previous[1], previous[2], point[0], point[1], point[2]);
            previous = point;
          }
        });
        // WHY: truncation counts the arcs drawn by time, so the list holds only the rows that got an arc
        state.timeLists.zarc = arcTimes;
        var arcGroup = new THREE.Group();
        state.arcSegments = segmentsObject(arcPositions, null, new THREE.LineBasicMaterial({ color: color }));
        state.arcOwn = segmentsObject(ownPositions, null, new THREE.LineBasicMaterial({ color: color }));
        state.arcGhost = segmentsObject(ghostPositions, null,
          new THREE.LineBasicMaterial({ color: inkNumber(0x52514e), transparent: true, opacity: 0.65 }));
        arcGroup.add(state.arcSegments);
        arcGroup.add(state.arcOwn);
        arcGroup.add(state.arcGhost);
        state.objects.zarc = arcGroup;
      }

      ['points', 'frames', 'zvec', 'diff', 'zarc'].forEach(function (id) {
        var object = state.objects[id];
        if (!object) return;
        state.group.add(object);
        state.markerDisposables.push(object);
      });
      applyElements(state);
      applyDisplayTime();
      dirty = true;
    }

    /* ---------------- robot model ---------------- */

    var robotPayloads = page.data.robots || [];
    var geometryCache = {};

    // Situations usually share one model and differ only in color, so the
    // triangle soups are decoded once per distinct model, not per situation.
    function geometriesFor(index) {
      if (!geometryCache[index]) {
        geometryCache[index] = robotPayloads[index].links.map(function (link) {
          var geometry = new THREE.BufferGeometry();
          geometry.setAttribute('position', new THREE.BufferAttribute(decodeTris(link.tris), 3));
          geometry.computeVertexNormals();
          return geometry;
        });
      }
      return geometryCache[index];
    }

    var robots = [];
    page.data.situations.forEach(function (sit) {
      var track = sit.robot_track;
      var payload = track ? robotPayloads[track.robot || 0] : null;
      if (!payload) return;
      var geometries = geometriesFor(track.robot || 0);
      var robot = { group: new THREE.Group(), links: [], sit: sit, lastIndex: -1 };
      payload.links.forEach(function (link, linkIndex) {
        var baseOpacity = link.opacity === undefined ? 0.55 : link.opacity;
        var material = new THREE.MeshLambertMaterial({
          color: link.color || sit.color,
          transparent: baseOpacity < 1,
          opacity: baseOpacity,
        });
        material.userData.baseOpacity = baseOpacity;
        var mesh = new THREE.Mesh(geometries[linkIndex], material);
        robot.group.add(mesh);
        robot.links.push(mesh);
      });
      robot.group.visible = page.visible[sit.name] !== false;
      scene.add(robot.group);
      robots.push(robot);
    });
    if (robots.length) {
      scene.add(new THREE.HemisphereLight(0xffffff, 0x9a9994, 1.0));
      var sun = new THREE.DirectionalLight(0xffffff, 0.65);
      sun.position.set(1.2, -0.8, 1.6);
      scene.add(sun);

      // The bounds so far know link *origins* only. A 250 mm arm or a payload
      // disc reaches far past its origin, so fold in each link's own extent —
      // otherwise the default fit frames the skeleton and crops the model.
      robots.forEach(function (robot) {
        var track = robot.sit.robot_track;
        robot.links.forEach(function (mesh, linkIndex) {
          mesh.geometry.computeBoundingSphere();
          var reach = mesh.geometry.boundingSphere.radius;
          [0, track.p.length - 1, track.p.length >> 1].forEach(function (sample) {
            var p = track.p[sample][linkIndex];
            bounds.expandByPoint(new THREE.Vector3(p[0] + reach, p[1] + reach, p[2] + reach));
            bounds.expandByPoint(new THREE.Vector3(p[0] - reach, p[1] - reach, p[2] - reach));
          });
        });
      });
      span = bounds.getSize(new THREE.Vector3()).length() || 1.0;
      center = bounds.getCenter(new THREE.Vector3());
    }

    function robotForSituation(name) {
      for (var i = 0; i < robots.length; i++) {
        if (robots[i].sit.name === name) return robots[i];
      }
      return null;
    }

    // Posed whether or not it is currently shown: a hidden model that is
    // re-enabled mid-scrub must already be standing at the scrub time.
    function poseRobots(time) {
      robots.forEach(function (robot) {
        var track = robot.sit.robot_track;
        var index = Math.max(0, countLeq(track.t, time) - 1);
        if (index === robot.lastIndex) return;
        robot.lastIndex = index;
        robot.links.forEach(function (mesh, linkIndex) {
          var p = track.p[index][linkIndex];
          var q = track.quat[index][linkIndex];
          mesh.position.set(p[0], p[1], p[2]);
          mesh.quaternion.set(q[1], q[2], q[3], q[0]); // three wants [x,y,z,w]
        });
      });
      dirty = true;
    }

    /* ---------------- time-limited drawing ---------------- */

    function applyDisplayTime() {
      var time = page.transport ? page.transport.eff() : Infinity;
      sitStates.forEach(function (state) {
        if (!state.solidPathGeometry) return; // not built yet during init
        var three = state.sit.three;
        var visibleSamples = countLeq(three.t, time);
        state.solidPathGeometry.setDrawRange(0, Math.max(visibleSamples, 1));

        var markers = countLeq(state.timeLists.points, time);
        if (state.objects.points) state.objects.points.geometry.setDrawRange(0, markers);
        if (state.objects.frames) state.objects.frames.geometry.setDrawRange(0, markers * 6);
        if (state.objects.zvec) state.objects.zvec.geometry.setDrawRange(0, markers * 2);
        if (state.arrowLines) {
          var arrows = countLeq(state.timeLists.diff, time);
          state.arrowLines.geometry.setDrawRange(0, arrows * 2);
          if (state.arrowCones) state.arrowCones.count = arrows;
        }
        if (state.arcSegments) {
          var arcs = countLeq(state.timeLists.zarc, time);
          state.arcSegments.geometry.setDrawRange(0, arcs * ARC_STEPS * 2);
          state.arcOwn.geometry.setDrawRange(0, arcs * 2);
          state.arcGhost.geometry.setDrawRange(0, arcs * 2);
        }
      });
      poseRobots(time);
      dirty = true;
    }

    /* ---------------- control panel ---------------- */

    function applyElements(state) {
      ['path', 'points', 'frames', 'zvec', 'diff', 'zarc'].forEach(function (id) {
        var object = state.objects[id];
        if (object) object.visible = !!state.enabled[id];
      });
      paintVisibility(state);   // the model rides on the same eye
    }

    function setElement(state, id, on, remember) {
      state.enabled[id] = on;
      if (remember) prefs.set(elementKey(state.sit, id), on);
      if (state.boxes[id]) state.boxes[id].checked = on;
      applyElements(state);
      if (state.paintButton) state.paintButton();
    }

    function paintVisibility(state) {
      state.group.visible = state.globalOn && state.eyeOn;
      var associatedRobot = robotForSituation(state.sit.name);
      if (associatedRobot) {
        associatedRobot.group.visible =
          state.globalOn && state.eyeOn && !!state.enabled.robot;
      }
      if (state.row) state.row.style.display = state.globalOn ? '' : 'none';
      if (state.eyeBtn) {
        state.eyeBtn.innerHTML = state.eyeOn ? EYE_OPEN : EYE_CLOSED;
        state.eyeBtn.className = 'tc-eye' + (state.eyeOn ? '' : ' off');
      }
      dirty = true;
    }

    var rows = el('div', 'tc-3drows', panel);
    sitStates.forEach(function (state) {
      var row = el('div', 'tc-3drow', rows);
      state.row = row;

      var eye = el('button', 'tc-eye', row);
      eye.title = 'show/hide everything for this situation in the 3D scene';
      state.eyeBtn = eye;
      eye.onclick = function () {
        state.eyeOn = !state.eyeOn;
        prefs.set(eyeKey(state.sit), state.eyeOn);
        paintVisibility(state);
      };

      var name = el('span', 'tc-3dname', row);
      var swatch = el('span', 'swatch', name);
      swatch.style.background = state.sit.color;
      name.appendChild(document.createTextNode(state.sit.title));
      name.title = state.sit.title;

      // full-word multi-select dropdown instead of a cryptic checkbox matrix;
      // the situation's robot model is one of the items
      var dd = el('div', 'tc-dd', row);
      var button = el('button', 'tc-ddbtn', dd);
      var menu = el('div', 'tc-ddmenu', dd);
      var available = availableElements(state.sit);
      state.boxes = {};

      function paintButton() {
        var on = available.filter(function (element) { return state.enabled[element.id]; });
        button.textContent = on.length === 0 ? 'nothing shown'
          : on.length === available.length ? 'everything shown'
          : on.map(function (element) { return elementLabel(element, page); }).join(', ');
      }
      state.paintButton = paintButton;

      available.forEach(function (element) {
        var label = el('label', 'tc-dditem', menu);
        var checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = !!state.enabled[element.id];
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(elementLabel(element, page)));
        if (element.robot) {
          var payload = robotPayloads[state.sit.robot_track.robot || 0];
          label.title = payload ? payload.name : 'robot model';
          el('span', 'tc-ddnote', label, label.title);
        }
        state.boxes[element.id] = checkbox;
        checkbox.onchange = function () {
          setElement(state, element.id, checkbox.checked, true);
        };
      });
      button.onclick = function (event) {
        event.stopPropagation();
        var open = menu.classList.contains('open');
        document.querySelectorAll('.tc-ddmenu.open').forEach(function (other) {
          other.classList.remove('open');
        });
        if (!open) menu.classList.add('open');
      };
      paintButton();
      paintVisibility(state);
    });
    // WHY: Zach flips several layers on/off in a row to compare them, so a click
    // inside an open menu (its checkboxes, labels, padding) must NOT close it;
    // only a click elsewhere on the page, or Escape, does.
    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      document.querySelectorAll('.tc-ddmenu.open').forEach(function (menu) {
        menu.classList.remove('open');
      });
    });
    document.addEventListener('click', function (event) {
      if (event.target.closest && event.target.closest('.tc-ddmenu')) return;
      document.querySelectorAll('.tc-ddmenu.open').forEach(function (menu) {
        menu.classList.remove('open');
      });
    });

    if (robots.length) {
      sliderRow('Model opacity', 5, 100, prefs.get('3d:opacity', 100), 5, function (value) {
        return value + '%';
      }, function (value) {
        prefs.set('3d:opacity', value);
        applyModelOpacity(value);
      });
      applyModelOpacity(prefs.get('3d:opacity', 100));
    }

    function applyModelOpacity(percent) {
      var scale = percent / 100;
      robots.forEach(function (robot) {
        robot.links.forEach(function (mesh) {
          mesh.material.opacity = mesh.material.userData.baseOpacity * scale;
          mesh.material.transparent = mesh.material.opacity < 1;
        });
      });
      dirty = true;
    }

    function sliderRow(label, min, max, value, step, format, onInput) {
      var row = el('div', 'sliderrow', panel);
      var labelEl = el('label', '', row);
      labelEl.appendChild(document.createTextNode(label));
      var output = el('output', '', labelEl, format(value));
      var slider = document.createElement('input');
      slider.type = 'range';
      slider.min = min; slider.max = max; slider.step = step; slider.value = value;
      row.appendChild(slider);
      slider.addEventListener('input', function () {
        var parsed = parseFloat(slider.value);
        output.textContent = format(parsed);
        onInput(parsed);
      });
      return slider;
    }

    var rebuildQueued = false;
    function queueRebuild() {
      if (rebuildQueued) return;
      rebuildQueued = true;
      requestAnimationFrame(function () {
        rebuildQueued = false;
        sitStates.forEach(buildMarkers);
      });
    }

    var densityDial = prefs.get('3d:density', 35);
    sliderRow('Marker density', 0, 100, densityDial, 1, function (value) {
      return String(Math.round(4 * Math.pow(100, value / 100)));
    }, function (value) {
      density = Math.round(4 * Math.pow(100, value / 100)); // 4 .. 400, log
      prefs.set('3d:density', value);
      queueRebuild();
    });
    density = Math.round(4 * Math.pow(100, densityDial / 100));

    markerSize = prefs.get('3d:markersize', Math.round(markerSize * 1000)) / 1000;
    sliderRow('Marker size', 5, 250, Math.round(markerSize * 1000), 5, function (value) {
      return (value) + ' mm';
    }, function (value) {
      markerSize = value / 1000;
      prefs.set('3d:markersize', value);
      queueRebuild();
    });

    var fitRow = el('div', 'btnrow', panel);
    var fitButton = el('button', '', fitRow, 'Fit view');
    fitButton.onclick = fitView;

    el('div', 'hint', panel,
      'Orbit: drag · zoom: wheel · pan: right-drag · fit: double-click or the button. ' +
      'Click an axis ball on the corner gizmo to fly to that view. ' +
      (page.data && page.data.reference_kind === 'run'
        ? 'Arrows → ' + page.data.reference_title + ': from a run’s pose to ' + page.data.reference_title + '’s pose at the same instant. ' +
          'Z rotation arcs: the gap between a run’s tool z and ' + page.data.reference_title + '’s (grey ghost).'
        : 'Arrows → target: from a run’s pose to the target’s pose at the same instant — ' +
          'points to where you should have been. ' +
          'Z rotation arcs: the gap between a run’s tool z and the target’s (grey ghost).'));

    /* ---------------- scrubber (page transport) ---------------- */

    if (page.transport) {
      TrajCompare.buildTransportBar(page, canvasBox);
      page.transport.onChange(function () { applyDisplayTime(); });
    }

    /* ---------------- lifecycle ---------------- */

    function resize() {
      var width = canvasBox.clientWidth || 800;
      canvasHeight = Math.round(heightFor(width));
      renderer.setSize(width, canvasHeight, false);
      canvas.style.height = canvasHeight + 'px';
      camera.aspect = width / canvasHeight;
      camera.updateProjectionMatrix();
      dirty = true;
    }
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(function () { resize(); }).observe(canvasBox);
    }

    var lastFrame = 0;

    function frame(now) {
      var delta = Math.min(0.1, (now - lastFrame) / 1000) || 0;
      lastFrame = now;
      if (active && viewHelper.animating) {
        viewHelper.update(delta);
        syncViewFromCamera();
        applyCamera();   // re-impose z-up; ViewHelper animates in its own frame
      }
      if (active && dirty) {
        var width = canvasBox.clientWidth || 800;
        renderer.setViewport(0, 0, width, canvasHeight);
        renderer.clear();
        renderer.render(scene, camera);
        viewHelper.render(renderer);
        dirty = false;
      }
      requestAnimationFrame(frame);
    }

    sitStates.forEach(function (state) {
      buildStatic(state);
      buildMarkers(state);
      paintVisibility(state);
    });
    applyDisplayTime();
    resize();
    fitView();
    requestAnimationFrame(frame);

    return {
      setSituationVisible: function (name, show) {
        sitStates.forEach(function (state) {
          if (state.sit.name === name) {
            state.globalOn = show;
            paintVisibility(state);
          }
        });
        dirty = true;
      },
      // Another scenario tab changed the 3D layout; adopt it.
      applyShared: function () {
        sitStates.forEach(function (state) {
          state.eyeOn = prefs.get(eyeKey(state.sit), true);
          availableElements(state.sit).forEach(function (element) {
            var want = prefs.get(elementKey(state.sit, element.id), element.on);
            if (want !== !!state.enabled[element.id]) setElement(state, element.id, want, false);
          });
          paintVisibility(state);
        });
      },
      setActive: function (value) {
        active = !!value;
        if (active) { resize(); dirty = true; }
      },
    };
  }

  return { create: create };
})();
