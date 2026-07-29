"""Offline tests for the public HTML feasibility experiment."""
import sys
import tempfile
import unittest
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_DIR))

from capture_public_mvp import (
    InitialStateNotFoundError,
    InvalidUrlError,
    extract_initial_state,
    error_code_for,
    find_note_object,
    main,
    normalize_note,
    resolve_note_id,
    select_candidate,
    validate_public_url,
    video_candidates,
    validate_media_file,
)


class UrlSafetyTests(unittest.TestCase):
    def test_accepts_supported_public_xhs_urls(self):
        self.assertEqual(
            resolve_note_id("https://www.xiaohongshu.com/explore/64fe12ab?xsec_token=abc"),
            "64fe12ab",
        )
        self.assertEqual(
            resolve_note_id("https://www.xiaohongshu.com/discovery/item/64fe12ab"),
            "64fe12ab",
        )
        self.assertEqual(
            resolve_note_id("https://www.xiaohongshu.com/user/profile/abc/64fe12ab"),
            "64fe12ab",
        )
        self.assertEqual(validate_public_url("https://xhslink.cn/o/abc").hostname, "xhslink.cn")

    def test_rejects_non_http_and_internal_hosts(self):
        for url in (
            "file:///tmp/note.html",
            "https://localhost/explore/64fe12ab",
            "http://127.0.0.1/explore/64fe12ab",
            "http://192.168.1.5/explore/64fe12ab",
        ):
            with self.subTest(url=url):
                with self.assertRaises(InvalidUrlError):
                    validate_public_url(url)


class InitialStateTests(unittest.TestCase):
    def test_extracts_nested_json_and_ignores_other_scripts(self):
        html = """
        <script>const ignored = {\"noteId\": \"wrong\"};</script>
        <script>
        window.__INITIAL_STATE__ = {"note":{"noteDetailMap":{"abc":{"noteId":"abc","title":"{brace}","nested":{"x":1}}}}};
        </script>
        """
        state = extract_initial_state(html)
        self.assertEqual(state["note"]["noteDetailMap"]["abc"]["title"], "{brace}")

    def test_accepts_trailing_semicolon_and_rejects_missing_state(self):
        self.assertEqual(extract_initial_state("<script>window.__INITIAL_STATE__ = {\"a\": 1};</script>"), {"a": 1})
        with self.assertRaises(InitialStateNotFoundError):
            extract_initial_state("<script>window.other = {};</script>")

    def test_conservatively_converts_js_undefined_outside_strings(self):
        state = extract_initial_state('<script>window.__INITIAL_STATE__ = {"missing":undefined,"text":"undefined"};</script>')
        self.assertEqual(state, {"missing": None, "text": "undefined"})


class NoteNormalizationTests(unittest.TestCase):
    def test_finds_matching_note_and_normalizes_field_variants(self):
        state = {
            "note": {
                "noteDetailMap": {
                    "note-1": {
                        "note_id": "note-1",
                        "title": "标题",
                        "desc": "正文",
                        "type": "video",
                        "tag_list": [{"name": "旅行"}, {"name": ""}],
                        "time": "1720000000000",
                        "user": {"user_id": "author-1", "nickname": "作者"},
                        "interact_info": {"liked_count": "12", "collected_count": "3"},
                    }
                }
            }
        }
        note = find_note_object(state, "note-1")
        result = normalize_note(note, {"input_url": "https://xhslink.cn/o/a", "resolved_url": "https://www.xiaohongshu.com/explore/note-1", "note_id": "note-1", "captured_at": "2026-07-28T00:00:00+00:00"})
        self.assertEqual(result["post"]["author"]["nickname"], "作者")
        self.assertEqual(result["post"]["metrics"]["likes"], 12)
        self.assertEqual(result["post"]["tags"], ["旅行"])
        self.assertEqual(result["post"]["published_at"], "2024-07-03T09:46:40+00:00")

    def test_returns_none_for_missing_optional_values(self):
        result = normalize_note({"noteId": "n"}, {"input_url": "a", "resolved_url": "b", "note_id": "n", "captured_at": "now"})
        self.assertIsNone(result["post"]["title"])
        self.assertIsNone(result["post"]["metrics"]["shares"])


class VideoTests(unittest.TestCase):
    def test_prefers_origin_then_resolution_and_deduplicates_urls(self):
        note = {
            "video": {
                "consumer": {"originVideoKey": "https://cdn.example/origin.mp4"},
                "media": {"stream": [
                    {"masterUrl": "https://cdn.example/stream.mp4", "width": 1920, "height": 1080, "bitrate": 100},
                    {"masterUrl": "https://cdn.example/stream.mp4", "width": 720, "height": 480, "bitrate": 1},
                ]},
            }
        }
        candidates = video_candidates(note)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(select_candidate(candidates)["url"], "https://cdn.example/origin.mp4")

    def test_uses_resolution_then_bitrate_and_validates_mp4_header(self):
        selected = select_candidate([
            {"url": "https://cdn.example/a.mp4", "source_path": "a", "width": 1280, "height": 720, "bitrate": 10, "size_bytes": None, "codec": None, "is_origin_candidate": False},
            {"url": "https://cdn.example/b.mp4", "source_path": "b", "width": 1920, "height": 1080, "bitrate": 1, "size_bytes": None, "codec": None, "is_origin_candidate": False},
        ])
        self.assertEqual(selected["url"], "https://cdn.example/b.mp4")
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "sample.mp4"
            media.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"x" * 20)
            report = validate_media_file(media)
        self.assertTrue(report["basic_header_valid"])
        self.assertEqual(report["size_bytes"], 32)


class CliArtifactTests(unittest.TestCase):
    def test_invalid_url_still_writes_required_failure_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            result = main(["--url", "file:///tmp/not-a-note", "--output-root", directory])
            run_directories = list(Path(directory).iterdir())
            self.assertEqual(result, 1)
            self.assertEqual(len(run_directories), 1)
            run_directory = run_directories[0]
            self.assertTrue((run_directory / "capture.json").is_file())
            self.assertTrue((run_directory / "run.log").is_file())
            self.assertTrue((run_directory / "validation_report.md").is_file())

    def test_maps_initial_state_errors_to_the_documented_reason(self):
        self.assertEqual(error_code_for(InitialStateNotFoundError("initial state is not standard JSON")), "initial_state_parse_failed")
        self.assertEqual(error_code_for(InitialStateNotFoundError("window.__INITIAL_STATE__ was not found")), "initial_state_not_found")


if __name__ == "__main__":
    unittest.main()
