"""Build a corpus manifest. Thin wrapper over the corpus adapters, kept so the plan's
`scripts/make_manifest.py` reference still works; the only manifest-building code path is
`adr_eval.corpora.registry.build` (each adapter's `build_manifest`).

Usage: python scripts/make_manifest.py <corpus>
  same as: python -m adr_eval.corpora.registry build <corpus>
  corpus: gov | research | bench | mini (mini writes tests/fixtures/mini/manifest.json)
"""

import sys

from adr_eval.corpora import registry


def main(argv: list[str]) -> None:
    registry.main(["build", *argv])


if __name__ == "__main__":
    main(sys.argv[1:])
