---
id: fb-2d0d8aef
polarity: negative
added: 2026-11-24
from: Zach
filed_by: claude-code (dispatcher lane FS)
model: claude-opus-5-5
words: exact
tracks: [trajectory-tracking-agent]
specs: []
source: [site/README.md, tools/build_site.py]
reacting_to: "the landing page running MuJoCo's WebAssembly build and Pyodide live in the browser"
became: "d693415"
---

# Play back saved runs

## Observed

You can just playback saved runs

## Desired

## Why

> [!ai] claude-code (lane FS), from site/README.md
> Until then the landing page simulated live in the browser. Since d693415 every run is simulated and scored by the
> ruler when `tta evaluate` runs it, and the page plays that saved record back; nothing is simulated or scored in the
> browser. `tests/test_site_static.py::test_no_live_runtime_is_shipped_or_loaded` keeps it that way.
