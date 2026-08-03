# Old Raspberry Pi GPIO ADS1256 driver

This directory keeps the previous Raspberry Pi direct GPIO/software-SPI ADS1256
driver and its diagnostic scripts.

Current hardware UI uses the STM32F103 ADS1256 parallel bridge in the parent
directory:

- `../stm32_parallel_bridge.py`
- `../stm32_parallel_test.py`

The old direct driver is retained only for reference, rollback, and standalone
diagnostics:

- `ads1256_bitbang.py`
- `check_connection.py`
- `monitor_in0.py`
- `scan_channels.py`

