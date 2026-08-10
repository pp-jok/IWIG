"""Offline tests for the public IWIG command surface."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import iwig
from build_analysis_index import AnalysisIndexError
from content_package import atomic_write_json, new_content_package


class IwigCliTests(unittest.TestCase):
    def test_capture_rejects_obsolete_raw_source_option(self):
        with patch.object(sys, "argv", ["iwig", "capture", "--url", "https://example.test/n", "--keep-raw-source"]):
            with self.assertRaises(SystemExit):
                iwig.main()

    def test_setup_does_not_forward_command_name(self):
        with patch.object(sys, "argv", ["iwig", "setup", "--dry-run"]), patch("setup.main", return_value=0) as setup:
            self.assertEqual(iwig.main(), 0)
            setup.assert_called_once_with(["--dry-run"])

    def test_index_failure_keeps_capture_completed_and_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            package = new_content_package("completed", "https://example.test/n")
            atomic_write_json(run / "content_package.json", package)
            target = run / "derived" / "analysis_index.json"
            target.parent.mkdir(parents=True)
            target.write_text('{"old": true}', encoding="utf-8")
            with patch("iwig.write_analysis_index", side_effect=AnalysisIndexError("disk unavailable")):
                self.assertEqual(iwig._rebuild_index_safely(run, package), "disk unavailable")
                self.assertEqual(iwig._rebuild_index_safely(run, package), "disk unavailable")
            saved = __import__("json").loads((run / "content_package.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(saved["capture_status"], "completed")
            self.assertEqual(saved["processing_status"], "failed")
            self.assertEqual(saved["processing"]["analysis_index"]["status"], "failed")
            self.assertEqual(len(saved["active_errors"]), 1)
            self.assertFalse(target.exists())
            self.assertEqual(len(list((run / "derived").glob("analysis_index.stale.*.json"))), 1)

    def test_successful_reindex_clears_active_index_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            package = new_content_package("completed", "https://example.test/n")
            package["processing_status"] = "partial"
            package["processing"]["analysis_index"] = {"status": "failed"}
            package["active_errors"] = [{"stage": "analysis_index", "code": "analysis_index_build_failed", "detail": "old"}]
            atomic_write_json(run / "content_package.json", package)
            self.assertIsNone(iwig._rebuild_index_safely(run, package))
            saved = __import__("json").loads((run / "content_package.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(saved["processing"]["analysis_index"]["status"], "completed")
            self.assertEqual(saved["processing_status"], "completed")
            self.assertEqual(saved["active_errors"], [])
            self.assertEqual(len(saved["error_history"]), 1)
            self.assertTrue((run / "derived" / "analysis_index.json").is_file())
            index = __import__("json").loads((run / "derived" / "analysis_index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["status"], "completed")
            self.assertEqual(index["state"]["processing"], saved["processing_status"])
            self.assertEqual(index["processing"]["analysis_index"]["status"], "completed")
            self.assertFalse(any(error["stage"] == "analysis_index" for error in index["active_errors"]))

    def test_result_never_reports_completed_for_invalid_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary); package = new_content_package("completed", "https://example.test/n")
            package["processing"]["analysis_index"] = {"status": "completed"}
            (run / "derived").mkdir(); (run / "derived" / "analysis_index.json").write_text("{}", encoding="utf-8")
            result = iwig._result(run, package)
            self.assertIsNone(result["analysis_index"])
            self.assertEqual(result["analysis_index_status"], "invalid")

    def test_cached_capture_does_not_recapture_when_index_rebuild_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            atomic_write_json(run / "content_package.json", new_content_package("completed", "https://example.test/n"))
            with patch.object(sys, "argv", ["iwig", "capture", "--url", "https://example.test/n", "--output-dir", temporary]), \
                    patch("iwig.find_existing_package", return_value=run), \
                    patch("iwig.write_analysis_index", side_effect=AnalysisIndexError("invalid package")), \
                    patch("iwig.run_capture.main", side_effect=AssertionError("must not recapture")):
                self.assertEqual(iwig.main(), 2)
