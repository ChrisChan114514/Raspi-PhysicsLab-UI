# ADS1256 Raspberry Pi Driver

这里先做连接完备性检查，不直接做正式采样 UI。

## 语言选择

当前阶段建议用 Python：

- 排线、复位、DRDY、寄存器读写问题可以快速打印出来。
- 后续 UI 主程序也大概率会先用 Python，诊断工具可以直接复用。
- ADS1256 真正高采样率连续读取时，再考虑把稳定逻辑移到 C++。

## 当前规定引脚

用户实际接线使用 WiringPi 编号。程序内部会自动转换成 `lgpio` 需要的 BCM 编号：

| ADS1256 |        Raspberry Pi |
| ------- | ------------------: |
| D3      |  WiringPi 0 / BCM17 |
| D2      |  WiringPi 1 / BCM18 |
| D1      |  WiringPi 2 / BCM27 |
| D0      |  WiringPi 3 / BCM22 |
| SCLK    |  WiringPi 4 / BCM23 |
| DIN     |  WiringPi 5 / BCM24 |
| DOUT    |  WiringPi 6 / BCM25 |
| DRDY    | WiringPi 27 / BCM16 |
| CS      | WiringPi 28 / BCM20 |
| RST     | WiringPi 29 / BCM21 |

注意：

- 树莓派 GPIO 只能承受 3.3V。ADS1256 数字侧如果是 5V，需要电平转换。
- 不要把 WiringPi 编号和 BCM 编号混用。`lgpio` 操作的是 BCM，脚本默认已按 WiringPi 转换。

## 安装依赖

建议用系统 Python 或继承系统包的 venv：

```bash
sudo apt install -y python3-lgpio
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
```

## 运行连接检查

```bash
cd ~/Desktop/Button_S21001
python Code/ADS1256/check_connection.py
```

如果你的目录是 `~/Desktop/UICode/ADS1256`：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/check_connection.py --skip-reset --skip-dpins
```

如果只想先检查 SPI 寄存器，不测试 D0-D3：

```bash
python Code/ADS1256/check_connection.py --skip-dpins
```

如果没有接 RST，或者 RST 使用了不可访问的 GPIO：

```bash
python Code/ADS1256/check_connection.py --skip-reset --skip-dpins
```

脚本默认按 WiringPi 编号解释固定引脚表。如果要临时切回旧的 BCM 解释：

```bash
python Code/ADS1256/check_connection.py --numbering bcm
```

## 检查内容

脚本会依次检查：

1. GPIO 是否能被 `lgpio` 打开。
2. `RST` 复位后 `DRDY` 是否会拉低。
3. 能否通过软件 SPI mode 1 读取 ADS1256 前 5 个寄存器。
4. 能否写入并读回 `DRATE` 寄存器。
5. 能否通过 ADS1256 的 `IO` 寄存器验证 D0-D3 双向连线。

典型成功输出里应该看到：

```text
[PASS] drdy_low: DRDY reached low
[PASS] register_sanity: STATUS=0x.. MUX=0x.. ADCON=0x.. DRATE=0x.. IO=0x..
[PASS] spi_write_read: DRATE original=0x.. wrote=0x.. read=0x..
```

如果寄存器全是 `0xFF`，优先检查 `CS/DOUT/GND`。

如果寄存器全是 `0x00`，优先检查 `DOUT` 是否被拉低、ADS1256 是否供电、SPI 时序是否接反。

如果 `DRDY` 一直不低，优先检查 ADS1256 供电、晶振/时钟、`DRDY` 接线。

## 监控 AIN0

`D0-D3` 不是 ADC 输入。ADS1256 的 8 路模拟输入是 `AIN0` 到 `AIN7`。

监控 `AIN0`，每 0.5 秒输出一次。脚本固定读取 IN0，每行只包含毫伏值和有符号 RAW 值。默认使用 30 SPS 和 3 点中值，以提高 Python 软件 SPI 在 Linux 调度下的时序余量：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/monitor_in0.py
```

输出示例：

```text
mV=+73.580740 RAW=123456
```

如果参考电压不是 2.5V，用 `--vref` 指定：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/monitor_in0.py --vref 5.0
```

0~3.3V 单端输入时，脚本默认关闭 ADS1256 输入 buffer。buffer 打开后有输入共模范围限制，可能导致高电压段被压缩或失真。只有确认输入范围满足 ADS1256 buffer 约束时才加：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/monitor_in0.py --buffer
```

初始化会强制写入 `ADCON = PGA`，也就是：

- `CLKOUT` 关闭
- `SDCS` Sensor Detect 电流源关闭
- `PGA` 按参数设置，默认 1

这样避免 ADS1256 残留的 Sensor Detect 电流源把 `AIN0` 通过外部电阻抬高。

调整平均采样数：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/monitor_in0.py --average 8
```

对照旧的 100 SPS 配置：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/monitor_in0.py --drate 100 --average 8
```

驱动启动时会执行硬件复位，并回读校验 `STATUS/MUX/ADCON/DRATE`。软件 SPI 使用微秒忙等待，避免 `time.sleep()` 在 Linux 下主动让出调度；若 RDATA 后 DRDY 状态表明事务失步，脚本会自动复位并重新配置 ADC。

如果怀疑通道接错或板子标号与 AIN 编号不一致，扫描 8 路：

```bash
/usr/bin/python3 /home/cc/Desktop/UICode/ADS1256/scan_channels.py
```
