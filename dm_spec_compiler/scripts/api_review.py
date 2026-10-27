#!/usr/bin/env python3
"""api_review.py — CLI wrapper for plugin_api.api_review_status / api_approve"""
import sys
import json

sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_review_status, api_approve

def main():
    if len(sys.argv) < 4:
        print(json.dumps({"status": "error", "error": "usage: api_review.py <pyroot> <design> <assume_yes> [dashboard]"}))
        sys.exit(1)
    design = sys.argv[2]
    assume_yes = sys.argv[3] == "true"
    dashboard = sys.argv[4] if len(sys.argv) > 4 else None

    # Check status first
    status = api_review_status(design)
    if status.get("data", {}).get("approved"):
        print(json.dumps(status))
        return

    # Not approved → attempt approval
    res = api_approve(design, assume_yes=assume_yes, dashboard=dashboard if dashboard else None)
    print(json.dumps(res))

if __name__ == "__main__":
    main()