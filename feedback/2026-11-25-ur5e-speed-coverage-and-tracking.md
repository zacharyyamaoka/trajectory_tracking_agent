---
id: fb-1af914b2
polarity: negative
added: 2026-11-25
from: Zach
filed_by: Codex
model: gpt-6.2-sol
words: paraphrase
tracks: [trajectory-tracking-agent]
specs: []
source: [tools/build_dropins.py, tools/build_coverage.py, site/reports/ur5e-speed-sweep.html]
---

# UR5e speed coverage and tracking

## Observed

Coverage exposed instantaneous joint speed distributions. Comparison combined a single nominal full-speed cohort with an automatic axis extending past 1.0. The site linked the older dataset target cards.

## Desired

Show the distribution of nominal time scales in stock Coverage. Show each controller’s tracking error across matched trajectories in tenth-speed buckets, with the first bucket at 0.1 and the axis ending at 1.0. Link the current stock Targets workbench and make it possible to open the exact charts from a report.

## Why

> [!ai] A nominal tape scale answers a different question from the time a joint spends near its limit. The same target paths at each speed make the comparison interpretable. The full-speed ranking and detailed recorded runs retain their existing provenance.
