"""Deterministic workshop calculation, runnable in the managed harness sandbox."""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys

FIELDS = ["id", "name", "capacity", "projector", "rental_czk", "catering_per_person_czk"]
PEOPLE = 12
LIMIT = Decimal("25000")
RESERVE = Decimal("0.10")


def calculate(path: Path) -> dict:
    offers = []
    seen = set()
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"CSV columns must be exactly {','.join(FIELDS)}")
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None or not value.strip() for value in row.values()):
                raise ValueError(f"Row {line}: missing or extra values")
            identifier = row["id"]
            if identifier in seen or not identifier.isascii() or not identifier.isalnum():
                raise ValueError(f"Row {line}: offer ID must be unique ASCII letters/digits")
            seen.add(identifier)
            if not row["capacity"].isascii() or not row["capacity"].isdigit():
                raise ValueError(f"Row {line}: capacity must be a positive integer")
            capacity = int(row["capacity"])
            if not 1 <= capacity <= 10000 or len(row["name"]) > 100:
                raise ValueError(f"Row {line}: invalid capacity or name")
            if row["projector"] not in {"true", "false"}:
                raise ValueError(f"Row {line}: projector must be true or false")
            prices = []
            for key in ("rental_czk", "catering_per_person_czk"):
                try:
                    amount = Decimal(row[key])
                except InvalidOperation as exc:
                    raise ValueError(f"Row {line}: {key} must be a finite CZK amount") from exc
                if (
                    not amount.is_finite() or amount < 0 or amount > 10000000
                    or amount != amount.quantize(Decimal("0.01"))
                ):
                    raise ValueError(f"Row {line}: {key} must be nonnegative with at most two decimals")
                prices.append(amount)
            base = prices[0] + PEOPLE * prices[1]
            total = (base * (1 + RESERVE)).quantize(Decimal("0.01"))
            reasons = []
            if capacity < PEOPLE:
                reasons.append("capacity")
            if row["projector"] != "true":
                reasons.append("projector")
            if total > LIMIT:
                reasons.append("budget")
            offers.append({
                "id": identifier, "name": row["name"], "capacity": capacity,
                "projector": row["projector"] == "true", "base_czk": str(base),
                "total_czk": str(total), "eligible": not reasons, "reasons": reasons,
            })
    if not offers or len(offers) > 100:
        raise ValueError("CSV must contain between 1 and 100 offers")
    eligible = sorted(
        (offer for offer in offers if offer["eligible"]),
        key=lambda offer: (Decimal(offer["total_czk"]), offer["id"]),
    )
    return {
        "fictional": True, "people": PEOPLE, "limit_czk": str(LIMIT),
        "reserve_percent": 10, "offers": offers,
        "winner": eligible[0]["id"] if eligible else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("offers", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = calculate(args.offers)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "budget.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        with (args.output_dir / "budget.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["id", "base_czk", "total_czk", "eligible", "reasons"])
            writer.writeheader()
            for offer in result["offers"]:
                writer.writerow({
                    key: ";".join(offer[key]) if key == "reasons" else offer[key]
                    for key in writer.fieldnames
                })
    except (OSError, ValueError, InvalidOperation) as exc:
        print(f"Workshop calculation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
