"""`mujoco` in the browser: MuJoCo's Python API, the part robot_controllers calls, over the official WASM build.

THE ONLY NON-ORIGINAL CODE ON THIS PAGE. Everything that imports `mujoco` above it (robot_controllers' UR5e plant,
its feed-forward and mass-matrix models, the boards, the host loop, robot_msgs and the agent's ruler) is the package
source, unmodified, installed from wheels built from each repo's committed HEAD. No physics or controller logic
lives here: every number comes from MuJoCo 3.11.0 compiled to WebAssembly by Google DeepMind (`@mujoco/mujoco`,
the same release as the native `mujoco==3.11.0` wheel), which the worker registers as the JS module `_mujoco_js`.

What it does, and nothing more:

- `MjModel` / `MjData` hand out numpy arrays shaped as the native bindings shape them (`site_xpos` (nsite, 3), ...;
  the trailing dimensions come from `mujoco_fields.json`, generated from native mujoco by tools/build_site.py).
  Pyodide and MuJoCo are two WASM modules with two memories, so an array cannot be a view of MuJoCo's memory as it
  is natively. Each array is a *mirror* instead: before every MuJoCo call the shim copies every mirror of the
  model and data it is given into MuJoCo, after the call it copies them all back. Code that keeps
  `qpos = data.qpos` and reads it after `mj_step` (as the plant does) sees exactly what a native view would show.
  Copies are float64 to float64 (or int32 to int32): exact.
- `mujoco.mj_*` functions forward to the same-named WASM function; a numpy argument (an out parameter such as
  `mj_fullM`'s matrix) goes in as a `DoubleBuffer` and is copied back into the numpy array in place.
- `MjModel.from_xml_path` writes the file into MuJoCo's own virtual file system at the same path, then compiles it
  there; `from_xml_string` compiles the string. `copy.deepcopy(model)` is MuJoCo's copy constructor.
- Named access (`model.joint(name).id`, `.dofadr`, ...), enums (`mujoco.mjtWarning.mjWARN_BADQACC`), the warning
  counters (`data.warning[i].number`) and `__version__`.

Anything robot_controllers does not use raises AttributeError / NotImplementedError naming what is missing, rather
than guessing.
"""

from __future__ import annotations

import enum
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

import _mujoco_js as _mj  # the official @mujoco/mujoco WASM module, registered by runtime/worker.js

__version__ = str(_mj.mj_versionString())

_FIELDS = json.loads((Path(__file__).with_name("mujoco_fields.json")).read_text())
_DTYPES = {
    "Float64Array": np.float64,
    "Float32Array": np.float32,
    "Int32Array": np.int32,
    "Uint32Array": np.uint32,
    "Uint8Array": np.uint8,
    "Int8Array": np.int8,
    "Uint16Array": np.uint16,
    "Int16Array": np.int16,
    "BigInt64Array": np.int64,
    "BigUint64Array": np.uint64,
}


def _typed_array_kind(value: Any) -> str | None:
    """The JS typed-array class name of `value`, or None when it is not a typed array."""
    if not hasattr(value, "BYTES_PER_ELEMENT"):
        return None
    try:
        return str(value.constructor.name)
    except Exception:  # noqa: BLE001
        return None


