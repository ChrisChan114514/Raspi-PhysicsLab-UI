from __future__ import annotations

from dataclasses import dataclass


SELF_TEST_PENDING = "pending"
SELF_TEST_RUNNING = "running"
SELF_TEST_PASSED = "passed"
SELF_TEST_FAILED = "failed"


@dataclass
class SelfTestItem:
    key: str
    label: str
    status: str = SELF_TEST_PENDING
    detail: str = "等待检查"


def startup_self_test_items() -> list[SelfTestItem]:
    return [
        SelfTestItem("display", "HDMI 显示"),
        SelfTestItem("ads1256", "ADS1256 模数转换器"),
        SelfTestItem("emm", "EMM 灯组转轮电机"),
        SelfTestItem("keypad", "4x4 矩阵键盘"),
        SelfTestItem("leds", "六路 LED PWM"),
        SelfTestItem("camera", "CSI 软排线摄像头"),
    ]


class SelfTestProgress:
    def __init__(self, items: list[SelfTestItem]) -> None:
        self.items = items
        self._items_by_key = {item.key: item for item in items}

    def update(self, key: str, status: str, detail: str) -> None:
        item = self._items_by_key[key]
        item.status = status
        item.detail = " ".join(str(detail).split())

    @property
    def completed_count(self) -> int:
        return sum(
            item.status in (SELF_TEST_PASSED, SELF_TEST_FAILED)
            for item in self.items
        )

    @property
    def failed_items(self) -> tuple[SelfTestItem, ...]:
        return tuple(item for item in self.items if item.status == SELF_TEST_FAILED)

    @property
    def is_complete(self) -> bool:
        return self.completed_count == len(self.items)
