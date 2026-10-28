#!/usr/bin/env python3
"""api_tokens.py — CLI wrapper for plugin_api.api_tokens (Token Economics)."""
import sys
import json

sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_tokens


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"status": "error", "error": "usage: api_tokens.py <pyroot> <design>"}))
        sys.exit(1)
    print(json.dumps(api_tokens(sys.argv[2])))


if __name__ == "__main__":
    main()
