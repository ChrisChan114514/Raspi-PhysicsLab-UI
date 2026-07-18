# Raspi Physics Lab UI

浙江省大学物理实验竞赛“不同材料下的光电流测量”树莓派控制程序。

程序固定使用 `1024x600` 全屏界面，通过 4x4 矩阵键盘完成现场操作。进入
UI 后立即开始 ADS1256 电压测量，自动把六灯位转轮定位到紫外光，并在
实际到位后以 `100%` 占空比点亮紫外灯。MF500 USB 摄像头支持曲线左上小窗
和右栏全屏两种画幅；转轮运动和手动调节期间会按用户最后选择的画幅自动
显示，电压采样继续在后台运行。

## 目录结构

```text
/home/cc/Desktop/UICode
|-- .venv
|-- 16Button       # 4x4 矩阵键盘驱动
|-- 42Motor        # EMM V5.0 六灯位转轮驱动
|-- ADS1256        # ADC 驱动和诊断工具
|-- Font           # UI 内置字体
|-- LED            # 紫外灯 PWM 驱动
|-- UI             # pygame 主程序
|-- USBCamara      # MF500 USB 摄像头驱动
|-- README.md
`-- 常用指令.txt
```

本仓库根目录就是部署目录 `UICode`。文档中的 `16Button/...`、`UI/...` 等
路径均从仓库根目录开始。

## 安装

安装系统依赖，并创建可读取系统 GPIO/OpenCV 包的虚拟环境：

```bash
sudo apt update
sudo apt install -y python3-venv python3-lgpio python3-opencv v4l-utils
cd /home/cc/Desktop/UICode
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r UI/requirements.txt
sudo usermod -aG video cc
```

修改 `video` 用户组后需要注销并重新登录。UI 不依赖树莓派系统字体，部署时
必须保留 `Font/SimHei.ttf` 和 `Font/Times New Roman.ttf`：

```bash
ls -lh /home/cc/Desktop/UICode/Font/SimHei.ttf
ls -lh "/home/cc/Desktop/UICode/Font/Times New Roman.ttf"
```

## 运行 UI

以下命令连接树莓派本机 `:0` 图形桌面。执行前需确保用户 `cc` 已登录桌面，
且 `/home/cc/.Xauthority` 存在。

硬件模式：

```bash
DISPLAY=:0 XAUTHORITY=/home/cc/.Xauthority \
/home/cc/Desktop/UICode/.venv/bin/python \
  /home/cc/Desktop/UICode/UI/app.py --backend hardware
```

模拟模式不会访问 GPIO：

```bash
DISPLAY=:0 XAUTHORITY=/home/cc/.Xauthority \
/home/cc/Desktop/UICode/.venv/bin/python \
  /home/cc/Desktop/UICode/UI/app.py --backend sim
```

常用调试参数：

```text
--debug-buttons       输出矩阵键盘事件
--debug-sensor        输出 ADS1256 RAW/mV 和滤波拒绝信息
--debug-motor         输出 EMM 串口帧
--debug-led           输出紫外灯 PWM 状态
--debug-camera        输出摄像头连接和首帧状态
--motor-port PATH     覆盖默认电机串口 /dev/serial0
--camera-device PATH  固定一个通过 MF500 名称校验的 /dev/video* 节点
```

## 键盘操作

程序启动时已经处于测量中，因此第一次按 `#` 会暂停，之后在开始和暂停间
切换。`A`、`4`、`6` 不改变测量状态。

| 物理键 | 界面动作 |
| --- | --- |
| `0`-`9` | 手动角度模块中直接输入目标角度；其他界面保留原动作或忽略 |
| `1` | 显示或隐藏 FFT 自动分析；手动角度模块中输入数字 `1` |
| `2` | 选择上一个参数；手动角度模块中输入数字 `2` |
| `8` | 选择下一个参数；手动角度模块中输入数字 `8` |
| `4` | 灯组焦点左移；光强减小；摄像选择小窗；手动模块输入 `4` |
| `5` | 开关常驻 USB 摄像；手动角度模块中输入数字 `5` |
| `6` | 灯组焦点右移；光强增加；摄像选择全屏；手动模块输入 `6` |
| `A` | 确认灯组焦点；摄像开关；手动角度 `+0.1°` |
| `B` | 光强增加 5%；手动角度 `-0.1°` |
| `C` | 光强减少 5%；手动角度 `+0.5°` |
| `D` | 清空曲线；手动角度 `-0.5°` |
| `#` | 开始/暂停测量；手动角度模块中保存并退出 |
| `*` | 手动角度模块中的小数点；其他界面不执行动作 |

