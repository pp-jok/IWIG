"""Offline tests for the formal public HTML capture provider."""
import json
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from public_html_provider import PublicCaptureError, USER_AGENT, _get_public_page, _redact_urls, _request_with_validated_redirects, _stream_download, capture_public_note, cover_candidates, image_candidates, redact_url, request_error, select_video_candidates
sys.path.insert(0, str(ROOT / "scripts"))
from run_capture import render_public_report
import run_capture


class CoverCandidateTests(unittest.TestCase):
    def test_select_video_candidates_keeps_all_public_backups(self):
        candidates = [
            {"is_origin_candidate": False, "width": 720, "height": 1280, "bitrate": 100, "source_path": "backup.1"},
            {"is_origin_candidate": True, "width": 720, "height": 1280, "bitrate": 100, "source_path": "master"},
            {"is_origin_candidate": False, "width": 720, "height": 1280, "bitrate": 100, "source_path": "backup.2"},
        ]
        self.assertEqual([item["source_path"] for item in select_video_candidates(candidates)], ["master", "backup.1", "backup.2"])

    def test_uses_direct_image_urls_and_ignores_file_ids(self):
        note = {
            "imageList": [
                {"infoList": [
                    {"url": "https://cdn.example/cover!nd_prv_wlteh_jpg_3", "imageScene": "WB_PRV"},
                    {"urlDefault": "https://cdn.example/cover-default!nd_dft_wlteh_jpg_3", "imageScene": "WB_DFT"},
                ]}
            ],
            "video": {"image": {"thumbnailFileid": "frame/only-a-file-id.webp"}},
        }

        self.assertEqual(
            cover_candidates(note),
            [
                {"url": "https://cdn.example/cover-default!nd_dft_wlteh_jpg_3", "source_path": "imageList.0.infoList.1.urlDefault"},
                {"url": "https://cdn.example/cover!nd_prv_wlteh_jpg_3", "source_path": "imageList.0.infoList.0.url"},
            ],
        )

    def test_image_candidates_preserve_page_order(self):
        note = {"imageList": [
            {"infoList": [{"url": "https://cdn.example/first-prv"}, {"url": "https://cdn.example/first-dft"}]},
            {"infoList": [{"url": "https://cdn.example/second-dft"}]},
        ]}
        self.assertEqual(
            image_candidates(note),
            [
                {"url": "https://cdn.example/first-dft", "source_path": "imageList.0.infoList.1.url", "index": 1},
                {"url": "https://cdn.example/second-dft", "source_path": "imageList.1.infoList.0.url", "index": 2},
            ],
        )


