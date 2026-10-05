#!/usr/bin/env python3
"""Add only a kernel-resume power-key guard to the pinned accepted RP6 daemon."""
import argparse
import ast
import hashlib
import os
from pathlib import Path
import stat

BASE_SHA256 = '1c1c25761996b6c5042ff1e3916bf787b547705ef372e74f8c0cfa4f7efa13d9'
PATCHED_SHA256 = 'd6eef68a80d88c08a27501b94a3f6872b6bdcbac2cc1e0a8eb1f68e290c8667e'
REPLACEMENTS = ((b'        last_standby = 0.0\n        while True:\n', b'        last_standby = 0.0\n        # CLOCK_BOOTTIME includes suspend; MONOTONIC excludes it.\n        sleep_offset = time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()\n        while True:\n'), (b'            keys = self.keys.poll(timeout, self.touch)\n            self.touch.tick(os.path.exists(STANDBY_FLAG))\n', b'            keys = self.keys.poll(timeout, self.touch)\n            offset = time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()\n            if offset - sleep_offset > 0.5:\n                last_standby = time.monotonic()\n                power_down_at = None\n                power_long_sent = False\n                log("s2idle wake: suppressing queued power key during resume grace")\n            sleep_offset = offset\n            self.touch.tick(os.path.exists(STANDBY_FLAG))\n'))


def upgrade(data):
    digest = hashlib.sha256(data).hexdigest()
    if digest == PATCHED_SHA256: return data
    if digest != BASE_SHA256: raise ValueError('accepted RP6 daemon SHA256 mismatch')
    for before, after in REPLACEMENTS:
        if data.count(before) != 1: raise ValueError('wake guard context mismatch')
        data = data.replace(before, after)
    ast.parse(data)
    if hashlib.sha256(data).hexdigest() != PATCHED_SHA256:
        raise ValueError('patched RP6 daemon SHA256 mismatch')
    return data


def apply(path):
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'r+b', buffering=0) as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o755):
            raise ValueError('daemon must be a root-owned mode0755 regular file')
        original = stream.read(1024 * 1024 + 1)
        if len(original) > 1024 * 1024: raise ValueError('daemon too large')
        updated = upgrade(original)
        if updated != original:
            # Preserve the accepted inode ownership, mode, ACLs and xattrs.
            stream.seek(0); view = memoryview(updated)
            while view:
                written = stream.write(view)
                if not written: raise OSError('short daemon write')
                view = view[written:]
            stream.truncate(); os.fsync(stream.fileno())
        stream.seek(0)
        if stream.read() != updated: raise ValueError('daemon readback mismatch')
    return {'before_sha256': hashlib.sha256(original).hexdigest(),
            'after_sha256': PATCHED_SHA256, 'changed': updated != original}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('daemon', type=Path)
    print(json.dumps(apply(parser.parse_args().daemon)))
