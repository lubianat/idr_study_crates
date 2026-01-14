#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import date
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
    parser.add_argument(
        "--no-index-crate",
        action="store_true",
        help="Skip generating an index RO-Crate that links to all subcrates",
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

    subcrates = []
    for study_path in study_files:
        metadata = decoder.decode(study_path)
        crate = encoder.encode(metadata)
        crate_dir = output_dir / study_path.stem
        crate_dir.mkdir(parents=True, exist_ok=True)
        output_path = crate_dir / "ro-crate-metadata.json"
        output_path.write_text(json.dumps(crate, indent=2, ensure_ascii=False), encoding="utf-8")
        subcrates.append((crate_dir, crate))

    if args.no_index_crate:
        return

    index_crate = build_index_crate(output_dir, subcrates)
    index_path = output_dir / "ro-crate-metadata.json"
    index_path.write_text(json.dumps(index_crate, indent=2, ensure_ascii=False), encoding="utf-8")


def build_index_crate(output_dir: Path, subcrates) -> dict:
    graph = []
    graph.append(
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
            "about": {"@id": "./"},
            "description": "Index RO-Crate metadata document",
        }
    )

    root = {
        "@id": "./",
        "@type": "Dataset",
        "name": "IDR study RO-Crates",
        "description": "Index of RO-Crates generated from IDR study metadata.",
        "datePublished": date.today().isoformat(),
        "hasPart": [],
    }

    for crate_dir, crate in subcrates:
        crate_rel = crate_dir.relative_to(output_dir).as_posix() + "/"
        root_entry = extract_root_entity(crate)
        entity = {
            "@id": crate_rel,
            "@type": "Dataset",
            "conformsTo": {"@id": "https://w3id.org/ro/crate"},
            "subjectOf": {"@id": f"{crate_rel}ro-crate-metadata.json"},
        }
        if root_entry:
            name = root_entry.get("name")
            description = root_entry.get("description")
            identifier = root_entry.get("@id")
            if name:
                entity["name"] = name
            if description:
                entity["description"] = description
            if identifier and identifier.startswith("http"):
                entity["identifier"] = identifier
        root["hasPart"].append({"@id": crate_rel})
        graph.append(entity)
        graph.append(
            {
                "@id": f"{crate_rel}ro-crate-metadata.json",
                "@type": "CreativeWork",
                "encodingFormat": "application/ld+json",
            }
        )

    graph.append(root)
    return {
        "@context": "https://w3id.org/ro/crate/1.2/context",
        "@graph": graph,
    }


def extract_root_entity(crate: dict) -> dict | None:
    graph = crate.get("@graph", [])
    if not isinstance(graph, list):
        return None
    entity_map = {entity.get("@id"): entity for entity in graph if isinstance(entity, dict) and entity.get("@id")}
    descriptor = entity_map.get("ro-crate-metadata.json")
    if descriptor and isinstance(descriptor.get("about"), dict):
        root_id = descriptor["about"].get("@id")
        if root_id and root_id in entity_map:
            return entity_map[root_id]
    return None


if __name__ == "__main__":
    main()
