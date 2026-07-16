# 4x4 Matrix Keypad Driver

这是 4x4 薄膜矩阵键盘的独立驱动模块。UI 和命令行测试都应复用这里的 API，不要在 UI 里重复写 GPIO 扫描、消抖和键值修正逻辑。

## 默认接线

默认把键盘 P1~P8 引脚连接到以下 WiringPi 编号：

| Keypad pin | WiringPi | BCM | Default role |
|---:|---:|---:|---|
| 1 | 13 | 9 | ROW1 |
| 2 | 14 | 11 | ROW2 |
| 3 | 30 | 0 | ROW3 |
| 4 | 21 | 5 | ROW4 |
| 5 | 22 | 6 | COL1 |
| 6 | 23 | 13 | COL2 |
| 7 | 24 | 19 | COL3 |
| 8 | 25 | 26 | COL4 |

程序内部用 `lgpio`，所以 WiringPi 编号会自动转换为 BCM GPIO 编号。

## 当前键值映射

当前默认 keymap 是根据实测结果修正后的 `measured` 映射：

```text
D C B A
# 9 6 3
0 8 5 2
* 7 4 1
```

因此用户实际按下的键会被修正为正确字符。若之后更换键盘或排线，可以用 `--keymap standard` 临时切回标准布局排查。

## 命令行测试

```bash
cd /home/cc/Desktop/UICode
source .venv/bin/activate
python 16Button/read_keypad.py
```

按键时应输出：

```text
KEY_DOWN key=1 keys=1
KEY_UP key=1 keys=NONE
```

如果排线行列接反：

```bash
python 16Button/read_keypad.py --swap-rc
```

如果要看空闲扫描：

```bash
python 16Button/read_keypad.py --print-idle
```

## 可分离 API

推荐上层代码只使用这几个入口：

```python
from matrix_keypad import (
    DEFAULT_WIRINGPI_PINS,
    DebouncedMatrixKeypad,
    MatrixKeypad,
    MatrixPins,
    keymap_by_name,
)

pins = MatrixPins.from_wiringpi(DEFAULT_WIRINGPI_PINS)
keypad = MatrixKeypad(pins=pins, keymap=keymap_by_name("measured"))

with DebouncedMatrixKeypad(keypad, debounce_s=0.035) as scanner:
    events = scanner.poll()
    stable_keys = scanner.stable_keys
```

分层约定：

- `MatrixKeypad`：只负责 GPIO 行列扫描。
- `DebouncedMatrixKeypad`：负责消抖、稳定状态、`KEY_DOWN/KEY_UP` 事件。
- `read_keypad.py`：只是命令行测试工具。
- UI 或其他业务逻辑不直接操作 GPIO，只依赖 `DebouncedMatrixKeypad` 的稳定键值和事件。

## 注意

- `WiringPi 13/14` 对应 SPI0 的 `MISO/SCLK` 功能脚；当普通 GPIO 使用时，建议关闭系统 SPI。
- `WiringPi 30` 对应 BCM0，是 HAT EEPROM 相关引脚。能用，但正式设备最好确认没有 HAT EEPROM 冲突。
- 当前扫描方式：行输出逐行拉高，列输入使用内部下拉读取。