class PublicReportTests(unittest.TestCase):
    def test_capture_archives_public_html_and_initial_state_by_default(self):
        source = (ROOT / "scripts" / "public_html_provider.py").read_text(encoding="utf-8")
        self.assertIn('(source_dir / "page.html").write_text(html, encoding="utf-8")', source)
        self.assertIn('(source_dir / "initial_state.json").write_text(', source)

    def test_successful_capture_syncs_capture_status(self):
        class Response:
            status_code = 200
            text = "<html></html>"
            url = "https://www.xiaohongshu.com/explore/note"

        class Client:
            def __enter__(self): return self
            def __exit__(self, *_): return False

        def download(_client, _url, target, *_args):
            target.write_bytes(b"video")
            return target

        with tempfile.TemporaryDirectory() as temporary, \
             patch("public_html_provider._validate_url"), \
             patch("httpx.Client", return_value=Client()), \
             patch("public_html_provider._get_public_page", return_value=Response()), \
             patch("public_html_provider._initial_state", return_value={}), \
             patch("public_html_provider._current_note", return_value=({"type": "video"}, "note")), \
             patch("public_html_provider._normalize", return_value=run_capture.new_content_package("partial", "https://www.xiaohongshu.com/explore/note")), \
             patch("public_html_provider._video_candidates", return_value=[{"url": "https://cdn.example/video.mp4", "source_path": "video.master", "is_origin_candidate": True, "width": 0, "height": 0, "bitrate": 0}]), \
             patch("public_html_provider._stream_download", side_effect=download):
            package = capture_public_note("https://www.xiaohongshu.com/explore/note", Path(temporary))
        self.assertEqual(package["status"], "completed")
        self.assertEqual(package["capture_status"], "completed")

    def test_transcript_processing_hashes_the_downloaded_video(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "derived").mkdir()
            (run / "video.mp4").write_bytes(b"video")
            result = run_capture.new_content_package("completed", "https://example.test/n")
            result["media"]["video"] = {"path": "video.mp4"}
            with patch("run_capture.transcribe", return_value=([{"start": 0, "end": 1, "text": "测试"}], {"raw_segments": []})):
                run_capture.process_transcript(result, run)
        self.assertEqual(result["processing"]["transcribe"]["status"], "completed")

    def test_enrich_reuses_completed_transcript_before_starting_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "media").mkdir()
            (run / "derived").mkdir()
            video = run / "media" / "video.mp4"
            video.write_bytes(b"video")
            outputs = ["derived/transcript_raw_segments.json", "derived/transcript_segments.json",
                       "derived/transcript.txt", "derived/subtitles.srt"]
            for output in outputs:
                (run / output).write_text("cached", encoding="utf-8")
            result = run_capture.new_content_package("completed", "https://example.test/n")
            result["media"]["video"] = {"path": "media/video.mp4"}
            options_hash = run_capture.hashlib.sha256(run_capture.json.dumps({
                "model": "small", "language": "zh", "device": "cpu", "compute_type": "int8", "vad_filter": True,
            }, sort_keys=True).encode()).hexdigest()
            result["processing"]["transcribe"] = {
                "status": "completed", "input_sha256": run_capture.file_record(video, run)["sha256"],
                "options_sha256": options_hash, "output_paths": outputs,
            }
            with patch("run_capture.transcribe") as transcribe:
                run_capture.process_local_stages(result, run, keyframes=False, ocr=False, transcribe=True)
            transcribe.assert_not_called()
            self.assertEqual(result["processing"]["transcribe"]["status"], "completed")

    def test_transcript_without_video_is_not_marked_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_capture.new_content_package("completed", "https://example.test/n")
            run_capture.process_local_stages(result, Path(temporary), keyframes=False, ocr=False, transcribe=True)
        self.assertEqual(result["processing"]["transcribe"]["status"], "not_run")

    def test_keyframes_without_video_are_not_marked_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_capture.new_content_package("completed", "https://example.test/n")
            run_capture.process_local_stages(result, Path(temporary), keyframes=True, ocr=False)
        self.assertEqual(result["processing"]["extract_keyframes"]["status"], "not_run")

    def test_ocr_checkpoints_each_stage_before_the_next_stage_starts(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "media").mkdir()
            (run / "media" / "cover.jpg").write_bytes(b"cover")
            (run / "media" / "page-001.jpg").write_bytes(b"page")
            result = run_capture.new_content_package("completed", "https://example.test/n")
            result["media"]["cover"] = {"path": "media/cover.jpg"}
            result["media"]["images"] = [{"path": "media/page-001.jpg"}]
            with patch("run_capture._ocr_records", side_effect=[[
                {"path": "media/cover.jpg", "status": "available", "text": "封面", "lines": []}
            ], KeyboardInterrupt]):
                with self.assertRaises(KeyboardInterrupt):
                    run_capture.process_local_stages(result, run, keyframes=False, ocr=True)
            persisted = json.loads((run / "content_package.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["processing"]["ocr_cover"]["status"], "completed")
        self.assertEqual(persisted["processing"]["ocr_images"]["status"], "running")

    def test_interrupted_transcription_persists_running_then_migrates_to_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "media").mkdir()
            (run / "media" / "video.mp4").write_bytes(b"video")
            result = run_capture.new_content_package("completed", "https://example.test/n")
            result["media"]["video"] = {"path": "media/video.mp4"}
            with patch("run_capture.transcribe", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    run_capture.process_transcript(result, run)
            persisted = json.loads((run / "content_package.json").read_text(encoding="utf-8"))
            migrated, _ = run_capture.migrate_content_package_in_memory(persisted)
        self.assertEqual(persisted["processing"]["transcribe"]["status"], "running")
        self.assertEqual(migrated["processing"]["transcribe"]["status"], "partial")
        self.assertIn("interrupted_or_unfinished", migrated["processing"]["transcribe"]["warnings"])

    def test_report_mentions_saved_cover_and_uncollected_comments(self):
        report = render_public_report({
            "source": {"resolved_url": "https://www.xiaohongshu.com/explore/note", "note_id": "note"},
            "post": {"title": "标题", "description": "正文", "tags": [], "author": {"nickname": "作者"}, "metrics": {"likes": None, "favorites": None, "comments": 3, "shares": None}},
            "media": {"video": {"path": "video.mp4"}, "cover": {"path": "cover.webp"}},
            "completeness": {"title": "available", "comments": "intentionally_not_collected"},
            "limitations": ["Comments are intentionally not collected by the public HTML provider."],
        })
        self.assertIn("cover.webp", report)
        self.assertIn("不采集评论详情", report)
        self.assertIn("获取完整度", report)
        self.assertIn("comments：intentionally_not_collected", report)

    def test_transcription_stage_is_explicit_and_independent_of_ocr(self):
        source = (ROOT / "scripts" / "run_capture.py").read_text(encoding="utf-8")
        self.assertIn("def process_transcript", source)
        self.assertIn("if transcribe:", source)
        self.assertIn("process_transcript(result, run, asr_model, language)", source)

    def test_local_processing_skips_asr_until_explicitly_requested(self):
        package = run_capture.new_content_package("completed", "https://example.test/n")
        package["media"]["video"] = None
        with tempfile.TemporaryDirectory() as temporary, patch("run_capture.process_transcript") as transcribe:
            run_capture.process_local_stages(package, Path(temporary), keyframes=False, ocr=False,
                                             transcribe=False, asr_model="small", language="zh")
        transcribe.assert_not_called()


class BrowserRemovalTests(unittest.TestCase):
    def test_formal_runtime_has_no_browser_automation_references(self):
        for relative in ("scripts/run_capture.py", "scripts/setup.py", "requirements.txt", "README.md", "SKILL.md"):
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            with self.subTest(relative=relative):
                self.assertNotIn("playwright", text)
                self.assertNotIn("cdp", text)
        self.assertFalse((ROOT / "scripts" / "start_chrome.sh").exists())

    def test_docs_describe_public_content_package(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("content_package.json", text)
        self.assertIn("Do not use a browser", text)


class TransportErrorTests(unittest.TestCase):
    def test_media_download_disables_automatic_redirect_handling(self):
        class Response:
            status_code = 200
            headers = {"content-type": "video/mp4"}
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def iter_bytes(self): yield b"\x00\x00\x00\x18ftypisom"
        class Client:
            def stream(self, *_args, **kwargs):
                self.kwargs = kwargs
                return Response()
        with tempfile.TemporaryDirectory() as temporary, patch("public_html_provider._validate_url"):
            client = Client()
            _stream_download(client, "https://cdn.example/video.mp4", Path(temporary) / "video.mp4", 1024, "https://www.xiaohongshu.com/explore/a", "video")
        self.assertFalse(client.kwargs["follow_redirects"])

    def test_media_redirect_to_private_target_is_rejected_before_next_request(self):
        class Response:
            status_code = 302
            headers = {"location": "http://127.0.0.1/private"}
            def __enter__(self): return self
            def __exit__(self, *_): return False
        class Client:
            def __init__(self): self.calls = []
            def stream(self, _method, url, **kwargs):
                self.calls.append((url, kwargs)); return Response()
        with tempfile.TemporaryDirectory() as temporary, patch("public_html_provider._validate_url", side_effect=[None, None, PublicCaptureError("invalid_url")]):
            client = Client()
            with self.assertRaisesRegex(PublicCaptureError, "invalid_url"):
                _stream_download(client, "https://cdn.example/video.mp4", Path(temporary) / "video.mp4", 1024, "https://www.xiaohongshu.com/explore/a", "video")
        self.assertEqual(len(client.calls), 1)

    def test_page_client_uses_html_accept_header_without_media_referer(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch("httpx.Client") as client, \
             patch("public_html_provider._validate_url"), \
             patch("public_html_provider._get_public_page", side_effect=OSError("stop after client setup")):
            with self.assertRaisesRegex(PublicCaptureError, "public_page_request_failed"):
                capture_public_note("http://xhslink.cn/o/example", Path(temporary))
        self.assertEqual(client.call_args.kwargs["headers"], {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def test_maps_transport_errors_to_a_reportable_public_error(self):
        mapped = request_error(OSError("dns unavailable"))
        self.assertIsInstance(mapped, PublicCaptureError)
        self.assertEqual(str(mapped), "public_page_request_failed")

    def test_selected_note_redacts_master_and_backup_urls(self):
        data = _redact_urls({"masterUrl": "https://cdn.test/video?token=secret", "backupUrls": ["https://cdn.test/backup?token=secret"], "label": "unchanged"})
        self.assertNotIn("https://", str(data)); self.assertEqual(data["label"], "unchanged")

    def test_media_transport_error_becomes_reportable_download_failure(self):
        class BrokenStream:
            def __enter__(self): raise OSError("read timed out")
            def __exit__(self, *_): return False
        class Client:
            def stream(self, *_args, **_kwargs): return BrokenStream()
        with tempfile.TemporaryDirectory() as temporary, patch("public_html_provider._validate_url"):
            with self.assertRaisesRegex(PublicCaptureError, "video_download_failed"):
                _stream_download(Client(), "https://cdn.example/video.mp4", Path(temporary) / "video.mp4", 1024, "https://www.xiaohongshu.com/explore/a", "video")

    def test_media_download_has_no_read_timeout_after_connecting(self):
        class Response:
            status_code = 200
            headers = {"content-type": "video/mp4"}
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def iter_bytes(self): yield b"\x00\x00\x00\x18ftypisom"
        class Client:
            def stream(self, *_args, **kwargs): self.kwargs = kwargs; return Response()
        with tempfile.TemporaryDirectory() as temporary, patch("public_html_provider._validate_url"):
            client = Client(); _stream_download(client, "https://cdn.example/video.mp4", Path(temporary) / "video.mp4", 1024, "https://www.xiaohongshu.com/explore/a", "video")
        timeout = client.kwargs["timeout"]
        self.assertIsNone(timeout.connect)
        self.assertIsNone(timeout.read)
        self.assertIsNone(timeout.write)
        self.assertIsNone(timeout.pool)

    def test_short_link_retries_transient_not_found_response(self):
        class Response:
            def __init__(self, status): self.status_code = status
            def close(self): pass
        with patch("public_html_provider._request_with_validated_redirects", side_effect=[Response(404), Response(200)]) as request:
            response = _get_public_page(object(), "http://xhslink.cn/o/example")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.call_count, 2)


class RedirectSafetyTests(unittest.TestCase):
    class Response:
        def __init__(self, status, location=None):
            self.status_code, self.headers = status, ({"location": location} if location else {})

    class Client:
        def __init__(self, responses): self.responses, self.urls = list(responses), []
        def get(self, url, **_): self.urls.append(url); return self.responses.pop(0)

    def test_redirect_to_private_target_is_rejected_before_request(self):
        client = self.Client([self.Response(302, "http://127.0.0.1/private")])
        with self.assertRaisesRegex(PublicCaptureError, "invalid_url"):
            _request_with_validated_redirects(client, "https://8.8.8.8/start")
        self.assertEqual(client.urls, ["https://8.8.8.8/start"])

    def test_redirect_limit_is_enforced(self):
        client = self.Client([self.Response(302, "/again")] * 6)
        with self.assertRaisesRegex(PublicCaptureError, "redirect_limit_exceeded"):
            _request_with_validated_redirects(client, "https://8.8.8.8/start")

    def test_redaction_removes_share_token(self):
        self.assertNotIn("xsec_token", redact_url("https://www.xiaohongshu.com/explore/a?xsec_token=secret&foo=ok"))
        self.assertIn("foo=ok", redact_url("https://www.xiaohongshu.com/explore/a?xsec_token=secret&foo=ok"))


if __name__ == "__main__":
    unittest.main()
