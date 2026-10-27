#!/usr/bin/env python3
"""api_emit.py — CLI wrapper for plugin_api.api_emit"""
import sys
import json

sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_emit

def main():
    if len(sys.argv) < 5:
        print(json.dumps({"status": "error", "error": "usage: api_emit.py <pyroot> <design> <target> <agents_csv> <force>"}))
        sys.exit(1)
    agents_csv = sys.argv[4]
    agents = agents_csv.split(",") if agents_csv else None
    force = sys.argv[5] == "true"
    res = api_emit(sys.argv[2], sys.argv[3], agents, force)
    print(json.dumps(res))

if __name__ == "__main__":
    main()