#!/usr/bin/env python3
"""api_events.py — CLI wrapper for plugin_api.api_events (System Logs & Alerts)."""
import sys
import json

sys.path.insert(0, sys.argv[1])

from dm_spec_compiler.plugin_api import api_events


def main():
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    channel = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
    print(json.dumps(api_events(limit=limit, channel=channel)))


if __name__ == "__main__":
    main()
