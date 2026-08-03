#!/usr/bin/env python3
"""Display Raspberry Pi CSI ribbon-camera live video in a Display0 window."""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass

try:
    import pygame
except ModuleNotFoundError as exc:  # pragma: no cover - Raspberry Pi runtime path
    raise SystemExit(
        "pygame is not installed. Run: "
        "sudo apt install -y python3-pygame or install UI/requirements.txt"
    ) from exc

try:
    from picamera2 import Picamera2
except ModuleNotFoundError as exc:  # pragma: no cover - Raspberry Pi runtime path
    raise SystemExit(
        "picamera2 is not installed. Run on Raspberry Pi: "
        "sudo apt install -y python3-picamera2"
    ) from exc

try:
    from libcamera import Transform
except ModuleNotFoundError:  # pragma: no cover - Raspberry Pi runtime path
    Transform = None


DEFAULT_DISPLAY_SIZE = (1024, 600)


@dataclass(frozen=True)
class CameraFrame:
    width: int
    height: int
    rgb_bytes: bytes


def parse_size(value: str) -> tuple[int, int]:
    normalized = value.lower().replace("*", "x")
    parts = normalized.split("x", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("size must look like 1024x600")
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("width and height must be integers") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("width and height must be positive")
    return width, height


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show CSI ribbon-camera live video in the Display0 pygame window."
    )
    parser.add_argument(
        "--display",
        default=os.environ.get("DISPLAY", ":0"),
        help="X display to use; Display0 on Raspberry Pi is usually :0.",
    )
    parser.add_argument(
        "--window-size",
        type=parse_size,
        default=DEFAULT_DISPLAY_SIZE,
        help="Pygame window size, for example 1024x600.",
    )
    parser.add_argument(
        "--camera-size",
        type=parse_size,
        default=(640, 480),
        help="CSI camera stream size, for example 640x480.",
    )
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--show-mouse", action="store_true")
    parser.add_argument("--hflip", action="store_true")
    parser.add_argument("--vflip", action="store_true")
    return parser.parse_args()


def configure_environment(display: str) -> None:
    os.environ["DISPLAY"] = display
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")
    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
    os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")


def open_camera(
    camera_index: int,
    camera_size: tuple[int, int],
    fps: float,
    hflip: bool,
    vflip: bool,
) -> Picamera2:
    if fps <= 0:
        raise ValueError("--fps must be positive")
    if (hflip or vflip) and Transform is None:
        raise RuntimeError("libcamera Transform is required for --hflip/--vflip")

    camera = Picamera2(camera_index)
    frame_duration_us = round(1_000_000 / fps)
    config_kwargs = {}
    if Transform is not None:
        config_kwargs["transform"] = Transform(hflip=int(hflip), vflip=int(vflip))
    config = camera.create_video_configuration(
        main={
            "size": camera_size,
            "format": "RGB888",
        },
        controls={
            "FrameDurationLimits": (frame_duration_us, frame_duration_us),
        },
        **config_kwargs,
    )
    camera.configure(config)
    camera.start()
    time.sleep(0.25)
    return camera


def read_frame(camera: Picamera2) -> CameraFrame:
    frame = camera.capture_array("main")
    if frame is None or frame.size == 0:
        raise RuntimeError("CSI camera returned an empty frame")
    height, width = frame.shape[:2]
    if len(frame.shape) != 3 or frame.shape[2] < 3:
        raise RuntimeError(f"unexpected camera frame shape: {frame.shape}")
    rgb = frame[:, :, :3]
    return CameraFrame(width=int(width), height=int(height), rgb_bytes=rgb.tobytes())


def draw_frame(
    screen: pygame.Surface,
    frame: CameraFrame,
    font: pygame.font.Font,
    measured_fps: float,
) -> None:
    screen.fill((10, 14, 20))
    viewport = screen.get_rect()
    frame_surface = pygame.image.frombuffer(
        frame.rgb_bytes,
        (frame.width, frame.height),
        "RGB",
    )
    scale = min(viewport.width / frame.width, viewport.height / frame.height)
    scaled_size = (
        max(1, round(frame.width * scale)),
        max(1, round(frame.height * scale)),
    )
    scaled = pygame.transform.smoothscale(frame_surface, scaled_size)
    destination = scaled.get_rect(center=viewport.center)
    screen.blit(scaled, destination)

    status = f"Display0 CSI LIVE  {frame.width}x{frame.height}  {measured_fps:4.1f} fps"
    status_surface = font.render(status, True, (236, 248, 255))
    status_bg = status_surface.get_rect(topleft=(12, 10)).inflate(14, 8)
    overlay = pygame.Surface(status_bg.size, pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 150))
    screen.blit(overlay, status_bg.topleft)
    screen.blit(status_surface, (status_bg.x + 7, status_bg.y + 4))
    pygame.display.flip()


def run() -> int:
    args = parse_args()
    configure_environment(args.display)

    camera = None
    pygame.init()
    try:
        flags = pygame.FULLSCREEN if args.fullscreen else 0
        screen = pygame.display.set_mode(args.window_size, flags)
        pygame.display.set_caption("Display0 - CSI Camera Test")
        pygame.mouse.set_visible(bool(args.show_mouse))
        font = pygame.font.Font(None, 28)
        clock = pygame.time.Clock()

        camera = open_camera(
            camera_index=args.camera_index,
            camera_size=args.camera_size,
            fps=args.fps,
            hflip=args.hflip,
            vflip=args.vflip,
        )
        print(
            f"[CSI CAMERA] opened index={args.camera_index} "
            f"camera={args.camera_size[0]}x{args.camera_size[1]} "
            f"display={args.display} window={args.window_size[0]}x{args.window_size[1]}",
            flush=True,
        )

        running = True
        measured_fps = 0.0
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key in {
                    pygame.K_ESCAPE,
                    pygame.K_q,
                }:
                    running = False

            frame = read_frame(camera)
            measured_fps = clock.get_fps()
            draw_frame(screen, frame, font, measured_fps)
            clock.tick(args.fps)
    finally:
        if camera is not None:
            camera.stop()
            camera.close()
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
