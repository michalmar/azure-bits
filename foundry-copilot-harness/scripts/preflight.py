"""Static manifest checks plus explicit read-only checks of the shared Azure target."""

import json
from pathlib import Path
import sys

import yaml

from cloud import ROOT, arm, az

manifest = yaml.safe_load((Path(__file__).resolve().parent.parent / "azure.yaml").read_text())
services = manifest["services"]
agent = services["workshop-agent"]
if (
    agent.get("kind") != "prompt"
    or agent.get("harness", {}).get("type") != "microsoft_copilot_preview"
    or agent.get("skills") != ["workshop-planner"]
    or "workshop-planner" not in agent.get("uses", [])
):
    raise SystemExit("Invalid harness agent/skill manifest")
environment = arm(f"{ROOT}/rg-foundry-mai-audio-demo/providers/Microsoft.App/managedEnvironments/foundry-mai-audio-env")
if environment["properties"]["environmentMode"] != "Express":
    raise SystemExit("Existing environment is not Express")
deployments = az("cognitiveservices", "account", "deployment", "list", "-g", "rg-ai", "-n", "demo-swe")
if not any(item["name"] == "gpt-5.4" and item["properties"]["provisioningState"] == "Succeeded" for item in deployments):
    raise SystemExit("Existing gpt-5.4 deployment is missing")
print("Read-only preflight passed. No agent, infrastructure, role or reader setting was changed.")
