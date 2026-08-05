"""Offline tests for the public IWIG command surface."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import iwig
from content_package import atomic_write_json, new_content_package


class IwigCliTests(unittest.TestCase):
    def test_capture_exposes_compatibility_arguments(self):
        with patch.object(sys, "argv", ["iwig", "capture", "--url", "https://example.test/n", "--max-video-mb", "10", "--timeout", "1", "--force", "--run-dir", "/tmp/run", "--keep-raw-source"]):
            def capture(argv):
                run = Path(argv[argv.index("--run-dir") + 1]); atomic_write_json(run / "content_package.json", new_content_package("completed", "https://example.test/n")); return 0
            with patch("iwig.run_capture.main", side_effect=capture), patch("iwig.write_analysis_index"):
                self.assertEqual(iwig.main(), 0)

    def test_setup_does_not_forward_command_name(self):
        with patch.object(sys, "argv", ["iwig", "setup", "--dry-run"]), patch("setup.main", return_value=0) as setup:
            self.assertEqual(iwig.main(), 0)
            setup.assert_called_once_with(["--dry-run"])
