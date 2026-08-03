#!/usr/bin/env python3
"""Thin alias into ``share_onboard`` interactive cold-start CLI.

Canonical entry: ``python -m share_onboard``
Alias:            ``python onboard_cli.py``

Do not invent a second installer stack — both paths call the same module.
"""

from __future__ import annotations

import sys

import share_onboard


def main(argv=None) -> int:
    return share_onboard.main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
