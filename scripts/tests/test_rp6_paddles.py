"""Exercise the DTB repair on synthetic kernels, without proprietary image data."""
import gzip
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'scripts/fix-rp6-paddles.py'
IMAGE = gzip.compress(b'unchanged kernel and embedded initramfs', mtime=0)


def dtb(model='Retroid Pocket 6'):
    source = f'''/dts-v1/;
    / {{ model = "{model}";
        soc@0 {{ geniqup@9c0000 {{ i2c@98c000 {{
            compatible = "qcom,geni-i2c-master-hub"; clock-frequency = <400000>;
            touchscreen@38 {{ compatible = "focaltech,ft5426"; reg = <0x38>;
                touchscreen-inverted-y;
            }};
        }}; }}; pinctrl@f100000 {{ compatible = "qcom,sm8550-tlmm";
            phandle = <7>;
            volume-up-state {{ phandle = <8>; pins = "gpio6"; }};
        }}; }};
        gpio-keys {{ compatible = "gpio-keys"; pinctrl-0 = <8>;
            pinctrl-names = "default";
            key-volume-up {{ gpios = <7 6 1>; linux,code = <115>; }};
        }};
        regulator {{ voltage = <3296000>; }};
    }};'''
    return subprocess.run(['dtc', '-q', '-I', 'dts', '-O', 'dtb'], input=source.encode(),
                          capture_output=True, check=True).stdout


def unpack(payload):
    pos = len(IMAGE)
    result = []
    while pos < len(payload):
        size = struct.unpack_from('>I', payload, pos + 4)[0]
        result.append(payload[pos:pos + size])
        pos += size
    return result


def prop(tree, node, name, kind='x'):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'tree.dtb'
        path.write_bytes(tree)
        return subprocess.run(['fdtget', '-t', kind, str(path), node, name],
                              check=True, capture_output=True, text=True).stdout.strip()


class PaddleImportTests(unittest.TestCase):
    def run_tool(self, payload, *flags):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'input', Path(tmp) / 'output'
            source.write_bytes(payload)
            result = subprocess.run(['python3', str(TOOL), *flags, str(source), str(output)],
                                    capture_output=True, text=True)
            return result, output.read_bytes() if output.exists() else None

    def test_adds_paddles_without_changing_other_devices_or_compressed_kernel(self):
        other = dtb('AYN Odin 2')
        result, output = self.run_tool(IMAGE + dtb() + other + dtb())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.startswith(IMAGE))
        first, unchanged, second = unpack(output)
        self.assertEqual(unchanged, other)
        self.assertEqual(first, second)
        self.assertEqual(prop(first, '/gpio-keys/key-paddle-left', 'gpios'), '7 39 1')
        self.assertEqual(prop(first, '/gpio-keys/key-paddle-left', 'linux,code'), '135')
        self.assertEqual(prop(first, '/gpio-keys/key-paddle-right', 'gpios'), '7 3a 1')
        self.assertEqual(prop(first, '/gpio-keys/key-paddle-right', 'linux,code'), '132')
        self.assertEqual(prop(first, '/gpio-keys', 'pinctrl-0'), '8 9')
        self.assertEqual(prop(first, '/regulator', 'voltage'), '324b00')
        self.assertEqual(prop(first, '/gpio-keys/key-volume-up', 'linux,code'), '73')
        repeated, same = self.run_tool(output)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(same, output, 'already fixed kernel must stay byte-identical')

    def test_rejects_truncated_or_unexpected_appended_data_without_output(self):
        for payload in [IMAGE + dtb()[:-1], IMAGE + dtb() + b'junk', IMAGE[:-2]]:
            with self.subTest(size=len(payload)):
                result, output = self.run_tool(payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(output)

    def test_rejects_conflicting_paddle_configuration_without_output(self):
        result, output = self.run_tool(IMAGE + dtb())
        self.assertEqual(result.returncode, 0, result.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tree.dtb'
            path.write_bytes(unpack(output)[0])
            subprocess.run(['fdtput', '-t', 'i', str(path), '/gpio-keys/key-paddle-left',
                            'linux,code', '999'], check=True)
            invalid, absent = self.run_tool(IMAGE + path.read_bytes())
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIsNone(absent)

    def test_rejects_paddles_that_cannot_emit_mapped_key_events(self):
        result, output = self.run_tool(IMAGE + dtb())
        self.assertEqual(result.returncode, 0, result.stderr)
        cases = [
            ('/gpio-keys', 'status', 's', ['disabled']),
            ('/gpio-keys/key-paddle-left', 'status', 's', ['disabled']),
            ('/gpio-keys/key-paddle-left', 'linux,input-type', 'i', ['3']),
            ('/gpio-keys', 'compatible', 's', ['wrong-driver']),
            ('/gpio-keys', 'pinctrl-names', 's', ['sleep', 'default']),
        ]
        for node, name, kind, values in cases:
            with self.subTest(node=node, name=name), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'tree.dtb'
                path.write_bytes(unpack(output)[0])
                subprocess.run(['fdtput', '-t', kind, str(path), node, name, *values], check=True)
                invalid, absent = self.run_tool(IMAGE + path.read_bytes())
                self.assertNotEqual(invalid.returncode, 0)
                self.assertIsNone(absent)

    def test_boot_check_rejects_missing_paddles_and_accepts_fixed_payload(self):
        def boot(payload):
            header = bytearray(2048)
            header[:8] = b'ANDROID!'
            struct.pack_into('<I', header, 8, len(payload))
            struct.pack_into('<I', header, 36, 2048)
            return bytes(header) + payload
        for fixed in [False, True]:
            payload = IMAGE + dtb()
            if fixed:
                result, payload = self.run_tool(payload)
                self.assertEqual(result.returncode, 0, result.stderr)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'KERNEL'
                path.write_bytes(boot(payload))
                checked = subprocess.run(['python3', str(TOOL), '--check-boot', str(path)],
                                         capture_output=True, text=True)
            self.assertEqual(checked.returncode == 0, fixed, checked.stderr)

    def test_requires_rp6_tree_in_shared_sm8550_kernel(self):
        result, output = self.run_tool(IMAGE + dtb('AYN Odin 2'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(output)


if __name__ == '__main__':
    unittest.main()
