#!/usr/bin/env python3
"""api_compile.py — CLI wrapper for plugin_api.api_compile"""
import sys
import json

sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_compile

def main():
    if len(sys.argv) < 6:
        print(json.dumps({"status": "error", "error": "usage: api_compile.py <pyroot> <spec_pack> <design> <mesh_name> <dashboard> [incoming]"}))
        sys.exit(1)
    incoming = sys.argv[6] if len(sys.argv) > 6 else None
    res = api_compile(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], incoming)
    print(json.dumps(res))

if __name__ == "__main__":
    main()