import hashlib
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from content_package import (build_timeline, compute_processing_status, extract_keyframes, field_status, file_record,
                             find_existing_package, hash_similarity, image_metadata, migrate_content_package_in_memory,
                             new_content_package, resolve_active_error, safe_artifact_path, scene_boundaries,
                             select_structural_keyframes, should_reuse, srt, upsert_active_error,
                             validate_content_package, video_metadata)
from build_analysis_index import AnalysisIndexError, build_analysis_index, validate_analysis_index, write_analysis_index
from run_capture import _ocr_records, process_keyframes


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

    def test_legacy_v2_package_migrates_without_changing_input(self):
        legacy = new_content_package("completed", "https://example.test/note")
        for key in ("capture_status", "processing_status", "active_errors", "error_history"):
            legacy.pop(key, None)
        legacy["processing"] = {"transcribe": {"status": "failed"}}
        migrated, notes = migrate_content_package_in_memory(legacy)
        self.assertNotIn("capture_status", legacy)
        self.assertEqual(migrated["capture_status"], "completed")
        self.assertEqual(migrated["processing_status"], "failed")
        self.assertEqual(migrated["active_errors"][0]["stage"], "transcribe")
        self.assertIn("added:capture_status", notes)
        self.assertEqual(validate_content_package(migrated), [])

    def test_processing_status_aggregation(self):
        self.assertEqual(compute_processing_status({}), "not_run")
        self.assertEqual(compute_processing_status({"a": {"status": "completed"}}), "completed")
        self.assertEqual(compute_processing_status({"a": {"status": "failed"}}), "failed")
        self.assertEqual(compute_processing_status({"a": {"status": "completed"}, "b": {"status": "failed"}}), "partial")
        self.assertEqual(compute_processing_status({"a": {"status": "partial"}}), "partial")

    def test_active_error_is_resolved_into_history(self):
        package = new_content_package("completed", "https://example.test/note")
        upsert_active_error(package, stage="transcribe", code="engine_unavailable")
        upsert_active_error(package, stage="transcribe", code="engine_unavailable")
        resolve_active_error(package, stage="transcribe")
        self.assertEqual(package["active_errors"], [])
        self.assertEqual(len(package["error_history"]), 1)

    def test_status_must_match_capture_status(self):
        package = new_content_package("completed", "https://example.test/note")
        package["capture_status"] = "failed"
        self.assertIn("inconsistent:status_capture_status", validate_content_package(package))

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

    def test_video_metadata_declares_optional_audio_fields(self):
        metadata = video_metadata(Path("missing.mp4"))
        self.assertIn("audio_codec", metadata)
        self.assertIn("frame_rate", metadata)

    def test_finds_existing_package_by_note_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "20260804-010101"; run.mkdir()
            package = new_content_package("completed", "https://example.test/abc")
            package["source"]["note_id"] = "abc"
            (run / "content_package.json").write_text(__import__("json").dumps(package), encoding="utf-8")
            self.assertIsNone(find_existing_package(Path(temporary), "abc"))

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

    def test_filtered_ocr_text_keeps_only_confident_nonempty_lines(self):
        record = {"text": "原始", "lines": [
            {"text": "清晰标题", "confidence": .99},
            {"text": "误识别", "confidence": .31},
            {"text": " ", "confidence": 1.0},
        ]}
        from content_package import filtered_ocr_text
        self.assertEqual(filtered_ocr_text(record), "清晰标题")

    def test_ocr_records_keep_raw_text_and_add_filtered_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "media").mkdir(); (run / "media" / "cover.jpg").write_bytes(b"cover")
            with patch("run_capture.ocr_macos_batch", return_value=[{
                "status": "available", "text": "标题\n噪声",
                "lines": [{"text": "标题", "confidence": .95}, {"text": "噪声", "confidence": .2}],
            }]):
                records = _ocr_records(run, [{"path": "media/cover.jpg"}])
        self.assertEqual(records[0]["text"], "标题\n噪声")
        self.assertEqual(records[0]["filtered_text"], "标题")

    def test_scene_change_selection_is_deterministic_and_explained(self):
        from content_package import select_scene_change_frames
        frames = [
            {"id": "frame-001", "time_seconds": 0, "adjacent_similarity": None},
            {"id": "frame-002", "time_seconds": 30, "adjacent_similarity": .88},
            {"id": "frame-003", "time_seconds": 60, "adjacent_similarity": .41},
            {"id": "frame-004", "time_seconds": 90, "adjacent_similarity": .66},
        ]
        selected = select_scene_change_frames(frames, threshold=.72, limit=2)
        self.assertEqual([item["frame_ref"] for item in selected], ["frame-003", "frame-004"])
        self.assertTrue(all(item["selection_basis"] == "adjacent_perceptual_hash" for item in selected))

    def test_evidence_segments_link_facts_without_semantic_claims(self):
        from content_package import build_evidence_segments
        segments = build_evidence_segments(
            [{"start": 0, "end": 8, "text": "今天讲三个方法"}],
            [{"id": "frame-001", "path": "derived/keyframes/001.jpg", "time_seconds": 3}],
            [{"frame_ref": "frame-001", "time_seconds": 3}],
            {"keyframes": [{"path": "derived/keyframes/001.jpg", "text": "三个方法"}]},
        )
        self.assertEqual(segments[0]["kind"], "fact")
        self.assertEqual(segments[0]["transcript_refs"], ["speech-001"])
        self.assertEqual(segments[0]["frame_refs"], ["frame-001"])
        self.assertEqual(segments[0]["ocr_refs"], ["ocr-frame-001"])
        self.assertNotIn("label", segments[0])

    def test_interpretation_keeps_evidence_reference_and_declares_inference(self):
        from content_package import rule_based_interpretations
        items = rule_based_interpretations([{
            "id": "evidence-001", "kind": "fact", "start": 0, "end": 4,
            "transcript_text": "先说一个很多人都会遇到的问题",
        }])
        self.assertEqual(items[0]["kind"], "inference")
        self.assertEqual(items[0]["label"], "problem")
        self.assertEqual(items[0]["evidence_refs"], ["evidence-001"])
        self.assertEqual(items[0]["method"], "rule_based_v1")

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

    def test_analysis_index_projects_facts_and_inferences_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            package = new_content_package("completed", "https://example.test/note")
            package["derived"]["evidence_segments"] = [{"id": "evidence-001", "kind": "fact", "start": 0, "end": 4}]
            package["derived"]["interpretations"] = [{"id": "inference-evidence-001", "kind": "inference", "label": "hook", "evidence_refs": ["evidence-001"]}]
            (run / "content_package.json").write_text(json.dumps(package), encoding="utf-8")
            index = build_analysis_index(run)
        self.assertEqual(index["evidence_segments"][0]["kind"], "fact")
        self.assertEqual(index["interpretations"][0]["kind"], "inference")
        self.assertEqual(index["analysis_readiness"]["evidence"], "ready")

    def test_analysis_index_rejects_invalid_package_and_keeps_previous_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary); (run / "derived").mkdir()
            (run / "content_package.json").write_text("{}", encoding="utf-8")
            target = run / "derived" / "analysis_index.json"; target.write_text('{"previous":true}', encoding="utf-8")
            with self.assertRaises(AnalysisIndexError): write_analysis_index(run)
            self.assertEqual(json.loads(target.read_text()), {"previous": True})

    def test_first_keyframe_stage_does_not_read_list_as_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = new_content_package("completed", "https://example.test/n")
            result["media"]["video"] = {"path": "media/missing.mp4"}
            process_keyframes(result, Path(temporary), enabled=True)
            self.assertEqual(result["derived"]["keyframes"], [])

    def test_available_keyframes_complete_the_processing_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "media").mkdir(); (run / "media" / "video.mp4").write_bytes(b"video")
            (run / "derived" / "keyframes").mkdir(parents=True); (run / "derived" / "keyframes" / "001.jpg").write_bytes(b"frame")
            result = new_content_package("completed", "https://example.test/n")
            result["media"]["video"] = {"path": "media/video.mp4"}
            upsert_active_error(result, stage="extract_keyframes", code="extract_keyframes_failed")
            with patch("run_capture.extract_keyframes", return_value={"status": "available", "frames": [{"path": "001.jpg", "time_seconds": 0}]}):
                process_keyframes(result, run, enabled=True)
            self.assertEqual(result["processing"]["extract_keyframes"]["status"], "completed")
            self.assertFalse(any(item["stage"] == "extract_keyframes" for item in result["active_errors"]))

    def test_safe_artifact_path_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError): safe_artifact_path(Path(temporary), "../../secret.json")
            with self.assertRaises(ValueError): safe_artifact_path(Path(temporary), None)

    def test_unsafe_cached_package_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "bad"; run.mkdir()
            package = new_content_package("completed", "https://example.test/n")
            package["source"]["note_id"] = "note"; package["media"]["video"] = {"path": "../../outside.mp4", "sha256": "bad"}
            (run / "content_package.json").write_text(json.dumps(package), encoding="utf-8")
            self.assertIsNone(find_existing_package(Path(temporary), "note"))

    def test_empty_completed_transcript_is_a_real_zero(self):
        package = new_content_package("completed", "https://example.test/n")
        package["media"]["video"] = {"path": "media/video.mp4"}
        package["transcript"] = []
        package["processing"]["transcribe"] = {"status": "completed"}
        from run_capture import recompute_completeness
        recompute_completeness(package)
        self.assertEqual(package["completeness"]["transcript"]["status"], "zero")

    def test_capture_manifest_is_written_before_local_processing(self):
        import run_capture
        with tempfile.TemporaryDirectory() as temporary:
            package = new_content_package("completed", "https://example.test/n")
            with patch("run_capture.capture_public_note", return_value=package), \
                 patch("run_capture.process_local_stages", side_effect=lambda _p, run, **_k: self.assertTrue((run / "content_package.json").is_file())):
                self.assertEqual(run_capture.main(["--url", "https://example.test/n", "--run-dir", temporary]), 0)


if __name__ == "__main__":
    unittest.main()
