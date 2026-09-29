"""Generate the dataset: `python -m generator [--out DIR] [--config config.yaml]`.

Writes data/ (visible) and hidden/ (ground truth) under DIR (default: repo root).
"""

import argparse
import json
from pathlib import Path

from . import load_config, write_dataset


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    stats = write_dataset(Path(args.out), load_config(args.config))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
