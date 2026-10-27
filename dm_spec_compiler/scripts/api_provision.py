#!/usr/bin/env python3
"""api_provision.py — CLI wrapper for plugin_api.api_provision.

argv: <pyroot> <design> <infra> [apply]
"""
import sys
import json

sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_provision

def main():
    if len(sys.argv) < 4:
        print(json.dumps({"status": "error",
                          "error": "usage: api_provision.py <pyroot> <design> <infra> [apply]"}))
        sys.exit(1)
    apply_flag = len(sys.argv) > 4 and sys.argv[4].lower() == "true"
    res = api_provision(sys.argv[2], sys.argv[3], apply=apply_flag)
    print(json.dumps(res))

if __name__ == "__main__":
    main()
