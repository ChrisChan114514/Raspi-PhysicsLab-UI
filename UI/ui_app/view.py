from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pygame

from .analysis import FFTResult, analyze_fft
from .self_test import (
    SELF_TEST_FAILED,
    SELF_TEST_PASSED,
    SELF_TEST_RUNNING,
    SelfTestItem,
)
from .state import (
    CONTROL_ITEMS,
    LAMP_SHORT_NAMES,
    TOUCH_INPUT_ANGLE,
    DeviceState,
)


BG = (13, 17, 20)
PANEL = (27, 33, 38)
PANEL_ACTIVE = (35, 47, 51)
PANEL_DARK = (18, 23, 27)
TEXT = (239, 243, 245)
MUTED = (157, 168, 175)
ACCENT = (54, 184, 139)
ACCENT_DARK = (26, 92, 74)
WARN = (238, 174, 71)
ERROR = (224, 91, 91)
GRID = (59, 68, 74)
CURVE = (100, 190, 235)
FFT_CURVE = (238, 174, 71)

CONTROL_LABELS = {
    "lamp": "灯组转轮",
    "intensity": "照明光强",
    "camera": "USB实时摄像",
}

KEY_GUIDES = (
    ("1", "FFT"),
    ("2", "上选"),
    ("8", "下选"),
    ("4", "左/减"),
    ("5", "摄像"),
    ("6", "右/增"),
    ("A", "确认"),
    ("B", "光强+"),
    ("C", "光强-"),
    ("D", "清空"),
    ("#", "启停"),
    ("*", "小数"),
)


