"""Offline tests for the formal public HTML capture provider."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from public_html_provider import PublicCaptureError, _request_with_validated_redirects, cover_candidates, image_candidates, redact_url, request_error
sys.path.insert(0, str(ROOT / "scripts"))
from run_capture import render_public_report


class CoverCandidateTests(unittest.TestCase):
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
    def test_maps_transport_errors_to_a_reportable_public_error(self):
        mapped = request_error(OSError("dns unavailable"))
        self.assertIsInstance(mapped, PublicCaptureError)
        self.assertEqual(str(mapped), "public_page_request_failed")


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
