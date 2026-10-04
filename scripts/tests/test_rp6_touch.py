"""Real FDT/boot fixtures catch edits to the wrong device or boot components."""
import gzip
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from test_rp6_paddles import dtb as paddle_dtb, prop

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'scripts/fix-rp6-touch.py'
IMAGE = gzip.compress(b'kernel with unchanged embedded initramfs', mtime=0)
BUS = '/soc@0/geniqup@9c0000/i2c@98c000'
TOUCH = BUS + '/touchscreen@38'


def dtb(model='Retroid Pocket 6', clock=100000, bulk_block=True,
        compatible='focaltech,ft5426', bus_compatible='qcom,geni-i2c-master-hub',
        status='okay', duplicate=False):
    source = f'''/dts-v1/;
    / {{ model = "{model}";
        vdd_disp_2v8: regulator {{ voltage = <3296000>; }};
        mdss_dsi0: display {{ panel@0 {{ vdd28-supply = <&vdd_disp_2v8>; }}; }};
        soc@0 {{ geniqup@9c0000 {{ i2c_hub_3: i2c@98c000 {{
            compatible = "{bus_compatible}"; clock-frequency = <{clock}>;
            status = "{status}"; #address-cells = <1>; #size-cells = <0>;
            touchscreen@38 {{ compatible = "{compatible}"; reg = <0x38>;
                touchscreen-inverted-y; touchscreen-size-x = <1080>;
                touchscreen-size-y = <1920>;
                {'no-regmap-bulk-read;' if bulk_block else ''}
            }};
            {'touchscreen@39 { compatible = "focaltech,ft5426"; reg = <0x39>; };' if duplicate else ''}
        }}; }}; }};
    }};'''
    return subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb'],
                          input=source.encode(), capture_output=True, check=True).stdout


def trees(payload):
    result, pos = [], len(IMAGE)
    while pos < len(payload):
        size = struct.unpack_from('>I', payload, pos + 4)[0]
        result.append(payload[pos:pos + size]); pos += size
    return result


