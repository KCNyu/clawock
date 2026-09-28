#!/usr/bin/env python3
"""Small, read-only view of the full snapshot still used by the filing gate."""
import json
import os
import sys
from pathlib import Path


def select(issues, terms):
    if not terms:
        return [i for i in issues if i.get("state") == "OPEN"]
    words = [term.casefold() for term in terms]
    return [i for i in issues if any(word in i.get("title", "").casefold()
                                    or word == str(i.get("number")) for word in words)]


def main():
    path = Path(os.environ.get("PATROL_STATE", "/root/logs/clawock-patrol")) / "issue_snapshot.json"
    issues = json.loads(path.read_text())["all"]
    terms = sys.argv[1:]
    matched = select(issues, terms)
    # All open issues are relevant; a keyword query is bounded and reports omissions.
    shown = matched[:20] if terms else matched
    print(f"{'Title matches' if terms else 'Open issues'}: {len(matched)}; snapshot: {path}")
    for issue in shown:
        print(f"#{issue['number']} [{issue['state']}/{issue.get('stateReason') or '-'}] {issue['title']}")
    if len(matched) > len(shown):
        print(f"{len(matched) - len(shown)} more; refine keywords or inspect the snapshot. The gate checks the full snapshot.")
    if terms and not matched:
        print("No title match is not proof of uniqueness; inspect related history and let the gate check the full snapshot.")


if __name__ == "__main__":
    main()
