#!/usr/bin/env python3
"""Command-line connection and frame test for the USB camera."""

from __future__ import annotations

import argparse
import time

from usb_camera import USBCamera, USBCameraConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test Raspberry Pi USB camera frames.")
    parser.add_argument(
        "--device",
        default=None,
        help="Optional MF500 node override; its sysfs name is still verified.",
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--no-mjpeg", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.frames < 1:
        raise SystemExit("--frames must be at least 1")

    config = USBCameraConfig(
        device=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        use_mjpeg=not args.no_mjpeg,
        debug=args.debug,
    )
    started = time.monotonic()
    with USBCamera(config) as camera:
        first = camera.read()
        last = first
        for _ in range(args.frames - 1):
            last = camera.read()
        device_path = camera.device_path
    elapsed = time.monotonic() - started
    measured_fps = args.frames / elapsed if elapsed > 0 else 0.0
    print(
        f"OK name='MF500 camera' device={device_path} "
        f"frame={last.width}x{last.height} "
        f"frames={args.frames} elapsed={elapsed:.2f}s fps={measured_fps:.1f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