系统不提供任何按键退出功能，`*` 和外接键盘 `Esc` 均不会关闭 UI。维护时
使用 `sudo systemctl stop raspi-ui.service`，前台调试时从启动终端发送
`Ctrl+C`。

## 开机自启动

启动脚本 `UI/run_hardware_ui.sh` 会等待图形桌面和 `.Xauthority` 最多
60 秒，再激活虚拟环境并以硬件模式运行 UI。如果 `.venv` 不存在，脚本会
优先使用 `/usr/bin/python3` 创建 `--system-site-packages` 环境，并自动安装
`UI/requirements.txt`；环境存在但缺少 pygame、NumPy、OpenCV 或 pyserial
时也会自动补装。先手动验证：

```bash
/bin/bash /home/cc/Desktop/UICode/UI/run_hardware_ui.sh
```

安装并启用 systemd 服务：

```bash
sudo cp /home/cc/Desktop/UICode/UI/systemd/raspi-ui.service \
  /etc/systemd/system/raspi-ui.service
sudo systemctl daemon-reload
sudo systemctl enable --now raspi-ui.service
```

常用服务命令：

```bash
systemctl status raspi-ui.service --no-pager
journalctl -u raspi-ui.service -f
sudo systemctl restart raspi-ui.service
sudo systemctl disable --now raspi-ui.service
```

service 通过 `/bin/bash` 调用启动脚本，因此脚本不依赖可执行权限。服务只在
程序异常退出或启动环境未就绪时重试；UI 不提供按键退出功能。
`lgpio` 必须由 `python3-lgpio` 系统包提供，脚本检测到缺失时会输出对应的
`apt` 安装命令后退出。

## GPIO 总览

硬件模式使用 `21` 个唯一 BCM GPIO：ADS1256 使用 10 个，矩阵键盘使用
8 个，紫外灯 PWM 使用 1 个，EMM 电机 GPIO UART 使用 2 个。USB 摄像头
使用 USB 总线，不占用 40Pin GPIO。目前模块间没有重复占用。

- `WiringPi` 是项目原始接线编号。
- `BCM` 是 `lgpio` 和树莓派系统使用的 GPIO 编号。
- 电源脚和 GND 不计入 GPIO 数量；所有外部模块必须与树莓派共地。

### 40Pin 引脚对照表

| WiringPi | BCM | 当前程序占用功能 | 物理脚（奇数排） | 物理脚（偶数排） | 当前程序占用功能 | BCM | WiringPi |
| ---: | ---: | --- | ---: | :--- | --- | ---: | ---: |
| - | - | - | 1（3.3V） | 2（5V） | - | - | - |
| 8 | 2 | 紫外灯 PWM 输出 | 3（GPIO2/SDA1） | 4（5V） | - | - | - |
| 9 | 3 | - | 5（GPIO3/SCL1） | 6（GND） | - | - | - |
| 7 | 4 | - | 7（GPIO4） | 8（GPIO14/TXD） | EMM TXD -> 驱动 RX | 14 | 15 |
| - | - | - | 9（GND） | 10（GPIO15/RXD） | EMM RXD <- 驱动 TX | 15 | 16 |
| 0 | 17 | ADS1256 D3 输入 | 11（GPIO17） | 12（GPIO18） | ADS1256 D2 输入 | 18 | 1 |
| 2 | 27 | ADS1256 D1 输入 | 13（GPIO27） | 14（GND） | - | - | - |
| 3 | 22 | ADS1256 D0 输入 | 15（GPIO22） | 16（GPIO23） | ADS1256 SCLK 输出 | 23 | 4 |
| - | - | - | 17（3.3V） | 18（GPIO24） | ADS1256 DIN 输出 | 24 | 5 |
| 12 | 10 | - | 19（GPIO10/MOSI） | 20（GND） | - | - | - |
| 13 | 9 | 键盘 P1/ROW1 输出 | 21（GPIO9/MISO） | 22（GPIO25） | ADS1256 DOUT 输入 | 25 | 6 |
| 14 | 11 | 键盘 P2/ROW2 输出 | 23（GPIO11/SCLK） | 24（GPIO8/CE0） | - | 8 | 10 |
| - | - | - | 25（GND） | 26（GPIO7/CE1） | - | 7 | 11 |
| 30 | 0 | 键盘 P3/ROW3 输出 | 27（GPIO0/ID_SD） | 28（GPIO1/ID_SC） | - | 1 | 31 |
| 21 | 5 | 键盘 P4/ROW4 输出 | 29（GPIO5） | 30（GND） | - | - | - |
| 22 | 6 | 键盘 P5/COL1 输入 | 31（GPIO6） | 32（GPIO12） | - | 12 | 26 |
| 23 | 13 | 键盘 P6/COL2 输入 | 33（GPIO13） | 34（GND） | - | - | - |
| 24 | 19 | 键盘 P7/COL3 输入 | 35（GPIO19） | 36（GPIO16） | ADS1256 DRDY 输入 | 16 | 27 |
| 25 | 26 | 键盘 P8/COL4 输入 | 37（GPIO26） | 38（GPIO20） | ADS1256 CS 输出 | 20 | 28 |
| - | - | - | 39（GND） | 40（GPIO21） | ADS1256 RST 输出 | 21 | 29 |

