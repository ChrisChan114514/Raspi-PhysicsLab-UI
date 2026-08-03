#!/usr/bin/env python3
"""Picamera2 driver for the Raspberry Pi CSI ribbon camera."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

try:
    from picamera2 import Picamera2
except ModuleNotFoundError:  # pragma: no cover - Raspberry Pi runtime path
    Picamera2 = None

try:
    from libcamera import Transform
except ModuleNotFoundError:  # pragma: no cover - Raspberry Pi runtime path
    Transform = None


class CSICameraError(RuntimeError):
    """The CSI camera could not be opened or did not return a frame."""


@dataclass(frozen=True)
class CSICameraConfig:
    camera_index: int = 0
    width: int = 640
    height: int = 480
    fps: float = 15.0
    channel_order: str = "bgr"
    warmup_timeout_s: float = 3.0
    hflip: bool = False
    vflip: bool = False
    debug: bool = False

    def validate(self) -> None:
        if self.camera_index < 0:
            raise ValueError("camera index must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("camera width and height must be positive")
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("camera fps must be a positive finite number")
        if self.channel_order not in {"rgb", "bgr"}:
            raise ValueError("camera channel order must be 'rgb' or 'bgr'")
        if self.warmup_timeout_s <= 0:
            raise ValueError("camera warmup timeout must be positive")
        if (self.hflip or self.vflip) and Transform is None:
            raise ValueError("libcamera Transform is required for hflip/vflip")


@dataclass(frozen=True)
class CSICameraFrame:
    width: int
    height: int
    rgb_bytes: bytes
    captured_at_s: float


class CSICamera:
    """Synchronous Picamera2 frame source intended for a capture thread."""

    def __init__(self, config: CSICameraConfig | None = None) -> None:
        self.config = config or CSICameraConfig()
        self.config.validate()
        self._camera = None
        self._opened = False

    @property
    def is_open(self) -> bool:
        return self._opened and self._camera is not None

    def open(self) -> CSICameraFrame:
        if self.is_open:
            return self.read()
        if Picamera2 is None:
            raise CSICameraError(
                "Picamera2 is not installed; run: "
                "sudo apt install -y python3-picamera2"
            )

        try:
            camera = Picamera2(self.config.camera_index)
            self._camera = camera
            frame_duration_us = round(1_000_000 / self.config.fps)
            config_kwargs = {}
            if Transform is not None:
                config_kwargs["transform"] = Transform(
                    hflip=int(self.config.hflip),
                    vflip=int(self.config.vflip),
                )
            video_config = camera.create_video_configuration(
                main={
                    "size": (self.config.width, self.config.height),
                    "format": "RGB888",
                },
                controls={
                    "FrameDurationLimits": (frame_duration_us, frame_duration_us),
                },
                **config_kwargs,
            )
            camera.configure(video_config)
            camera.start()
            self._opened = True
            deadline = time.monotonic() + self.config.warmup_timeout_s
            last_error = ""
            while time.monotonic() < deadline:
                try:
                    frame = self.read()
                except CSICameraError as exc:
                    last_error = str(exc)
                    time.sleep(0.05)
                    continue
                self._debug(
                    f"opened CSI index={self.config.camera_index} "
                    f"frame={frame.width}x{frame.height} "
                    f"fps={self.config.fps:g} "
                    f"channel_order={self.config.channel_order}"
                )
                return frame
            raise CSICameraError(last_error or "CSI camera returned no frames")
        except Exception as exc:
            self.close()
            if isinstance(exc, CSICameraError):
                raise
            raise CSICameraError(f"CSI camera open failed: {exc}") from exc

    def read(self) -> CSICameraFrame:
        if not self.is_open:
            raise CSICameraError("CSI camera is not open")

        try:
            frame = self._camera.capture_array("main")
            if frame is None or frame.size == 0:
                raise CSICameraError("CSI camera returned an empty frame")
            return self._to_rgb_frame(frame)
        except CSICameraError:
            raise
        except Exception as exc:
            raise CSICameraError(f"CSI camera frame capture failed: {exc}") from exc

    def close(self) -> None:
        if self._camera is not None:
            try:
                if self._opened:
                    self._camera.stop()
            finally:
                self._camera.close()
                self._camera = None
                self._opened = False
                self._debug("closed")

    def _to_rgb_frame(self, frame) -> CSICameraFrame:  # noqa: ANN001
        height, width = frame.shape[:2]
        if len(frame.shape) != 3 or frame.shape[2] < 3:
            raise CSICameraError(f"unexpected CSI camera frame shape: {frame.shape}")
        rgb = frame[:, :, :3]
        if self.config.channel_order == "bgr":
            rgb = rgb[:, :, ::-1]
        return CSICameraFrame(
            width=int(width),
            height=int(height),
            rgb_bytes=rgb.tobytes(),
            captured_at_s=time.monotonic(),
        )

    def _debug(self, message: str) -> None:
        if self.config.debug:
            print(f"[CSI CAMERA] {message}", flush=True)
