# 树莓派光电流实验 UI

浙江省大学物理实验竞赛控制界面。程序固定使用 `1024×600` 分辨率并强制全屏，鼠标光标会自动隐藏。现场操作全部通过 `16Button` 目录中的 4×4 矩阵键盘完成。

部署位置：

```text
/home/cc/Desktop/UICode
├── .venv
├── 16Button
│   └── matrix_keypad.py
├── 42Motor
│   └── emm_v5.py
├── Font
│   ├── SimHei.ttf
│   └── Times New Roman.ttf
└── UI
    └── app.py
```

## 安装

安装 GPIO 支持：

```bash
sudo apt update
sudo apt install -y python3-lgpio
```

UI 不依赖树莓派系统字体。中文固定使用项目内的黑体，英文、数字、单位和符号固定使用项目内的 Times New Roman。传输程序时必须将整个 `Font` 目录一并放到 `/home/cc/Desktop/UICode`。

在树莓派上确认两个字体文件存在：

```bash
ls -lh /home/cc/Desktop/UICode/Font/SimHei.ttf
ls -lh "/home/cc/Desktop/UICode/Font/Times New Roman.ttf"
```

启动时终端会打印实际字体路径：

```text
[UI] Chinese font=/home/cc/Desktop/UICode/Font/SimHei.ttf
[UI] Latin font=/home/cc/Desktop/UICode/Font/Times New Roman.ttf
```

安装 UI 的 Python 依赖：

```bash
/home/cc/Desktop/UICode/.venv/bin/python -m pip install -r /home/cc/Desktop/UICode/UI/requirements.txt
```

## 六灯位 EMM 转轮

硬件模式会同时打开地址 `1` 的 EMM V5.0 电机，自动筛选 CH340 串口，并使用 `115200/8N1/0x6B` 通讯。灯组转轮共有六个绝对位置：`0°`、`60°`、`120°`、`180°`、`240°`、`300°`。

在 UI 中用 `2/8` 选中“灯组转轮”，再按 `4/6` 切换灯位。界面会先显示“转动中”，后台持续读取实时位置和到位状态；只有实际角度进入容差并且驱动器到位标志置位后，界面才显示 `OK`。转动期间 pygame 主线程不会被串口阻塞，光电采样上下文也只会在新灯位确认到位后切换。

如果树莓派上有多个 CH340，启动时显式指定电机串口：

```bash
python /home/cc/Desktop/UICode/UI/app.py --backend hardware \
  --motor-port /dev/ttyUSB0
```

默认按照驱动器 16 细分使用每圈 `3200` 脉冲。如果 `MStep` 已修改，例如改为 32 细分，则启动参数也必须改为：

```bash
python /home/cc/Desktop/UICode/UI/app.py --backend hardware \
  --motor-pulses-per-revolution 6400
```

需要检查串口帧时增加 `--debug-motor`。独立电机测试和 UI 不可同时运行，否则会争用同一个串口。

## 通过 SSH 运行

以下命令均显式连接树莓派本机的 `:0` 图形桌面。执行前需要确保用户 `cc` 已经登录树莓派桌面，并且 `/home/cc/.Xauthority` 存在。

进入 UI 主程序最常用的是下面这条硬件模式命令，直接在 SSH 终端中完整执行：

```bash
DISPLAY=:0 XAUTHORITY=/home/cc/.Xauthority \
/home/cc/Desktop/UICode/.venv/bin/python /home/cc/Desktop/UICode/UI/app.py --backend hardware
```

更新程序或字体后，先按 `*` 退出旧界面，再重新执行上述命令。若 UI 由 systemd 服务启动，则使用：

```bash
sudo systemctl restart raspi-ui.service
```

模拟硬件模式：

```bash
DISPLAY=:0 XAUTHORITY=/home/cc/.Xauthority \
/home/cc/Desktop/UICode/.venv/bin/python /home/cc/Desktop/UICode/UI/app.py --backend sim
```

4×4 键盘硬件模式：

```bash
DISPLAY=:0 XAUTHORITY=/home/cc/.Xauthority \
/home/cc/Desktop/UICode/.venv/bin/python /home/cc/Desktop/UICode/UI/app.py --backend hardware
```

按键无响应时，使用调试模式查看终端输出：

```bash
DISPLAY=:0 XAUTHORITY=/home/cc/.Xauthority \
/home/cc/Desktop/UICode/.venv/bin/python /home/cc/Desktop/UICode/UI/app.py --backend hardware --debug-buttons
```

`#` 键会暂停新采样并冻结曲线，按 `A` 可以恢复；`*` 键关闭 UI。开发调试时也可以使用外接键盘的 `Esc` 键退出。

## IN0 光电流跨阻电压

曲线显示量为 ADS1256 `AIN0 - AINCOM` 的跨阻输出电压，单位为 `mV`。项目中尚未配置跨阻反馈电阻或标定系数，因此 UI 不会把电压虚拟换算成 `nA`。

两种后端的数据源：

- `--backend hardware`：读取真实 ADS1256 IN0，使用 2.5 V 参考、PGA 1、30 SPS、3 点中值滤波。
- `--backend sim`：保留原来的正弦波、灯组、光强和随机噪声示例函数，不访问 GPIO。

