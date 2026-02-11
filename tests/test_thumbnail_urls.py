import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idr_rocrate import IDRDecoder, ROCrateEncoder


def _root_entity(crate: dict, accession: str) -> dict:
    root_id = f"https://idr.openmicroscopy.org/study/{accession}/"
    for entity in crate.get("@graph", []):
        if entity.get("@id") == root_id:
            return entity
    raise AssertionError(f"Root dataset {root_id} not found")


def test_thumbnail_urls_are_embeddable_render_thumbnail_links() -> None:
    metadata_text = "\n".join(
        [
            "Study Title\tExample Study",
            "Comment[IDR Study Accession]\tidr9999",
            "Screen Number\t1",
            "Screen Example Images\thttps://idr.openmicroscopy.org/webclient/?show=well-592362\thttps://idr.openmicroscopy.org/webclient/img_detail/1239777/",
            "Experiment Number\t1",
            "Experiment Example Images\thttps://idr.openmicroscopy.org/webclient/?show=image-3125701",
            "",
        ]
    )

    metadata = IDRDecoder().decode_text(metadata_text)
    crate = ROCrateEncoder().encode(metadata)
    root = _root_entity(crate, "idr9999")

    assert root["thumbnailUrl"] == [
        "https://idr.openmicroscopy.org/webgateway/render_thumbnail/1239777/?",
        "https://idr.openmicroscopy.org/webgateway/render_thumbnail/3125701/?",
    ]


def test_thumbnail_urls_are_deduplicated_and_canonicalized() -> None:
    metadata_text = "\n".join(
        [
            "Study Title\tExample Study",
            "Comment[IDR Study Accession]\tidr9998",
            "Screen Number\t1",
            "Screen Example Images\thttps://idr.openmicroscopy.org/webgateway/render_thumbnail/3125701/?\thttp://id.openmicroscopy.org/webclient/img_detail/3125701/\thttps://idr.openmicroscopy.org/webclient/?show=image-3125701",
            "",
        ]
    )

    metadata = IDRDecoder().decode_text(metadata_text)
    crate = ROCrateEncoder().encode(metadata)
    root = _root_entity(crate, "idr9998")

    assert root["thumbnailUrl"] == [
        "https://idr.openmicroscopy.org/webgateway/render_thumbnail/3125701/?"
    ]
