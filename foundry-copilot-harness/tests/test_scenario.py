import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scenario import ROOT, REFERENCE, calculation


def test_exact_budget():
    assert REFERENCE["fictional"] is True
    assert REFERENCE["winner"] == "A"
    assert [offer["total_czk"] for offer in REFERENCE["offers"]] == ["21120.00", "26840.00", "15400.00"]
    assert [offer["reasons"] for offer in REFERENCE["offers"]] == [[], ["budget"], ["capacity", "projector"]]


def test_script_outputs(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "skills/workshop-planner/scripts/calculate_budget.py"),
         str(ROOT / "data/offers.csv"), "--output-dir", str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == REFERENCE
    assert json.loads((tmp_path / "budget.json").read_text()) == REFERENCE
    rows = list(csv.DictReader((tmp_path / "budget.csv").open()))
    assert len(rows) == 3 and rows[0]["total_czk"] == "21120.00"


@pytest.mark.parametrize("old,new", [
    ("12000", "NaN"), ("12000", "-1"), ("12000", "1.001"),
    ("16,true", "0,true"), ("16,true", "12,yes"), ("B,Forum", "A,Forum"),
    ("id,name", "name,id"),
])
def test_invalid_csv(tmp_path, old, new):
    path = tmp_path / "offers.csv"
    path.write_text((ROOT / "data/offers.csv").read_text().replace(old, new))
    with pytest.raises(ValueError):
        calculation.calculate(path)


def test_manifest_matches_capabilities():
    manifest = yaml.safe_load((ROOT / "azure.yaml").read_text())
    services = manifest["services"]
    agent = services["workshop-agent"]
    assert agent["kind"] == "prompt"
    assert agent["harness"]["type"] == "microsoft_copilot_preview"
    assert agent["skills"] == ["workshop-planner"]
    assert "workshop-planner" in agent["uses"]
    assert services["workshop-planner"]["archive"] == "./skills/workshop-planner"
    assert [tool["type"] for tool in agent["tools"]] == ["microsoft_copilot_toolset_preview", "web_search"]
    assert agent["tools"][0]["defaultConfig"]["enabled"] is False
    assert "subagents" not in [config["name"] for config in agent["tools"][0]["configs"]]
