"""Offline tests for the formal public HTML capture provider."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from public_html_provider import PublicCaptureError, cover_candidates, request_error
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


class PublicReportTests(unittest.TestCase):
    def test_report_mentions_saved_cover_and_uncollected_comments(self):
        report = render_public_report({
            "source": {"resolved_url": "https://www.xiaohongshu.com/explore/note", "note_id": "note"},
            "post": {"title": "标题", "description": "正文", "tags": [], "author": {"nickname": "作者"}, "metrics": {"likes": None, "favorites": None, "comments": 3, "shares": None}},
            "media": {"video": {"path": "video.mp4"}, "cover": {"path": "cover.webp"}},
            "limitations": ["Comments are intentionally not collected by the public HTML provider."],
        })
        self.assertIn("cover.webp", report)
        self.assertIn("不采集评论详情", report)


class BrowserRemovalTests(unittest.TestCase):
    def test_formal_runtime_has_no_browser_automation_references(self):
        for relative in ("scripts/run_capture.py", "scripts/setup.py", "requirements.txt", "README.md", "SKILL.md"):
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            with self.subTest(relative=relative):
                self.assertNotIn("playwright", text)
                self.assertNotIn("cdp", text)
        self.assertFalse((ROOT / "scripts" / "start_chrome.sh").exists())


class TransportErrorTests(unittest.TestCase):
    def test_maps_transport_errors_to_a_reportable_public_error(self):
        mapped = request_error(OSError("dns unavailable"))
        self.assertIsInstance(mapped, PublicCaptureError)
        self.assertEqual(str(mapped), "public_page_request_failed")


if __name__ == "__main__":
    unittest.main()