@dataclass(frozen=True)
class TouchRegion:
    action: str
    rect: pygame.Rect
    value: object = None

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
        self.touch_regions: list[TouchRegion] = []
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
        self.touch_regions = []
        self.screen.fill(BG)
        width, height = self.screen.get_size()
        margin = 16
        header_h = 64
        footer_h = 76
        gap = 12
        header = pygame.Rect(margin, 14, width - margin * 2, header_h)
        footer = pygame.Rect(margin, height - footer_h - margin, width - margin * 2, footer_h)
        content_y = header.bottom + gap
        content_h = footer.top - gap - content_y
        left_w = 340
        controls = pygame.Rect(margin, content_y, left_w, content_h)
        chart = pygame.Rect(controls.right + 14, content_y, width - controls.right - 30, content_h)

        self._draw_header(header, state)
        self._draw_touch_controls(controls, state)
        self._draw_chart(chart, state)
        self._draw_touch_toolbar(footer, state)
        if state.touch_input_active:
            self._draw_numeric_overlay(state)
        pygame.display.flip()

    def find_touch_region(self, position: tuple[int, int]) -> TouchRegion | None:
        for region in reversed(self.touch_regions):
            if region.rect.collidepoint(position):
                return region
        return None

    def _add_touch_region(
        self,
        action: str,
        rect: pygame.Rect,
        value: object = None,
    ) -> None:
        self.touch_regions.append(TouchRegion(action, rect.copy(), value))

    def draw_self_test(
        self,
        items: list[SelfTestItem],
        summary: str = "正在检查硬件连接",
    ) -> None:
        self.screen.fill(BG)
        width, height = self.screen.get_size()
        content_width = min(860, width - 80)
        left = (width - content_width) // 2

        self._text("系统启动自检", self.font_title, TEXT, left, 36)
        self._text(summary, self.font_body, MUTED, left, 82, max_width=content_width)

        completed = sum(
            item.status in (SELF_TEST_PASSED, SELF_TEST_FAILED)
            for item in items
        )
        progress = completed / max(1, len(items))
        progress_rect = pygame.Rect(left, 116, content_width, 8)
        pygame.draw.rect(self.screen, GRID, progress_rect, border_radius=4)
        if progress > 0:
            fill_rect = pygame.Rect(
                progress_rect.x,
                progress_rect.y,
                max(8, round(progress_rect.width * progress)),
                progress_rect.height,
            )
            pygame.draw.rect(self.screen, ACCENT, fill_rect, border_radius=4)

        status_names = {
            "pending": "等待",
            SELF_TEST_RUNNING: "检查中",
            SELF_TEST_PASSED: "正常",
            SELF_TEST_FAILED: "异常",
        }
        status_colors = {
            "pending": MUTED,
            SELF_TEST_RUNNING: WARN,
            SELF_TEST_PASSED: ACCENT,
            SELF_TEST_FAILED: ERROR,
        }
        row_top = 148
        row_height = 60
        for index, item in enumerate(items):
            y = row_top + index * row_height
            color = status_colors[item.status]
            pygame.draw.circle(self.screen, color, (left + 10, y + 22), 6)
            self._text(item.label, self.font_body, TEXT, left + 30, y + 9)
            self._text(
                item.detail,
                self.font_small,
                MUTED if item.status != SELF_TEST_FAILED else ERROR,
                left + 250,
                y + 12,
                max_width=content_width - 350,
            )
            status_text = status_names[item.status]
            status_width = self.font_small.size(status_text)[0]
            self._text(
                status_text,
                self.font_small,
                color,
                left + content_width - status_width,
                y + 12,
            )
            pygame.draw.line(
                self.screen,
                GRID,
                (left, y + row_height - 5),
                (left + content_width, y + row_height - 5),
                1,
            )

        footer = f"{completed} / {len(items)}"
        footer_width = self.font_small.size(footer)[0]
        self._text(
            footer,
            self.font_small,
            MUTED,
            left + content_width - footer_width,
            height - 46,
        )
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

        self._text("最近输入", self.font_small, MUTED, rect.right - 150, rect.y + 23)
        key_rect = pygame.Rect(rect.right - 66, rect.y + 14, 46, 38)
        pygame.draw.rect(self.screen, PANEL_DARK, key_rect, border_radius=5)
        pygame.draw.rect(self.screen, ACCENT_DARK, key_rect, width=2, border_radius=5)
        self._center_text(state.last_key or "-", self.font_key, TEXT, key_rect)

    def _draw_touch_controls(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        self._text("触控控制", self.font_heading, TEXT, rect.x + 16, rect.y + 12)
        self._text(
            "点选灯位 · 点数值输入",
            self.font_small,
            MUTED,
            rect.right - 170,
            rect.y + 18,
            max_width=154,
        )

        gap = 8
        lamp_h = 180
        intensity_h = 96
        camera_h = rect.height - 44 - lamp_h - intensity_h - gap * 2
        lamp_rect = pygame.Rect(rect.x + 12, rect.y + 44, rect.width - 24, lamp_h)
        intensity_rect = pygame.Rect(
            rect.x + 12,
            lamp_rect.bottom + gap,
            rect.width - 24,
            intensity_h,
        )
        camera_rect = pygame.Rect(
            rect.x + 12,
            intensity_rect.bottom + gap,
            rect.width - 24,
            max(70, camera_h),
        )

        self._draw_lamp_touch_card(lamp_rect, state)
        self._draw_intensity_touch_card(intensity_rect, state)
        self._draw_camera_touch_card(camera_rect, state)

    def _draw_lamp_touch_card(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL_DARK, rect, border_radius=6)
        pygame.draw.rect(self.screen, ACCENT_DARK, rect, width=1, border_radius=6)
        title = "转盘灯位"
        if state.motor_moving:
            title += " · 转动中"
        elif state.motor_ready:
            title += " · 已到位"
        else:
            title += " · 待定位"
        self._text(title, self.font_small, MUTED, rect.x + 12, rect.y + 9)
        self._text(
            f"目标 {state.motor_target_deg:.2f}° / 当前 {state.motor_position_deg:.2f}°",
            self.font_small,
            WARN if state.motor_moving else MUTED,
            rect.x + 12,
            rect.y + 31,
            max_width=rect.width - 24,
        )

        grid_top = rect.y + 50
        button_gap = 7
        button_w = (rect.width - 28 - button_gap * 2) // 3
        button_h = 37
        for index, name in enumerate(LAMP_SHORT_NAMES):
            column = index % 3
            row = index // 3
            button_rect = pygame.Rect(
                rect.x + 14 + column * (button_w + button_gap),
                grid_top + row * (button_h + button_gap),
                button_w,
                button_h,
            )
            selected = index == state.lamp_index
            reached = index == state.active_lamp_index
            subtext = "当前" if reached else f"{state.lamp_angles_deg[index]:.0f}°"
            self._draw_touch_button(
                button_rect,
                name,
                subtext,
                active=selected,
                accent=ACCENT if reached else WARN,
            )
            if not state.motor_adjustment_active:
                self._add_touch_region("select_lamp", button_rect, index)

        action_y = rect.bottom - 43
        if state.motor_adjustment_active:
            input_rect = pygame.Rect(rect.x + 12, action_y, 116, 34)
            save_rect = pygame.Rect(input_rect.right + 8, action_y, 100, 34)
            close_rect = pygame.Rect(save_rect.right + 8, action_y, rect.right - save_rect.right - 20, 34)
            self._draw_touch_button(
                input_rect,
                "重新输入",
                "角度",
                active=not state.motor_moving,
                disabled=state.motor_moving,
            )
            self._draw_touch_button(
                save_rect,
                "保存偏移",
                "写入配置",
                active=not state.motor_moving,
                accent=ACCENT,
                disabled=state.motor_moving,
            )
            self._draw_touch_button(close_rect, "退出", "不保存", accent=WARN)
            if not state.motor_moving:
                self._add_touch_region("open_angle_input", input_rect)
            if not state.motor_moving:
                self._add_touch_region("save_angle_offset", save_rect)
            self._add_touch_region("close_angle_adjustment", close_rect)
            if state.motor_adjustment_error:
                self._text(
                    state.motor_adjustment_error,
                    self.font_small,
                    WARN,
                    rect.x + 12,
                    action_y - 23,
                    max_width=rect.width - 24,
                )
        else:
            input_rect = pygame.Rect(rect.x + 12, action_y, rect.width - 24, 34)
            self._draw_touch_button(
                input_rect,
                "输入转盘角度",
                "弹出数字键盘",
                active=False,
                accent=WARN,
            )
            self._add_touch_region("open_angle_input", input_rect)

    def _draw_intensity_touch_card(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL_DARK, rect, border_radius=6)
        pygame.draw.rect(self.screen, WARN if state.light_on else GRID, rect, width=1, border_radius=6)
        self._text(
            "PWM 调光 · 灯亮" if state.light_on else "PWM 调光 · 灯灭",
            self.font_small,
            MUTED,
            rect.x + 12,
            rect.y + 9,
        )

        minus_rect = pygame.Rect(rect.x + 12, rect.y + 32, 48, 40)
        plus_rect = pygame.Rect(rect.right - 60, rect.y + 32, 48, 40)
        value_rect = pygame.Rect(minus_rect.right + 8, rect.y + 32, plus_rect.x - minus_rect.right - 16, 40)
        self._draw_touch_button(minus_rect, "－", "-5%", accent=WARN)
        self._draw_touch_button(plus_rect, "＋", "+5%", accent=WARN)
        self._draw_touch_button(
            value_rect,
            f"{state.intensity_percent}%",
            "点此输入 PWM",
            active=True,
            accent=WARN,
        )
        self._add_touch_region("intensity_down", minus_rect)
        self._add_touch_region("intensity_up", plus_rect)
        self._add_touch_region("open_intensity_input", value_rect)

        track_rect = pygame.Rect(rect.x + 14, rect.bottom - 20, rect.width - 28, 10)
        pygame.draw.rect(self.screen, GRID, track_rect, border_radius=5)
        fill_rect = track_rect.copy()
        fill_rect.width = round(track_rect.width * state.intensity_percent / 100)
        if fill_rect.width:
            pygame.draw.rect(self.screen, WARN, fill_rect, border_radius=5)
        thumb_x = track_rect.x + fill_rect.width
        pygame.draw.circle(self.screen, TEXT, (thumb_x, track_rect.centery), 9)
        self._add_touch_region("intensity_slider", track_rect.inflate(0, 26))

    def _draw_camera_touch_card(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL_DARK, rect, border_radius=6)
        status = (
            "已连接"
            if state.camera_ready
            else "异常"
            if state.camera_error
            else "连接中"
            if state.camera_enabled
            else "已关闭"
        )
        self._text("摄像画面", self.font_small, MUTED, rect.x + 12, rect.y + 9)
        self._text(
            status,
            self.font_small,
            ACCENT if state.camera_ready else WARN if state.camera_enabled else MUTED,
            rect.right - 66,
            rect.y + 9,
            max_width=54,
        )
        gap = 8
        button_y = rect.y + 30
        button_h = max(30, rect.bottom - button_y - 8)
        button_w = (rect.width - 24 - gap * 2) // 3
        toggle_rect = pygame.Rect(rect.x + 12, button_y, button_w, button_h)
        small_rect = pygame.Rect(toggle_rect.right + gap, button_y, button_w, button_h)
        full_rect = pygame.Rect(small_rect.right + gap, button_y, rect.right - small_rect.right - gap - 12, button_h)
        self._draw_touch_button(
            toggle_rect,
            "开启" if not state.camera_enabled else "关闭",
            "摄像",
            active=state.camera_enabled,
        )
        self._draw_touch_button(
            small_rect,
            "小窗",
            "曲线叠加",
            active=state.camera_view_mode == "small",
        )
        self._draw_touch_button(
            full_rect,
            "全屏",
            "右侧画面",
            active=state.camera_view_mode == "full",
        )
        self._add_touch_region("toggle_camera", toggle_rect)
        self._add_touch_region("camera_view_small", small_rect)
        self._add_touch_region("camera_view_full", full_rect)

    def _draw_touch_toolbar(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        inner = rect.inflate(-12, -12)
        gap = 8
        actions = (
            (
                "toggle_measurement",
                "暂停测量" if state.measuring else "开始测量",
                "ADS1256",
                state.measuring,
                ACCENT,
            ),
            ("clear_curve", "清空曲线", f"{len(state.samples)} 点", False, ERROR),
            (
                "toggle_fft",
                "关闭 FFT" if state.fft_visible else "打开 FFT",
                "频谱分析",
                state.fft_visible,
                WARN,
            ),
            (
                "toggle_camera",
                "关闭摄像" if state.camera_enabled else "开启摄像",
                state.camera_view_name,
                state.camera_enabled,
                ACCENT,
            ),
            (
                "toggle_camera_view",
                "全屏画面" if state.camera_view_mode == "small" else "小窗画面",
                "摄像布局",
                False,
                ACCENT,
            ),
        )
        button_w = (inner.width - gap * (len(actions) - 1)) // len(actions)
        x = inner.x
        for action, label, subtext, active, accent in actions:
            button_rect = pygame.Rect(x, inner.y, button_w, inner.height)
            self._draw_touch_button(
                button_rect,
                label,
                subtext,
                active=active,
                accent=accent,
                danger=action == "clear_curve",
            )
            self._add_touch_region(action, button_rect)
            x += button_w + gap

    def _draw_numeric_overlay(self, state: DeviceState) -> None:
        width, height = self.screen.get_size()
        self._add_touch_region("modal_block", pygame.Rect(0, 0, width, height))
        scrim = pygame.Surface((width, height), pygame.SRCALPHA)
        scrim.fill((0, 0, 0, 178))
        self.screen.blit(scrim, (0, 0))

        panel = pygame.Rect((width - 620) // 2, 62, 620, height - 94)
        pygame.draw.rect(self.screen, PANEL, panel, border_radius=9)
        pygame.draw.rect(self.screen, ACCENT, panel, width=2, border_radius=9)

        is_angle = state.touch_input_kind == TOUCH_INPUT_ANGLE
        title = "转盘角度输入" if is_angle else "PWM 光强输入"
        range_text = "范围 0~360°，A/确认后开始转动" if is_angle else "范围 0~100%，整数百分比"
        value_suffix = "°" if is_angle else "%"
        self._text(title, self.font_title, TEXT, panel.x + 24, panel.y + 18)
        self._text(range_text, self.font_body, MUTED, panel.x + 24, panel.y + 58)

        value_rect = pygame.Rect(panel.x + 24, panel.y + 88, panel.width - 48, 62)
        pygame.draw.rect(self.screen, PANEL_DARK, value_rect, border_radius=6)
        pygame.draw.rect(self.screen, WARN if state.touch_input_error else ACCENT, value_rect, width=2, border_radius=6)
        value_text = state.touch_input_value or "--"
        self._center_text(f"{value_text}{value_suffix}", self.font_title, TEXT, value_rect)
        if state.touch_input_error:
            self._text(
                state.touch_input_error,
                self.font_small,
                WARN,
                value_rect.x + 8,
                value_rect.bottom + 7,
                max_width=value_rect.width - 16,
            )

        key_gap = 10
        key_w = 96
        key_h = 58
        key_x = panel.x + 24
        key_y = panel.y + 178
        keys = (
            ("1", "2", "3"),
            ("4", "5", "6"),
            ("7", "8", "9"),
            ("." if is_angle else "", "0", "⌫"),
        )
        for row, row_keys in enumerate(keys):
            for column, key in enumerate(row_keys):
                key_rect = pygame.Rect(
                    key_x + column * (key_w + key_gap),
                    key_y + row * (key_h + key_gap),
                    key_w,
                    key_h,
                )
                if not key:
                    self._draw_touch_button(key_rect, "—", "", disabled=True)
                    continue
                if key == "⌫":
                    self._draw_touch_button(key_rect, "退格", "C", accent=WARN)
                    self._add_touch_region("numeric_backspace", key_rect)
                else:
                    self._draw_touch_button(key_rect, key, "", active=True)
                    self._add_touch_region("numeric_token", key_rect, key)

        side_x = key_x + 3 * (key_w + key_gap) + 16
        side_w = panel.right - side_x - 24
        confirm_rect = pygame.Rect(side_x, key_y, side_w, key_h * 2 + key_gap)
        clear_rect = pygame.Rect(side_x, confirm_rect.bottom + key_gap, side_w, key_h)
        cancel_rect = pygame.Rect(side_x, clear_rect.bottom + key_gap, side_w, key_h)
        self._draw_touch_button(confirm_rect, "确认", "A", active=True, accent=ACCENT)
        self._draw_touch_button(clear_rect, "清空", "D", accent=WARN)
        self._draw_touch_button(cancel_rect, "取消", "#", danger=True, accent=ERROR)
        self._add_touch_region("numeric_submit", confirm_rect)
        self._add_touch_region("numeric_clear", clear_rect)
        self._add_touch_region("numeric_cancel", cancel_rect)

        hint = "物理矩阵键盘现在只在这个数字输入界面生效"
        self._center_text(
            hint,
            self.font_small,
            MUTED,
            pygame.Rect(panel.x + 24, panel.bottom - 34, panel.width - 48, 22),
        )

    def _draw_touch_button(
        self,
        rect: pygame.Rect,
        label: str,
        subtext: str = "",
        *,
        active: bool = False,
        accent: tuple[int, int, int] = ACCENT,
        danger: bool = False,
        disabled: bool = False,
    ) -> None:
        fill = PANEL_ACTIVE if active else PANEL
        border = ERROR if danger else accent if active else GRID
        if disabled:
            fill = PANEL_DARK
            border = GRID
        pygame.draw.rect(self.screen, fill, rect, border_radius=6)
        pygame.draw.rect(self.screen, border, rect, width=2 if active or danger else 1, border_radius=6)
        label_color = MUTED if disabled else TEXT
        sub_color = MUTED if disabled else accent if active else MUTED
        if subtext:
            self._center_text(
                label,
                self.font_body if len(label) <= 6 else self.font_small,
                label_color,
                pygame.Rect(rect.x + 4, rect.y + 5, rect.width - 8, rect.height // 2),
            )
            self._center_text(
                subtext,
                self.font_small,
                sub_color,
                pygame.Rect(rect.x + 4, rect.centery, rect.width - 8, rect.height // 2 - 3),
            )
        else:
            self._center_text(
                label,
                self.font_heading if len(label) <= 3 else self.font_body,
                label_color,
                rect,
            )

    def _draw_controls(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        self._text("实验参数", self.font_heading, TEXT, rect.x + 16, rect.y + 13)
        self._text("2 / 8 选择", self.font_small, MUTED, rect.right - 96, rect.y + 18)

        values = {"intensity": f"{state.intensity_percent}%"}
        item_y = rect.y + 50
        for key in CONTROL_ITEMS:
            active = state.selected_name == key
            item_h = 118 if key in {"lamp", "camera"} else 72
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
                label += " · 灯亮" if state.light_on else " · 灯灭"
            elif not state.camera_enabled and state.camera_auto_visible:
                label += " · 自动显示"
            elif not state.camera_enabled:
                label += " · 已关闭"
            elif state.camera_ready:
                label += " · 已连接"
            elif state.camera_error:
                label += " · 异常"
            else:
                label += " · 连接中"
            self._text(label, self.font_small, MUTED, item_rect.x + 14, item_rect.y + 9)

            if key == "lamp":
                self._draw_lamp_selector(item_rect, state, active)
            elif key == "camera":
                self._draw_camera_selector(item_rect, state, active)
            else:
                self._text(values[key], self.font_heading, TEXT, item_rect.x + 14, item_rect.y + 34)

            if key == "intensity":
                bar = pygame.Rect(item_rect.right - 92, item_rect.y + 43, 72, 7)
                pygame.draw.rect(self.screen, GRID, bar, border_radius=3)
                fill = bar.copy()
                fill.width = round(bar.width * state.intensity_percent / 100)
                if fill.width:
                    pygame.draw.rect(self.screen, WARN, fill, border_radius=3)
            item_y = item_rect.bottom + 8

        if state.selected_name == "lamp":
            control_hint = "4 / 6 选灯，中间 A 手动调节"
        elif state.selected_name == "intensity":
            control_hint = "4 / 6 调整光强"
        else:
            control_hint = "4 小窗 / 6 全屏，A 或 5 开关"
        self._text(
            control_hint,
            self.font_small,
            MUTED,
            rect.x + 16,
            rect.bottom - 27,
            max_width=rect.width - 32,
        )

    def _draw_motor_adjustment(
        self,
        rect: pygame.Rect,
        state: DeviceState,
    ) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        pygame.draw.rect(
            self.screen,
            WARN,
            (rect.x, rect.y, 6, rect.height),
            border_radius=3,
        )
        self._text("手动角度调节", self.font_heading, TEXT, rect.x + 18, rect.y + 13)
        self._text(
            LAMP_SHORT_NAMES[state.lamp_index],
            self.font_body,
            WARN,
            rect.right - 88,
            rect.y + 16,
            max_width=72,
        )

        input_rect = pygame.Rect(rect.x + 14, rect.y + 54, rect.width - 28, 76)
        pygame.draw.rect(self.screen, PANEL_DARK, input_rect, border_radius=5)
        pygame.draw.rect(self.screen, ACCENT, input_rect, width=2, border_radius=5)
        angle_text = f"{state.motor_adjustment_input or '--'}°"
        self._center_text(angle_text, self.font_title, TEXT, input_rect)

        self._text(
            f"装配偏移：{state.lamp_angle_offset_deg:+.3f}°",
            self.font_small,
            MUTED,
            rect.x + 16,
            input_rect.bottom + 10,
        )
        motor_text = (
            "电机转动中"
            if state.motor_moving
            else f"当前位置：{state.motor_position_deg:.3f}°"
        )
        self._text(
            state.motor_adjustment_error or motor_text,
            self.font_small,
            WARN if state.motor_adjustment_error or state.motor_moving else ACCENT,
            rect.x + 16,
            input_rect.bottom + 34,
            max_width=rect.width - 32,
        )
        self._text(
            "目标角度范围：0~360°",
            self.font_small,
            MUTED,
            rect.x + 16,
            input_rect.bottom + 58,
        )

        key_gap = 8
        key_width = (rect.width - 36 - key_gap) // 2
        key_height = 45
        key_x = rect.x + 14
        key_y = rect.y + 226
        adjustment_keys = (
            ("A", "确认转动"),
            ("D", "清空输入"),
        )
        for index, (key, label) in enumerate(adjustment_keys):
            column = index % 2
            row = index // 2
            key_rect = pygame.Rect(
                key_x + column * (key_width + key_gap),
                key_y + row * (key_height + key_gap),
                key_width,
                key_height,
            )
            self._draw_adjustment_key(key_rect, key, label)

        footer_y = rect.bottom - 50
        self._text("*  小数点", self.font_body, TEXT, rect.x + 18, footer_y)
        save_rect = pygame.Rect(rect.right - 128, footer_y - 7, 112, 38)
        pygame.draw.rect(self.screen, ACCENT_DARK, save_rect, border_radius=5)
        pygame.draw.rect(self.screen, ACCENT, save_rect, width=2, border_radius=5)
        self._center_text("#  保存退出", self.font_small, TEXT, save_rect)

    def _draw_adjustment_key(
        self,
        rect: pygame.Rect,
        key: str,
        label: str,
    ) -> None:
        pygame.draw.rect(self.screen, PANEL_DARK, rect, border_radius=5)
        key_rect = pygame.Rect(rect.x + 7, rect.y + 7, 30, rect.height - 14)
        pygame.draw.rect(self.screen, GRID, key_rect, border_radius=4)
        self._center_text(key, self.font_key, TEXT, key_rect)
        self._text(label, self.font_body, TEXT, rect.x + 46, rect.y + 11)

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
        center_focused = active and state.lamp_arrow_focus == 0
        right_focused = active and state.lamp_arrow_focus > 0
        self._draw_arrow_button(left_rect, -1, left_focused)
        self._draw_arrow_button(right_rect, 1, right_focused)

        if center_focused:
            focus_rect = pygame.Rect(
                center_rect.x - 4,
                center_rect.y - 4,
                center_rect.width + 8,
                80,
            )
            pygame.draw.rect(
                self.screen,
                ACCENT_DARK,
                focus_rect,
                border_radius=5,
            )
            pygame.draw.rect(
                self.screen,
                ACCENT,
                focus_rect,
                width=2,
                border_radius=5,
            )

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
            f"当前：{LAMP_SHORT_NAMES[state.active_lamp_index]}",
            self.font_small,
            MUTED,
            pygame.Rect(center_rect.x, center_rect.bottom - 4, center_rect.width, 20),
        )

        left_label_rect = pygame.Rect(left_rect.x - 9, left_rect.bottom + 4, 60, 18)
        right_label_rect = pygame.Rect(right_rect.x - 9, right_rect.bottom + 4, 60, 18)
        self._center_text(
            LAMP_SHORT_NAMES[(state.lamp_index - 1) % len(LAMP_SHORT_NAMES)],
            self.font_small,
            MUTED,
            left_label_rect,
        )
        self._center_text(
            LAMP_SHORT_NAMES[(state.lamp_index + 1) % len(LAMP_SHORT_NAMES)],
            self.font_small,
            MUTED,
            right_label_rect,
        )

    def _draw_camera_selector(
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
        self._draw_arrow_button(
            left_rect,
            -1,
            active and state.camera_view_mode == "small",
        )
        self._draw_arrow_button(
            right_rect,
            1,
            active and state.camera_view_mode == "full",
        )

        enabled_text = "实时开启" if state.camera_enabled else "已关闭"
        enabled_color = ACCENT if state.camera_enabled else MUTED
        self._center_text(
            enabled_text,
            self.font_heading,
            enabled_color,
            pygame.Rect(center_rect.x, center_rect.y - 2, center_rect.width, 28),
        )
        self._center_text(
            state.camera_view_name,
            self.font_small,
            TEXT,
            pygame.Rect(center_rect.x, center_rect.y + 27, center_rect.width, 22),
        )
        self._center_text(
            "小窗",
            self.font_small,
            MUTED,
            pygame.Rect(left_rect.x - 9, left_rect.bottom + 4, 60, 18),
        )
        self._center_text(
            "全屏",
            self.font_small,
            MUTED,
            pygame.Rect(right_rect.x - 9, right_rect.bottom + 4, 60, 18),
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
        if state.camera_visible and state.camera_view_mode == "full":
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

        if state.camera_visible and state.camera_view_mode == "small":
            self._draw_camera_thumbnail(rect, state)

    def _draw_camera(self, rect: pygame.Rect, state: DeviceState) -> None:
        pygame.draw.rect(self.screen, PANEL, rect, border_radius=6)
        self._text("USB实时摄像", self.font_heading, TEXT, rect.x + 16, rect.y + 13)

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
        self._draw_camera_frame(viewport, state, compact=False)

        overlay = pygame.Rect(
            viewport.x,
            viewport.bottom - 42,
            viewport.width,
            42,
        )
        overlay_surface = pygame.Surface(overlay.size, pygame.SRCALPHA)
        overlay_surface.fill((0, 0, 0, 170))
        self.screen.blit(overlay_surface, overlay.topleft)
        overlay_text = (
            f"转动中 → {state.lamp_name}  {state.motor_target_deg:.2f}°"
            if state.motor_moving
            else f"实时观察 · {state.camera_view_name}"
        )
        self._text(
            overlay_text,
            self.font_body,
            TEXT,
            overlay.x + 14,
            overlay.y + 10,
            max_width=overlay.width - 28,
        )

    def _draw_camera_thumbnail(
        self,
        chart_rect: pygame.Rect,
        state: DeviceState,
    ) -> None:
        plot_area = pygame.Rect(
            chart_rect.x + 20,
            chart_rect.y + 60,
            chart_rect.width - 40,
            chart_rect.height - 122,
        )
        viewport = pygame.Rect(
            plot_area.x,
            plot_area.y,
            max(1, plot_area.width // 2),
            max(1, plot_area.height // 2),
        )
        self._draw_camera_frame(viewport, state, compact=True)
        pygame.draw.rect(self.screen, ACCENT_DARK, viewport, width=2, border_radius=4)

        status_bar = pygame.Rect(viewport.x + 2, viewport.y + 2, viewport.width - 4, 27)
        status_surface = pygame.Surface(status_bar.size, pygame.SRCALPHA)
        status_surface.fill((0, 0, 0, 178))
        self.screen.blit(status_surface, status_bar.topleft)
        status_color = ACCENT if state.camera_ready else WARN
        pygame.draw.circle(
            self.screen,
            status_color,
            (status_bar.x + 13, status_bar.centery),
            4,
        )
        self._text(
            "MF500 · LIVE" if state.camera_ready else "MF500 · CONNECTING",
            self.font_small,
            TEXT,
            status_bar.x + 23,
            status_bar.y + 5,
            max_width=status_bar.width - 31,
        )

    def _draw_camera_frame(
        self,
        viewport: pygame.Rect,
        state: DeviceState,
        compact: bool,
    ) -> None:
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
                    self.font_small if compact else self.font_heading,
                    WARN,
                    viewport,
                )
        else:
            message = "摄像头连接中..." if not state.camera_error else "摄像头暂不可用"
            self._center_text(
                message,
                self.font_small if compact else self.font_heading,
                WARN,
                viewport,
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
