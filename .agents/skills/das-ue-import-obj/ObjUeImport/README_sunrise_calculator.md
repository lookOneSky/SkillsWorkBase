# 日出计算命令行工具

`sunrise_calculator.exe` 使用 NOAA 太阳位置近似公式计算指定地点、指定日期的当地日出时间。
经纬度采用十进制度：北纬、东经为正，南纬、西经为负。

直接双击 `sunrise_calculator.exe`，或不带参数启动，即可打开 Qt 输入界面。界面可输入日期、
经纬度和 UTC 偏移，并预置了可直接测试的北京参数。

带参数启动时进入命令行模式。

完整参数示例（北京，2026-09-09）：

```powershell
.\sunrise_calculator.exe --date 2026-09-09 --latitude 39.9042 --longitude 116.4074 --utc-offset 8 --format text
```

JSON 输出：

```powershell
.\sunrise_calculator.exe --date 2026-09-09 --latitude 39.9042 --longitude 116.4074 --utc-offset 8 --format json
```

参数：

- `--date`：当地日期，严格使用 `YYYY-MM-DD`。
- `--latitude`：纬度，范围 `-90` 到 `90`，北纬为正。
- `--longitude`：经度，范围 `-180` 到 `180`，东经为正。
- `--utc-offset`：当地时间相对 UTC 的小时偏移，范围 `-14` 到 `14`。
- `--format`：`text` 或 `json`，默认 `text`。

结果里的 `sunrise_local` 是当地钟表时间；`time_of_day_0_2400` 是 UDS 使用的线性时间刻度，
例如 `548.5` 表示约 `05:29:06`，并不是普通的 `HHMM` 数字。

正常成功返回 `0`，参数错误返回 `2`，极昼或极夜导致当天没有日出时返回 `3`。
