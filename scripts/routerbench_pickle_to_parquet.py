#!/usr/bin/env python3
"""One-time converter: RouterBench HF pickle -> parquet, so the scorer never unpickles again.

Unpickling runs arbitrary code; only convert a copy you downloaded yourself from the
official HF repo. Requires an explicit --allow-pickle flag.
"""
import argparse
import sys
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", help="local RouterBench .pkl/.pickle")
    ap.add_argument("dst", nargs="?", help="output .parquet (default: SRC with .parquet suffix)")
    ap.add_argument("--allow-pickle", action="store_true", help="required: acknowledge unpickling runs code")
    a = ap.parse_args(argv)
    if not a.allow_pickle:
        raise SystemExit("refusing to unpickle without --allow-pickle (pickle loading runs arbitrary code)")
    src = Path(a.src).expanduser()
    if src.suffix.lower() not in (".pkl", ".pickle"):
        raise SystemExit(f"expected a .pkl/.pickle file: {src}")
    dst = Path(a.dst).expanduser() if a.dst else src.with_suffix(".parquet")
    import pandas as pd
    pd.read_pickle(src).to_parquet(dst)
    print(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
