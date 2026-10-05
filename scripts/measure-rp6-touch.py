#!/usr/bin/env python3
"""Read RP6 touchscreen evdev frames without grabbing input or saving coordinates."""
import argparse
import json
import os
from pathlib import Path
import select
import statistics
import struct
import time
import tempfile

EVENT = struct.Struct('@llHHi')


def summarize(events):
    intervals = []
    previous = None
    lost = False
    frames = dropped = gaps = 0
    for timestamp, kind, code, value in events:
        if kind != 0:
            continue
        if code == 3:  # SYN_DROPPED: ignore until resynchronization.
            dropped += 1
            previous = None
            lost = True
        elif code == 0:
            if lost:
                lost = False
                continue
            frames += 1
            if previous is not None:
                delta = timestamp - previous
                if 0 < delta <= 0.1:
                    intervals.append(delta)
                else:
                    gaps += 1
            previous = timestamp
    median = statistics.median(intervals) if intervals else None
    return {'frames': frames, 'syn_dropped': dropped, 'idle_gaps': gaps,
            'active_intervals': len(intervals),
            'median_interval_ms': median * 1000 if median else None,
            'active_report_hz': 1 / median if median else None,
            'min_interval_ms': min(intervals) * 1000 if intervals else None,
            'max_interval_ms': max(intervals) * 1000 if intervals else None,
            'interpretation': 'evdev reports during movement; excludes gaps over 100 ms; not panel refresh'}


def touchscreen():
    matches = []
    for event in Path('/sys/class/input').glob('event*'):
        for relative in ('device/of_node/compatible', 'device/device/of_node/compatible'):
            compatible = event / relative
            if compatible.is_file() and b'focaltech,ft5426' in compatible.read_bytes().split(b'\0'):
                matches.append(event)
                break
    if len(matches) != 1:
        raise ValueError('expected exactly one focaltech,ft5426 evdev device')
    return matches[0]


def capture(seconds):
    model = Path('/proc/device-tree/model').read_text().rstrip('\0\n')
    if model not in ('Retroid Pocket 6', 'Retroid Pocket 6 TOP-DPAD'):
        raise ValueError('RP6 only')
    event = touchscreen()
    node = Path('/dev/input') / event.name
    frames = []
    deadline = time.monotonic() + seconds
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    try:
        while time.monotonic() < deadline:
            if not select.select([fd], [], [], max(0, deadline - time.monotonic()))[0]:
                break
            try:
                data = os.read(fd, EVENT.size * 64)
            except BlockingIOError:
                continue
            if not data or len(data) % EVENT.size:
                raise ValueError('short evdev record')
            for sec, usec, kind, code, value in EVENT.iter_unpack(data):
                if kind == 0:  # Keep timing/sync only, never touch coordinates.
                    frames.append((sec + usec / 1000000, kind, code, value))
    finally:
        os.close(fd)
    return {'model': model, 'event': str(node), 'duration_seconds': seconds,
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'captured_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            **summarize(frames)}


def save_report(output, report):
    output.parent.mkdir(exist_ok=True)
    if output.parent.is_symlink() or output.is_symlink():
        raise ValueError('refusing redirected diagnostic path')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=output.parent,
                                         prefix='.up02-touch-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(report)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error('seconds must be between 1 and 60')
    report = json.dumps(capture(args.seconds), indent=2) + '\n'
    if args.output:
        # Only the fixed BOOT diagnostic directory is used by the root service.
        if args.output != Path('/boot/debug-logs/up02-touch.json'):
            raise ValueError('output must be /boot/debug-logs/up02-touch.json')
        save_report(args.output, report)
    print(report, end='')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
