"""Phase 2 probe sets (spec §10.2): deterministic, no model calls, written to `runs/`.

`temporal`: T1-T5 on gov (`adr-eval probes temporal gov`). `acl`: the leak and fail-closed
probes of the content tools (`adr-eval probes acl <corpus>`, B1, B4, B5). `equivalence`: B2
against reference stores of each view (`adr-eval probes equivalence <corpus>`). The probe
modules may import `adr_store` directly (plan, shared rules)."""

from pathlib import Path

SEED = 20261116
OUT_ROOT = Path("runs")  # where `adr-eval probes` writes by default (tests redirect it)