### 复用与冲突

- BCM0（物理 27）是 HAT EEPROM 的 `ID_SD`，当前用于键盘 ROW3。
- BCM2（物理 3）是 I2C1 SDA1 且通常带上拉，当前用于紫外灯 PWM。
- BCM9/11（物理 21/23）是 SPI0 MISO/SCLK，当前用于键盘扫描。
- BCM14/15（物理 8/10）专用于 `/dev/serial0` 电机通信，必须关闭
  serial console。
- ADS1256 在 BCM23/24/25 上运行软件 SPI，不使用 Linux SPI0。
- 树莓派 GPIO 只能承受 3.3 V；5 V 数字侧必须增加电平转换。

## 4x4 矩阵键盘

`16Button/matrix_keypad.py` 是独立驱动模块。UI 和命令行工具复用其扫描、
消抖和键值修正 API，不在界面层直接操作 GPIO。

### 默认接线

| Keypad pin | WiringPi | BCM | Role |
| ---: | ---: | ---: | --- |
| 1 | 13 | 9 | ROW1 |
| 2 | 14 | 11 | ROW2 |
| 3 | 30 | 0 | ROW3 |
| 4 | 21 | 5 | ROW4 |
| 5 | 22 | 6 | COL1 |
| 6 | 23 | 13 | COL2 |
| 7 | 24 | 19 | COL3 |
| 8 | 25 | 26 | COL4 |

当前 `measured` 键值映射来自实测：

```text
D C B A
# 9 6 3
0 8 5 2
* 7 4 1
```

单独测试：

```bash
cd /home/cc/Desktop/UICode
source .venv/bin/activate
python 16Button/read_keypad.py
python 16Button/read_keypad.py --swap-rc     # 行列接反时
python 16Button/read_keypad.py --print-idle  # 显示空闲扫描
```

上层推荐只使用 `MatrixKeypad` 和 `DebouncedMatrixKeypad`。前者负责 GPIO
行列扫描，后者负责消抖、稳定状态及 `KEY_DOWN/KEY_UP` 事件。

## ADS1256

`ADS1256/ads1256_bitbang.py` 使用 `lgpio` 软件 SPI。当前固定接线：

| ADS1256 | Raspberry Pi |
| --- | ---: |
| D3 | WiringPi 0 / BCM17 |
| D2 | WiringPi 1 / BCM18 |
| D1 | WiringPi 2 / BCM27 |
| D0 | WiringPi 3 / BCM22 |
| SCLK | WiringPi 4 / BCM23 |
| DIN | WiringPi 5 / BCM24 |
| DOUT | WiringPi 6 / BCM25 |
| DRDY | WiringPi 27 / BCM16 |
| CS | WiringPi 28 / BCM20 |
| RST | WiringPi 29 / BCM21 |

`D0-D3` 是 ADS1256 数字 I/O，不是模拟输入。模拟输入为 `AIN0-AIN7`。

连接检查：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/check_connection.py \
  --skip-reset --skip-dpins
```

工具依次检查 GPIO、DRDY、前 5 个寄存器、DRATE 写入回读和 D0-D3 双向
连线。寄存器全 `0xFF` 时优先检查 `CS/DOUT/GND`；全 `0x00` 时检查供电、
DOUT 和 SPI 时序；DRDY 始终不低时检查供电、晶振和 DRDY 接线。

监控 `AIN0 - AINCOM`：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/monitor_in0.py
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/scan_channels.py
```