class _Struct:
    """An MjModel or MjData: attribute reads give numpy mirrors (see the module docstring), scalars read through."""

    _kind = ""

    def __init__(self, js: Any) -> None:
        object.__setattr__(self, "_js", js)
        object.__setattr__(self, "_mirrors", {})

    # ── mirrors ────────────────────────────────────────────────────────────────────────────────────────────

    def _mirror(self, name: str) -> np.ndarray | None:
        mirrors = self._mirrors
        array = mirrors.get(name)
        if array is not None:
            return array
        value = getattr(self._js, name)
        kind = _typed_array_kind(value)
        if kind is None:
            return None
        trailing = _FIELDS[self._kind].get(name)
        if trailing is None:
            raise AttributeError(f"mujoco shim: {self._kind}.{name} has no shape in mujoco_fields.json")
        length = int(value.length)
        per_row = int(np.prod(trailing)) if trailing else 1
        if per_row and length % per_row:
            raise ValueError(f"mujoco shim: {self._kind}.{name} has {length} values, not rows of {trailing}")
        shape = (length // per_row, *trailing) if trailing else (length,)
        array = np.empty(shape, dtype=_DTYPES[kind])
        if length:
            value.assign_to(array.reshape(-1))
        mirrors[name] = array
        return array

    def _push(self) -> None:
        """Every mirror -> MuJoCo (before a call)."""
        js = self._js
        for name, array in self._mirrors.items():
            view = getattr(js, name)
            if array.size and int(view.length) == array.size:
                view.assign(array.reshape(-1))

    def _pull(self) -> None:
        """MuJoCo -> every mirror (after a call), in place, so references held by the caller stay live. A field whose
        length the call changed (the constraint rows, sized by nefc) is dropped and re-read on its next access, as the
        native bindings hand out a fresh view of it each time."""
        js = self._js
        for name, array in list(self._mirrors.items()):
            view = getattr(js, name)
            if int(view.length) != array.size:
                del self._mirrors[name]
            elif array.size:
                view.assign_to(array.reshape(-1))

    # ── attribute access ───────────────────────────────────────────────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        array = self._mirror(name) if name in _FIELDS[self._kind] else None
        if array is not None:
            return array
        if name in _ACCESSORS:
            return _Named(self, _ACCESSORS[name])
        if name == "warning":
            return _WarningList(self._js)
        if name in ("opt", "stat", "vis"):  # MjOption / MjStatistic / MjVisual: read-only snapshots
            self._push()
            return _Accessor(getattr(self._js, name))
        try:
            value = getattr(self._js, name)
        except AttributeError:
            raise AttributeError(f"mujoco shim: {self._kind} has no {name!r}") from None
        if isinstance(value, (bool, int, float, str)):
            return value
        raise NotImplementedError(f"mujoco shim: {self._kind}.{name} is not exposed (robot_controllers never uses it)")

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _FIELDS[self._kind]:
            self._mirror(name)[...] = value
            return
        current = getattr(self._js, name)
        if isinstance(current, (bool, int, float)):
            setattr(self._js, name, value)
            return
        raise NotImplementedError(f"mujoco shim: cannot set {self._kind}.{name}")


class MjModel(_Struct):
    _kind = "MjModel"

    @staticmethod
    def from_xml_string(xml: str, assets: Any = None) -> MjModel:
        if assets:
            raise NotImplementedError("mujoco shim: from_xml_string(assets=...) is not used by robot_controllers")
        return MjModel(_call_js(lambda: _mj.MjModel.from_xml_string(xml)))

    @staticmethod
    def from_xml_path(path: str, assets: Any = None) -> MjModel:
        if assets:
            raise NotImplementedError("mujoco shim: from_xml_path(assets=...) is not used by robot_controllers")
        path = os.path.abspath(str(path))
        # WHY write it into MuJoCo's own file system: the WASM module cannot see Pyodide's, and compiling from a
        # path (not the text) keeps MuJoCo's own relative-path rules for anything the file references
        _mj.FS.mkdirTree(os.path.dirname(path))
        _mj.FS.writeFile(path, Path(path).read_text())
        return MjModel(_call_js(lambda: _mj.MjModel.from_xml_path(path)))

    def __deepcopy__(self, memo: Any) -> MjModel:
        self._push()
        return MjModel(_mj.MjModel.new(self._js))


class MjData(_Struct):
    _kind = "MjData"

    def __init__(self, model: MjModel) -> None:
        model._push()
        super().__init__(_mj.MjData.new(model._js))


# ── named access: model.joint(name).id, model.site(name).id, model.body(name).id ──────────────────────────

# the native bindings' names -> the WASM bindings' (which use MuJoCo's short C prefixes)
_ACCESSORS = {
    "joint": "jnt", "jnt": "jnt", "body": "body", "site": "site", "geom": "geom", "actuator": "actuator",
    "sensor": "sensor", "camera": "cam", "cam": "cam", "light": "light", "tendon": "tendon", "mesh": "mesh",
    "eq": "eq", "equality": "eq", "key": "key", "keyframe": "key", "material": "mat", "mat": "mat",
    "texture": "tex", "tex": "tex", "hfield": "hfield", "pair": "pair", "exclude": "exclude",
    "numeric": "numeric", "tuple": "tuple", "skin": "skin",
}


class _Named:
    """`model.joint` etc.: call with a name or id; the result's arrays are read-only copies (writes through a named
    accessor would not reach MuJoCo, so they raise instead of silently doing nothing)."""

    def __init__(self, struct: _Struct, kind: str) -> None:
        self._struct, self._kind = struct, kind

    def __call__(self, key: int | str) -> Any:
        self._struct._push()
        return _Accessor(getattr(self._struct._js, self._kind)(key))


class _Accessor:
    def __init__(self, js: Any) -> None:
        object.__setattr__(self, "_js", js)

    def __setattr__(self, name: str, value: Any) -> None:
        raise NotImplementedError(f"mujoco shim: writing {name} through a named accessor or struct is not supported")

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        value = getattr(self._js, name)
        kind = _typed_array_kind(value)
        if kind is None:
            return value
        array = np.empty(int(value.length), dtype=_DTYPES[kind])
        value.assign_to(array)
        array.flags.writeable = False
        return array


class _WarningList:
    """`data.warning[i].number` / `.lastinfo`: read from MuJoCo on access (a copy, as the WASM binding returns)."""

    def __init__(self, js_data: Any) -> None:
        self._js_data = js_data

    def __getitem__(self, index: int) -> Any:
        number, lastinfo = _warning_stat(self._js_data, int(index)).to_py()
        return _Warning(int(number), int(lastinfo))


def _js_function(*args: str) -> Any:
    import js

    return js.Function.new(*args)


# WHY a JS function: Pyodide maps a JS object with a `get` method onto Python's Mapping.get, so `vec.get(i)` on the
# embind vector would not call the vector's own get. The stat it returns is a copy and is freed; the vector is MjData's
# own (every `data.warning` is a handle to the same pointer: deleting it would destroy MjData's warnings, measured)
_warning_stat = _js_function(
    "data", "index",
    "const stat = data.warning.get(index); const out = [stat.number, stat.lastinfo]; stat.delete(); return out;",
)


class _Warning:
    __slots__ = ("number", "lastinfo")

    def __init__(self, number: int, lastinfo: int) -> None:
        self.number, self.lastinfo = number, lastinfo


# ── functions ──────────────────────────────────────────────────────────────────────────────────────────────


def _call_js(thunk: Any) -> Any:
    try:
        return thunk()
    except Exception as error:  # a JS exception from MuJoCo (compile error, bad size): native raises ValueError
        raise ValueError(str(error)) from None


def _function(name: str) -> Any:
    js_function = getattr(_mj, name)

    def call(*args: Any) -> Any:
        structs: list[_Struct] = []
        buffers: list[tuple[np.ndarray, Any]] = []
        js_args: list[Any] = []
        for arg in args:
            if isinstance(arg, _Struct):
                arg._push()
                structs.append(arg)
                js_args.append(arg._js)
            elif isinstance(arg, np.ndarray):
                if arg.dtype != np.float64:
                    raise NotImplementedError(f"mujoco shim: {name} with a {arg.dtype} array argument")
                buffer = _mj.DoubleBuffer.new(int(arg.size))
                buffer.GetView().assign(np.ascontiguousarray(arg).reshape(-1))
                buffers.append((arg, buffer))
                js_args.append(buffer)
            elif isinstance(arg, (list, tuple)):
                from pyodide.ffi import to_js

                js_args.append(to_js([float(v) for v in arg]))
            elif isinstance(arg, enum.Enum):
                js_args.append(int(arg.value))
            else:
                js_args.append(arg)
        try:
            result = _call_js(lambda: js_function(*js_args))
        finally:
            for array, buffer in buffers:
                out = np.empty(array.size, dtype=np.float64)
                buffer.GetView().assign_to(out)
                array[...] = out.reshape(array.shape)
                buffer.delete()
            for struct in structs:
                struct._pull()
        return result

    call.__name__ = name
    call.__doc__ = f"mujoco.{name}, forwarded to the WASM build (shim)"
    return call


# ── enums: mujoco.mjtWarning.mjWARN_BADQACC, ... (IntEnums built from the WASM module's own values) ─────────


def _enum(name: str) -> type[enum.IntEnum] | None:
    import js

    js_enum = getattr(_mj, name, None)
    if js_enum is None:
        return None
    members = {}
    for key in js.Object.keys(js_enum).to_py():
        if key == "values":
            continue
        member = getattr(js_enum, key)
        value = getattr(member, "value", None)
        if isinstance(value, int):
            members[str(key)] = value
    return enum.IntEnum(name, members) if members else None


_ENUMS: dict[str, Any] = {}


def __getattr__(name: str) -> Any:
    if name.startswith("mjt"):
        if name not in _ENUMS:
            built = _enum(name)
            if built is None:
                raise AttributeError(f"mujoco shim: no enum {name}")
            _ENUMS[name] = built
        return _ENUMS[name]
    if name.startswith(("mj_", "mju_", "mjd_")) and hasattr(_mj, name):
        function = _function(name)
        globals()[name] = function
        return function
    raise AttributeError(f"mujoco shim: mujoco.{name} is not exposed (robot_controllers never uses it)")
