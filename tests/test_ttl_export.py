import json
import sys
from pathlib import Path

import pytest

rdflib = pytest.importorskip("rdflib")
from rdflib import Graph, URIRef

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from batch_generate import write_merged_ttl


def build_minimal_crate(study_id: str) -> dict:
    study_uri = f"https://idr.openmicroscopy.org/study/{study_id}/"
    return {
        "@context": {
            "@vocab": "http://schema.org/",
            "about": {"@id": "http://schema.org/about", "@type": "@id"},
            "conformsTo": {"@id": "http://purl.org/dc/terms/conformsTo", "@type": "@id"},
        },
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
                "about": {"@id": study_uri},
            },
            {
                "@id": study_uri,
                "@type": "Dataset",
                "name": f"Study {study_id}",
            },
        ],
    }


def test_write_merged_ttl(tmp_path: Path) -> None:
    output_dir = tmp_path / "ro-crates"
    output_dir.mkdir(parents=True, exist_ok=True)

    subcrates = []
    for study_id in ("idr0001", "idr0002"):
        crate = build_minimal_crate(study_id)
        crate_dir = output_dir / study_id
        crate_dir.mkdir(parents=True, exist_ok=True)
        output_path = crate_dir / "ro-crate-metadata.json"
        output_path.write_text(json.dumps(crate, indent=2), encoding="utf-8")
        subcrates.append((crate_dir, crate))

    ttl_path = output_dir / "merged.ttl"
    write_merged_ttl(ttl_path, subcrates, index_path=None)

    assert ttl_path.exists()
    assert ttl_path.stat().st_size > 0

    graph = Graph()
    graph.parse(str(ttl_path), format="turtle")
    for study_id in ("idr0001", "idr0002"):
        study_uri = URIRef(f"https://idr.openmicroscopy.org/study/{study_id}/")
        descriptor_uri = URIRef(f"https://idr.openmicroscopy.org/study/{study_id}/ro-crate-metadata.json")
        assert any(graph.triples((study_uri, None, None)))
        assert any(graph.triples((descriptor_uri, None, None)))
