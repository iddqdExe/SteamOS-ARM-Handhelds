"""Volume Up must survive InputPlumber's grab and keyboard target removal."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'steamos-overlay/usr/lib/steamos/sm8550-volume-keys'
loader = importlib.machinery.SourceFileLoader('volume_keys', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
volume = importlib.util.module_from_spec(spec)
loader.exec_module(volume)


class VolumeTests(unittest.TestCase):
    def test_captured_volume_up_routes_without_a_keyboard_target(self):
        config = yaml.safe_load((REPO / 'steamos-overlay/etc/inputplumber/capability_maps.d/retroid_mcu.yaml').read_text())
        routes = [m['target_event'] for m in config['mapping']
                  if any(s.get('evdev', {}).get('event_code') == 'KEY_VOLUMEUP'
                         for s in m['source_events'])]
        self.assertEqual(routes, [{'dbus': 'ui_volume_up'}])

    def test_dbus_press_increases_volume_once_and_unmutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'state.json'
            state.write_text(json.dumps({'percent': 28, 'muted': True}))
            # Exercise the real subprocess boundary without changing host audio.
            pactl = root / 'pactl'
            pactl.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['TEST_VOLUME_STATE'])
s = json.loads(p.read_text())
command, sink, *args = sys.argv[1:]
assert sink == '@DEFAULT_SINK@'
if command == 'get-sink-volume':
    print(f"Volume: front-left: 18244 / {s['percent']}% / -33 dB")
elif command == 'set-sink-mute':
    s['muted'] = args[0] == '1'
elif command == 'set-sink-volume':
    value = args[0]
    n = int(value.rstrip('%'))
    s['percent'] = s['percent'] + n if value.startswith(('-', '+')) else n
else:
    raise AssertionError(command)
p.write_text(json.dumps(s))
''')
            pactl.chmod(0o755)
            env = {'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'TEST_VOLUME_STATE': str(state)}
            with patch.dict(os.environ, env):
                for value in ['1.0', '0.0']:
                    line = ("/org/shadowblip/InputPlumber/devices/target/dbus0: "
                            "org.shadowblip.Input.DBusDevice.InputEvent "
                            f"('ui_volume_up', {value})")
                    code = volume.dbus_volume_code(line)
                    if code is not None:
                        volume.apply(code)
            self.assertEqual(json.loads(state.read_text()), {'percent': 33, 'muted': False})

    def test_only_inputplumber_volume_press_signals_change_audio(self):
        prefix = '/org/shadowblip/InputPlumber/devices/target/dbus7: org.shadowblip.Input.DBusDevice.InputEvent '
        cases = [
            (prefix + "('ui_volume_up', 1.0)", 115),
            (prefix + "('ui_volume_down', 1.0)", 114),
            (prefix + "('ui_volume_mute', 1.0)", 113),
            (prefix + "('ui_volume_up', 0.0)", None),
            (prefix + "('ui_volume_up', 2.0)", None),
            (prefix + "('ui_volume_up', nan)", None),
            (prefix + "('ui_accept', 1.0)", None),
            (prefix.replace('InputEvent', 'TouchEvent') + "('ui_volume_up', 1.0)", None),
            (prefix.replace('devices/target/dbus7', 'devices/source/event5') + "('ui_volume_up', 1.0)", None),
            ('The name org.shadowblip.InputPlumber is owned by :1.10', None),
        ]
        for line, wanted in cases:
            with self.subTest(line=line):
                self.assertEqual(volume.dbus_volume_code(line), wanted)

    def test_config_only_delivers_the_volume_handler_and_enabled_user_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'usr').mkdir()
            result = subprocess.run(['bash', str(REPO / 'scripts/install-inputplumber-sm8550.sh'),
                                     str(root), '--config-only'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            script = root / 'usr/lib/steamos/sm8550-volume-keys'
            self.assertTrue(script.is_file(), 'volume handler missing from image-only builds')
            self.assertTrue(script.stat().st_mode & 0o111)
            service = root / 'usr/lib/systemd/user/sm8550-volume-keys.service'
            self.assertTrue(service.is_file())
            link = root / 'etc/systemd/user/default.target.wants/sm8550-volume-keys.service'
            self.assertTrue(link.is_symlink(), 'volume handler must start with the user session')
            self.assertEqual(str(link.readlink()), '/usr/lib/systemd/user/sm8550-volume-keys.service')


if __name__ == '__main__':
    unittest.main()
