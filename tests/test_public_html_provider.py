"""Offline tests for the formal public HTML capture provider."""
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
            result = {"media": {"video": {"path": "video.mp4"}}, "processing": {}, "derived": {}}
            with patch("run_capture.transcribe", return_value=([{"start": 0, "end": 1, "text": "测试"}], {"raw_segments": []})):
                run_capture.process_transcript(result, run)
        self.assertEqual(result["processing"]["transcribe"]["status"], "completed")

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

    def test_transcription_stage_is_independent_of_ocr(self):
        source = (ROOT / "scripts" / "run_capture.py").read_text(encoding="utf-8")
        self.assertIn("def process_transcript", source)
        self.assertIn("process_transcript(result, run)", source)


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
    def test_media_download_uses_client_redirect_handling(self):
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
        self.assertTrue(client.kwargs["follow_redirects"])

    def test_page_client_does_not_send_media_referer_to_short_links(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch("httpx.Client") as client, \
             patch("public_html_provider._validate_url"), \
             patch("public_html_provider._get_public_page", side_effect=OSError("stop after client setup")):
            with self.assertRaisesRegex(PublicCaptureError, "public_page_request_failed"):
                capture_public_note("http://xhslink.cn/o/example", Path(temporary))
        self.assertEqual(client.call_args.kwargs["headers"], {"User-Agent": USER_AGENT})

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
