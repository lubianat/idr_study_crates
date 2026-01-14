import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idr_rocrate import IDRDecoder, ROCrateDecoder, ROCrateEncoder


def rows_signature(rows):
    return [(row.key, row.values) for row in rows]


class RoundTripTests(unittest.TestCase):
    def assert_roundtrip(self, input_path: Path) -> None:
        metadata = IDRDecoder().decode(input_path)
        study_rows, _ = metadata.split_study_rows()
        crate = ROCrateEncoder().encode(metadata)
        serialized = json.loads(json.dumps(crate, ensure_ascii=False))
        recovered = ROCrateDecoder().decode_data(serialized)
        recovered_study, _ = recovered.split_study_rows()
        self.assertEqual(rows_signature(study_rows), rows_signature(recovered_study))

    def test_idr0001_roundtrip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assert_roundtrip(root / "examples" / "idr0001.txt")

    def test_idr0002_roundtrip(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assert_roundtrip(root / "examples" / "idr0002.txt")


if __name__ == "__main__":
    unittest.main()
