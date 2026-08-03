# CE_MES_SEC 关键逻辑与功能代码块参考

> 用途：重构 / 三星客户新项目时，按模块复制模式与接口，不必再翻 6900 行 `test.py`。  
> 原则：本文提炼**可复用骨架与关键算法**；工位差异只保留「过水 016」完整模板，其余工位注明入口与差异。  
> 源码锚点：文件路径 + 函数名，便于回源核对。

---

## 目录

1. [系统总览与数据流](#1-系统总览与数据流)
2. [启动 / 线程 / 工作状态机](#2-启动--线程--工作状态机)
3. [配置加载](#3-配置加载)
4. [串口层](#4-串口层)
5. [治具帧协议（组帧 / 拆帧）](#5-治具帧协议组帧--拆帧)
6. [命令路由与工位分发](#6-命令路由与工位分发)
7. [扫码门闸（编码规则 + MES 过站）](#7-扫码门闸编码规则--mes-过站)
8. [门闸应答连发（0x57 / 0x58 / 0x89）](#8-门闸应答连发0x57--0x58--0x89)
9. [工位模板：基站过水 016（完整可复制骨架）](#9-工位模板基站过水-016完整可复制骨架)
10. [工位一览与模式入口](#10-工位一览与模式入口)
11. [MES 门面与双后端](#11-mes-门面与双后端)
12. [UI 关键接口](#12-ui-关键接口)
13. [上位机工具工位（≥100）](#13-上位机工具工位100)
14. [数据库 / CSV / 工具函数](#14-数据库--csv--工具函数)
15. [重构时建议的接口切面](#15-重构时建议的接口切面)

---

## 1. 系统总览与数据流

```
main.py
  └─ wx.App → ui.MainFrame
                 ├─ load_config()          # 读 config.yaml
                 ├─ start_work_thread()    # 循环 test_run_process
                 └─ start_serial_thread()  # 循环 test_serial_process

扫码枪(键盘楔入) → barcode_q → barcode_check_process / 工具工位
治具串口 RX     → test_rx_q  → 拆帧 → test_cmd_handle → *_mode
上位机 TX       → test_tx_q  → 串口 write
业务结果        → mes_run.add_report / send_report → CSV + MES
UI 刷新         → wx.CallAfter(MainFrame.up_*)
```

| 角色 | 源文件 |
|------|--------|
| 入口 | `main.py` |
| UI | `ui/MainFrame.py` |
| 线程 | `mythread.py` |
| 业务核心 | `test_tool/test.py` |
| 串口 | `myserial/use_serial.py`, `myserial/test_serial.py` |
| MES | `mes/mes_run.py`, `celink_mes.py`, `anker_mes.py` |
| 编码规则 | `test_tool/encode_rules.py` |
| 工具工位 | `bind_robot.py` / `withstand_vol.py` / `sn_check.py` / `weigh_station.py` |
| DB | `database/sqlite_db.py` |
| 工具函数 | `tool_box/tool.py` |

**两类工位：**

| 条件 | 含义 | 触发方式 |
|------|------|----------|
| `device_type < 100` | 主板治具（海能帧协议） | 治具发 `0x66` → 扫码门闸 → `0x77`/`0x88` |
| `device_type ≥ 100` | 上位机工具 | 扫码直接 `idle→running`，自管串口/纯软件 |

---

## 2. 启动 / 线程 / 工作状态机

### 2.1 入口（`main.py`）

```python
import wx
from ui import MainFrame

def print_hi(name):
    app = wx.App()
    window = MainFrame.MainFrame(parent=None)
    window.Show()
    app.MainLoop()

if __name__ == '__main__':
    print_hi('海能机器人')
```

### 2.2 双线程（`mythread.py`）

```python
import threading
from myserial import test_serial
from test_tool import test

work_stop_event = threading.Event()
serial_stop_event = threading.Event()

def thread_test_running():
    while not work_stop_event.is_set():
        test.test_run_process()   # 业务主循环 ~10ms

def thread_serial_running():
    while not work_stop_event.is_set():   # 注意：现实现误用 work_stop_event
        test_serial.test_serial_process()

def start_work_thread():
    work_stop_event.clear()
    threading.Thread(target=thread_test_running, daemon=False).start()

def start_serial_thread():
    serial_stop_event.clear()
    threading.Thread(target=thread_serial_running, daemon=False).start()
```

### 2.3 工作状态机（`test_tool/test.py`）

```python
# 全局状态
test_work_state = "init"   # init → idle → running → stop
barcode_q = queue.Queue()  # 扫码枪字符串
check_sn_enable = False    # 治具发 0x66 后置 True，允许过站
check_sn_str = ""          # 当前会话 SN
test_start_time = datetime.now()
test_end_time = datetime.now()

def test_run_process():
    check_ser_connect_and_up_ui()
    if error_handle():
        return
    check_process_run_state()

    # 主板治具：扫码门闸 + 串口帧
    if int(load_cfg.dev) < 100:
        barcode_check_process()
        rv50_omini_air_config_push_tick()   # 015/021 配置码下发
        fixture_reply_burst_tick()          # 0x57/58/89 连发
        test_serial_rx_data_handle()

    if test_work_state == "running":
        # 上位机工具分发
        if int(load_cfg.dev) == 101:
            withstand_vol.test_process()
        elif int(load_cfg.dev) == 100:
            bind_robot.bind_sn_process()
        elif int(load_cfg.dev) == 102:
            check_barcodes_match_process()
        elif int(load_cfg.dev) == 103:
            sn_check.check_barcodes_of_parts_box_process()
        elif int(load_cfg.dev) == 104:
            withstand_vol.test_mode_zc7122d_process()
        elif int(load_cfg.dev) == 105:
            withstand_vol.test_mode_new_zc7122d_process()
        elif int(load_cfg.dev) == 106:
            weigh_station.process()
    elif test_work_state == "idle":
        test_idle_work()
    elif test_work_state == "init":
        load_config()
        test_init_work()
        test_work_state = "idle"
    elif test_work_state == "stop":
        pass
    time.sleep(0.01)
```

### 2.4 工具工位：扫码进入 running

```python
def check_process_run_state():
    global test_work_state, barcode_msg_update, test_start_time
    if test_work_state == "idle":
        dev = int(load_cfg.dev)
        if dev in (100, 101, 102, 103, 104, 105, 106):
            if barcode_msg_update:
                test_start_time = datetime.now()
                test_work_state = "running"
                barcode_msg_update = False
                # 收集 SN 到 sn_save_list，置 sn_up_enable 等
```

### 2.5 init 提示文案分支（摘要）

```python
def test_init_work():
    if int(load_cfg.dev) in (102, 103):
        # 打开 SQLite + 「请扫条码」
        ...
    elif int(load_cfg.dev) == 106:
        # 称重方案一/二提示
        ...
    elif int(load_cfg.dev) >= 100:
        # 「请扫主机条码开始测试」
        ...
    else:
        # 「请启动治具开始测试」
        ...
```

---

## 3. 配置加载

### 3.1 配置结构（`LoadCfg` 精简版）

```python
from dataclasses import dataclass

@dataclass
class LoadCfg:
    dev: str = "001"          # device_type 三位字符串
    com: str = ""             # user_com，空=自动识别
    mes: str = "3"            # use_mes：意图 1双/2海能/3安克（见下方坑）
    mcu_ver: str = ""         # 基站/MCU 版本期望
    base_station_config_expected: str = ""  # XX.XX.XX
    show_base_station_config_ui: int = 1
    test_tool: str = ""       # 治具编码（海能 MES）
    parts_sn_head: str = ""   # 103 配件条码头
    project_name: str = ""
    # 106 称重
    weight_min_kg: float = 100.0
    weight_max_kg: float = 150.0
    weight_read_delay_sec: float = 1.0
    weight_read_timeout_sec: float = 2.0
    weigh_scheme: str = "1"   # "1"固定限 "2"μ±kσ
    weigh_pass_first_n: int = 5
    weigh_sigma_k: float = 1.0
    weigh_history_json_path: str = "weigh_106_history.json"
    # 各工位阈值字段：rv50water_* / rv50air_* / rv50_* / omini_* / rv30_* ...
    # （完整列表见 test.py LoadCfg）

load_cfg = LoadCfg()
```

### 3.2 加载骨架

```python
def load_config():
    config = read_yaml(get_config_path())  # 打包后旁路 exe 目录

    load_cfg.com = config.get('user_com', "")
    load_cfg.dev = config['device_type']
    load_cfg.mcu_ver = normalize_ver_string(str(config.get('mcu_version', "")).strip())
    load_cfg.test_tool = config.get('test_tool', "治具未编码")
    load_cfg.mes = config.get('use_mes', "3")
    load_cfg.parts_sn_head = config.get('parts_sn_head', "")
    load_cfg.project_name = config.get('project_name', "C10B ")
    # ... 各工位阈值 config.get(...) ...

    if not is_com_port(load_cfg.com):
        load_cfg.com = ""

    # ⚠ 现实现坑：合法 1~3 时强制改成 '002'（仅海能路径）
    if int(load_cfg.mes) < 1 or int(load_cfg.mes) > 3:
        load_cfg.mes = str(load_cfg.mes)
    else:
        load_cfg.mes = '002'   # 重构时务必改掉：保留用户选择
```

### 3.3 `config.yaml` 公共项（复制用）

```yaml
device_type: "016"          # 工位编号
project_name: "RV50"        # 窗口标题前缀
use_mes: "2"                # 1=双MES  2=仅海能  3=仅安克
user_com: ""                # 空=自动识别 CH340/CP210x/PL2303
mcu_version: "005.001.013"  # 空或注释=不比对版本
base_station_config_expected: "FF.FF.FF"
show_base_station_config_ui: 0
```

**跳过规则约定（基站工位通用）：**

- 区间类：上下限均为 `0` → 不参与比较、不显示、不上报  
- 精确值类（水量等）：期望 `-1` → 跳过  
- 版本/配置码：空字符串 → 跳过  

---

## 4. 串口层

### 4.1 开/关与波特率（`myserial/use_serial.py`）

```python
def serial_open(ser, port, ser_timeout):
    if ser.is_open:
        return 0
    ser.port = port
    # 耐压仪 / 电子秤：9600；治具主板：115200
    if test.load_cfg.dev in ("101", "104", "105", "106"):
        ser.baudrate = 9600
    else:
        ser.baudrate = 115200
    ser.timeout = ser_timeout
    ser.open()
    return 0 if ser.is_open else 1
```

### 4.2 TX/RX 队列（`myserial/test_serial.py`）

```python
test_ser = serial.Serial()
test_rx_q = queue.Queue()
test_tx_q = queue.Queue()

# USB PID 优先：CH340 / CP210x / PL2303
com_id_list = [29987, 60000, 8963]

def test_serial_send(dat: bytes):
    if not test_tx_q.full():
        test_tx_q.put(dat)

def test_serial_process():
    test_serial_rx_run()
    test_serial_tx_run()
    time.sleep(0.01)

def open_test_com() -> bool:
    ports = use_serial.get_serial_list()
    com, com_id = "", -1
    for port in ports:
        if test.load_cfg.com:
            if port.name == test.load_cfg.com:
                com, com_id = port.name, port.pid
                break
        else:
            com, com_id = port.name, port.pid
            if com_id in com_id_list:
                break
    if not com:
        return False
    timeout = 0.05 if test.load_cfg.dev in ("101","104","105","106") else 0.01
    return use_serial.serial_open(test_ser, com, timeout) == 0
```

---

## 5. 治具帧协议（组帧 / 拆帧）

### 5.1 帧格式

```
| 0xA5 | 0x5A | len | dev | cmd | payload[0..n] | checksum |
         len = 2 + len(payload)   # 含 dev+cmd
         checksum = sum(len, dev, cmd, ...payload) % 256
```

### 5.2 关键命令字

| cmd | 方向 | 含义 |
|-----|------|------|
| `0x66` | 治具→PC | 开始测试 / 请求扫码 |
| `0x57` | PC→治具 | 门闸通过（payload=SN 字节） |
| `0x58` | PC→治具 | 门闸失败 |
| `0x77` | 治具→PC | 实时产测数据 |
| `0x88` | 治具→PC | 结束（首字节常：`03`正常 / `04`通讯失败） |
| `0x89` | PC→治具 | 异常应答（常见 payload `[0x03]`） |
| `0x68` | 治具→PC | 部分工位阈值/参数上传 |

帧内 `dev` 字节 ≈ `int(device_type)`（如 016→0x10，050→0x32）。

### 5.3 组帧发送

```python
from tool_box import tool

def ser_send_cmd(dev, cmd):
    ck_sum = (0x02 + dev + cmd) % 256
    ser_dat = bytes([0xA5, 0x5A, 0x02, dev, cmd, ck_sum])
    test_serial.test_serial_send(ser_dat)

def ser_send_data(dev, cmd, data):
    """data: list[int] 字节列表"""
    data_len = len(data)
    ck_sum = tool.check_sum([0x02 + data_len, dev, cmd] + data)
    ser_dat = bytes([0xA5, 0x5A, 0x02 + data_len, dev, cmd] + data + [ck_sum])
    test_serial.test_serial_send(ser_dat)
```

### 5.4 字节流拆帧状态机

```python
pack_data, check_data = [], []
pack_data_len = check_dev = check_cmd = check_sum = 0

def test_rx_data_handle(hex_dat):
    global pack_data, pack_data_len, check_dev, check_cmd, check_data, check_sum
    pack_data.append(hex_dat)

    if len(pack_data) == 1:
        if hex_dat != 0xA5:
            pack_data = []
        return
    if len(pack_data) == 2:
        if hex_dat != 0x5A:
            pack_data = []
        return
    if len(pack_data) == 3:
        pack_data_len = hex_dat
        check_sum = hex_dat
        return
    if len(pack_data) == 4:
        check_dev = hex_dat
        check_sum += hex_dat
        return
    if len(pack_data) == 5:
        check_cmd = hex_dat
        check_sum += hex_dat
        check_data = []
        return
    if 5 < len(pack_data) <= pack_data_len + 3:
        check_data.append(hex_dat)
        check_sum += hex_dat
        return
    # 校验字节
    if check_sum % 256 == hex_dat:
        test_cmd_handle(check_dev, check_cmd, check_data)
    pack_data = []
```

### 5.5 校验和（`tool_box/tool.py`）

```python
def check_sum(data):
    ck_sum = 0
    for dat in data:
        ck_sum += dat
    return ck_sum % 256
```

---

## 6. 命令路由与工位分发

```python
def test_cmd_handle(dev, cmd, dat):
    if len(dat) < 1:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second="治具数据异常", color=wx.RED)
        return
    if int(load_cfg.dev) != int(dev):
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second="治具类型不匹配", color=wx.RED)
        return

    d = int(dev)
    if d in (1, 6):
        dust_collector_mode(dev, cmd, dat)
    elif d in (3, 4):
        lt_bump_mode(dev, cmd, dat)
    elif d == 5:
        cliff_tool_mode(dev, cmd, dat)
    elif d == 7:
        robot_static_current_mode(dev, cmd, dat)
    elif d in (10, 11):
        left_right_wheel_mode(dev, cmd, dat)
    elif d == 12:
        side_brush_mode(dev, cmd, dat)
    elif d == 13:
        main_brush_mode(dev, cmd, dat)
    elif d == 16:
        RV50_water_mode(dev, cmd, dat)
    elif d == 15:
        RV50_air_mode(dev, cmd, dat)
    elif d == 21:
        Omini_air_mode(dev, cmd, dat)
    elif d == 22:
        Omini_water_mode(dev, cmd, dat)
    elif d == 20:
        Omini_finished_product_mode(dev, cmd, dat)
    elif d == 17:
        RV50_finished_product_mode(dev, cmd, dat)
    elif d == 18:
        RV50_pcba_mode(dev, cmd, dat)
    elif d == 19:
        wsxqmx_mode(dev, cmd, dat)
    elif d == 50:
        RV30_finished_product_mode(dev, cmd, dat)
```

**重构建议：** 用 `STATION_REGISTRY[d].on_frame(cmd, dat)` 替换整段 `elif`。

---

## 7. 扫码门闸（编码规则 + MES 过站）

### 7.1 通用模式（多数 &lt;100 工位）

```python
def barcode_check_process():
    global check_sn_enable, check_sn_str
    if not (check_sn_enable and not barcode_q.empty()):
        return

    sn = barcode_q.get()
    sn_bytes = [int(b) for b in sn.encode('utf-8')]

    # 1) 编码规则
    if not encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn)):
        # 回 0x58（部分工位用三连发 fixture_gate_fail_burst）
        ser_send_data(int(load_cfg.dev), 0x58, sn_bytes)
        check_sn_enable = False
        return

    # 2) MES 过站
    ok = mes_run.check_sn_is_ok(sn)
    check_sn_str = sn
    if ok:
        ser_send_data(int(load_cfg.dev), 0x57, sn_bytes)  # 或 fixture_gate_pass_burst
        # 置会话 RUNNING，清 finalize 标志
        wx.CallAfter(..., second="过站成功，等待治具发送产测命令", ...)
    else:
        ser_send_data(int(load_cfg.dev), 0x58, sn_bytes)
    check_sn_enable = False
```

各工位差异（复制时对照源码）：

| dev | 过站成功 | 过站失败 | 备注 |
|-----|----------|----------|------|
| 016/015/017/019/050 | `fixture_gate_*_burst`（连发） | 同左 | 015 成功还下发配置码 |
| 020 | 单次 0x57 | 0x58+0x89 | |
| 018/021/022 等 | 单次或连发 | 视分支 | |

### 7.2 SN 编码规则（`encode_rules.py`）

```python
sn_encoding_rules = {
    "001": [r"A([0-9A-Z]){2}A06\d([0-9A-Z]){4}\d{5}"],
    "003": [r"H481500000236XX-Q\d{2}-...", ...],
    "007": [r"A([0-9A-Z]){2}A00\d([0-9A-Z]){4}\d{5}"],
    "010": [r"^AGEC10L\d{2}...$"],
    # ... 按 device_type；绑码另有 "robot"/"bat"/"front"
}

def match_sn_encoding_rules(dev="001", sn=""):
    rules = sn_encoding_rules.get(dev)
    if rules:
        for rule in rules:
            if re.match(rule, sn):
                return True
        # ⚠ 现实现：有规则但全不匹配时仍 return True（注释掉了 return False）
    return True   # 无规则 → 放行
```

---

## 8. 门闸应答连发（0x57 / 0x58 / 0x89）

治具可能丢首包，上位机对门闸应答做短间隔连发；收到首帧 `0x77` 可取消成功连发。

```python
FIXTURE_REPLY_BURST_COUNT = 3          # 实际常量见 test.py
FIXTURE_REPLY_BURST_INTERVAL_MS = 50   # 见源码

def fixture_gate_pass_burst(dev, payload):
    fixture_gate_burst_start(dev, 0x57, payload, cancel_on_77=True)

def fixture_gate_fail_burst(dev, payload):
    fixture_gate_burst_start(dev, 0x58, payload, cancel_on_77=False)

def fixture_gate_burst_start(dev, cmd, payload, max_count=..., cancel_on_77=False):
    # 立即发第 1 包；后续由 fixture_gate_burst_tick() 在主循环补发
    ser_send_data(fixture_gate_burst_tx_dev(dev), cmd, list(payload))
    ...

def fixture_89_burst_start(dev):
    ser_send_data(..., 0x89, [0x03])
    # tick 补发
```

主循环每轮：`fixture_reply_burst_tick()`。

---

## 9. 工位模板：基站过水 016（完整可复制骨架）

> 这是当前代码里最完整的「字段注册表 + 会话状态机」范式，新工位建议照抄再改字段。

### 9.1 会话常量与状态

```python
RV50WATER_SESS_IDLE = "idle"
RV50WATER_SESS_WAIT_SN = "wait_sn"
RV50WATER_SESS_RUNNING = "running"
RV50WATER_SESS_DONE = "done"
RV50WATER_77_DATA_LEN = 24   # 0x77 数据区字节数

rv50water_session_state = RV50WATER_SESS_IDLE
rv50water_last_step = -1
rv50water_last_p = None
rv50water_got_step3 = False
rv50water_finalize_done = False
```

### 9.2 字段注册表（UI / MES / 判据一体）

```python
RV50WATER_FIELD_REGISTRY = [
    {"field": "clear_vol", "kind": "exact_int", "ui": "clear_water_volume",
     "mes": "清水通路过水", "parse_key": "clear_water_volume",
     "expect_attr": "rv50water_clear_volume_expected"},
    {"field": "duty_vol", "kind": "exact_int", "ui": "duty_water_volume",
     "mes": "污水通路过水", "parse_key": "duty_water_volume",
     "expect_attr": "rv50water_duty_volume_expected"},
    {"field": "left_mop_temp", "kind": "range_int", "ui": "left_mop_temperature",
     "mes": "左拖布温度adc", "parse_key": "left_mop_temperature",
     "min_attr": "rv50water_left_mop_temp_min", "max_attr": "rv50water_left_mop_temp_max"},
    {"field": "base_ver", "kind": "version", "ui": "base_station_ver", "mes": "基站版本",
     "parse_key": "base_ver"},
    {"field": "base_config", "kind": "string", "ui": "base_station_config", "mes": "基站配置码",
     "parse_key": "base_config", "expect_attr": "base_station_config_expected"},
    # ... 其余字段同 test.py
]

def rv50water_field_enabled(field) -> bool:
    entry = _lookup(field)
    if entry["kind"] == "exact_int":
        return int(getattr(load_cfg, entry["expect_attr"], -1)) >= 0
    if entry["kind"] == "range_int":
        lo = getattr(load_cfg, entry["min_attr"]); hi = getattr(load_cfg, entry["max_attr"])
        return not (int(lo) == 0 and int(hi) == 0)
    if entry["kind"] == "version":
        return bool((load_cfg.mcu_ver or "").strip())
    if entry["kind"] == "string":
        return bool(str(getattr(load_cfg, entry["expect_attr"], "")).strip())
    return False
```

### 9.3 解析 0x77

```python
def rv50water_u16_be(hi, lo):
    return ((int(hi) & 0xFF) << 8) | (int(lo) & 0xFF)

def rv50water_parse_77(dat, min_len=RV50WATER_77_DATA_LEN):
    if len(dat) < min_len:
        return None
    return {
        "step": int(dat[0]),
        "clear_water_volume": rv50water_u16_be(dat[1], dat[2]),
        "duty_water_volume": rv50water_u16_be(dat[3], dat[4]),
        "left_mop_water_volume": rv50water_u16_be(dat[5], dat[6]),
        "right_mop_water_volume": rv50water_u16_be(dat[7], dat[8]),
        "left_mop_temperature": rv50water_u16_be(dat[9], dat[10]),
        "right_mop_temperature": rv50water_u16_be(dat[11], dat[12]),
        "cleaner_liquid_level": int(dat[13]) & 0xFF,
        "base_hot_water_temp": rv50water_u16_be(dat[14], dat[15]),
        "base_ver": rv50_fmt_ver_3bytes(dat, 16),      # "AAA.BBB.CCC"
        "base_config": rv50_fmt_config_3bytes(dat, 19), # "XX.XX.XX"
        "host_hot_water_temp": rv50water_u16_be(dat[22], dat[23]),
    }
```

### 9.4 判据

```python
def rv50water_field_ok(p, field):
    if not rv50water_field_enabled(field):
        return None   # 跳过
    entry = _lookup(field)
    if entry["kind"] == "exact_int":
        return int(p[entry["parse_key"]]) == int(getattr(load_cfg, entry["expect_attr"]))
    if entry["kind"] == "range_int":
        lo, hi = rv50water_int_limits(field)
        if lo > hi: lo, hi = hi, lo
        return lo <= int(p[entry["parse_key"]]) <= hi
    if entry["kind"] == "version":
        return ver_triplet_matches(p["base_ver"], load_cfg.mcu_ver)
    if entry["kind"] == "string":
        return config_triplet_matches(p["base_config"], load_cfg.base_station_config_expected)
    return None

def rv50water_all_ok(p) -> bool:
    if p is None:
        return False
    for entry in RV50WATER_FIELD_REGISTRY:
        if rv50water_field_ok(p, entry["field"]) is False:
            return False
    return True
```

### 9.5 模式主入口（0x66 / 0x77 / 0x88）

```python
def RV50_water_mode(dev, cmd, dat):
    global test_start_time, check_sn_enable

    if cmd == 0x66 and dat[0] == 0x00:
        fixture_all_reply_bursts_stop()
        test_start_time = datetime.now()
        mes_run.clear_report()
        tool.clear_queue(barcode_q)
        check_sn_enable = True
        rv50water_reset_session()
        rv50water_session_state = RV50WATER_SESS_WAIT_SN
        wx.CallAfter(MainFrame.main_frame.reset_ui)
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")

    elif cmd == 0x77:
        if rv50water_session_state != RV50WATER_SESS_RUNNING:
            return
        fixture_gate_burst_cancel_on_first_77()
        p = rv50water_parse_77(dat)
        if p is None:
            return
        rv50water_last_p = p
        rv50water_refresh_test_ui_callafter(p, finalize=False)  # 实时绿/白
        # step 变化 → 提示文案；step==2 液位引导等

    elif cmd == 0x88:
        rv50water_finalize_88(dev, dat)
```

### 9.6 终判 + MES + UI（`finalize_88` 模式）

```python
def rv50water_finalize_88(dev, dat):
    global rv50water_finalize_done, test_end_time
    if rv50water_finalize_done:
        return
    rv50water_finalize_done = True
    test_end_time = datetime.now()

    # dat[0]==0x04 → 基站通讯失败：直接 NG + 提示，不跑全项
    if dat and int(dat[0]) == 0x04:
        mes_run.add_report(name="基站通讯", result="NG", value="通讯失败")
        mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        wx.CallAfter(..., second="基站通讯失败", color=wx.RED)
        rv50water_reset_session()
        return

    p = rv50water_last_p
    rv50water_refresh_test_ui_callafter(p, finalize=True)  # 终判着色
    rv50water_add_reports(p)   # 按注册表 add_report
    overall = "OK" if rv50water_all_ok(p) else "NG"
    mes_run.send_report(test_start_time, test_end_time, check_sn_str, overall)
    color = wx.GREEN if overall == "OK" else wx.RED
    wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                 second="测试完成  " + ("PASS" if overall == "OK" else "NG"),
                 color=color)
    rv50water_reset_session()
```

### 9.7 动态 UI 列（启动时）

```python
def rv50water_build_item_result():
    items = []
    for entry in RV50WATER_FIELD_REGISTRY:
        if entry["ui"] == "base_station_config" and not show_cfg_ui:
            continue
        if rv50water_field_enabled(entry["field"]):
            items.append({entry["ui"]: [LABELS[entry["ui"]], "", "white"]})
    return items
```

同族工位（015/017/018/020/021/022/050）结构相同，差异在：`parse_77` 布局、注册表字段、`0x88` 语义、门闸是否连发。

---

## 10. 工位一览与模式入口

### 10.1 主板治具（&lt;100）

| device_type | 名称 | 帧 dev | 模式函数 |
|-------------|------|--------|----------|
| 001 | 过水（旧）/ 历史集尘 | 0x01 | `dust_collector_mode` |
| 002 | 充电座 | 0x02 | （标题有；路由缺失，遗留） |
| 003/004 | 前撞组件/PCB | 0x03/04 | `lt_bump_mode` |
| 005 | 地检 | 0x05 | `cliff_tool_mode` |
| 006 | 集尘桶 PCB | 0x06 | `dust_collector_mode` |
| 007 | 静态电流 | 0x07 | `robot_static_current_mode` |
| 010/011 | 左/右轮 | 0x0A/0B | `left_right_wheel_mode` |
| 012 | 边刷摆臂 | 0x0C | `side_brush_mode` |
| 013 | 中扫 | 0x0D | `main_brush_mode` |
| 015 | RV50 过气 | 0x0F | `RV50_air_mode` |
| 016 | RV50 过水 | 0x10 | `RV50_water_mode` |
| 017 | RV50 全功能 | 0x11 | `RV50_finished_product_mode` |
| 018 | 基站 PCBA | 0x12 | `RV50_pcba_mode` |
| 019 | 污水箱气密 | 0x13 | `wsxqmx_mode` |
| 020 | Omini 全功能 | 0x14 | `Omini_finished_product_mode` |
| 021 | Omini 过气 | 0x15 | `Omini_air_mode` |
| 022 | Omini 过水 | 0x16 | `Omini_water_mode` |
| 050 | RV30 全功能 | 0x32 | `RV30_finished_product_mode` |

### 10.2 上位机工具（≥100）

| device_type | 名称 | 入口 |
|-------------|------|------|
| 100 | 绑主机/电池/前撞 | `bind_robot.bind_sn_process` |
| 101 | 耐压 | `withstand_vol.test_process` |
| 102 | 条码比对 | `check_barcodes_match_process` + SQLite |
| 103 | 配件纸箱 | `sn_check.check_barcodes_of_parts_box_process` |
| 104 | 耐压 ZC7122D | `test_mode_zc7122d_process` |
| 105 | 耐高压新 | `test_mode_new_zc7122d_process` |
| 106 | 称重 | `weigh_station.process` |

---

## 11. MES 门面与双后端

### 11.1 门面 API（`mes/mes_run.py`）——重构时保留这 5 个语义

```python
anker_report = []
celink_report = []

def check_sn_is_ok(sn="") -> bool:
    """过站。mes 未启用 → True；双 MES 需两边都过。"""
    if load_cfg.mes not in ("001", "002", "003"):
        return True
    if load_cfg.mes in ("001", "002"):
        if not celink_mes.check_sn_is_ok(sn):
            return False
    if load_cfg.mes in ("001", "003"):
        if not anker_mes.check_sn_is_ok(sn):
            return False
    return True

def clear_report():
    global celink_report, anker_report
    celink_report, anker_report = [], []

def add_report(name="", result="", value="", val_max="", val_min=""):
    """result: "OK" | "NG" | "un_test" → 同时填两家报项列表"""
    ...

def send_report(start_time, end_time, sn, result) -> bool:
    """提交 MES + 无论成败都 save_report 落 CSV"""
    ...

def save_report(time, sn="", result=""):
    path = f"测试记录\\{heading_line_dict[dev]}记录{YYYY-MM}.csv"
    # 列：日期 / SN / 结果 / 各测试项 PASS-NG + 值 + 阈值
```

**⚠ 现 `send_report` 用 `elif` 链：`001` 双 MES 时安克分支可能到不了。重构应用独立 if。**

### 11.2 海能 HTTP（`celink_mes.py`）

```python
url = 'http://192.168.7.90/CelinkHNSDJWCFService/OrBitWebAPI.ashx'

station_sn_code = {        # device_type → 站码
    "016": "HNJZGSCS", "015": "HNJZQMXCS", "017": "HNJZQGNCS",
    "050": "HNXJCTQGNCS", "106": "HNBZCZ", ...
}

# 过站
dat = {
    'API': 'HN_CheckLotSN',
    'UserParameter': station_sn_code[dev],
    'UserData': json.dumps({"LotSN": sn, "TestDevice": test_tool}),
}
ok, msg = celink_mes_communication(dat)  # POST，看 ResultCode=="OK"

# 上报
dat = {
    "API": "HN_SubmitTestData",
    "UserParameter": station_report_code[dev],
    "UserData": json.dumps({
        "LotSN": sn, "TestDevice": ..., "UserCode": "001",
        "TestResult": result,  # "OK"/"NG"
        "StartTime": "...", "EndTime": "...",
        "TestDataItem": mes_run.celink_report,
    }),
}

# 绑码
# API = HN_BindData，BindData: [{AssemblyType:"Bat",...},{AssemblyType:"Front",...}]
```

报项结构：

```python
{"ItemName": name, "ItemValue": value, "ItemResult": "OK"|"NG", "Description": "max:.. min:.."}
```

### 11.3 安克 TCP（`anker_mes.py`）

```python
anker_mes_ip, anker_mes_port = "127.0.0.1", 20480

# 消息 type：
# CheckSn / CheckMac / CheckSnStation / TestReport / BindExtend
# TCP JSON 收发，res==True 为成功

# 报项：result int  0未测 1跳过 2成功 3失败
{"name": name, "result": 2, "val": value, "max": "", "min": ""}

# TestReport.result：0未测 1成功 2失败 3错误（与报项枚举不同！）
```

部分工位用 SN（001/007/101/104），其余用 Mac 字段传条码。

---

## 12. UI 关键接口

### 12.1 扫码（键盘楔入）

```python
# MainFrame.on_key_event
if key_code in (wx.WXK_RETURN, wx.WXK_TAB):
    self.up_sn_ui(self.barcode_data)
    if not test.barcode_q.full():
        test.barcode_q.put(self.barcode_data)
    test.barcode_msg_update = True
    self.barcode_data = ""
else:
    self.barcode_data += chr(key_code)
```

### 12.2 业务→UI（一律 `wx.CallAfter`）

```python
MainFrame.main_frame.reset_ui()
MainFrame.main_frame.up_notification_ui(first="", second="", third="", color=wx.RED)
MainFrame.main_frame.up_notification_ui_item(num=1, text="", color=wx.GREEN)
MainFrame.main_frame.up_test_ui(name='clear_water_volume', result='pass'|'fail'|'monitor', value='123')
MainFrame.main_frame.up_sn_ui("")
MainFrame.main_frame.up_connect_ui("com_connect", True/False)
MainFrame.main_frame.up_open_ser_button_text("打开串口"|"关闭串口"|"启动/复位")
```

### 12.3 标题字典（节选）

```python
heading_line_dict = {
    "016": "过水测试治具", "015": "过气测试治具", "017": "全功能测试",
    "018": "基站PCBA测试", "050": "RV30全功能", "106": "称重工位",
    "100": "绑定主机、前撞、电池", ...
}
title = load_cfg.project_name + heading_line_dict.get(load_cfg.dev, "未知设备")
```

### 12.4 测试格数据结构

```python
# list[dict[str, list]]  键=up_test_ui 的 name
[{"clear_water_volume": ["清水通路水量：", "", "white"]}, ...]
# 第三元：white / green / red / 对应 bitmap
```

---

## 13. 上位机工具工位（≥100）

### 13.1 绑码 100（`bind_robot.py`）

```python
def bind_sn_process():
    sn_list = test.get_sn_collect_res()   # 期望 3 个：主机/电池/前撞
    if test.is_sn_up_enable():
        return
    robot_sn, bat_sn, lt_sn = sn_list[0], sn_list[1], sn_list[2]

    if not check_robot_bat_lt_sn_rules_is_ok(...):  # encode_rules robot/bat/front
        test.test_work_state = "idle"; return

    if load_cfg.mes in ("1", "2"):   # ⚠ 与 mes_run 的 "001"/"002" 不一致
        celink_mes.celink_bind_robot_bat_lt_sn(robot_sn, bat_sn, lt_sn)
    if load_cfg.mes in ("1", "3"):
        anker_mes.anker_bind_robot_bat_lt_sn(...)
        anker_mes.anker_send_report(...)
    test.test_work_state = "idle"
```

### 13.2 耐压 101（`withstand_vol.py`）

```python
test_cmd_data = (0x11, 0x08, 0x02, 0x00, 0x54)   # 启动
reset_cmd_data = (0x11, 0x08, 0x02, 0x00, 0x52)  # 复位
# 流程：扫 SN → 编码 → MES 过站 → 清 RX → 复位 → 启动 → 条件等待 RX → 解析结果 → add_report → send_report
# 波特率 9600；104/105 为不同仪表协议变体
```

### 13.3 称重 106（`weigh_station.py`）

```python
WEIGH_CMD_READ = b"R\r\n"
WEIGHT_LINE_PATTERN = re.compile(r"[+-]\s*([\d.]+)\s*kg", re.IGNORECASE)

def process():
    sn = get_sn_collect_res()[0]
    encode_rules.match_sn_encoding_rules(...)
    mes_run.check_sn_is_ok(sn)
    time.sleep(weight_read_delay_sec)
    clear_queue(test_rx_q)
    test_serial_send(WEIGH_CMD_READ)
    text = read_scale_response_text(timeout)
    kg = parse_weight_kg_from_text(text)
    # 方案1：weight_min_kg ~ weight_max_kg
    # 方案2：前 N 台直通，之后 μ±kσ（weigh_limits）
    mes_run.clear_report()
    mes_run.add_report(name="重量(kg)", result=..., value=..., val_min=..., val_max=...)
    mes_run.send_report(..., "OK"|"NG")
    test.test_work_state = "idle"
```

### 13.4 条码 102/103 + SQLite

```python
# database/sqlite_db.py
robot_db_path = r'C:\CelinkDB\robot_sn.db'
parts_db_path = r'C:\CelinkDB\parts_sn.db'
# 表 sn_records(sn UNIQUE, times, name, box_sn, reserved)
# API: open_sn_database / is_sn_in_database / insert ...
```

---

## 14. 数据库 / CSV / 工具函数

### 14.1 CSV 落盘（`excel.add_record_to_csv`）

```python
def add_record_to_csv(file_path, record: dict):
    with open(file_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=record.keys())
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(record)
```

### 14.2 通用工具（`tool_box/tool.py`）

```python
def conditional_sleep(timeout, condition_check, interval=0.3) -> bool:
    """条件满足提前返回 True；超时 False"""

def clear_queue(q):
    while True:
        try: q.get_nowait()
        except Empty: break

def extract_bits(data, start, end): ...
def check_bit(data, n): ...
def bytes_to_float(bytes_data):  # struct.unpack('>f', ...)
def split_sn_barcode(barcode):   # 头部 + 尾部数字
def check_sum(data): return sum(data) % 256
```

### 14.3 日志（`applog.py`）

滚动文件 → `logs/app.log`；UI 就绪后 `AppLog()`，串口收发 `log.info("tx:/rx: ...")`。

---

## 15. 重构时建议的接口切面

把上文代码块收成插件后，建议落成这些接口（伪代码，可直接当新项目骨架）：

```python
class StationHandler(Protocol):
    id: str
    title: str
    def build_ui_schema(self, cfg) -> list: ...
    def on_fixture_start(self, ctx): ...          # 0x66
    def on_barcode(self, sn: str, ctx) -> GateResult: ...
    def on_realtime(self, payload: bytes, ctx): ...  # 0x77
    def on_finish(self, payload: bytes, ctx) -> SessionResult: ...  # 0x88

class MesPort(Protocol):
    def check_sn(self, sn: str) -> bool: ...
    def clear_items(self): ...
    def add_item(self, name, result, value, vmin="", vmax=""): ...
    def submit(self, sn, start, end, overall) -> bool: ...

class SerialPort(Protocol):
    def send_frame(self, dev, cmd, payload: list[int]): ...
    def send_raw(self, data: bytes): ...

class UiPort(Protocol):
    def notify(self, *, first="", second="", third="", color="red"): ...
    def set_item(self, name, result, value): ...
    def reset(self): ...
```

**主循环伪代码：**

```python
def work_tick():
    station = registry[cfg.device_type]
    if cfg.is_fixture:
        drain_barcode_gate(station)
        for frame in serial.recv_frames():
            station.dispatch(frame)
        burst_tick()
    elif state == RUNNING:
        station.tool_process()
```

---

## 附录 A：完整主流程（治具工位）

```
打开软件 → load_config → 建测试格 → 启双线程 → idle
用户打开串口
治具 0x66 → check_sn_enable=True → UI「请扫码」
扫码 → 编码规则 → MES 过站 → 0x57/0x58
过站成功 → 会话 RUNNING
循环 0x77 → 解析 → 刷新测试格 / 步骤提示
0x88 → 综合判据 → add_report* → send_report → CSV → PASS/NG UI
复位会话 → 等待下一轮 0x66
```

## 附录 B：源码速查

| 逻辑 | 位置 |
|------|------|
| 主循环 | `test_tool/test.py` → `test_run_process` |
| 拆帧 | `test_rx_data_handle` |
| 路由 | `test_cmd_handle` |
| 扫码门闸 | `barcode_check_process` |
| 过水模板 | `RV50_water_mode` / `RV50WATER_FIELD_REGISTRY` |
| 组帧 | `ser_send_data` |
| MES 门面 | `mes/mes_run.py` |
| 海能/安克 | `mes/celink_mes.py` / `anker_mes.py` |
| 串口 | `myserial/test_serial.py` |
| UI | `ui/MainFrame.py` |
| 配置 | `config.yaml` + `load_config` |

## 附录 C：已知实现陷阱（重构必改）

1. `use_mes` 合法时被强制写成 `'002'`  
2. `mes_run.send_report` 的 `elif` 使双 MES 时安克可能不上报  
3. `bind_robot` 用 `"1"/"2"/"3"`，门面用 `"001"/"002"/"003"`  
4. `match_sn_encoding_rules` 匹配失败仍返回 `True`  
5. 串口线程停用 `work_stop_event` 而非 `serial_stop_event`  
6. `device_type` 分支散落 UI / MES 站码 / 编码规则 / 主循环 ≥5 处  

---

*文档版本：基于 CE_MES_SEC 仓库整理，供三星版重构对照复制使用。*
