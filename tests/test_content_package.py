import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from content_package import field_status, file_record, find_existing_package, image_metadata, should_reuse, srt, video_metadata


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

    def test_image_metadata_reads_png_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pixel.png"
            path.write_bytes(bytes.fromhex("89504e470d0a1a0a0000000d494844520000000200000003080200000000000000"))
            self.assertEqual(image_metadata(path), {"format": "png", "width": 2, "height": 3})

    def test_image_metadata_reads_jpeg_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pixel.jpg"
            path.write_bytes(bytes.fromhex("ffd8ffc00011080003000203011100021101031101ffd9"))
            self.assertEqual(image_metadata(path), {"format": "jpeg", "width": 2, "height": 3})

    def test_image_metadata_reads_webp_vp8x_dimensions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pixel.webp"
            path.write_bytes(b"RIFF\x1a\x00\x00\x00WEBPVP8X" + b"\x0a\x00\x00\x00" + bytes([0, 0, 0, 0, 1, 0, 0, 2, 0, 0]))
            self.assertEqual(image_metadata(path), {"format": "webp", "width": 2, "height": 3})

    def test_video_metadata_reports_unavailable_without_pyav(self):
        self.assertEqual(video_metadata(Path("missing.mp4"))["status"], "failed")

    def test_finds_existing_package_by_note_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "20260804-010101"; run.mkdir()
            (run / "content_package.json").write_text('{"source":{"note_id":"abc"}}', encoding="utf-8")
            self.assertEqual(find_existing_package(Path(temporary), "abc"), run)

    def test_force_disables_package_reuse(self):
        self.assertTrue(should_reuse(Path("run"), force=False))
        self.assertFalse(should_reuse(Path("run"), force=True))


if __name__ == "__main__":
    unittest.main()
