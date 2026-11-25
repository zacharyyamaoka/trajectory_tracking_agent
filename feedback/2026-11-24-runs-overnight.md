---
id: fb-6b484fb1
polarity: negative
added: 2026-11-24
from: Zach
filed_by: claude-code (pick-trajgen box agent)
model: claude-opus-5-5
words: paraphrase
tracks: [trajectory-tracking-agent]
specs: []
source: [src/trajectory_tracking_agent/files.py, src/trajectory_tracking_agent/ledger.py, src/trajectory_tracking_agent/evaluate.py, tests/test_runs_overnight.py]
reacting_to: "the black box search on its first day"
became: "43a958b"
---

# Leave it running overnight

## Observed

The black box is not reliable yet: it cannot be left to keep running through the night.

## Desired

Leave the search running overnight and find it still going, its record intact, in the morning.

## Why

> [!ai] claude-code (pick-trajgen box agent), from tests/test_runs_overnight.py
> AGENTS.md already promised that state lives in files, so any session can stop at any point and the next resumes.
> Nothing held that promise, and a run on 2026-11-25 with under 8 % of memory free broke it three ways:
> - **A killed worker was scored.** `multiprocessing.Pool` replaced the workers the machine killed without a word, so
>   the evaluation waited out its whole backstop deadline (160 s on four 1 s tasks; about 25 min on the dev split)
>   and then wrote each lost task as a failed `completed`. The machine's kill went into the ledger as the
>   controller's failure. Now the pool breaks at once, nothing is written, and `tta evaluate` exits 75 ("evaluate
>   again"); the score repeats bit for bit ([`tests/test_ruler_determinism.py`](../tests/test_ruler_determinism.py)).
> - **A torn ledger line would stop every command.** A row cut off by a crash made `ledger.rows()` raise. Now only a
>   torn last line is skipped, the next append cuts it off first, and a bad line with rows after it still raises.
> - **A half-written scorecard, run record, PROGRESS.md or status.json** stopped the next step that read it. Every
>   file `tta` writes now goes through `files.write_text`: a temporary file, flushed, renamed over the old one.
>
> [`tests/test_runs_overnight.py`](../tests/test_runs_overnight.py) holds all three. Each test failed before its fix.
> Still open: the search itself is driven by an agent session. When that session ends overnight, nothing here starts
> the next one; that is the driver's job, outside this repo.
