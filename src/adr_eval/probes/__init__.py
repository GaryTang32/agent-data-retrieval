"""Phase 2 probe sets (spec §10.2): deterministic, no model calls, written to `runs/`.

`temporal`: T1-T5 on gov (`adr-eval probes temporal gov`). `acl`: the leak and fail-closed
probes of the content tools (`adr-eval probes acl <corpus>`, B1, B4, B5). `equivalence`: B2
against reference stores of each view (`adr-eval probes equivalence <corpus>`). Phase 3
(spec §10.4): `tables`, the probes of the table tools (`adr-eval probes tables-<kind> <corpus>`,
S1–S3 and the MCP leg of D1; seed `tables.SEED3`). Phase 4 (spec §15.4): `units`, the probes
of the unit tools (`adr-eval probes units-<kind> <corpus>`, S1, S2, U1–U3, applicability and
the MCP leg of D1; seed `units.SEED4`). The probe modules may import `adr_store`
directly (plan, shared rules)."""

from pathlib import Path

SEED = 20261116
OUT_ROOT = Path("runs")  # where `adr-eval probes` writes by default (tests redirect it)
