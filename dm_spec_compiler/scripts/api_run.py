#!/usr/bin/env python3
"""api_run.py — CLI wrapper for plugin_api.api_run.

argv: <pyroot> <incoming> <spec_pack> <design> <target> <infra> <mesh_name> <assume_yes>
"""
import sys
import json

sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_run

def main():
    if len(sys.argv) < 9:
        print(json.dumps({"status": "error",
                          "error": "usage: api_run.py <pyroot> <incoming> <spec_pack> <design> <target> <infra> <mesh_name> <assume_yes>"}))
        sys.exit(1)
    assume_yes = sys.argv[8].lower() == "true"
    res = api_run(incoming=sys.argv[2], spec_pack=sys.argv[3], design=sys.argv[4],
                  target=sys.argv[5], infra=sys.argv[6], mesh_name=sys.argv[7],
                  assume_yes=assume_yes)
    print(json.dumps(res))

if __name__ == "__main__":
    main()