监控默认使用 2.5 V 参考、PGA 1、30 SPS 和 3 点中值。可用 `--vref 5.0`、
`--average 8`、`--drate 100` 调整。0-3.3 V 单端输入默认关闭输入 buffer；
只有确认共模范围满足约束时才增加 `--buffer`。

驱动初始化会硬件复位并回读 `STATUS/MUX/ADCON/DRATE`，强制关闭 CLKOUT
和 Sensor Detect 电流源。RDATA 事务失步时会自动复位并重新配置 ADC。

## EMM V5.0 六灯位转轮

`42Motor/emm_v5.py` 的默认配置：

- 地址 `1`，串口 `115200/8N1`，校验字节 `0x6B`。
- 默认端口 `/dev/serial0`，可用 `--motor-port` 覆盖。
- 默认速度 `60 RPM`，加速度档位 `50`。
- 默认 16 细分，每圈 `3200` 脉冲。

六个基础角度为 `0`、`60`、`120`、`180`、`240`、`300` 度，并统一加上
`42Motor/motor_config.json` 的装配偏移：

```json
{
  "lamp_angle_offset_deg": 0.0
}
```

例如设为 `21.22` 后，目标角度为 `21.22`、`81.22`、`141.22`、
`201.22`、`261.22`、`321.22` 度。偏移直接加到 EMM 绝对坐标，不折算到
`0-360` 度。配置缺失、JSON 错误或数值非有限时，程序会拒绝启动。

在左栏选中“灯组转轮”后，`4/6` 可在左箭头、中间灯位和右箭头间移动焦点。
中间灯位聚焦时按 `A` 进入左栏手动角度模块：数字键实时输入当前灯位绝对
角度，`*` 输入小数点，`A/B` 实时 `+0.1/-0.1°`，`C/D` 实时
`+0.5/-0.5°`，`#` 将换算后的统一装配偏移写入 `motor_config.json` 并退出。
例如蓝光灯位输入 `81.22°` 会保存偏移 `+21.22°`。调节界面只占左栏，右栏
继续显示光电流曲线或 MF500 画面。

驱动核心 API：

```python
from emm_v5 import EmmConfig, EmmV5Motor

motor = EmmV5Motor(EmmConfig())
motor.open()
result = motor.select_lamp(3)
print(result.actual_angle_deg)
motor.close()
```

`open()` 会打开串口、读取版本并使能电机；`select_lamp()`、
`move_to_angle()` 会等待实际到位；`read_position()` 和 `read_state()` 读取
实时状态；`stop()` 立即停止。该 API 本身是同步的，UI 通过
`MotorWorkerThread` 后台调用，避免阻塞 pygame 主线程。

单独测试：

```bash
/home/cc/Desktop/UICode/.venv/bin/python \
  /home/cc/Desktop/UICode/42Motor/raspi_test_position.py
```

`42Motor/test/test_serial.py` 用于只读握手，`test_position.py` 用于交互位置
测试。UI 与测试程序不能同时占用串口。若驱动器改为 32 细分，启动 UI 时
增加 `--motor-pulses-per-revolution 6400`。

## 紫外灯 PWM

`LED/led_pwm.py` 使用 WiringPi 8 / BCM2 / 物理脚 3，默认输出 1 kHz
主动高电平 PWM，UI 初始占空比为 `100%`。

GPIO 不能直接给紫外灯供电，必须连接 MOSFET、三极管或带 PWM 输入的恒流
驱动器，并与树莓派共地。BCM2 通常带上拉，外部驱动级必须保证程序接管前
默认关断；低电平有效模块启动时增加 `--led-active-low`。

紫外灯仅在以下条件全部满足时输出 PWM：实际到位灯位为紫外光、转轮已到位
且静止、测量状态为“测量中”、占空比大于 0。暂停测量、开始转轮、切换灯位
或退出程序时立即熄灯。

独立测试前先停止 UI：

```bash
sudo systemctl stop raspi-ui.service
/usr/bin/python3 /home/cc/Desktop/UICode/LED/test_uv_led.py \
  --duty 30 --seconds 3
sudo systemctl start raspi-ui.service
```

低电平有效时增加 `--active-low`。正常结束或 `Ctrl+C` 中断都会恢复熄灯电平。

## MF500 USB 摄像头

`USBCamara/usb_camera.py` 使用 OpenCV V4L2 后端，只允许产品名严格等于
`MF500 camera` 的设备。无法读取 USB 产品名时，V4L2 节点名称也必须完全
相同；其他摄像头即使位于 `/dev/video0` 也不会被打开。

