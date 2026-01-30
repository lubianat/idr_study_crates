#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = ["tqdm>=4.60", "rdflib>=6.0"] # rdflib is optional for --ttl-out.
# ///
import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idr_rocrate import IDRDecoder, ROCrateEncoder

RO_CRATE_CONTEXT_URL = "https://w3id.org/ro/crate/1.2/context"
# READ the JSON-LD context from scripts/ro-crate-context.json
RO_CRATE_CONTEXT_FALLBACK_PATH = ROOT / "scripts" / "ro-crate-context.json"

with RO_CRATE_CONTEXT_FALLBACK_PATH.open(encoding="utf-8") as f:
    RO_CRATE_CONTEXT_FALLBACK = json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-generate RO-Crates from IDR study metadata files."
    )
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
    parser.add_argument(
        "--ttl-out",
        default=None,
        help="Write merged Turtle output for all generated crates (requires rdflib)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-crate progress details",
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

    try:
        from tqdm import tqdm
    except ImportError as exc:
        raise SystemExit(
            "tqdm is required for progress output. Run with `uv run` or install via `python3 -m pip install tqdm`."
        ) from exc

    progress = tqdm(
        study_files,
        desc=f"Generating {len(study_files)} RO-Crates",
        unit="study",
        disable=not sys.stderr.isatty(),
    )

    def log(message: str) -> None:
        if not args.verbose:
            return
        progress.write(message)

    log(f"Found {len(study_files)} study metadata files under {input_dir}")
    log(f"Writing RO-Crates to {output_dir}")

    subcrates = []
    for study_path in progress:
        metadata = decoder.decode(study_path)
        crate = encoder.encode(metadata)
        crate_dir = output_dir / study_path.stem
        crate_dir.mkdir(parents=True, exist_ok=True)
        output_path = crate_dir / "ro-crate-metadata.json"
        output_path.write_text(
            json.dumps(crate, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log(f"Wrote {output_path}")
        subcrates.append((crate_dir, crate))

    index_path: Optional[Path] = None
    if not args.no_index_crate:
        index_crate = build_index_crate(output_dir, subcrates)
        index_path = output_dir / "ro-crate-metadata.json"
        index_path.write_text(
            json.dumps(index_crate, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log(f"Wrote index crate to {index_path}")

    if args.ttl_out:
        ttl_path = Path(args.ttl_out)
        write_merged_ttl(ttl_path, subcrates, index_path)
        log(f"Wrote merged Turtle to {ttl_path}")


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


def write_merged_ttl(output_path: Path, subcrates, index_path: Optional[Path]) -> None:
    try:
        from rdflib import Graph
    except ImportError as exc:
        raise SystemExit(
            "rdflib is required to write Turtle output. Run with `uv run` or install via `python3 -m pip install rdflib`."
        ) from exc

    from rdflib.plugins.shared.jsonld import context as jsonld_context

    graph = Graph()
    original_fetch = jsonld_context.Context._fetch_context

    def _fetch_context(self, source: str, base: Optional[str], referenced_contexts):  # type: ignore[no-untyped-def]
        source_url = urljoin(base or "", source)
        if source_url == RO_CRATE_CONTEXT_URL:
            return RO_CRATE_CONTEXT_FALLBACK
        return original_fetch(self, source, base, referenced_contexts)

    jsonld_context.Context._fetch_context = _fetch_context
    try:
        if index_path is not None:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
            index_base = crate_base_iri(index_data, index_path.resolve().as_uri())
            graph.parse(
                data=json.dumps(index_data), format="json-ld", publicID=index_base
            )

        for crate_dir, crate in subcrates:
            crate_path = (crate_dir / "ro-crate-metadata.json").resolve()
            crate_base = crate_base_iri(crate, crate_path.as_uri())
            graph.parse(data=json.dumps(crate), format="json-ld", publicID=crate_base)
    finally:
        jsonld_context.Context._fetch_context = original_fetch

    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(output_path), format="turtle")


def extract_root_entity(crate: dict) -> dict | None:
    graph = crate.get("@graph", [])
    if not isinstance(graph, list):
        return None
    entity_map = {
        entity.get("@id"): entity
        for entity in graph
        if isinstance(entity, dict) and entity.get("@id")
    }
    descriptor = entity_map.get("ro-crate-metadata.json")
    if descriptor and isinstance(descriptor.get("about"), dict):
        root_id = descriptor["about"].get("@id")
        if root_id and root_id in entity_map:
            return entity_map[root_id]
    return None


def crate_base_iri(crate: dict, fallback: str) -> str:
    root_entity = extract_root_entity(crate)
    root_id = root_entity.get("@id") if root_entity else None
    if root_id and urlparse(root_id).scheme:
        return root_id
    return fallback


if __name__ == "__main__":
    main()
