# EMM V5.0 灯组转轮驱动

`emm_v5.py` 是供树莓派 UI 调用的电机驱动。默认配置如下：

- 电机地址：`1`
- 波特率：`115200`
- 串口格式：`8N1`
- 校验字节：`0x6B`
- 速度：`60 RPM`
- 加速度档位：`50`
- 每圈脉冲数：`3200`（驱动器为默认 16 细分）

六个灯位与绝对角度的映射：

| 灯位索引 | 角度 |
| --- | ---: |
| 0 | 0° |
| 1 | 60° |
| 2 | 120° |
| 3 | 180° |
| 4 | 240° |
| 5 | 300° |

## 驱动 API

```python
from emm_v5 import EmmConfig, EmmV5Motor

motor = EmmV5Motor(EmmConfig())
motor.open()                  # 自动选择 CH340，握手并确保电机使能
result = motor.select_lamp(3) # 转到 180°，确认实际到位后返回
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

如果系统存在多个 CH340，可在 UI 启动时指定端口：

```bash
python /home/cc/Desktop/UICode/UI/app.py --backend hardware --motor-port /dev/ttyUSB0
```

如果驱动器的 `MStep` 不是默认 16 细分，需要同步传入实际每圈脉冲数。例如 32 细分使用：

```bash
python /home/cc/Desktop/UICode/UI/app.py --backend hardware \
  --motor-pulses-per-revolution 6400
```

`test/test_serial.py` 用于只读握手测试，`test/test_position.py` 用于单独进行交互位置测试。UI 与测试程序不能同时占用同一个串口。
