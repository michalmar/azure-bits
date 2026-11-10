from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPT = (ROOT / "prompts/workshop.txt").read_text(encoding="utf-8")
OFFERS = (ROOT / "data/offers.csv").read_bytes()

spec = importlib.util.spec_from_file_location(
    "workshop_calculation", ROOT / "skills/workshop-planner/scripts/calculate_budget.py",
)
if spec is None or spec.loader is None:
    raise RuntimeError("Workshop calculation module is missing")
calculation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calculation)
REFERENCE = calculation.calculate(ROOT / "data/offers.csv")