默认从 `/sys/class/video4linux/video*` 自动发现设备，请求 `640x480`、
`15 FPS` 和 MJPEG。确认设备：

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
for name in /sys/class/video4linux/video*/name; do \
  printf '%s: ' "${name%/name}"; cat "$name"; \
done
```

独立测试：

```bash
sudo systemctl stop raspi-ui.service
/home/cc/Desktop/UICode/.venv/bin/python \
  /home/cc/Desktop/UICode/USBCamara/test_usb_camera.py --frames 30 --debug
sudo systemctl start raspi-ui.service
```

同一台设备可能暴露多个 video 节点。可用 `--device /dev/video2` 固定测试
节点，或用 UI 的 `--camera-device /dev/video2` 固定运行节点，但路径参数不能
绕过名称校验。`--camera-width`、`--camera-height` 和 `--camera-fps` 可调整
采集参数。

摄像头默认开启并使用“小窗”模式。左侧第三个控制项为“USB实时摄像”：用
`4` 选择小窗、`6` 选择全屏，按 `A` 开关摄像；无论当前选择哪个控制项，
都可用 `5` 快速开关。小窗位于光电流曲线绘图区左上四分之一区域，可同时
观察实验现象和电压变化；全屏模式占用整个右侧区域。关闭摄像后采集线程会
释放设备，重新开启时自动连接名称严格匹配的 MF500。即使用户关闭了常驻
摄像，转轮换灯和手动角度调节期间也会临时自动采集并显示；自动显示沿用用户
最后一次选择的小窗/全屏画幅，不修改用户开关或画幅偏好，调节结束后恢复。

## 光电流数据与 FFT

曲线显示 ADS1256 `AIN0 - AINCOM` 跨阻输出电压，单位 `mV`。项目尚未配置
跨阻反馈电阻或标定系数，因此不会虚拟换算成 `nA`。

- 硬件后端读取真实 IN0，使用 2.5 V 参考、PGA 1、30 SPS、3 点中值。
- 模拟后端生成正弦波、灯组、光强和随机噪声，不访问 GPIO。

ADS1256 采样运行在线程中。暂停期间冻结曲线且不累计横轴有效时间，恢复后
FFT 不会把暂停空档当作信号。硬件 UI 与 `monitor_in0.py` 不能同时运行，
否则会出现 `lgpio.error: 'GPIO busy'`。

数据链路：

```text
pygame 主线程
  <- 消息队列 <- IN0 采样线程
  <- ADS1256PhotocurrentSensor
  <- ADS1256BitBang（RDATA、24 位有符号 RAW、VREF/PGA 电压换算）
  <- lgpio / Raspberry Pi GPIO
```

显示滤波顺序：软件量程 `-3300-5000 mV` 与动态中位数/MAD 异常门限、
5 点 FIR 移动平均、一阶 IIR 低通（`alpha=0.35`）。拒绝的尖峰不改变当前
滤波输出。

按 `1` 开启 FFT 后，程序会从最近数据选择不超过 256 点的最大二次幂长度，
按真实时间戳估计采样率并重采样，再去直流、加 Hann 窗并查找主频。

## 代码结构

```text
16Button/matrix_keypad.py       矩阵键盘扫描与消抖
42Motor/emm_v5.py               EMM V5.0 串口协议
42Motor/motor_config.json       六灯位装配偏移
ADS1256/ads1256_bitbang.py      ADS1256 软件 SPI 驱动
LED/led_pwm.py                  紫外灯 PWM 驱动
USBCamara/usb_camera.py         MF500 V4L2 驱动
UI/app.py                       启动入口和命令行参数
UI/ui_app/config.py             1024x600 配置和路径
UI/ui_app/analysis.py           尖峰门限、FIR/IIR 和 FFT
UI/ui_app/state.py              设备状态和曲线缓存
UI/ui_app/input.py              4x4 键盘动作定义
UI/ui_app/hardware.py           模拟/真实硬件适配器
UI/ui_app/workers.py            键盘、ADC、电机、摄像头线程
UI/ui_app/controller.py         实验控制逻辑
UI/ui_app/view.py               中文全屏界面绘制
UI/ui_app/app.py                pygame 主循环
UI/systemd/raspi-ui.service     开机自启动服务
UI/run_hardware_ui.sh           硬件 UI 启动脚本
```
