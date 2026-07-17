# 紫外灯 PWM 驱动

`led_pwm.py` 使用 `lgpio` 控制紫外灯驱动输入：

- WiringPi 编号：`8`
- BCM 编号：`GPIO2`
- 树莓派 40 针接口：物理引脚 `3`
- 默认 PWM：`1000 Hz`、主动高电平
- UI 默认占空比：`30%`

GPIO 只能输出 3.3 V 逻辑信号，不能直接给紫外灯供电。必须通过 MOSFET、
三极管或带 PWM 输入的恒流驱动器控制灯电源，并让树莓派与灯驱动器共地。
如果驱动输入会向 GPIO 输出 5 V，必须增加电平转换。WiringPi 8 对应的
BCM GPIO2 同时是 I2C SDA1，不要再连接 I2C 设备。

BCM GPIO2 在树莓派板上通常带上拉。主动高电平驱动可能在开机到程序接管
GPIO 之前短暂亮灯，因此外部驱动级必须具备可靠的默认关断设计。如果外部
模块支持低电平有效，建议使用低电平有效输入，并在 UI 启动参数中增加
`--led-active-low`。

## 独立测试

先停止 UI，避免两个程序同时占用 GPIO：

```bash
sudo systemctl stop raspi-ui.service
/usr/bin/python3 /home/cc/Desktop/UICode/LED/test_uv_led.py \
  --duty 30 --seconds 3
```

如果外部灯驱动是低电平有效，增加 `--active-low`。测试结束或按
`Ctrl+C` 中断时，驱动都会关闭 PWM 并将输出恢复为熄灯电平。

重新启动 UI：

```bash
sudo systemctl start raspi-ui.service
```

## UI 联动

硬件 UI 中，紫外灯只在以下条件全部满足时输出 PWM：

1. 当前实际到位灯位为“紫外光”。
2. 转轮已到位且没有运动。
3. 测量状态为“测量中”。
4. 光强占空比大于 `0%`。

按 `#` 暂停、转轮开始运动、切换至其他灯位或退出 UI 时会立即熄灯。
`4/6`、`B/C` 修改的光强百分比会直接更新 PWM 占空比。
