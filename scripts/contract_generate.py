# Copyright (c) 2026 NightWorksIO
"""Write `src/lemonfiber/_generated/` from the vendored contract artefact: `uv run just generate`."""

from scripts.contract_generator import ROOT, run

if __name__ == "__main__":
    raise SystemExit(run(ROOT))