按 `A` 开始或恢复采样，按 `#` 暂停新采样并冻结当前曲线。横轴记录有效采样时间，暂停期间不累计时间，避免恢复后 FFT 把暂停空档误当成信号。ADS1256 采样运行在独立线程中，pygame 绘制和矩阵键盘不会被 DRDY 等待阻塞。

硬件模式启动后会占用 ADS1256 GPIO。不要同时运行 UI 和独立监控脚本，否则会出现 `lgpio.error: 'GPIO busy'`。如需运行监控脚本，先按 `*` 退出 UI：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/monitor_in0.py
```

UI 不会启动 `monitor_in0.py` 子进程。实际数据链路为：

```text
pygame 主线程
  <- 消息队列 <- IN0 采样线程
  <- ADS1256PhotocurrentSensor
  <- ADS1256BitBang（RDATA、24 位有符号 RAW、VREF/PGA 电压换算）
  <- lgpio / Raspberry Pi GPIO
```

需要把 UI 收到的原始值与独立脚本对照时，运行：

```bash
DISPLAY=:0 XAUTHORITY=/home/cc/.Xauthority \
/home/cc/Desktop/UICode/.venv/bin/python /home/cc/Desktop/UICode/UI/app.py --backend hardware --debug-sensor
```

终端将输出：

```text
[SENSOR READ] mV=-9.422302 RAW=-15808
```

### 滤波与 FFT

屏幕曲线和 FFT 使用滤波后的电压，不直接显示 ADC 原始尖峰。滤波顺序为：

1. UI 软件显示量程 `-3300～5000 mV` 和动态中位数/MAD 异常门限；量程内的负电压会正常进入曲线。
2. 5 点 FIR 移动平均。
3. 一阶 IIR 低通，系数 `α=0.35`。

被拒绝的尖峰不会改变当前滤波输出，界面底部会显示累计“已滤尖峰”数量。`--debug-sensor` 仍输出滤波前的 RAW/mV，并额外打印 `[FILTER REJECT]`，便于核对。

按 `1` 开启 FFT 自动分析，右侧同时显示时域和频域曲线；再按一次 `1` 返回全尺寸时域曲线。FFT 会自动：

- 从最近有效数据中选择不超过 256 点的最大 2 的幂采样长度。
- 根据真实时间戳估计采样率并重采样到等间隔时间轴。
- 去直流、加 Hann 窗并查找主频。
- 根据主频和频率分辨率决定显示中心、频率范围和分析时长。

## 4×4 键盘操作

驱动返回的键值与 `16Button/read_keypad.py` 一致，均为 `0` 至 `9`、`*`、`#`、`A` 至 `D`。当前 UI 使用以下按键：

| 物理键 | 界面动作                           |
| ------ | ---------------------------------- |
| `1`  | 显示或隐藏 FFT 自动分析            |
| `2`  | 选择上一个参数                     |
| `8`  | 选择下一个参数                     |
| `4`  | 减小当前参数；选中测量状态时为暂停 |
| `6`  | 增大当前参数；选中测量状态时为开始 |
| `A`  | 开始或暂停测量                     |
| `B`  | 光强增加 5%                        |
| `C`  | 光强减少 5%                        |
| `D`  | 清空光电流曲线                     |
| `#`  | 暂停新采样并冻结曲线               |
| `*`  | 退出程序                           |

底部操作条使用这些真实键值显示操作，并高亮最近按下的按键。其他未分配动作的矩阵键仍会显示在顶部“最近按键”区域，但不会改变设备状态。

单独检查键盘驱动：

```bash
/home/cc/Desktop/UICode/.venv/bin/python /home/cc/Desktop/UICode/16Button/read_keypad.py
```

如果出现 `No module named 'matrix_keypad'`，表示 UI 没有在预期位置找到驱动。检查文件是否存在：

```bash
ls -l /home/cc/Desktop/UICode/16Button/matrix_keypad.py
```

## 开机自启动

安装服务模板：

```bash
sudo cp /home/cc/Desktop/UICode/UI/systemd/raspi-ui.service /etc/systemd/system/raspi-ui.service
sudo systemctl daemon-reload
sudo systemctl enable --now raspi-ui.service
```

查看日志：

```bash
journalctl -u raspi-ui.service -f
```

服务已内置 `DISPLAY=:0` 和 `XAUTHORITY=/home/cc/.Xauthority`。它只会在程序异常退出时重启；使用 `*` 正常退出后不会自动重新打开。

## 代码结构

```text
app.py                         启动入口和命令行参数
ui_app/config.py               1024×600 运行配置和路径
ui_app/analysis.py             尖峰门限、FIR/IIR 滤波和自动 FFT
ui_app/state.py                设备状态和曲线缓存
ui_app/input.py                4×4 键盘动作定义
ui_app/hardware.py             矩阵键盘、模拟硬件和设备接口
ui_app/workers.py              矩阵键盘和 ADS1256 IN0 后台轮询线程
ui_app/controller.py           实验控制逻辑
ui_app/view.py                 中文全屏界面绘制
ui_app/app.py                  pygame 主循环
systemd/raspi-ui.service       开机自启动服务
```
