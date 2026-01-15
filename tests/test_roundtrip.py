import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idr_rocrate import IDRDecoder, ROCrateDecoder, ROCrateEncoder


def rows_signature(rows):
    return [(row.key, row.values) for row in rows]


def assert_roundtrip(input_path: Path) -> None:
    metadata = IDRDecoder().decode(input_path)
    study_rows, _ = metadata.split_study_rows()
    crate = ROCrateEncoder().encode(metadata)
    serialized = json.loads(json.dumps(crate, ensure_ascii=False))
    recovered = ROCrateDecoder().decode_data(serialized)
    recovered_study, _ = recovered.split_study_rows()
    assert rows_signature(study_rows) == rows_signature(recovered_study)


@pytest.mark.parametrize(
    "input_path",
    [
        ROOT / "examples" / "idr0001.txt",
        ROOT / "examples" / "idr0002.txt",
    ],
)
def test_roundtrip(input_path: Path) -> None:
    assert_roundtrip(input_path)
