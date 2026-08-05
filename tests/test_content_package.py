import hashlib
import sys
import tempfile
import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from content_package import build_timeline, extract_keyframes, field_status, file_record, find_existing_package, hash_similarity, image_metadata, new_content_package, safe_artifact_path, scene_boundaries, select_structural_keyframes, should_reuse, srt, validate_content_package, video_metadata
from build_analysis_index import build_analysis_index, validate_analysis_index, write_analysis_index
from run_capture import process_keyframes


class ContentPackageTests(unittest.TestCase):
    def test_field_status_distinguishes_zero_from_missing(self):
        self.assertEqual(field_status(0)["status"], "zero")
        self.assertEqual(field_status(None)["status"], "not_exposed")
        self.assertEqual(field_status("title")["status"], "available")
        self.assertEqual(field_status([])["status"], "not_exposed")

    def test_all_statuses_share_a_valid_package_contract(self):
        for status in ("completed", "partial", "failed"):
            with self.subTest(status=status):
                self.assertEqual(validate_content_package(new_content_package(status, "https://example.test/note")), [])

    def test_file_record_has_size_and_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "item.txt"
            path.write_bytes(b"content")
            self.assertEqual(file_record(path)["size_bytes"], 7)
            self.assertEqual(file_record(path)["sha256"], hashlib.sha256(b"content").hexdigest())
            self.assertEqual(file_record(path, Path(temporary))["path"], "item.txt")

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
            package = new_content_package("completed", "https://example.test/abc")
            package["source"]["note_id"] = "abc"
            (run / "content_package.json").write_text(__import__("json").dumps(package), encoding="utf-8")
            self.assertEqual(find_existing_package(Path(temporary), "abc"), run)

    def test_force_disables_package_reuse(self):
        self.assertTrue(should_reuse(Path("run"), force=False))
        self.assertFalse(should_reuse(Path("run"), force=True))

    def test_keyframe_extraction_reports_missing_video(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(extract_keyframes(Path("missing.mp4"), Path(temporary))["status"], "failed")

    def test_structural_selection_prefers_hook_and_text_rich_change(self):
        frames = [{"id": "frame-001", "path": "001.jpg", "time_seconds": 2, "ocr": {"text": "开头承诺"}}, {"id": "frame-002", "path": "002.jpg", "time_seconds": 30, "ocr": {"text": ""}}, {"id": "frame-003", "path": "003.jpg", "time_seconds": 60, "ocr": {"text": "第一步 方法 清单"}}]
        selected = select_structural_keyframes(frames, duration_seconds=90, limit=2)
        self.assertEqual([item["path"] for item in selected], ["001.jpg", "003.jpg"])
        self.assertIn("reasons", selected[0])

    def test_timeline_attaches_frame_to_overlapping_speech(self):
        timeline = build_timeline([{"start": 0, "end": 5, "text": "开头"}], [{"id": "frame-001", "path": "001.jpg", "time_seconds": 2, "ocr": {"text": "标题"}}])
        self.assertEqual({item["type"] for item in timeline["events"]}, {"speech", "frame", "ocr"})

    def test_scene_boundaries_report_visual_change(self):
        frames = [{"path": "001.jpg", "perceptual_hash": "0000000000000000"}, {"path": "002.jpg", "perceptual_hash": "ffffffffffffffff"}]
        self.assertEqual(len(scene_boundaries(frames, threshold=.8)), 2)
        self.assertEqual(frames[1]["adjacent_similarity"], 0.0)
        self.assertEqual(hash_similarity("0000000000000000", "ffffffffffffffff"), 0.0)

    def test_analysis_index_is_local_and_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary); package = new_content_package("partial", "https://example.test/note")
            (run / "content_package.json").write_text(__import__("json").dumps(package), encoding="utf-8")
            index = build_analysis_index(run)
            self.assertEqual(validate_analysis_index(index), [])
            self.assertTrue(index["quality"]["package_valid"])

    def test_analysis_index_rejects_invalid_package_and_keeps_previous_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary); (run / "derived").mkdir()
            (run / "content_package.json").write_text("{}", encoding="utf-8")
            target = run / "derived" / "analysis_index.json"; target.write_text('{"previous":true}', encoding="utf-8")
            with self.assertRaises(ValueError): write_analysis_index(run)
            self.assertEqual(json.loads(target.read_text()), {"previous": True})

    def test_first_keyframe_stage_does_not_read_list_as_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = new_content_package("completed", "https://example.test/n")
            result["media"]["video"] = {"path": "media/missing.mp4"}
            process_keyframes(result, Path(temporary), enabled=True)
            self.assertEqual(result["derived"]["keyframes"], [])

    def test_safe_artifact_path_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError): safe_artifact_path(Path(temporary), "../../secret.json")

    def test_empty_completed_transcript_is_a_real_zero(self):
        package = new_content_package("completed", "https://example.test/n")
        package["media"]["video"] = {"path": "media/video.mp4"}
        package["transcript"] = []
        package["processing"]["transcribe"] = {"status": "completed"}
        from run_capture import recompute_completeness
        recompute_completeness(package)
        self.assertEqual(package["completeness"]["transcript"]["status"], "zero")


if __name__ == "__main__":
    unittest.main()
