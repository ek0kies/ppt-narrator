#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    runtime_src = _find_runtime_src()
    if runtime_src:
        sys.path.insert(0, str(runtime_src))
    from ppt_narrator.update import main as update_main

    return update_main()


def _find_runtime_src() -> Path | None:
    script_path = Path(__file__).resolve()
    for parent in script_path.parents:
        candidate = parent / "runtime" / "src"
        if (candidate / "ppt_narrator").is_dir():
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
