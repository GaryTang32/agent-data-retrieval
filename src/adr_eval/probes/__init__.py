"""Phase 2 probe sets (spec §10.2): deterministic, no model calls, written to `runs/`.

`temporal`: T1-T5 on gov (`adr-eval probes temporal gov`). The probe modules may import
`adr_store` directly (plan, shared rules)."""

from pathlib import Path

SEED = 20261116
OUT_ROOT = Path("runs")  # where `adr-eval probes` writes by default (tests redirect it)
