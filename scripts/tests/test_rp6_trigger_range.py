"""Regressions from the RP6 7.0.14 hardware capture: signed trigger data."""
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader(
    'sm8550_fixpad', str(REPO / 'steamos-overlay/usr/lib/steamos/sm8550-fixpad'))
spec = importlib.util.spec_from_loader(loader.name, loader)
fixpad = importlib.util.module_from_spec(spec)
loader.exec_module(fixpad)


class TriggerRangeTests(unittest.TestCase):
    def apply_to_captured_device(self, model='Retroid Pocket 6',
                                 kernel='7.0.14-edge-sm8550',
                                 phys='rsinput-gamepad/input0', expected_result=0):
        # EVIOCGABS / EVIOCSABS need a Linux input device. Only that hardware
        # boundary is substituted; the production apply and selection run.
        axes = {axis: (0, -1408, 1408, 24, 96, 0) for axis in (0, 1, 3, 4)}
        axes.update({axis: (-32768, 0, 1830, 0, 30, 0) for axis in (2, 5)})

        def ioctl(_fd, request, buffer):
            direction = request >> 30
            code = (request & 255) - (0xC0 if direction == 1 else 0x40)
            if direction == 2:
                buffer[:] = struct.pack('iiiiii', *axes[code])
            elif direction == 1:
                axes[code] = struct.unpack('iiiiii', buffer)
            else:
                raise AssertionError('unexpected ioctl direction')

        with mock.patch.object(fixpad, 'iter_gamepads', return_value=[
                ('/dev/input/event3', f'AYN Odin2 Gamepad ({phys})')]), \
                mock.patch.object(fixpad.os, 'open', return_value=42), \
                mock.patch.object(fixpad.os, 'close'), \
                mock.patch.object(fixpad.os, 'uname', return_value=SimpleNamespace(release=kernel)), \
                mock.patch.object(fixpad.fcntl, 'ioctl', side_effect=ioctl), \
                mock.patch('builtins.open', side_effect=lambda *a, **k: io.StringIO(model + '\0')), \
                mock.patch('sys.stderr', new_callable=io.StringIO), \
                mock.patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(fixpad.apply(740), expected_result)
        return axes

    def test_signed_trigger_samples_retain_quarter_half_and_full_travel(self):
        axes = self.apply_to_captured_device()
        # InputPlumber normalizes ABS_Z/RZ using the advertised min/max.
        # These independently chosen sample points must reach Steam as
        # 0, 25, 50, 75 and 100 percent, rather than clipping to 0/100.
        for code in (2, 5):
            _, minimum, maximum, *_ = axes[code]
            for raw, expected in ((-32768, 0), (-16384, .25), (0, .5),
                                  (16384, .75), (32767, 1)):
                with self.subTest(axis=code, raw=raw):
                    normalized = max(0, min(1, (raw - minimum) / (maximum - minimum)))
                    self.assertAlmostEqual(normalized, expected, delta=.00002)

    def test_other_model_keeps_legacy_unsigned_trigger_calibration(self):
        axes = self.apply_to_captured_device(model='AYN Odin 2')
        for code in (2, 5):
            self.assertEqual(axes[code], (-32768, 0, 1830, 0, 30, 0))

    def test_unvalidated_kernel_keeps_existing_trigger_calibration(self):
        axes = self.apply_to_captured_device(kernel='7.1.0-edge-sm8550')
        for code in (2, 5):
            self.assertEqual(axes[code], (-32768, 0, 1830, 0, 30, 0))

    def test_external_device_keeps_existing_trigger_calibration(self):
        axes = self.apply_to_captured_device(phys='usb-1/input0', expected_result=1)
        for code in (2, 5):
            self.assertEqual(axes[code], (-32768, 0, 1830, 0, 30, 0))

    def test_validated_rp6_without_native_pad_does_not_report_calibration_success(self):
        with mock.patch.object(fixpad, 'iter_gamepads', return_value=[]), \
                mock.patch.object(fixpad.os, 'uname', return_value=SimpleNamespace(
                    release='7.0.14-edge-sm8550')), \
                mock.patch('builtins.open', side_effect=lambda *a, **k: io.StringIO('Retroid Pocket 6\0')), \
                mock.patch('sys.stderr', new_callable=io.StringIO):
            self.assertNotEqual(fixpad.apply(740), 0)

    def test_near_match_phys_does_not_select_another_controller(self):
        axes = self.apply_to_captured_device(phys='rsinput-gamepad/input01', expected_result=1)
        for code in (2, 5):
            self.assertEqual(axes[code], (-32768, 0, 1830, 0, 30, 0))


if __name__ == '__main__':
    unittest.main()
