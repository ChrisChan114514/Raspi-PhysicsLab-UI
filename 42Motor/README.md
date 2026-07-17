# EMM V5.0 灯组转轮驱动

`emm_v5.py` 是供树莓派 UI 调用的电机驱动。默认配置如下：

- 电机地址：`1`
- 波特率：`115200`
- 串口格式：`8N1`
- 校验字节：`0x6B`
- 速度：`60 RPM`
- 加速度档位：`50`
- 每圈脉冲数：`3200`（驱动器为默认 16 细分）

六个灯位的基础角度如下。驱动会再为每个灯位统一加上
`motor_config.json` 中的装配偏移量：

| 灯位索引 | 角度 |
| --- | ---: |
| 0 | 0° |
| 1 | 60° |
| 2 | 120° |
| 3 | 180° |
| 4 | 240° |
| 5 | 300° |

## 装配偏移量

`motor_config.json` 保存与真实电机装配有关的参数。目前只有灯组转轮的
统一角度偏移：

```json
{
  "lamp_angle_offset_deg": 0.0
}
```

现场标定后直接修改这个数值。例如设为 `21.22` 后，六个实际目标角度为
`21.22°`、`81.22°`、`141.22°`、`201.22°`、`261.22°`、`321.22°`。
负偏移可写成 `-8.5`。程序启动时读取该文件，修改后需要重启 UI 才会生效。

偏移量直接加到 EMM 的绝对坐标，不会自动折算到 `0～360°`。如果 JSON
缺失、格式错误或偏移量不是有限数值，程序会拒绝启动并报告配置错误，避免
使用错误灯位。

## 驱动 API

```python
from emm_v5 import EmmConfig, EmmV5Motor

motor = EmmV5Motor(EmmConfig())
motor.open()                  # 默认使用树莓派 GPIO UART /dev/serial0，握手并确保电机使能
result = motor.select_lamp(3) # 转到 180° + 装配偏移量，确认实际到位后返回
print(result.actual_angle_deg)
motor.close()
```

主要函数：

- `open()`：打开串口、读取版本并使能电机。
- `select_lamp(index)`：控制灯位 `0..5`，到位后返回 `MoveResult`。
- `move_to_angle(angle)`：发送绝对角度并等待实际到位。
- `read_position()`：读取实时角度。
- `read_state()`：读取使能、到位和堵转状态。
- `stop()`：立即停止当前运动。
- `close()`：停止电机并关闭串口。

驱动不是异步 API。UI 已通过 `MotorWorkerThread` 在后台调用它，避免串口轮询阻塞 pygame 主线程。

## 现场配置

安装串口依赖：

```bash
/home/cc/Desktop/UICode/.venv/bin/python -m pip install pyserial
```

默认会使用树莓派 GPIO UART `/dev/serial0`。如果需要覆盖端口，可在 UI 启动时指定：

```bash
python /home/cc/Desktop/UICode/UI/app.py --backend hardware --motor-port /dev/serial0
```

树莓派上单独测试电机位置时，可直接运行：

```bash
/home/cc/Desktop/UICode/.venv/bin/python /home/cc/Desktop/UICode/42Motor/raspi_test_position.py
```

如果驱动器的 `MStep` 不是默认 16 细分，需要同步传入实际每圈脉冲数。例如 32 细分使用：

```bash
python /home/cc/Desktop/UICode/UI/app.py --backend hardware \
  --motor-pulses-per-revolution 6400
```

`test/test_serial.py` 用于只读握手测试，`test/test_position.py` 用于单独进行交互位置测试；`raspi_test_position.py` 是放在 `42Motor` 根目录的树莓派运行入口。UI 与测试程序不能同时占用同一个串口。
