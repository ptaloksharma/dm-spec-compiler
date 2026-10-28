#!/usr/bin/env python3
"""api_refine.py — CLI wrapper for plugin_api.api_refine (conversational design edit)"""
import sys
import json

sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_refine


def main():
    if len(sys.argv) < 4:
        print(json.dumps({"status": "error",
                          "error": "usage: api_refine.py <pyroot> <design> <instruction> [dashboard]"}))
        sys.exit(1)
    design = sys.argv[2]
    instruction = sys.argv[3]
    dashboard = sys.argv[4] if len(sys.argv) > 4 else None
    res = api_refine(design, instruction, dashboard=dashboard if dashboard else None)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
