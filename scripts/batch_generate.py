#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idr_rocrate import IDRDecoder, ROCrateEncoder


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-generate RO-Crates from IDR study metadata files.")
    parser.add_argument(
        "--input-dir",
        default="examples",
        help="Directory to scan for idr*-study.txt files (default: examples)",
    )
    parser.add_argument(
        "--output-dir",
        default="ro-crates",
        help="Directory to write generated RO-Crates (default: ro-crates)",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    decoder = IDRDecoder()
    encoder = ROCrateEncoder()

    study_files = sorted(input_dir.rglob("idr*-study.txt"))
    if not study_files:
        raise SystemExit(f"No idr*-study.txt files found under {input_dir}")

    for study_path in study_files:
        metadata = decoder.decode(study_path)
        crate = encoder.encode(metadata)
        crate_dir = output_dir / study_path.stem
        crate_dir.mkdir(parents=True, exist_ok=True)
        output_path = crate_dir / "ro-crate-metadata.json"
        output_path.write_text(json.dumps(crate, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
