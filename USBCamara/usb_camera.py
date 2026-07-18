#!/usr/bin/env python3
"""OpenCV/V4L2 driver for a USB camera on Raspberry Pi."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import cv2
except ModuleNotFoundError:
    cv2 = None


class USBCameraError(RuntimeError):
    """The USB camera could not be opened or did not return a frame."""


REQUIRED_CAMERA_NAME = "MF500 camera"


def opencv_device_index(device: str) -> int:
    """Convert a Linux V4L2 node path to the index OpenCV expects."""
    match = re.fullmatch(r"/dev/video(\d+)", device)
    if match is None:
        raise USBCameraError(f"unsupported V4L2 video node path: {device}")
    return int(match.group(1))


@dataclass(frozen=True)
class VideoDeviceInfo:
    device: str
    name: str
    product_name: str = ""

    @property
    def matches_required_camera(self) -> bool:
        if self.product_name:
            return self.product_name == REQUIRED_CAMERA_NAME
        return self.name == REQUIRED_CAMERA_NAME


def discover_video_devices(
    sysfs_root: Path = Path("/sys/class/video4linux"),
    dev_root: Path = Path("/dev"),
) -> tuple[VideoDeviceInfo, ...]:
    devices: list[VideoDeviceInfo] = []
    if not sysfs_root.is_dir():
        return ()

    def sort_key(entry: Path) -> tuple[str, int]:
        match = re.fullmatch(r"([A-Za-z_-]+)(\d+)", entry.name)
        return (match.group(1), int(match.group(2))) if match else (entry.name, -1)

    for entry in sorted(sysfs_root.glob("video*"), key=sort_key):
        try:
            name = (entry / "name").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        product_name = ""
        try:
            device_path = (entry / "device").resolve(strict=True)
        except OSError:
            device_path = None
        if device_path is not None:
            for parent in (device_path, *device_path.parents):
                try:
                    product_name = (parent / "product").read_text(
                        encoding="utf-8"
                    ).strip()
                except OSError:
                    continue
                if product_name:
                    break
        devices.append(
            VideoDeviceInfo(
                device=str(dev_root / entry.name),
                name=name,
                product_name=product_name,
            )
        )
    return tuple(devices)


@dataclass(frozen=True)
class USBCameraConfig:
    device: str | None = None
    required_name: str = REQUIRED_CAMERA_NAME
    width: int = 640
    height: int = 480
    fps: float = 15.0
    warmup_timeout_s: float = 3.0
    use_mjpeg: bool = True
    debug: bool = False

    def validate(self) -> None:
        if self.device is not None and not self.device:
            raise ValueError("camera device override must not be empty")
        if self.required_name != REQUIRED_CAMERA_NAME:
            raise ValueError(
                f"camera name is fixed to exactly '{REQUIRED_CAMERA_NAME}'"
            )
        if self.width <= 0 or self.height <= 0:
            raise ValueError("camera width and height must be positive")
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("camera fps must be a positive finite number")
        if self.warmup_timeout_s <= 0:
            raise ValueError("camera warmup timeout must be positive")


@dataclass(frozen=True)
class USBCameraFrame:
    width: int
    height: int
    rgb_bytes: bytes
    captured_at_s: float


class USBCamera:
    """Synchronous frame source intended for a dedicated capture thread."""

    def __init__(self, config: USBCameraConfig | None = None) -> None:
        self.config = config or USBCameraConfig()
        self.config.validate()
        self._capture = None
        self._pending_frame: USBCameraFrame | None = None
        self._device_path: str | None = None

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    @property
    def device_path(self) -> str | None:
        return self._device_path

    def open(self) -> USBCameraFrame:
        if self.is_open:
            if self._pending_frame is not None:
                return self._pending_frame
            return self.read()
        if cv2 is None:
            raise USBCameraError(
                "OpenCV is not installed; run: sudo apt install -y python3-opencv"
            )

        candidates = self._matching_devices()
        errors: list[str] = []
        for device in candidates:
            try:
                device_index = opencv_device_index(device)
            except USBCameraError as exc:
                errors.append(f"{device}: {exc}")
                continue

            # OpenCV's V4L2 backend on Raspberry Pi accepts a numeric camera
            # index here; passing '/dev/videoN' is treated as a filename.
            capture = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
            if not capture.isOpened():
                capture.release()
                errors.append(f"{device}: cannot open")
                continue

            try:
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if self.config.use_mjpeg:
                    capture.set(
                        cv2.CAP_PROP_FOURCC,
                        cv2.VideoWriter_fourcc(*"MJPG"),
                    )
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
                capture.set(cv2.CAP_PROP_FPS, self.config.fps)
                self._capture = capture
                self._device_path = device

                deadline = time.monotonic() + self.config.warmup_timeout_s
                while time.monotonic() < deadline:
                    ok, frame_bgr = capture.read()
                    if ok and frame_bgr is not None and frame_bgr.size:
                        frame = self._to_rgb_frame(frame_bgr)
                        self._pending_frame = frame
                        self._debug(
                            f"opened {device} name='{REQUIRED_CAMERA_NAME}' "
                            f"frame={frame.width}x{frame.height} "
                            f"requested_fps={self.config.fps:g}"
                        )
                        return frame
                    time.sleep(0.05)
                errors.append(f"{device}: no frame")
            except Exception as exc:
                errors.append(f"{device}: {exc}")
            finally:
                if self._pending_frame is None:
                    capture.release()
                    self._capture = None
                    self._device_path = None

        detail = "; ".join(errors) if errors else "no usable matching node"
        raise USBCameraError(
            f"'{REQUIRED_CAMERA_NAME}' was found but could not capture: {detail}"
        )

    def read(self) -> USBCameraFrame:
        if self._pending_frame is not None:
            frame = self._pending_frame
            self._pending_frame = None
            return frame
        if not self.is_open:
            raise USBCameraError("USB camera is not open")

        ok, frame_bgr = self._capture.read()
        if not ok or frame_bgr is None or not frame_bgr.size:
            raise USBCameraError(
                f"USB camera returned an empty frame: {self._device_path}"
            )
        return self._to_rgb_frame(frame_bgr)

    def close(self) -> None:
        self._pending_frame = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None
            self._device_path = None
            self._debug("closed")

    def _matching_devices(self) -> tuple[str, ...]:
        devices = discover_video_devices()
        if self.config.device is not None:
            selected = next(
                (item for item in devices if item.device == self.config.device),
                None,
            )
            if selected is None:
                raise USBCameraError(
                    f"camera device is not a V4L2 video node: {self.config.device}"
                )
            if not selected.matches_required_camera:
                raise USBCameraError(
                    f"rejected {selected.device}: node name='{selected.name}', "
                    f"USB product='{selected.product_name or '<unavailable>'}', "
                    f"required exactly '{REQUIRED_CAMERA_NAME}'"
                )
            return (selected.device,)

        matches = tuple(
            item.device for item in devices if item.matches_required_camera
        )
        if matches:
            return matches

        found = ", ".join(
            f"{item.device}=node:'{item.name}',product:"
            f"'{item.product_name or '<unavailable>'}'"
            for item in devices
        ) or "no video devices"
        raise USBCameraError(
            f"required USB camera name not found: '{REQUIRED_CAMERA_NAME}'; "
            f"found: {found}"
        )

    def __enter__(self) -> "USBCamera":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # noqa: ANN001
        self.close()

    @staticmethod
    def _to_rgb_frame(frame_bgr) -> USBCameraFrame:  # noqa: ANN001
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        return USBCameraFrame(
            width=int(width),
            height=int(height),
            rgb_bytes=rgb.tobytes(),
            captured_at_s=time.monotonic(),
        )

    def _debug(self, message: str) -> None:
        if self.config.debug:
            print(f"[CAMERA] {message}", flush=True)