def load_boot():
    spec = importlib.util.spec_from_file_location('touch_test_boot', REPO / 'external-and-mods/ufs-install/ufs-bootimg.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def boot(payload):
    module = load_boot()
    page = 2048
    def pad(data): return data + b'\0' * (-len(data) % page)
    ramdisk, second = gzip.compress(b'unchanged ramdisk', mtime=0), b'unchanged second stage'
    cmd, extra = b'root=PARTUUID=00000000-02 mem_sleep_default=s2idle', b'extra header field'
    header = module.HDR.pack(b'ANDROID!', len(payload), 0x10008000,
                            len(ramdisk), 0x16000000, len(second), 0x18000000,
                            0x10000100, page, 0, 123, b'RP6', cmd, b'\0' * 32, extra)
    image = module.BootImg(pad(header) + pad(payload) + pad(ramdisk) + pad(second))
    return image.build(image.cmdline)


class TouchTests(unittest.TestCase):
    def run_tool(self, payload, *flags):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'input', Path(tmp) / 'output'
            source.write_bytes(payload)
            result = subprocess.run(['python3', str(TOOL), *flags, str(source), str(output)],
                                    capture_output=True, text=True)
            self.assertEqual(source.read_bytes(), payload)
            return result, output.read_bytes() if output.exists() else None

    def test_edits_both_rp6_variants_and_preserves_kernel_other_models_and_properties(self):
        other = dtb('AYN Thor')
        result, output = self.run_tool(IMAGE + dtb() + other + dtb('Retroid Pocket 6 TOP-DPAD'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.startswith(IMAGE))
        first, unchanged, second = trees(output)
        self.assertEqual(unchanged, other)
        for tree in (first, second):
            self.assertEqual(prop(tree, BUS, 'clock-frequency', 'i'), '400000')
            self.assertEqual(prop(tree, TOUCH, 'touchscreen-size-x', 'i'), '1080')
            self.assertEqual(prop(tree, TOUCH, 'touchscreen-size-y', 'i'), '1920')
            self.assertEqual(prop(tree, '/regulator', 'voltage'), '324b00')
            self.assertEqual(prop(tree, TOUCH, 'touchscreen-inverted-y'), '')
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'tree'; path.write_bytes(tree)
                properties = subprocess.check_output(['fdtget', '-p', str(path), TOUCH], text=True).splitlines()
            self.assertNotIn('no-regmap-bulk-read', properties)

    def test_already_fast_payload_is_byte_identical_on_every_run(self):
        payload = IMAGE + dtb(clock=400000, bulk_block=False)
        result, output = self.run_tool(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, payload)
        repeated, again = self.run_tool(output)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(again, payload)

    def test_existing_bulk_read_and_partially_applied_fix_are_supported(self):
        for clock, bulk in ((100000, False), (400000, True)):
            with self.subTest(clock=clock, bulk=bulk):
                result, output = self.run_tool(IMAGE + dtb(clock=clock, bulk_block=bulk))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(prop(trees(output)[0], BUS, 'clock-frequency', 'i'), '400000')
                checked = self.check(boot(output))
                self.assertEqual(checked.returncode, 0, checked.stderr)

    def check(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'KERNEL'; path.write_bytes(data)
            result = subprocess.run(['python3', str(TOOL), '--check-boot', str(path)], capture_output=True, text=True)
            self.assertEqual(path.read_bytes(), data)
            return result

    def test_boot_preflight_rejects_slow_bus_or_byte_reads(self):
        for clock, bulk, success in ((100000, False, False), (400000, True, False), (400000, False, True)):
            with self.subTest(clock=clock, bulk=bulk):
                result = self.check(boot(IMAGE + dtb(clock=clock, bulk_block=bulk)))
                self.assertEqual(result.returncode == 0, success, result.stderr)

    def test_rejects_missing_ambiguous_disabled_or_conflicting_hardware(self):
        cases = [dtb('Retroid Pocket Nova'), dtb(clock=1000000), dtb(compatible='focaltech,ft5452'),
                 dtb(bus_compatible='unknown,bus'), dtb(status='disabled'), dtb(duplicate=True)]
        for tree in cases:
            with self.subTest(tree_hash=hashlib.sha256(tree).hexdigest()[:8]):
                result, output = self.run_tool(IMAGE + tree)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(output)

    def test_rejects_malformed_payload_and_leaves_output_absent(self):
        for payload in (IMAGE[:-1], IMAGE + dtb()[:-1], IMAGE + dtb() + b'junk', IMAGE):
            result, output = self.run_tool(payload)
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(output)

    def test_rejects_duplicate_properties_or_full_node_paths(self):
        source = subprocess.run(['dtc', '-q', '-I', 'dtb', '-O', 'dts'],
                                input=dtb(clock=400000, bulk_block=False),
                                capture_output=True, check=True).stdout.decode()
        cases = [source.replace('clock-frequency = <0x61a80>;',
                                'clock-frequency = <100000>; clock-frequency = <400000>;'),
                 source.replace('regulator {', 'shadow { flag = <1>; }; shadow { flag = <2>; }; regulator {')]
        for invalid in cases:
            # dtc -f deliberately emits invalid binary trees, like a corrupt import.
            tree = subprocess.run(['dtc', '-f', '-I', 'dts', '-O', 'dtb'],
                                  input=invalid.encode(), capture_output=True, check=True).stdout
            result, output = self.run_tool(IMAGE + tree)
            with self.subTest(mode='patch', tree_hash=hashlib.sha256(tree).hexdigest()[:8]):
                self.assertNotEqual(result.returncode, 0, 'ambiguous DTB was accepted')
                self.assertIsNone(output)
            checked = self.check(boot(IMAGE + tree))
            with self.subTest(mode='check', tree_hash=hashlib.sha256(tree).hexdigest()[:8]):
                self.assertNotEqual(checked.returncode, 0, 'ambiguous DTB passed preflight')

    def test_source_append_compiles_fast_touch_and_keeps_panel_orientation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'base.dtb'; base.write_bytes(dtb())
            source = subprocess.check_output(['dtc', '-q', '-I', 'dtb', '-O', 'dts', str(base)], text=True)
            # Keep real labels for the existing source append, independent of helper code.
            source = source.replace('regulator {', 'vdd_disp_2v8: regulator {').replace('display {', 'mdss_dsi0: display {').replace('i2c@98c000 {', 'i2c_hub_3: i2c@98c000 {')
            # UP-03 adds a reference to the real SD controller; include it
            # in this small synthetic board while still testing the touch bus.
            source += '\n/ { sdhc_2: mmc { sdhci-caps-mask = <3 0>; }; };\n'
            # UP-04's real RP6 sleep labels and resolved binding constants.
            source += '/ { tlmm: pinctrl {}; pcieport0: pcie {}; vdd_mcu_3v3: mcu {}; gamepad: gamepad {}; vreg_l15b_1p8: codec {}; vreg_bob1: bob {}; };\n'
            append = (REPO / 'external-and-mods/kernel-sm8550/dts/qcs8550-retroidpocket-rp6.dts.append').read_text()
            append = append.replace('GPIO_ACTIVE_LOW', '1').replace('RPMH_REGULATOR_MODE_LPM', '1')
            tree = subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb'], input=(source + append).encode(), capture_output=True, check=True).stdout
            self.assertEqual(prop(tree, BUS, 'clock-frequency', 'i'), '400000')
            result = self.check(boot(IMAGE + tree))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(prop(tree, TOUCH, 'touchscreen-inverted-y'), '')

    def test_boot_patch_preserves_ramdisk_second_stage_header_and_paddles(self):
        # Use actual paddle helper first, then attach touch bus to that tree.
        with tempfile.TemporaryDirectory() as tmp:
            treepath = Path(tmp) / 'tree'; treepath.write_bytes(paddle_dtb())
            source = subprocess.check_output(['dtc', '-q', '-I', 'dtb', '-O', 'dts', str(treepath)], text=True)
            touch_source = subprocess.check_output(['dtc', '-q', '-I', 'dtb', '-O', 'dts'], input=dtb()).decode()
            merged = subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb'], input=(source + touch_source.replace('/dts-v1/;', '')).encode(), capture_output=True, check=True).stdout
            payload, fixed = Path(tmp) / 'payload', Path(tmp) / 'fixed'
            payload.write_bytes(IMAGE + merged)
            subprocess.run(['python3', str(REPO / 'scripts/fix-rp6-paddles.py'), str(payload), str(fixed)], check=True, capture_output=True)
            original = boot(fixed.read_bytes())
        result, output = self.run_tool(original, '--patch-boot', '--expect-sha256', hashlib.sha256(original).hexdigest())
        self.assertEqual(result.returncode, 0, result.stderr)
        module = load_boot(); before, after = module.BootImg(original), module.BootImg(output)
        for name in ('ramdisk', 'second', 'cmdline', 'extra', 'name', 'os_version', 'kernel_addr', 'ramdisk_addr', 'second_addr', 'tags_addr', 'page_size'):
            self.assertEqual(getattr(before, name), getattr(after, name), name)
        self.assertEqual(after.id, after.expected_id())
        self.assertTrue(after.kernel.startswith(IMAGE))
        self.assertEqual(prop(trees(after.kernel)[0], '/gpio-keys/key-paddle-left', 'gpios'), '7 39 1')
        self.assertEqual(prop(trees(after.kernel)[0], '/gpio-keys/key-paddle-right', 'gpios'), '7 3a 1')
        self.assertEqual(prop(trees(after.kernel)[0], '/gpio-keys/key-volume-up', 'linux,code'), '73')
        bad, absent = self.run_tool(original, '--patch-boot', '--expect-sha256', '0' * 64)
        self.assertNotEqual(bad.returncode, 0); self.assertIsNone(absent)

    def test_image_derivation_delivers_touch_and_paddles_together(self):
        spec = importlib.util.spec_from_file_location('touch_image_builder', REPO / 'scripts/prepare-rp6-beta8-test.py')
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        original = boot(IMAGE + paddle_dtb() + paddle_dtb('Retroid Pocket 6 TOP-DPAD'))
        # Fixture starts fast; force the same 100 kHz prebuilt input used in production.
        module = load_boot(); image = module.BootImg(original)
        with tempfile.TemporaryDirectory() as tmp:
            changed = []
            for tree in trees(image.kernel):
                path = Path(tmp) / 'tree'; path.write_bytes(tree)
                subprocess.run(['fdtput', '-t', 'i', str(path), BUS, 'clock-frequency', '100000'], check=True)
                changed.append(path.read_bytes())
            image.kernel = IMAGE + b''.join(changed); image.kernel_size = len(image.kernel)
            original = image.build(image.cmdline)
        result = builder.prepare_kernel(original)
        after = module.BootImg(result)
        self.assertEqual(after.ramdisk, image.ramdisk)
        self.assertEqual(after.second, image.second)
        self.assertEqual(after.id, after.expected_id())
        for tree in trees(after.kernel):
            self.assertEqual(prop(tree, BUS, 'clock-frequency', 'i'), '400000')
            self.assertEqual(prop(tree, '/gpio-keys/key-paddle-left', 'gpios'), '7 39 1')
            self.assertEqual(prop(tree, '/gpio-keys/key-paddle-right', 'gpios'), '7 3a 1')


if __name__ == '__main__':
    unittest.main()
