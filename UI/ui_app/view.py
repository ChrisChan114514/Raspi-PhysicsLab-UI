from __future__ import annotations

from pathlib import Path

import pygame

from .analysis import FFTResult, analyze_fft
from .state import CONTROL_ITEMS, LAMP_NAMES, DeviceState


BG = (13, 17, 20)
PANEL = (27, 33, 38)
PANEL_ACTIVE = (35, 47, 51)
PANEL_DARK = (18, 23, 27)
TEXT = (239, 243, 245)
MUTED = (157, 168, 175)
ACCENT = (54, 184, 139)
ACCENT_DARK = (26, 92, 74)
WARN = (238, 174, 71)
GRID = (59, 68, 74)
CURVE = (100, 190, 235)
FFT_CURVE = (238, 174, 71)

CONTROL_LABELS = {
    "lamp": "灯组转轮",
    "intensity": "照明光强",
    "measurement": "测量状态",
}

KEY_GUIDES = (
    ("1", "FFT"),
    ("2", "上选"),
    ("8", "下选"),
    ("4", "左/减"),
    ("6", "右/增"),
    ("A", "确认"),
    ("B", "光强+"),
    ("C", "光强-"),
    ("D", "清空"),
    ("#", "启停"),
    ("*", "退出"),
)

class MixedFont:
    def __init__(
        self,
        chinese_path: Path,
        latin_path: Path,
        size: int,
        bold: bool = False,
    ) -> None:
        self.chinese = pygame.font.Font(str(chinese_path), size)
        self.latin = pygame.font.Font(str(latin_path), size)
        self.chinese.set_bold(bold)
        self.latin.set_bold(bold)
        self.line_height = max(self.chinese.get_linesize(), self.latin.get_linesize())
        self.baseline = max(self.chinese.get_ascent(), self.latin.get_ascent())

    def _font_for(self, character: str) -> pygame.font.Font:
        return self.latin if character.isascii() else self.chinese

    def _runs(self, text: str) -> list[tuple[pygame.font.Font, str]]:
        if not text:
            return []
        runs: list[tuple[pygame.font.Font, str]] = []
        current_font = self._font_for(text[0])
        current_text = text[0]
        for character in text[1:]:
            font = self._font_for(character)
            if font is current_font:
                current_text += character
            else:
                runs.append((current_font, current_text))
                current_font = font
                current_text = character
        runs.append((current_font, current_text))
        return runs

    def size(self, text: str) -> tuple[int, int]:
        width = sum(font.size(run)[0] for font, run in self._runs(text))
        return width, self.line_height

    def render(
        self,
        text: str,
        antialias: bool,
        color: tuple[int, int, int],
    ) -> pygame.Surface:
        runs = self._runs(text)
        width = sum(font.size(run)[0] for font, run in runs)
        surface = pygame.Surface((max(1, width), self.line_height), pygame.SRCALPHA)
        x = 0
        for font, run in runs:
            rendered = font.render(run, antialias, color)
            y = max(0, self.baseline - font.get_ascent())
            surface.blit(rendered, (x, y))
            x += font.size(run)[0]
        return surface


