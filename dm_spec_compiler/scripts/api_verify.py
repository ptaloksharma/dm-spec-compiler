#!/usr/bin/env python3
"""api_verify.py — CLI wrapper for plugin_api.api_verify"""
import sys
import json

sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_verify

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"status": "error", "error": "usage: api_verify.py <pyroot> <target> [design]"}))
        sys.exit(1)
    target = sys.argv[2]
    design = sys.argv[3] if len(sys.argv) > 3 else None
    res = api_verify(sys.argv[2], design if design else None)
    print(json.dumps(res))

if __name__ == "__main__":
    main()