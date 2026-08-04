import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from content_package import field_status, file_record, srt


class ContentPackageTests(unittest.TestCase):
    def test_field_status_distinguishes_zero_from_missing(self):
        self.assertEqual(field_status(0), "zero")
        self.assertEqual(field_status(None), "not_exposed")
        self.assertEqual(field_status("title"), "available")

    def test_file_record_has_size_and_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "item.txt"
            path.write_bytes(b"content")
            self.assertEqual(file_record(path)["size_bytes"], 7)
            self.assertEqual(file_record(path)["sha256"], hashlib.sha256(b"content").hexdigest())

    def test_srt_formats_timestamped_segments(self):
        self.assertEqual(srt([{"start": 0, "end": 1.2, "text": "你好"}]), "1\n00:00:00,000 --> 00:00:01,200\n你好\n")


if __name__ == "__main__":
    unittest.main()