class MainView:
    def __init__(self, screen: pygame.Surface, font_dir: Path) -> None:
        self.screen = screen
        pygame.font.init()
        chinese_path = font_dir / "SimHei.ttf"
        latin_path = font_dir / "Times New Roman.ttf"
        missing = [str(path) for path in (chinese_path, latin_path) if not path.is_file()]
        if missing:
            raise FileNotFoundError("缺少 UI 字体文件：" + ", ".join(missing))
        print(f"[UI] Chinese font={chinese_path}", flush=True)
        print(f"[UI] Latin font={latin_path}", flush=True)
        self.font_title = self._make_font(chinese_path, latin_path, 30, bold=True)
        self.font_value = self._make_font(chinese_path, latin_path, 28, bold=True)
        self.font_heading = self._make_font(chinese_path, latin_path, 22, bold=True)
        self.font_body = self._make_font(chinese_path, latin_path, 18)
        self.font_small = self._make_font(chinese_path, latin_path, 15)
        self.font_key = self._make_font(chinese_path, latin_path, 17, bold=True)

    @staticmethod
    def _make_font(
        chinese_path: Path,
        latin_path: Path,
        size: int,
        bold: bool = False,
    ) -> MixedFont:
        return MixedFont(chinese_path, latin_path, size, bold)

    def draw(self, state: DeviceState) -> None:
        self.screen.fill(BG)
        width, height = self.screen.get_size()
        margin = 16
        header_h = 64
        footer_h = 64
        gap = 12
        header = pygame.Rect(margin, 14, width - margin * 2, header_h)
        footer = pygame.Rect(margin, height - footer_h - margin, width - margin * 2, footer_h)
        content_y = header.bottom + gap
        content_h = footer.top - gap - content_y
        left_w = 304
        controls = pygame.Rect(margin, content_y, left_w, content_h)
        chart = pygame.Rect(controls.right + 14, content_y, width - controls.right - 30, content_h)

        self._draw_header(header, state)
        self._draw_controls(controls, state)
        self._draw_chart(chart, state)
        self._draw_key_guide(footer, state.last_key)
        pygame.display.flip()

    def _draw_header(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        pygame.draw.rect(self.screen, ACCENT, (rect.x, rect.y, 6, rect.height), border_radius=3)
        self._text("不同材料光电流测量", self.font_title, TEXT, rect.x + 22, rect.y + 13)

        status_color = ACCENT if state.measuring else WARN
        pygame.draw.circle(self.screen, status_color, (rect.right - 346, rect.centery), 6)
        self._text(
            state.status,
            self.font_body,
            TEXT,
            rect.right - 330,
            rect.y + 20,
            max_width=180,
        )

        self._text("最近按键", self.font_small, MUTED, rect.right - 138, rect.y + 23)
        key_rect = pygame.Rect(rect.right - 58, rect.y + 14, 38, 38)
        pygame.draw.rect(self.screen, PANEL_DARK, key_rect, border_radius=5)
        pygame.draw.rect(self.screen, ACCENT_DARK, key_rect, width=2, border_radius=5)
        self._center_text(state.last_key or "-", self.font_key, TEXT, key_rect)

    def _draw_controls(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        self._text("实验参数", self.font_heading, TEXT, rect.x + 16, rect.y + 13)
        self._text("2 / 8 选择", self.font_small, MUTED, rect.right - 96, rect.y + 18)

        values = {
            "intensity": f"{state.intensity_percent}%",
            "measurement": "测量中" if state.measuring else "已暂停",
        }
        item_y = rect.y + 50
        for key in CONTROL_ITEMS:
            active = state.selected_name == key
            item_h = 118 if key == "lamp" else 72
            item_rect = pygame.Rect(rect.x + 12, item_y, rect.width - 24, item_h)
            pygame.draw.rect(
                self.screen,
                PANEL_ACTIVE if active else PANEL_DARK,
                item_rect,
                border_radius=5,
            )
            if active:
                pygame.draw.rect(self.screen, ACCENT, item_rect, width=2, border_radius=5)
                pygame.draw.rect(
                    self.screen,
                    ACCENT,
                    (item_rect.x, item_rect.y + 10, 4, item_rect.height - 20),
                    border_radius=2,
                )
            label = CONTROL_LABELS[key]
            if key == "lamp":
                if state.motor_moving:
                    label += " · 转动中"
                elif state.motor_ready:
                    label += " · 已到位"
                else:
                    label += " · 待定位"
            elif key == "intensity":
                label += " · UV亮" if state.light_on else " · UV灭"
            self._text(label, self.font_small, MUTED, item_rect.x + 14, item_rect.y + 9)

            if key == "lamp":
                self._draw_lamp_selector(item_rect, state, active)
            else:
                value_color = ACCENT if key == "measurement" and state.measuring else TEXT
                self._text(values[key], self.font_heading, value_color, item_rect.x + 14, item_rect.y + 34)

            if key == "intensity":
                bar = pygame.Rect(item_rect.right - 92, item_rect.y + 43, 72, 7)
                pygame.draw.rect(self.screen, GRID, bar, border_radius=3)
                fill = bar.copy()
                fill.width = round(bar.width * state.intensity_percent / 100)
                if fill.width:
                    pygame.draw.rect(self.screen, WARN, fill, border_radius=3)
            item_y = item_rect.bottom + 8

        camera_rect = pygame.Rect(rect.x + 12, item_y + 2, rect.width - 24, 50)
        pygame.draw.rect(self.screen, PANEL_DARK, camera_rect, border_radius=5)
        self._text("USB摄像头", self.font_small, MUTED, camera_rect.x + 14, camera_rect.y + 15)
        if state.camera_ready:
            camera_text = "已连接"
            camera_color = ACCENT
        elif state.camera_error:
            camera_text = "异常"
            camera_color = WARN
        else:
            camera_text = "连接中"
            camera_color = MUTED
        self._text(camera_text, self.font_body, camera_color, camera_rect.right - 78, camera_rect.y + 13)

        if state.selected_name == "lamp":
            control_hint = "4 / 6 选择方向，A 确认"
        elif state.selected_name == "intensity":
            control_hint = "4 / 6 调整光强"
        else:
            control_hint = "# 开始 / 暂停测量"
        self._text(
            control_hint,
            self.font_small,
            MUTED,
            rect.x + 16,
            rect.bottom - 27,
            max_width=rect.width - 32,
        )

    def _draw_lamp_selector(
        self,
        item_rect: pygame.Rect,
        state: DeviceState,
        active: bool,
    ) -> None:
        arrow_y = item_rect.y + 50
        arrow_size = 42
        left_rect = pygame.Rect(item_rect.x + 14, arrow_y, arrow_size, arrow_size)
        right_rect = pygame.Rect(
            item_rect.right - arrow_size - 14,
            arrow_y,
            arrow_size,
            arrow_size,
        )
        center_rect = pygame.Rect(
            left_rect.right + 8,
            item_rect.y + 35,
            right_rect.x - left_rect.right - 16,
            56,
        )
        left_focused = active and state.lamp_arrow_focus < 0
        right_focused = active and state.lamp_arrow_focus > 0
        self._draw_arrow_button(left_rect, -1, left_focused)
        self._draw_arrow_button(right_rect, 1, right_focused)

        value_color = WARN if not state.motor_ready else TEXT
        self._center_text(
            state.lamp_name,
            self.font_heading,
            value_color,
            pygame.Rect(center_rect.x, center_rect.y - 5, center_rect.width, 28),
        )
        self._center_text(
            f"{state.motor_target_deg:.2f}°",
            self.font_heading,
            value_color,
            pygame.Rect(center_rect.x, center_rect.y + 21, center_rect.width, 28),
        )
        self._center_text(
            f"当前：{LAMP_NAMES[state.active_lamp_index]}",
            self.font_small,
            MUTED,
            pygame.Rect(center_rect.x, center_rect.bottom - 4, center_rect.width, 20),
        )

        left_label_rect = pygame.Rect(left_rect.x - 9, left_rect.bottom + 4, 60, 18)
        right_label_rect = pygame.Rect(right_rect.x - 9, right_rect.bottom + 4, 60, 18)
        self._center_text(
            LAMP_NAMES[(state.lamp_index - 1) % len(LAMP_NAMES)],
            self.font_small,
            MUTED,
            left_label_rect,
        )
        self._center_text(
            LAMP_NAMES[(state.lamp_index + 1) % len(LAMP_NAMES)],
            self.font_small,
            MUTED,
            right_label_rect,
        )

    def _draw_arrow_button(
        self,
        rect: pygame.Rect,
        direction: int,
        focused: bool,
    ) -> None:
        pygame.draw.rect(
            self.screen,
            ACCENT_DARK if focused else PANEL,
            rect,
            border_radius=5,
        )
        pygame.draw.rect(
            self.screen,
            ACCENT if focused else GRID,
            rect,
            width=2,
            border_radius=5,
        )
        if direction < 0:
            points = (
                (rect.centerx - 8, rect.centery),
                (rect.centerx + 7, rect.centery - 11),
                (rect.centerx + 7, rect.centery + 11),
            )
        else:
            points = (
                (rect.centerx + 8, rect.centery),
                (rect.centerx - 7, rect.centery - 11),
                (rect.centerx - 7, rect.centery + 11),
            )
        pygame.draw.polygon(self.screen, TEXT if focused else MUTED, points)

    def _draw_chart(self, rect: pygame.Rect, state: DeviceState) -> None:
        if state.motor_moving:
            self._draw_camera(rect, state)
            return

        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        self._text("光电流实时曲线（IN0）", self.font_heading, TEXT, rect.x + 16, rect.y + 13)
        latest = state.samples[-1].voltage_mv if state.samples else 0.0
        value_surface = self.font_value.render(f"{latest:0.3f} mV", True, ACCENT)
        self.screen.blit(value_surface, (rect.right - value_surface.get_width() - 18, rect.y + 10))

        samples = state.samples[-240:]
        if state.fft_visible:
            time_plot = pygame.Rect(rect.x + 20, rect.y + 61, rect.width - 40, 112)
            self._draw_time_plot(
                time_plot,
                samples,
                state.measuring,
                label="时域",
            )
            fft_result = analyze_fft(
                [sample.timestamp_s for sample in state.samples],
                [sample.voltage_mv for sample in state.samples],
            )
            info_y = time_plot.bottom + 21
            if fft_result is None:
                self._text("FFT：等待至少16个有效采样点", self.font_small, WARN, rect.x + 20, info_y)
            else:
                self._text(
                    f"FFT主频：{fft_result.center_frequency_hz:.3f} Hz  "
                    f"范围：{fft_result.range_min_hz:.3f}-{fft_result.range_max_hz:.3f} Hz  "
                    f"时长：{fft_result.duration_s:.1f} s",
                    self.font_small,
                    WARN,
                    rect.x + 20,
                    info_y,
                    max_width=rect.width - 40,
                )
            fft_plot = pygame.Rect(rect.x + 20, rect.y + 222, rect.width - 40, 130)
            self._draw_fft_plot(fft_plot, fft_result)
        else:
            plot = pygame.Rect(rect.x + 20, rect.y + 60, rect.width - 40, rect.height - 122)
            self._draw_time_plot(plot, samples, state.measuring)

        elapsed = samples[-1].timestamp_s if samples else 0.0
        self._text(
            f"采样点：{len(state.samples)}  已滤尖峰：{state.rejected_spikes}",
            self.font_small,
            MUTED,
            rect.x + 20,
            rect.bottom - 22,
        )
        elapsed_surface = self.font_small.render(f"测量时间：{elapsed:0.1f} 秒", True, MUTED)
        self.screen.blit(elapsed_surface, (rect.right - elapsed_surface.get_width() - 20, rect.bottom - 22))

    def _draw_camera(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        self._text("转盘定位画面", self.font_heading, TEXT, rect.x + 16, rect.y + 13)

        status_text = "USB CAMERA · LIVE" if state.camera_ready else "USB CAMERA"
        status_color = ACCENT if state.camera_ready else WARN
        status_surface = self.font_small.render(status_text, True, status_color)
        self.screen.blit(
            status_surface,
            (rect.right - status_surface.get_width() - 18, rect.y + 20),
        )

        viewport = pygame.Rect(
            rect.x + 18,
            rect.y + 55,
            rect.width - 36,
            rect.height - 75,
        )
        pygame.draw.rect(self.screen, PANEL_DARK, viewport, border_radius=4)

        frame_width, frame_height = state.camera_frame_size
        if (
            state.camera_frame_rgb is not None
            and frame_width > 0
            and frame_height > 0
        ):
            expected_size = frame_width * frame_height * 3
            if len(state.camera_frame_rgb) == expected_size:
                frame_surface = pygame.image.frombuffer(
                    state.camera_frame_rgb,
                    (frame_width, frame_height),
                    "RGB",
                )
                scale = min(
                    viewport.width / frame_width,
                    viewport.height / frame_height,
                )
                scaled_size = (
                    max(1, round(frame_width * scale)),
                    max(1, round(frame_height * scale)),
                )
                scaled = pygame.transform.smoothscale(frame_surface, scaled_size)
                destination = scaled.get_rect(center=viewport.center)
                self.screen.blit(scaled, destination)
            else:
                self._center_text(
                    "摄像头帧格式错误",
                    self.font_heading,
                    WARN,
                    viewport,
                )
        else:
            message = "摄像头连接中..." if not state.camera_error else "摄像头暂不可用"
            self._center_text(message, self.font_heading, WARN, viewport)

        overlay = pygame.Rect(
            viewport.x,
            viewport.bottom - 42,
            viewport.width,
            42,
        )
        overlay_surface = pygame.Surface(overlay.size, pygame.SRCALPHA)
        overlay_surface.fill((0, 0, 0, 170))
        self.screen.blit(overlay_surface, overlay.topleft)
        self._text(
            f"转动中 → {state.lamp_name}  {state.motor_target_deg:.2f}°",
            self.font_body,
            TEXT,
            overlay.x + 14,
            overlay.y + 10,
            max_width=overlay.width - 28,
        )

    def _draw_plot_grid(self, plot: pygame.Rect) -> None:
        pygame.draw.rect(self.screen, PANEL_DARK, plot, border_radius=4)
        for index in range(1, 5):
            y = plot.y + index * plot.height // 5
            pygame.draw.line(self.screen, GRID, (plot.x, y), (plot.right, y), 1)
        for index in range(1, 6):
            x = plot.x + index * plot.width // 6
            pygame.draw.line(self.screen, GRID, (x, plot.y), (x, plot.bottom), 1)

    def _draw_time_plot(
        self,
        plot: pygame.Rect,
        samples: list,
        measuring: bool,
        label: str = "",
    ) -> None:
        self._draw_plot_grid(plot)
        if label:
            self._plot_label(label, plot.right - 45, plot.y + 6)
        if len(samples) >= 2:
            values = [sample.voltage_mv for sample in samples]
            min_v = min(values)
            max_v = max(values)
            span = max(max_v - min_v, 1.0)
            lower = min_v - span * 0.08
            upper = max_v + span * 0.08
            scale = upper - lower
            start_time = samples[0].timestamp_s
            end_time = samples[-1].timestamp_s
            time_span = max(end_time - start_time, 0.001)
            points: list[tuple[int, int]] = []
            for sample in samples:
                x = plot.x + int((sample.timestamp_s - start_time) * (plot.width - 1) / time_span)
                y = plot.bottom - 1 - int((sample.voltage_mv - lower) * (plot.height - 2) / scale)
                points.append((x, y))
            pygame.draw.lines(self.screen, CURVE, False, points, 2)
            self._plot_label(f"{upper:0.1f}", plot.x + 7, plot.y + 6)
            self._plot_label(f"{lower:0.1f}", plot.x + 7, plot.bottom - 23)
            self._draw_x_axis_labels(plot, start_time, end_time, "s")
        else:
            message = "等待首个采样点" if measuring else "按 # 开始测量"
            surface = self.font_heading.render(message, True, MUTED)
            self.screen.blit(surface, surface.get_rect(center=plot.center))

    def _draw_fft_plot(self, plot: pygame.Rect, result: FFTResult | None) -> None:
        self._draw_plot_grid(plot)
        self._plot_label("FFT频谱", plot.right - 78, plot.y + 6)
        if result is None or len(result.frequencies_hz) < 2:
            message = "采样中..."
            surface = self.font_body.render(message, True, MUTED)
            self.screen.blit(surface, surface.get_rect(center=plot.center))
            return

        frequencies = result.frequencies_hz
        amplitudes = result.amplitudes_mv
        minimum_hz = result.range_min_hz
        maximum_hz = result.range_max_hz
        frequency_span = max(maximum_hz - minimum_hz, 1e-9)
        maximum_amplitude = max(float(max(amplitudes)), 1e-9)
        points = []
        for frequency, amplitude in zip(frequencies, amplitudes):
            x = plot.x + int((float(frequency) - minimum_hz) * (plot.width - 1) / frequency_span)
            y = plot.bottom - 1 - int(float(amplitude) * (plot.height - 2) / maximum_amplitude)
            points.append((x, y))
        if len(points) >= 2:
            pygame.draw.lines(self.screen, FFT_CURVE, False, points, 2)
        self._plot_label(f"{maximum_amplitude:.2f} mV", plot.x + 7, plot.y + 6)
        self._draw_x_axis_labels(plot, minimum_hz, maximum_hz, "Hz")

    def _draw_x_axis_labels(
        self,
        plot: pygame.Rect,
        minimum: float,
        maximum: float,
        unit: str,
    ) -> None:
        middle = (minimum + maximum) / 2.0
        labels = (
            (f"{minimum:.1f} {unit}", plot.x),
            (f"{middle:.1f} {unit}", plot.centerx),
            (f"{maximum:.1f} {unit}", plot.right),
        )
        for index, (text, anchor_x) in enumerate(labels):
            surface = self.font_small.render(text, True, MUTED)
            if index == 0:
                x = anchor_x
            elif index == 1:
                x = anchor_x - surface.get_width() // 2
            else:
                x = anchor_x - surface.get_width()
            self.screen.blit(surface, (x, plot.bottom + 2))

    def _draw_key_guide(self, rect: pygame.Rect, active_key: str) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        inner = rect.inflate(-12, -12)
        gap = 6
        item_w = (inner.width - gap * (len(KEY_GUIDES) - 1)) // len(KEY_GUIDES)
        x = inner.x
        for key, label in KEY_GUIDES:
            item = pygame.Rect(x, inner.y, item_w, inner.height)
            active = key == active_key
            pygame.draw.rect(self.screen, PANEL_ACTIVE if active else PANEL_DARK, item, border_radius=5)
            if active:
                pygame.draw.rect(self.screen, ACCENT, item, width=2, border_radius=5)
            key_rect = pygame.Rect(item.x + 6, item.y + 6, 28, 28)
            pygame.draw.rect(self.screen, ACCENT_DARK if active else GRID, key_rect, border_radius=4)
            self._center_text(key, self.font_key, TEXT, key_rect)
            self._text(label, self.font_small, TEXT if active else MUTED, item.x + 39, item.y + 12)
            x += item_w + gap

    def _plot_label(self, text: str, x: int, y: int) -> None:
        surface = self.font_small.render(text, True, MUTED)
        background = surface.get_rect(topleft=(x, y)).inflate(6, 2)
        pygame.draw.rect(self.screen, PANEL_DARK, background)
        self.screen.blit(surface, (x, y))

    def _center_text(
        self,
        text: str,
        font: MixedFont,
        color: tuple[int, int, int],
        rect: pygame.Rect,
    ) -> None:
        surface = font.render(text, True, color)
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def _text(
        self,
        text: str,
        font: MixedFont,
        color: tuple[int, int, int],
        x: int,
        y: int,
        max_width: int | None = None,
    ) -> None:
        display_text = text
        surface = font.render(display_text, True, color)
        if max_width is not None and surface.get_width() > max_width:
            suffix = "..."
            while display_text and font.size(display_text + suffix)[0] > max_width:
                display_text = display_text[:-1]
            surface = font.render(display_text + suffix, True, color)
        self.screen.blit(surface, (x, y))
