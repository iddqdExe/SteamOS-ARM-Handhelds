"""Touch rate must exclude idle gaps and lost-event resynchronization."""
import importlib.util
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]


class MeasurementTests(unittest.TestCase):
    def helper(self):
        path = REPO / 'scripts/measure-rp6-touch.py'
        self.assertTrue(path.exists(), 'touch measurement helper missing')
        spec = importlib.util.spec_from_file_location('measure', path)
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        return tool

    def test_reports_only_touch_frames_and_excludes_idle_gap(self):
        events = [(1, 0, 0, 0), (1.008, 0, 0, 0), (1.009, 3, 53, 42),
                  (1.016, 0, 0, 0), (3, 0, 0, 0), (3.008, 0, 0, 0)]
        report = self.helper().summarize(events)
        self.assertEqual(report['frames'], 5)
        self.assertEqual(report['idle_gaps'], 1)
        self.assertAlmostEqual(report['median_interval_ms'], 8)
        self.assertAlmostEqual(report['active_report_hz'], 125)

    def test_dropped_events_break_interval_chain(self):
        events = [(1, 0, 0, 0), (1.002, 0, 3, 0), (1.003, 3, 53, 42),
                  (1.004, 0, 0, 0), (1.012, 0, 0, 0), (1.020, 0, 0, 0)]
        report = self.helper().summarize(events)
        self.assertEqual(report['syn_dropped'], 1)
        self.assertAlmostEqual(report['median_interval_ms'], 8)

    def test_stationary_or_absent_touch_does_not_claim_a_rate(self):
        report = self.helper().summarize([(1, 0, 0, 0), (3, 0, 0, 0)])
        self.assertIsNone(report['active_report_hz'])
        self.assertIsNone(report['median_interval_ms'])

    def test_failed_publish_keeps_previous_report_and_allows_next_capture(self):
        tool = self.helper()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'up02-touch.json'; output.write_text('previous')
            with patch.object(tool.os, 'replace', side_effect=OSError('disk write failed')):
                with self.assertRaises(OSError): tool.save_report(output, 'new report')
            self.assertEqual(output.read_text(), 'previous')
            self.assertEqual(list(Path(tmp).iterdir()), [output])
            tool.save_report(output, 'next report')
            self.assertEqual(output.read_text(), 'next report')
