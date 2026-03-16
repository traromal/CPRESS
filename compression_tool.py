#!/usr/bin/env python3
"""
Compatibility wrapper: run the packaged cpress CLI.
"""
from cpress.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
