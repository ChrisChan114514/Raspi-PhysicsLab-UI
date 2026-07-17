# 树莓派光电流实验 UI

浙江省大学物理实验竞赛控制界面。程序固定使用 `1024×600` 分辨率并强制全屏，鼠标光标会自动隐藏。现场操作全部通过 `16Button` 目录中的 4×4 矩阵键盘完成。

部署位置：

```text
/home/cc/Desktop/UICode
├── .venv
├── 16Button
│   └── matrix_keypad.py
├── 42Motor
│   ├── emm_v5.py
│   ├── motor_config.py
│   └── motor_config.json
├── LED
│   ├── led_pwm.py
│   └── test_uv_led.py
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

## 紫外灯 PWM

紫外灯驱动输入使用 WiringPi `8`，程序内部转换为 BCM `GPIO2`（40 针接口
物理引脚 `3`）。默认输出 `1000 Hz` 主动高电平 PWM，UI 的光强百分比就是
PWM 占空比。

GPIO2 只能提供 3.3 V 控制信号，不能直接给紫外灯供电。必须使用 MOSFET、
三极管或带 PWM 输入的恒流驱动器，并将树莓派与灯驱动电源共地。完整接线
注意事项见 `LED/README.md`。GPIO2 自带上拉，主动高电平方案还必须保证
程序启动前硬件处于默认关断状态。

停止 UI 后可单独测试 30% 占空比：

```bash
sudo systemctl stop raspi-ui.service
/usr/bin/python3 /home/cc/Desktop/UICode/LED/test_uv_led.py \
  --duty 30 --seconds 3
sudo systemctl start raspi-ui.service
```

硬件 UI 中，测量状态为“测量中”、紫外灯位已到位且转轮静止时才会点亮；
暂停测量、开始转轮、切换到其他灯位、光强为 `0%` 或退出程序时会熄灭。
界面的“照明光强”标题会显示 `UV亮` 或 `UV灭`。

外部驱动低电平有效时增加 `--led-active-low`；修改 PWM 频率可使用
`--led-pwm-frequency 1000`。调试输出使用：

```bash
DISPLAY=:0 XAUTHORITY=/home/cc/.Xauthority \
/home/cc/Desktop/UICode/.venv/bin/python /home/cc/Desktop/UICode/UI/app.py \
  --backend hardware --debug-led
```

## 六灯位 EMM 转轮

硬件模式会同时打开地址 `1` 的 EMM V5.0 电机，默认使用树莓派 GPIO UART `/dev/serial0`，并使用 `115200/8N1/0x6B` 通讯。灯组转轮的六个基础位置为 `0°`、`60°`、`120°`、`180°`、`240°`、`300°`，实际位置会统一加上 `42Motor/motor_config.json` 中的 `lamp_angle_offset_deg`。

例如真实装配需要整体增加 `21.22°`，将配置改为：

```json
{
  "lamp_angle_offset_deg": 21.22
}
```

修改后重启 UI，界面显示、启动时的最近灯位判断和电机运动命令都会使用偏移后的实际角度。该 JSON 必须和 `emm_v5.py`、`motor_config.py` 一起部署到树莓派的 `42Motor` 目录。

在 UI 中用 `2/8` 选中“灯组转轮”，再按 `4/6` 聚焦左/右箭头，最后按 `A` 确认切换灯位。界面会先显示“转动中”，后台持续读取实时位置和到位状态；只有实际角度进入容差并且驱动器到位标志置位后，界面才显示 `OK`。转动期间 pygame 主线程不会被串口阻塞，光电采样上下文也只会在新灯位确认到位后切换。

如果需要覆盖默认 GPIO UART 端口，启动时显式指定电机串口：

```bash
python /home/cc/Desktop/UICode/UI/app.py --backend hardware \
  --motor-port /dev/serial0
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

`#` 键独立控制测量开始或暂停；`A`、`4`、`6` 都不会改变测量状态。`*` 键关闭 UI。开发调试时也可以使用外接键盘的 `Esc` 键退出。

## IN0 光电流跨阻电压

曲线显示量为 ADS1256 `AIN0 - AINCOM` 的跨阻输出电压，单位为 `mV`。项目中尚未配置跨阻反馈电阻或标定系数，因此 UI 不会把电压虚拟换算成 `nA`。

两种后端的数据源：

- `--backend hardware`：读取真实 ADS1256 IN0，使用 2.5 V 参考、PGA 1、30 SPS、3 点中值滤波。
- `--backend sim`：保留原来的正弦波、灯组、光强和随机噪声示例函数，不访问 GPIO。

无论当前选中哪个参数，按 `#` 都会在“开始测量”和“暂停测量”之间切换。暂停时冻结当前曲线；恢复后继续采样。`A` 键只用于确认灯组转轮的箭头选择，与测量启停完全解耦；测量过程中确认切灯也不会自动暂停。横轴记录有效采样时间，暂停期间不累计时间，避免恢复后 FFT 把暂停空档误当成信号。ADS1256 采样运行在独立线程中，pygame 绘制和矩阵键盘不会被 DRDY 等待阻塞。

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
| `4`  | 灯组转轮中选左箭头；照明光强减小   |
| `6`  | 灯组转轮中选右箭头；照明光强增大   |
| `A`  | 确认灯组转轮的箭头选择，不控制测量 |
| `B`  | 光强增加 5%                        |
| `C`  | 光强减少 5%                        |
| `D`  | 清空光电流曲线                     |
| `#`  | 开始或暂停测量；暂停时冻结曲线     |
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

UI 启动脚本为 `UI/run_hardware_ui.sh`。它等价于手动进入
`/home/cc/Desktop/UICode`、激活 `.venv`，再设置 `DISPLAY=:0` 和
`XAUTHORITY=/home/cc/.Xauthority` 后以硬件模式运行 UI。脚本还会等待图形
桌面和 `.Xauthority` 最多 60 秒，适合在开机阶段由 systemd 调用。

先手动测试脚本：

```bash
/bin/bash /home/cc/Desktop/UICode/UI/run_hardware_ui.sh
```

确认 UI 能正常打开后，安装并启用服务：

```bash
sudo cp /home/cc/Desktop/UICode/UI/systemd/raspi-ui.service /etc/systemd/system/raspi-ui.service
sudo systemctl daemon-reload
sudo systemctl enable --now raspi-ui.service
```

如果旧版 service 在 `enable --now` 时一直等待，先按 `Ctrl+C`，再重新复制
当前 service 并执行 `daemon-reload`。`Ctrl+C` 只中断等待，不会删除已经创建的
开机自启动链接。

查看运行状态和实时日志：

```bash
systemctl status raspi-ui.service --no-pager
journalctl -u raspi-ui.service -f
```

修改程序后重启 UI：

```bash
sudo systemctl restart raspi-ui.service
```

停止服务并取消开机自启动：

```bash
sudo systemctl disable --now raspi-ui.service
```

service 通过 `/bin/bash` 调用脚本，因此脚本不依赖可执行权限。服务只会在
程序异常退出或启动环境未就绪时重试；使用 `*` 正常退出后不会自动重新打开。
树莓派必须启用 `cc` 用户的桌面自动登录，否则不会生成可供 UI 使用的
`:0` 图形会话和 `/home/cc/.Xauthority`，服务会等待并定期重试。

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
run_hardware_ui.sh             硬件 UI 启动脚本
```
