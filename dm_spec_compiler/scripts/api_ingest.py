#!/usr/bin/env python3
"""api_ingest.py — CLI wrapper for plugin_api.api_ingest"""
import sys
import json

# Ensure the package is on sys.path
sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_ingest

def main():
    if len(sys.argv) < 4:
        print(json.dumps({"status": "error", "error": "usage: api_ingest.py <pyroot> <incoming> <spec_pack>"}))
        sys.exit(1)
    res = api_ingest(sys.argv[2], sys.argv[3])
    print(json.dumps(res))

if __name__ == "__main__":
    main()