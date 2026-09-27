#!/usr/bin/env python3
"""Remove only the clock fields declared for one dashboard output."""
import json
import sys
from pathlib import Path


def strip_output(output_path: str, payload, contract: dict):
    spec = contract["outputs"][output_path]
    recursive = set(spec.get("recursive_clock_fields", []))
    top_level = set(spec.get("top_level_clock_fields", []))

    def strip(node, *, top=False):
        if isinstance(node, dict):
            return {key: strip(value) for key, value in node.items()
                    if key not in recursive and not (top and key in top_level)}
        if isinstance(node, list):
            return [strip(value) for value in node]
        return node

    return strip(payload, top=True)


def main() -> None:
    output_path = sys.argv[1]
    contract = json.loads(Path("config/dashboard-outputs.json").read_text())
    payload = json.loads(Path(output_path).read_text())
    print(json.dumps(strip_output(output_path, payload, contract), sort_keys=True))


if __name__ == "__main__":
    main()
