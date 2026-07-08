import time
import yaml
import re
from datetime import datetime

from myserial import test_serial
import wx
from ui import MainFrame
from test_tool import withstand_vol
from dataclasses import dataclass
from mes import mes_run
import queue
from tool_box import tool
from test_tool import bind_robot
from test_tool import excel
from test_tool import encode_rules
from mes import anker_mes
from database import sqlite_db
from test_tool import voice
from test_tool import sn_check
from test_tool import weigh_station  # [WEIGH-106] 称重工位 106
import applog


test_work_state = "init"
barcode_msg_update = False
test_ser_connect = False
error_display_str = ""
test_error_str = ""

# 定义使用双地检模式使能
TWO_CLIFF_SENSOR_MODE_EN = True


barcode_q = queue.Queue()  # 扫码枪数据
rx_sn_cmd_q = queue.Queue()  # 收到SN信息，模拟治具给治具处理模块发一条命令（dev < 100）
check_sn_enable = False  # 检测SN，当使用mes系统时，需要过站检测
check_sn_str = ""  # 保存过站码用于，上传记录

cliff_sn_dict = {
    "left": "",
    "right": ""
}

# 列表用于存储，主界面接收到的SN号
sn_save_list = []
# 更新 sn 使能开关
sn_up_enable = False

test_start_time = datetime.now()
test_end_time = datetime.now()


@dataclass
class LoadCfg:
    dev: str = "001"     # 测试类型编码
    com: str = ""        # 串口端口 如：'COM1'
    mes: str = "3"       # 是否使用mes
    mcu_ver: str = ""    # 集尘桶或集尘桶PCB软件版本
    base_station_config_expected: str = ""  # 015/021：0x57 下发；其它工位 0x77 比对（格式 XX.XX.XX 十六进制）
    show_base_station_config_ui: int = 1  # 0=不显示「基站配置码」测试格  1=显示
    test_tool: str = ""  # 治具名称或编码
    parts_sn_head: str = ""  # 103 配件纸盒条码头，前7位
    project_name: str = ""   # 项目代号
    # --- WEIGH-106-BEGIN: 称重工位 106 配置（见 WEIGH_STATION_106_SPEC.md）---
    weight_min_kg: float = 100.0
    weight_max_kg: float = 150.0
    weight_read_delay_sec: float = 1.0
    weight_read_timeout_sec: float = 2.0
    weigh_scheme: str = "1"  # "1" 固定限；"2" 前 weigh_pass_first_n 台直通后 μ±kσ
    weigh_pass_first_n: int = 5
    weigh_sigma_k: float = 1.0  # 方案二：μ ± kσ
    # 方案二历史重量 JSON；相对路径相对 exe 目录（frozen）或当前工作目录
    weigh_history_json_path: str = "weigh_106_history.json"
    # --- WEIGH-106-END ---
    # #[RV30-PROTO] 基站 device_type=50 实时判据（config.yaml，与 doc/ce_mes_iteration/RV30_BASESTATION_PROTOCOL_AND_IMPLEMENTATION_SPEC.md 一致）
    rv30_charge_Hmin: int = 0
    rv30_charge_Hmax: int = 0
    rv30_charge_Lmin: int = 0
    rv30_charge_Lmax: int = 0
    # 集尘吸力判据：协议/H/L 字节为 10Pa 计数；config 见 rv30_suction_kpa_min/max
    rv30_suction_10pa_Hmin: int = 0
    rv30_suction_10pa_Hmax: int = 0
    rv30_suction_10pa_Lmin: int = 0
    rv30_suction_10pa_Lmax: int = 0

    # rv30_freq_min: int = 0
    # rv30_freq_max: int = 0
    rv30_freq_expected: int = 0

    rv30_ir_l: int = 0
    rv30_ir_lc: int = 0
    rv30_ir_rc: int = 0
    rv30_ir_r: int = 0
    rv30_dust_bag_expected: int = 0
    rv30_led_expected: int = 0
    # [WSXQMX-019] RV50 污水箱气密性：保压结束气压判据（kPa，含端点）
    wsxqmx_hold_kpa_min: float = -20.0
    wsxqmx_hold_kpa_max: float = -17.0
    # #[RV50-015-AIR-PROTO] device_type=015 基站过气（帧 dev=0x0F）；阈值为 kPa
    rv50air_clear_kpa_min: float = 20.0
    rv50air_clear_kpa_max: float = 80.0
    rv50air_mop_kpa_min: float = 20.0
    rv50air_mop_kpa_max: float = 230.0
    rv50air_duty_kpa_min: float = -30.0
    rv50air_duty_kpa_max: float = -18.0
    # #[OMINIAIR-021-PROTO] device_type=021 Omini 基站过气（帧 dev=0x15）；0=不参与比较
    ominiair_clear_kpa_min: float = 0.0
    ominiair_clear_kpa_max: float = 0.0
    ominiair_mop_kpa_min: float = 0.0
    ominiair_mop_kpa_max: float = 0.0
    ominiair_duty_kpa_min: float = 0.0
    ominiair_duty_kpa_max: float = 0.0
    # #[OMINIWATER-022-PROTO] device_type=022 Omini 基站过水（帧 dev=0x16）；-1=不参与比较
    ominiwater_clear_volume_expected: int = -1
    ominiwater_duty_volume_expected: int = -1
    ominiwater_left_mop_volume_expected: int = -1
    ominiwater_right_mop_volume_expected: int = -1
    ominiwater_cleaner_level_expected: int = -1
    ominiwater_left_mop_temp_min: int = 0
    ominiwater_left_mop_temp_max: int = 0
    ominiwater_right_mop_temp_min: int = 0
    ominiwater_right_mop_temp_max: int = 0
    ominiwater_base_hot_temp_min: int = 0
    ominiwater_base_hot_temp_max: int = 0
    # #[RV50-016-WATER-PROTO] device_type=016 基站过水（帧 dev=0x10）
    rv50water_clear_volume_expected: int = -1
    rv50water_duty_volume_expected: int = -1
    rv50water_left_mop_volume_expected: int = -1
    rv50water_right_mop_volume_expected: int = -1
    rv50water_cleaner_level_expected: int = -1
    rv50water_left_mop_temp_min: int = 800
    rv50water_left_mop_temp_max: int = 1800
    rv50water_right_mop_temp_min: int = 800
    rv50water_right_mop_temp_max: int = 1800
    rv50water_base_hot_temp_min: int = 600
    rv50water_base_hot_temp_max: int = 1300
    rv50water_host_hot_temp_min: int = 0
    rv50water_host_hot_temp_max: int = 0
    # #[RV50-017-PROTO] device_type=017 基站全功能（帧设备字节 0x11）
    rv50_charge_Hmin: int = 0
    rv50_charge_Hmax: int = 0
    rv50_charge_Lmin: int = 0
    rv50_charge_Lmax: int = 0
    rv50_suction_10pa_Hmin: int = 0
    rv50_suction_10pa_Hmax: int = 0
    rv50_suction_10pa_Lmin: int = 0
    rv50_suction_10pa_Lmax: int = 0
    rv50_ir_l: int = 0
    rv50_ir_r: int = 0
    rv50_ir_n: int = 0
    rv50_clear_tank_expected: int = 0
    rv50_duty_tank_expected: int = 0
    rv50_dust_expected: int = 0
    rv50_clean_base_expected: int = 0
    rv50_clean_pump_min: int = 0
    rv50_clean_pump_max: int = 0
    rv50_vacuum_pump_min: int = 0
    rv50_vacuum_pump_max: int = 0
    rv50_base_level_up_min: int = 0
    rv50_base_level_up_max: int = 0
    rv50_base_level_down_min: int = 0
    rv50_base_level_down_max: int = 0
    rv50_em_valve_min: int = 0
    rv50_em_valve_max: int = 0
    rv50_wash_pump_min: int = 0
    rv50_wash_pump_max: int = 0
    rv50_turbidity_min: int = 0
    rv50_turbidity_max: int = 0
    rv50_hot_diff_min: int = 0
    rv50_hot_diff_max: int = 0
    # #[OMINI-020-PROTO] device_type=020 Omini 基站全功能（帧 dev=0x14）；0=不参与比较
    omini_charge_min: int = 0
    omini_charge_max: int = 0
    omini_suction_10pa_Hmin: int = 0
    omini_suction_10pa_Hmax: int = 0
    omini_suction_10pa_Lmin: int = 0
    omini_suction_10pa_Lmax: int = 0
    omini_ir_l: int = 0
    omini_ir_r: int = 0
    omini_ir_n: int = 0
    omini_clear_tank_expected: int = 0
    omini_duty_tank_expected: int = 0
    omini_dust_expected: int = 0
    omini_clean_base_expected: int = 0
    omini_clean_pump_min: int = 0
    omini_clean_pump_max: int = 0
    omini_vacuum_pump_min: int = 0
    omini_vacuum_pump_max: int = 0
    omini_base_level_up_min: int = 0
    omini_base_level_up_max: int = 0
    omini_base_level_down_min: int = 0
    omini_base_level_down_max: int = 0
    omini_em_valve_min: int = 0
    omini_em_valve_max: int = 0
    omini_wash_pump_min: int = 0
    omini_wash_pump_max: int = 0
    omini_turbidity_min: int = 0
    omini_turbidity_max: int = 0
    omini_hot_diff_min: int = 0
    omini_hot_diff_max: int = 0
    # #[RV50-018-PCBA-PROTO] device_type=018 基站 PCBA（帧设备字节 0x12）
    rv50pcba_charge_min: int = 0
    rv50pcba_charge_max: int = 0
    rv50pcba_ir_l: int = 0
    rv50pcba_ir_r: int = 0
    rv50pcba_ir_n: int = 0
    rv50pcba_clear_tank_expected: int = 0
    rv50pcba_duty_tank_expected: int = 0
    rv50pcba_dust_expected: int = 0
    rv50pcba_clean_base_expected: int = 0
    rv50pcba_clean_pump_min: int = 0
    rv50pcba_clean_pump_max: int = 0
    rv50pcba_vacuum_pump_min: int = 0
    rv50pcba_vacuum_pump_max: int = 0
    rv50pcba_base_level_up_min: int = 0
    rv50pcba_base_level_up_max: int = 0
    rv50pcba_base_level_down_min: int = 0
    rv50pcba_base_level_down_max: int = 0
    rv50pcba_em_valve_min: int = 0
    rv50pcba_em_valve_max: int = 0
    rv50pcba_wash_pump_min: int = 0
    rv50pcba_wash_pump_max: int = 0
    rv50pcba_turbidity_min: int = 0
    rv50pcba_turbidity_max: int = 0
    rv50pcba_hot_diff_min: int = 0
    rv50pcba_hot_diff_max: int = 0
    rv50pcba_blower_freq_min: int = 0
    rv50pcba_blower_freq_max: int = 0


@dataclass
class DustThreshold:
    # 交流充电阈值
    cc_max: int = 0
    cc_min: int = 0
    # 阈值 ac 过载频率
    ac_lv_max: int = 0
    ac_lv_min: int = 0
    # 阈值 外接气压计 上线下线；吸力值，暂时未使用
    out_barometer_max: int = 0
    out_barometer_min: int = 0
    # 阈值 气压值小板 上线下线；检测尘满
    barometer_max: int = 0
    barometer_min: int = 0


dust_th = DustThreshold()
load_cfg = LoadCfg()

# #[RV30-PROTO] RV30 基站(device_type=50) 会话状态机常量（调优时只改 RV30_finished_product_mode 与下列变量）
RV30_SESS_IDLE = 0
RV30_SESS_WAIT_SN = 1
RV30_SESS_RUNNING = 2
RV30_SESS_FINISHED = 3
RV30_SESS_ABORTED = 4
rv30_session_state = RV30_SESS_IDLE
rv30_last_step = -1
rv30_max_step = 0  # [RV30-步骤4终判-WBH] 本轮实时数据到达过的最大治具步骤
rv30_89_mes_done = False
rv30_finalize_done = False  # [RV30-0x88-RETRY] 本轮 0x88 已处理，重复结束帧直接忽略
rv30_realtime_ng = False
rv30_last_p = None  # [up_test_ui_WBH] 最近一帧 0x77 解析结果，供结束帧刷新测试格
rv30_last_dust_notify = -1  # [RV30-尘袋步骤3-WBH] 防抖：上次已提示的 dust 状态
# #[RV30-PROTO-68-MOD] 0x68 数据区字节数（回充4+版本4+频率1+尘袋1+充电4+LED1+集尘4）；PNG 若版本为 3 字节则改为 18 并改 parse 下标
RV30_68_DATA_LEN = 19

# [WSXQMX-019] RV50 污水箱气密性 device_type=019，帧设备字节 0x13；仅用 up_notification_ui，不用 up_test_ui
WSXQMX_SESS_IDLE = 0
WSXQMX_SESS_WAIT_SN = 1
WSXQMX_SESS_RUNNING = 2
WSXQMX_SESS_FINISHED = 3
wsxqmx_session_state = WSXQMX_SESS_IDLE
wsxqmx_last_step = -1
wsxqmx_hold_pressure_kpa = None  # [WSXQMX-019] 步骤03锁存的保压结束气压（kPa）
wsxqmx_got_step3 = False
wsxqmx_finalize_done = False  # [WSXQMX-0x88-RETRY] 本轮 0x88 已处理，重复结束帧直接忽略

# #[RV50-015-AIR-PROTO] RV50 基站过气 device_type=015，帧设备字节 0x0F；0x77 数据区 13 字节（含配置回读）
RV50AIR_77_DATA_LEN = 13
RV50AIR_SESS_IDLE = 0
RV50AIR_SESS_WAIT_SN = 1
RV50AIR_SESS_RUNNING = 2
RV50AIR_SESS_FINISHED = 3
rv50air_session_state = RV50AIR_SESS_IDLE
rv50air_last_step = -1
rv50air_last_p = None
rv50air_got_step3 = False
rv50air_config_push_active = False
rv50air_config_push_payload = None
rv50air_config_push_last_ms = 0.0
rv50air_finalize_done = False  # [RV50AIR-0x88-RETRY] 本轮 0x88 已处理，重复结束帧直接忽略

# #[OMINIAIR-021-PROTO] Omini 基站过气 device_type=021，帧设备字节 0x15；0x77 数据区 13 字节（含配置回读）
OMINIAIR_77_DATA_LEN = 13
OMINIAIR_SESS_IDLE = 0
OMINIAIR_SESS_WAIT_SN = 1
OMINIAIR_SESS_RUNNING = 2
OMINIAIR_SESS_FINISHED = 3
ominiair_session_state = OMINIAIR_SESS_IDLE
ominiair_last_step = -1
ominiair_last_p = None
ominiair_got_step3 = False
ominiair_config_push_active = False
ominiair_config_push_payload = None
ominiair_config_push_last_ms = 0.0
ominiair_finalize_done = False  # [OMINIAIR-0x88-RETRY] 本轮 0x88 已处理，重复结束帧直接忽略

# #[RV50-OMINI-AIR-CONFIG-PUSH] 015/021：MES 通过后 0x57 帧尾带配置码，循环至首帧 0x77
AIR_CONFIG_PUSH_INTERVAL_MS = 500

# #[FIXTURE-GATE-BURST] 015/016/017/019/050 门闸 0x57/0x58 三连发；017/050 实时 NG 0x89 三连发
FIXTURE_REPLY_BURST_COUNT = 3
FIXTURE_REPLY_BURST_INTERVAL_MS = 500
GATE_BURST_DEVS = (15, 16, 17, 19, 50)
fixture_gate_burst_active = False
fixture_gate_burst_dev = 0
fixture_gate_burst_cmd = 0
fixture_gate_burst_payload = None
fixture_gate_burst_sent = 0
fixture_gate_burst_max = FIXTURE_REPLY_BURST_COUNT
fixture_gate_burst_last_ms = 0.0
fixture_gate_burst_cancel_on_77 = False
fixture_89_burst_active = False
fixture_89_burst_dev = 0
fixture_89_burst_sent = 0
fixture_89_burst_max = FIXTURE_REPLY_BURST_COUNT
fixture_89_burst_last_ms = 0.0

# #[OMINIWATER-022-PROTO] Omini 基站过水 device_type=022，帧设备字节 0x16
OMINIWATER_77_DATA_LEN = 22
OMINIWATER_SESS_IDLE = 0
OMINIWATER_SESS_WAIT_SN = 1
OMINIWATER_SESS_RUNNING = 2
OMINIWATER_SESS_FINISHED = 3
ominiwater_session_state = OMINIWATER_SESS_IDLE
ominiwater_last_step = -1
ominiwater_last_p = None
ominiwater_got_step3 = False
ominiwater_last_level_notify = -1
ominiwater_finalize_done = False  # [OMINIWATER-0x88-RETRY] 本轮 0x88 已处理，重复结束帧直接忽略

# #[RV50-016-WATER-PROTO] RV50 基站过水 device_type=016，帧设备字节 0x10；022 仍为 22 字节
RV50WATER_77_DATA_LEN = 24
RV50WATER_SESS_IDLE = 0
RV50WATER_SESS_WAIT_SN = 1
RV50WATER_SESS_RUNNING = 2
RV50WATER_SESS_FINISHED = 3
rv50water_session_state = RV50WATER_SESS_IDLE
rv50water_last_step = -1
rv50water_last_p = None
rv50water_got_step3 = False
rv50water_last_level_notify = -1
rv50water_finalize_done = False  # [RV50WATER-0x88-RETRY] 本轮 0x88 已处理，重复结束帧直接忽略

# #[RV50-017-PROTO] RV50 基站全功能 device_type=017，0x77 数据区 38 字节（帧长 0x26）
RV50_77_DATA_LEN = 38
RV50_SESS_IDLE = 0
RV50_SESS_WAIT_SN = 1
RV50_SESS_RUNNING = 2
RV50_SESS_FINISHED = 3
RV50_SESS_ABORTED = 4
rv50_session_state = RV50_SESS_IDLE
rv50_last_step = -1
rv50_max_step = 0
rv50_last_p = None
rv50_last_step4_notify_key = ""
rv50_89_mes_done = False
rv50_finalize_done = False  # [RV50-0x88-RETRY] 本轮 0x88 已处理，重复结束帧直接忽略
rv50_realtime_ng = False
ir_code_near = 0
rv50_base_level_up_adc = 0
rv50_base_level_down_adc = 0
rv50_hot_start_adc = 0
rv50_hot_end_adc = 0
rv50_hot_diff_adc = 0

# [RV50-步骤4向导-WBH] 步骤四模块顺序：清水箱→尘袋→清洁底座→污水箱→LED
RV50_STEP4_MODULE_FIELDS = ("clear_tank", "dust", "clean_base", "duty_tank")
RV50_STEP4_SUBSTEPS = (
    ("clear_tank", "清水箱", "请提起清水箱", "请放下清水箱",
     "提起/放下清水箱，直到「清水箱在位」通过"),
    ("dust", "尘袋", "请拔出尘袋", "请插入尘袋",
     "拔插尘袋，直到「尘袋」通过"),
    ("clean_base", "清洁底座", "请取出清洁底座", "请放入清洁底座",
     "取出/放入清洁底座，直至「清洁底座在位」通过"),
    ("duty_tank", "污水箱", "请提起污水箱", "请放下污水箱",
     "提起/放下污水箱，直至「污水箱在位」通过"),
)
RV50_STEP4_ORDER_HINT = "步骤四：请严格按顺序操作（清水箱→尘袋→清洁底座→污水箱→观察灯显）"
RV50_STEP4_LED_HINT = "请工人观察LED灯显示，正常按开始键，异常按结束键"

# #[RV50-017-PROTO] 动态测试项注册表（对标 OMINI_FIELD_REGISTRY）
RV50_UI_LABELS = {
    "mcu_ver": "MCU版本：",
    "base_station_config": "基站配置码：",
    "charge_value": "充电电流：",
    "rv50_hot_start": "热风开始：",
    "ir_code_left": "左回充码：",
    "ir_code_right": "右回充码：",
    "ir_code_near": "近卫回充码：",
    "clear_tank_install": "清水箱在位：",
    "duty_tank_install": "污水箱在位：",
    "dust_bug_install": "尘袋：",
    "clean_base_install": "清洁底座在位：",
    "dust_collection_suction": "集尘吸力(kPa)：",
    "clean_water_pump_current": "清水泵电流：",
    "duty_water_pump_current": "真空泵电流：",
    "rv50_base_level_up": "底座液位(抬起)：",
    "rv50_base_level_down": "底座液位(按下)：",
    "electromagnetic_three_way_current": "电磁三通电流：",
    "rv50_hot_end": "热风结束：",
    "cleaner_pump_current": "清洁泵电流：",
    "turbidity_data": "浊度：",
    "rv50_hot_diff": "热风差值：",
}

RV50_FIELD_REGISTRY = [
    {"field": "dev_ver", "kind": "version", "ui": "mcu_ver", "mes": "MCU版本", "active_from_step": 4},
    {"field": "base_config", "kind": "string", "ui": "base_station_config", "mes": "基站配置码",
     "expect_attr": "base_station_config_expected", "active_from_step": 4},
    {"field": "charge", "kind": "range_charge", "ui": "charge_value", "mes": "充电电流",
     "active_from_step": 1},
    {"field": "ir_l", "kind": "expected", "ui": "ir_code_left", "mes": "左回充码",
     "expect_attr": "rv50_ir_l", "active_from_step": 3},
    {"field": "ir_r", "kind": "expected", "ui": "ir_code_right", "mes": "右回充码",
     "expect_attr": "rv50_ir_r", "active_from_step": 3},
    {"field": "ir_n", "kind": "expected", "ui": "ir_code_near", "mes": "近卫回充码",
     "expect_attr": "rv50_ir_n", "active_from_step": 3},
    {"field": "clear_tank", "kind": "expected", "ui": "clear_tank_install", "mes": "清水箱在位",
     "expect_attr": "rv50_clear_tank_expected", "active_from_step": 4, "step4_module": True},
    {"field": "duty_tank", "kind": "expected", "ui": "duty_tank_install", "mes": "污水箱在位",
     "expect_attr": "rv50_duty_tank_expected", "active_from_step": 4, "step4_module": True},
    {"field": "dust", "kind": "expected", "ui": "dust_bug_install", "mes": "尘袋",
     "expect_attr": "rv50_dust_expected", "active_from_step": 4, "step4_module": True},
    {"field": "clean_base", "kind": "expected", "ui": "clean_base_install", "mes": "清洁底座在位",
     "expect_attr": "rv50_clean_base_expected", "active_from_step": 4, "step4_module": True},
    {"field": "suction_10pa", "kind": "range_suction", "ui": "dust_collection_suction", "mes": "集尘吸力kPa",
     "active_from_step": 5},
    {"field": "clean_pump", "kind": "range", "ui": "clean_water_pump_current", "mes": "清水泵电流",
     "min_attr": "rv50_clean_pump_min", "max_attr": "rv50_clean_pump_max", "active_from_step": 6},
    {"field": "vacuum_pump", "kind": "range", "ui": "duty_water_pump_current", "mes": "真空泵电流",
     "min_attr": "rv50_vacuum_pump_min", "max_attr": "rv50_vacuum_pump_max", "active_from_step": 6},
    {"field": "base_level_up", "kind": "range", "ui": "rv50_base_level_up", "mes": "底座液位(抬起)",
     "min_attr": "rv50_base_level_up_min", "max_attr": "rv50_base_level_up_max", "active_from_step": 6},
    {"field": "base_level_down", "kind": "range", "ui": "rv50_base_level_down", "mes": "底座液位(按下)",
     "min_attr": "rv50_base_level_down_min", "max_attr": "rv50_base_level_down_max", "active_from_step": 6},
    {"field": "em_valve", "kind": "range", "ui": "electromagnetic_three_way_current", "mes": "电磁三通电流",
     "min_attr": "rv50_em_valve_min", "max_attr": "rv50_em_valve_max", "active_from_step": 6},
    {"field": "wash_pump", "kind": "range", "ui": "cleaner_pump_current", "mes": "清洁泵电流",
     "min_attr": "rv50_wash_pump_min", "max_attr": "rv50_wash_pump_max", "active_from_step": 7},
    {"field": "turbidity", "kind": "range", "ui": "turbidity_data", "mes": "浊度数据",
     "min_attr": "rv50_turbidity_min", "max_attr": "rv50_turbidity_max", "active_from_step": 7},
    {"field": "hot_diff", "kind": "range", "ui": "rv50_hot_diff", "mes": "热风差值",
     "min_attr": "rv50_hot_diff_min", "max_attr": "rv50_hot_diff_max", "active_from_step": 7},
    {"field": "hot_start", "kind": "monitor", "ui": "rv50_hot_start", "mes": "热风开始", "active_from_step": 7},
    {"field": "hot_end", "kind": "monitor", "ui": "rv50_hot_end", "mes": "热风结束", "active_from_step": 7},
]

# #[OMINI-020-PROTO] Omini 基站全功能 device_type=020，0x77 数据区 38 字节（帧 dev=0x14）
OMINI_77_DATA_LEN = 38
OMINI_SESS_IDLE = 0
OMINI_SESS_WAIT_SN = 1
OMINI_SESS_RUNNING = 2
OMINI_SESS_FINISHED = 3
OMINI_SESS_ABORTED = 4
omini_session_state = OMINI_SESS_IDLE
omini_last_step = -1
omini_max_step = 0
omini_last_p = None
omini_last_step4_notify_key = ""
omini_89_mes_done = False
omini_finalize_done = False  # [OMINI-0x88-RETRY] 本轮 0x88 已处理，重复结束帧直接忽略
omini_realtime_ng = False

OMINI_STEP4_MODULE_FIELDS = ("clear_tank", "dust", "clean_base", "duty_tank")
OMINI_STEP4_SUBSTEPS = (
    ("clear_tank", "清水箱", "请提起清水箱", "请放下清水箱",
     "提起/放下清水箱，直到「清水箱在位」通过"),
    ("dust", "尘袋", "请拔出尘袋", "请插入尘袋", "拔插尘袋，直到「尘袋」通过"),
    ("clean_base", "清洁底座", "请取出清洁底座", "请放入清洁底座",
     "取出/放入清洁底座，直至「清洁底座在位」通过"),
    ("duty_tank", "污水箱", "请提起污水箱", "请放下污水箱",
     "提起/放下污水箱，直至「污水箱在位」通过"),
)
OMINI_STEP4_ORDER_HINT = "步骤四：请严格按顺序操作（清水箱→尘袋→清洁底座→污水箱→观察灯显）"
OMINI_STEP4_LED_HINT = "请工人观察LED灯显示，正常按开始键，异常按结束键"

# #[RV50-018-PCBA-PROTO] RV50 基站 PCBA device_type=018，0x77 数据区 38 字节（帧长字段 0x26）
RV50PCBA_77_DATA_LEN = 38
RV50PCBA_SESS_IDLE = 0
RV50PCBA_SESS_WAIT_SN = 1
RV50PCBA_SESS_RUNNING = 2
RV50PCBA_SESS_FINISHED = 3
RV50PCBA_SESS_ABORTED = 4
rv50pcba_session_state = RV50PCBA_SESS_IDLE
rv50pcba_last_step = -1
rv50pcba_max_step = 0
rv50pcba_last_p = None
rv50pcba_89_mes_done = False
rv50pcba_realtime_ng = False
rv50pcba_blower_freq = 0

RV50PCBA_REALTIME_FIELDS = (
    "dev_ver",
    "ir_l", "ir_r", "ir_n",
    "clear_tank", "duty_tank", "dust", "clean_base",
    "clean_pump", "vacuum_pump", "base_level_up", "base_level_down", "em_valve",
    "wash_pump", "turbidity", "hot_diff", "charge", "blower_freq",
)

RV50PCBA_FINALIZE_FIELDS = (
    "dev_ver",
    "ir_l", "ir_r", "ir_n",
    "clear_tank", "duty_tank", "dust", "clean_base",
    "clean_pump", "vacuum_pump", "base_level_up", "base_level_down", "em_valve",
    "wash_pump", "turbidity", "hot_diff", "charge", "blower_freq",
)


def _rv50_config_suction_10pa(config):
    if "rv50_suction_kpa_min" in config or "rv50_suction_kpa_max" in config:
        kmin = float(config.get("rv50_suction_kpa_min", 0))
        kmax = float(config.get("rv50_suction_kpa_max", 0))
        umin = _rv30_kpa_to_10pa(kmin)
        umax = _rv30_kpa_to_10pa(kmax)
        if umin > umax and (umin != 0 or umax != 0):
            umin, umax = umax, umin
        return umin, umax
    return _rv30_config_u16(
        config,
        "rv50_suction_10pa_min", "rv50_suction_10pa_max",
        "rv50_suction_10pa_Hmin", "rv50_suction_10pa_Lmin",
        "rv50_suction_10pa_Hmax", "rv50_suction_10pa_Lmax",
    )


def _rv50_suction_threshold_10pa():
    su = (
        load_cfg.rv50_suction_10pa_Hmin, load_cfg.rv50_suction_10pa_Lmin,
        load_cfg.rv50_suction_10pa_Hmax, load_cfg.rv50_suction_10pa_Lmax,
    )
    if su == (0, 0, 0, 0):
        return 0, 0
    slo = (su[0] << 8) | (su[1] & 0xFF)
    shi = (su[2] << 8) | (su[3] & 0xFF)
    if slo > shi and (slo != 0 or shi != 0):
        slo, shi = shi, slo
    return slo, shi


def _omini_config_suction_10pa(config):
    if "omini_suction_kpa_min" in config or "omini_suction_kpa_max" in config:
        kmin = float(config.get("omini_suction_kpa_min", 0))
        kmax = float(config.get("omini_suction_kpa_max", 0))
        umin = _rv30_kpa_to_10pa(kmin)
        umax = _rv30_kpa_to_10pa(kmax)
        if umin > umax and (umin != 0 or umax != 0):
            umin, umax = umax, umin
        return umin, umax
    return _rv30_config_u16(
        config,
        "omini_suction_10pa_min", "omini_suction_10pa_max",
        "omini_suction_10pa_Hmin", "omini_suction_10pa_Lmin",
        "omini_suction_10pa_Hmax", "omini_suction_10pa_Lmax",
    )


def _omini_suction_threshold_10pa():
    su = (
        load_cfg.omini_suction_10pa_Hmin, load_cfg.omini_suction_10pa_Lmin,
        load_cfg.omini_suction_10pa_Hmax, load_cfg.omini_suction_10pa_Lmax,
    )
    if su == (0, 0, 0, 0):
        return 0, 0
    slo = (su[0] << 8) | (su[1] & 0xFF)
    shi = (su[2] << 8) | (su[3] & 0xFF)
    if slo > shi and (slo != 0 or shi != 0):
        slo, shi = shi, slo
    return slo, shi


def _rv30_u16_be(hi, lo):
    # #[RV30-PROTO-68-MOD] 协议 HH/LL 大端 16 位
    return (int(hi) & 0xFF) << 8 | (int(lo) & 0xFF)


def _rv30_u16_to_hl(value):
    v = int(value) & 0xFFFF
    return (v >> 8) & 0xFF, v & 0xFF


def _rv30_config_u16(config, key_min, key_max, key_hmin, key_lmin, key_hmax, key_lmax):
    if key_min in config:
        umin = int(config[key_min])
    else:
        umin = _rv30_u16_be(config.get(key_hmin, 0), config.get(key_lmin, 0))
    if key_max in config:
        umax = int(config[key_max])
    else:
        umax = _rv30_u16_be(config.get(key_hmax, 0), config.get(key_lmax, 0))
    if umin > umax and (umin != 0 or umax != 0):
        umin, umax = umax, umin
    return umin, umax


def _rv30_kpa_to_10pa(kpa):
    # #[RV30-DISPLAY] config.yaml / MES / UI 用 kPa；治具 0x77/0x68 仍为 10Pa 计数
    return int(round(float(kpa) * 100))


def _rv30_10pa_to_kpa(raw_10pa):
    return float(int(raw_10pa)) * 0.01


def _rv30_fmt_ir_byte(value):
    # #[RV30-DISPLAY] 与 config.yaml 中 0x50 等形式一致，便于工人对照
    return "0x{:02X}".format(int(value) & 0xFF)


def _rv30_fmt_suction_kpa(raw_10pa):
    # #[RV30-DISPLAY] 协议实测为 10Pa 计数，展示与 MES 上报为 kPa
    return "{:.1f}".format(_rv30_10pa_to_kpa(raw_10pa))


def _rv30_config_suction_10pa(config):
    # #[RV30-DISPLAY] 优先 rv30_suction_kpa_*；兼容旧 rv30_suction_10pa_* / H/L 四字节
    if "rv30_suction_kpa_min" in config or "rv30_suction_kpa_max" in config:
        kmin = float(config.get("rv30_suction_kpa_min", 0))
        kmax = float(config.get("rv30_suction_kpa_max", 0))
        umin = _rv30_kpa_to_10pa(kmin)
        umax = _rv30_kpa_to_10pa(kmax)
        if umin > umax and (umin != 0 or umax != 0):
            umin, umax = umax, umin
        return umin, umax
    return _rv30_config_u16(
        config,
        "rv30_suction_10pa_min", "rv30_suction_10pa_max",
        "rv30_suction_10pa_Hmin", "rv30_suction_10pa_Lmin",
        "rv30_suction_10pa_Hmax", "rv30_suction_10pa_Lmax",
    )


def _rv30_suction_threshold_10pa():
    # 从 load_cfg 四字节还原 u16 上下限（判据与 0x68 刷新后的运行时阈值）
    su = (
        load_cfg.rv30_suction_10pa_Hmin, load_cfg.rv30_suction_10pa_Lmin,
        load_cfg.rv30_suction_10pa_Hmax, load_cfg.rv30_suction_10pa_Lmax,
    )
    if su == (0, 0, 0, 0):
        return 0, 0
    slo = (su[0] << 8) | (su[1] & 0xFF)
    shi = (su[2] << 8) | (su[3] & 0xFF)
    if slo > shi:
        slo, shi = shi, slo
    return slo, shi


# import sys
# import os

# def resource_path(relative_path):
#     """获取资源文件的绝对路径，兼容开发和打包"""
#     try:
#         # PyInstaller 创建的临时目录
#         base_path = sys._MEIPASS
#     except AttributeError:
#         base_path = os.path.abspath(".")
#     return os.path.join(base_path, relative_path)


import sys
import os

def resource_path(relative_path):
    """获取资源的绝对路径，兼容开发环境和 PyInstaller 打包后的环境"""
    if getattr(sys, 'frozen', False):
        # 打包后，资源文件被解压到 sys._MEIPASS 目录
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def test_run_process():
    # [WEIGH-106] running 态：elif int(load_cfg.dev)==106 -> weigh_station.process()
    global test_work_state
    global barcode_msg_update

    # 检测并更新串口显示
    check_ser_connect_and_up_ui()
    if error_handle():
        return
    # 对测试任务进行监控，比如开始结束等等
    check_process_run_state()
    # 串口数据处理
    if int(load_cfg.dev) < 100:  # 海能主板测试工具 dev 小于100
        barcode_check_process()
        rv50_omini_air_config_push_tick()
        fixture_reply_burst_tick()
        test_serial_rx_data_handle()
    if test_work_state == "running":
        if int(load_cfg.dev) == 101:  # 打高压测试（耐压测试）
            withstand_vol.test_process()
        elif int(load_cfg.dev) == 100:  # 绑定前撞、电池、主机
            bind_robot.bind_sn_process()
            barcode_msg_update = False  # 清二维码更新标志，防止直接进入
        elif int(load_cfg.dev) == 102:  # 比较条码是否相同
            check_barcodes_match_process()
        elif int(load_cfg.dev) == 103:  # 配件纸盒SN检查工具
            sn_check.check_barcodes_of_parts_box_process()
        elif int(load_cfg.dev) == 104:  # 打高压测试，另外一款
            withstand_vol.test_mode_zc7122d_process()
        elif int(load_cfg.dev) == 105:
            withstand_vol.test_mode_new_zc7122d_process()
        elif int(load_cfg.dev) == 106:  # [WEIGH-106] 称重工位
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


def error_handle():
    # 如果基站配置异常不执行测试
    if anker_mes.is_station_cfg_error():
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second="工站配置异常，请配置正确，并重启测试软件", color=wx.RED)
        time.sleep(1)
        return True
    elif sqlite_db.db_error_state != "":
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second="数据库异常：" + str(sqlite_db.db_error_state), color=wx.RED)
        time.sleep(1)
        return True
    elif test_error_str != "":
        time.sleep(1)
        return True

    return False


def test_init_work():
    # [WEIGH-106] 106 分支：称重工位 idle 文案（见 elif dev==106）
    global test_work_state

    if int(load_cfg.dev) == 102 or int(load_cfg.dev) == 103:  # 条码比较, 配件纸箱条码检测工具
        if int(load_cfg.dev) == 102:
            voice.play_voice_init()
            sq_res = sqlite_db.open_sn_database("robot_sn")
            if sq_res[0] is False:
                voice.play_voice("db_error")

        else:  # 103
            voice.play_voice_init()
            sq_res = sqlite_db.open_sn_database("parts_sn")

        if sq_res[0]:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫条码", color=wx.RED)
        else:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="数据库打开异常，请检测后重启软件", color=wx.RED)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=str(sq_res[1]), color=wx.RED)
            test_work_state = "stop"
            sqlite_db.db_error_state = str(sq_res[1])
        wx.CallAfter(MainFrame.main_frame.up_notification_ui_item_size, num=3, size=42)
    elif int(load_cfg.dev) == 106:  # [WEIGH-106] 称重工位 idle 提示
        wlo = load_cfg.weight_min_kg
        whi = load_cfg.weight_max_kg
        if str(getattr(load_cfg, "weigh_scheme", "1")).strip() == "2":
            _k = float(getattr(load_cfg, "weigh_sigma_k", 1.0))
            rng = (
                "方案二：前 {} 台直通；之后合格判据为 μ±kσ（k={:.1f}，总体标准差）；"
                "直通段 MES 上下限仍为 {:.2f} ~ {:.2f} kg；历史文件 {}（config.yaml：weigh_history_json_path）。"
            ).format(
                int(getattr(load_cfg, "weigh_pass_first_n", 5)),
                _k,
                wlo,
                whi,
                str(getattr(load_cfg, "weigh_history_json_path", "weigh_106_history.json")),
            )
        else:
            rng = "方案一：当前合格区间 {:.2f} ~ {:.2f} kg。".format(wlo, whi)
        wx.CallAfter(
            MainFrame.main_frame.up_notification_ui,
            first="称重工位：货物先放稳再上秤，再扫 SN。",
            second=rng,
            color=wx.RED,
        )
    elif int(load_cfg.dev) >= 100:  # 绑定主机、SN
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫主机条码开始测试", color=wx.RED)
    else:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请启动治具开始测试", color=wx.RED)

    if int(load_cfg.dev) == 100 or int(load_cfg.dev) == 102 or int(load_cfg.dev) == 103:
        wx.CallAfter(MainFrame.main_frame.up_open_ser_button_text, "启动/复位")


def test_idle_work():
    global test_work_state


def _notify_mes_pass_wait_fixture(sn=""):
    """治具门闸型：过站成功并已回 0x57 后，提示等待治具产测帧（0x77 等）。"""
    wx.CallAfter(
        MainFrame.main_frame.up_notification_ui,
        second="过站成功，等待治具发送产测命令",
        third=sn,
        color=wx.BLUE,
    )


def fixture_gate_burst_tx_dev(dev):
    if int(dev) == 50:
        return rv30_proto_tx_dev_byte()
    return int(dev)


def fixture_gate_burst_stop():
    global fixture_gate_burst_active, fixture_gate_burst_payload
    fixture_gate_burst_active = False
    fixture_gate_burst_payload = None


def fixture_89_burst_stop():
    global fixture_89_burst_active
    fixture_89_burst_active = False


def fixture_all_reply_bursts_stop():
    fixture_gate_burst_stop()
    fixture_89_burst_stop()


def fixture_gate_burst_start(dev, cmd, payload, max_count=FIXTURE_REPLY_BURST_COUNT,
                             cancel_on_77=False):
    global fixture_gate_burst_active, fixture_gate_burst_dev, fixture_gate_burst_cmd
    global fixture_gate_burst_payload, fixture_gate_burst_sent, fixture_gate_burst_max
    global fixture_gate_burst_last_ms, fixture_gate_burst_cancel_on_77
    tx_dev = fixture_gate_burst_tx_dev(dev)
    data = list(payload)
    fixture_gate_burst_dev = tx_dev
    fixture_gate_burst_cmd = int(cmd)
    fixture_gate_burst_payload = data
    fixture_gate_burst_sent = 0
    fixture_gate_burst_max = int(max_count)
    fixture_gate_burst_cancel_on_77 = bool(cancel_on_77)
    fixture_gate_burst_active = True
    fixture_gate_burst_last_ms = time.time() * 1000.0
    ser_send_data(tx_dev, fixture_gate_burst_cmd, data)
    fixture_gate_burst_sent = 1
    if fixture_gate_burst_sent >= fixture_gate_burst_max:
        fixture_gate_burst_stop()


def fixture_gate_burst_tick():
    global fixture_gate_burst_sent, fixture_gate_burst_last_ms
    if not fixture_gate_burst_active or fixture_gate_burst_payload is None:
        return
    if fixture_gate_burst_sent >= fixture_gate_burst_max:
        fixture_gate_burst_stop()
        return
    now_ms = time.time() * 1000.0
    if now_ms - fixture_gate_burst_last_ms < FIXTURE_REPLY_BURST_INTERVAL_MS:
        return
    fixture_gate_burst_last_ms = now_ms
    ser_send_data(fixture_gate_burst_dev, fixture_gate_burst_cmd, fixture_gate_burst_payload)
    fixture_gate_burst_sent += 1
    if fixture_gate_burst_sent >= fixture_gate_burst_max:
        fixture_gate_burst_stop()


def fixture_gate_burst_cancel_on_first_77():
    if fixture_gate_burst_active and fixture_gate_burst_cancel_on_77:
        fixture_gate_burst_stop()


def fixture_gate_pass_burst(dev, payload):
    fixture_gate_burst_start(dev, 0x57, payload, cancel_on_77=True)


def fixture_gate_fail_burst(dev, payload):
    fixture_gate_burst_start(dev, 0x58, payload, cancel_on_77=False)


def fixture_89_burst_start(dev):
    global fixture_89_burst_active, fixture_89_burst_dev, fixture_89_burst_sent
    global fixture_89_burst_last_ms
    if fixture_89_burst_active:
        return
    fixture_89_burst_dev = fixture_gate_burst_tx_dev(dev)
    fixture_89_burst_sent = 0
    fixture_89_burst_active = True
    fixture_89_burst_last_ms = time.time() * 1000.0
    ser_send_data(fixture_89_burst_dev, 0x89, [0x03])
    fixture_89_burst_sent = 1
    if fixture_89_burst_sent >= fixture_89_burst_max:
        fixture_89_burst_stop()


def fixture_89_burst_tick():
    global fixture_89_burst_sent, fixture_89_burst_last_ms
    if not fixture_89_burst_active:
        return
    if fixture_89_burst_sent >= fixture_89_burst_max:
        fixture_89_burst_stop()
        return
    now_ms = time.time() * 1000.0
    if now_ms - fixture_89_burst_last_ms < FIXTURE_REPLY_BURST_INTERVAL_MS:
        return
    fixture_89_burst_last_ms = now_ms
    ser_send_data(fixture_89_burst_dev, 0x89, [0x03])
    fixture_89_burst_sent += 1
    if fixture_89_burst_sent >= fixture_89_burst_max:
        fixture_89_burst_stop()


def fixture_reply_burst_tick():
    fixture_gate_burst_tick()
    fixture_89_burst_tick()


def barcode_check_process():
    global check_sn_enable
    global check_sn_str
    global rv30_session_state
    global rv30_last_step
    global rv30_max_step
    global rv30_89_mes_done
    global rv30_finalize_done
    global rv30_realtime_ng
    global wsxqmx_session_state
    global wsxqmx_last_step
    global wsxqmx_got_step3
    global wsxqmx_finalize_done
    global rv50air_session_state
    global rv50air_last_step
    global rv50air_got_step3
    global rv50air_finalize_done
    global ominiair_session_state
    global ominiair_last_step
    global ominiair_got_step3
    global ominiair_finalize_done
    global ominiwater_session_state
    global ominiwater_last_step
    global ominiwater_got_step3
    global ominiwater_last_level_notify
    global ominiwater_finalize_done
    global rv50water_session_state
    global rv50water_last_step
    global rv50water_got_step3
    global rv50water_last_level_notify
    global rv50water_finalize_done
    global rv50_session_state
    global rv50_last_step
    global rv50_max_step
    global rv50_finalize_done
    global omini_session_state
    global omini_last_step
    global omini_max_step
    global omini_last_step4_notify_key
    global omini_89_mes_done
    global omini_finalize_done
    global omini_realtime_ng
    global rv50pcba_session_state
    global rv50pcba_last_step
    global rv50pcba_max_step
    global rv50pcba_89_mes_done
    global rv50pcba_realtime_ng

    if check_sn_enable and (barcode_q.empty() is not True):
        sn = barcode_q.get()
        str_list = [int(byte) for byte in sn.encode('utf-8')]
        if int(load_cfg.dev) == 5:  # 地检
            return
        elif int(load_cfg.dev) == 17:  # #[RV50-017-PROTO] 门闸 0x57/0x58 三连发；失败不发 0x89
            print("[RV50-017] check sn: " + sn)
            encode_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn))
            if encode_res is not True:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="SN码异常，请检测：" + str(sn),
                             color=wx.RED)
                fixture_gate_fail_burst(17, str_list)
                check_sn_str = sn
                check_sn_enable = False
                rv50_session_state = RV50_SESS_ABORTED
                return
            res = mes_run.check_sn_is_ok(sn)
            check_sn_str = sn
            if res:
                fixture_gate_pass_burst(17, str_list)
                rv50_session_state = RV50_SESS_RUNNING
                rv50_last_step = -1
                rv50_max_step = 0
                rv50_finalize_done = False
                rv50_89_mes_done = False
                rv50_realtime_ng = False
                _notify_mes_pass_wait_fixture(sn)
            else:
                fixture_gate_fail_burst(17, str_list)
                rv50_session_state = RV50_SESS_ABORTED
            check_sn_enable = False
            return
        elif int(load_cfg.dev) == 20:  # #[OMINI-020-PROTO] 门闸失败 0x58+0x89[0x03]，不上报 MES
            print("[OMINI-020] check sn: " + sn)
            encode_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn))
            if encode_res is not True:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="SN码异常，请检测：" + str(sn),
                             color=wx.RED)
                ser_send_data(dev=20, cmd=0x58, data=str_list)
                ser_send_data(dev=20, cmd=0x89, data=[0x03])
                check_sn_str = sn
                check_sn_enable = False
                omini_session_state = OMINI_SESS_ABORTED
                return
            res = mes_run.check_sn_is_ok(sn)
            check_sn_str = sn
            if res:
                ser_send_data(dev=20, cmd=0x57, data=str_list)
                omini_session_state = OMINI_SESS_RUNNING
                omini_last_step = -1
                omini_max_step = 0
                omini_last_step4_notify_key = ""
                omini_finalize_done = False
                omini_89_mes_done = False
                omini_realtime_ng = False
                _notify_mes_pass_wait_fixture(sn)
            else:
                ser_send_data(dev=20, cmd=0x58, data=str_list)
                ser_send_data(dev=20, cmd=0x89, data=[0x03])
                omini_session_state = OMINI_SESS_ABORTED
            check_sn_enable = False
            return
        elif int(load_cfg.dev) == 18:  # #[RV50-018-PCBA-PROTO] 帧设备字节 0x12
            print("[RV50-018-PCBA] check sn: " + sn)
            encode_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn))
            if encode_res is not True:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="SN码异常，请检测：" + str(sn),
                             color=wx.RED)
                ser_send_data(dev=18, cmd=0x58, data=str_list)
                check_sn_str = sn
                check_sn_enable = False
                rv50pcba_session_state = RV50PCBA_SESS_ABORTED
                return
            res = mes_run.check_sn_is_ok(sn)
            check_sn_str = sn
            if res:
                ser_send_data(dev=18, cmd=0x57, data=str_list)
                rv50pcba_session_state = RV50PCBA_SESS_RUNNING
                rv50pcba_last_step = -1
                rv50pcba_max_step = 0
                rv50pcba_89_mes_done = False
                rv50pcba_realtime_ng = False
                _notify_mes_pass_wait_fixture(sn)
            else:
                ser_send_data(dev=18, cmd=0x58, data=str_list)
                rv50pcba_session_state = RV50PCBA_SESS_ABORTED
            check_sn_enable = False
            return
        elif int(load_cfg.dev) == 50:  # #[RV30-PROTO] 门闸 0x57/0x58 三连发；失败不发 0x89
            print("check sn: " + sn)
            encode_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn))
            if encode_res is not True:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="SN码异常，请检测：" + str(sn),
                             color=wx.RED)
                fixture_gate_fail_burst(50, str_list)
                check_sn_str = sn
                check_sn_enable = False
                return
            res = mes_run.check_sn_is_ok(sn)
            check_sn_str = sn
            if res:
                fixture_gate_pass_burst(50, str_list)
                rv30_session_state = RV30_SESS_RUNNING
                rv30_last_step = -1
                rv30_max_step = 0
                rv30_finalize_done = False
                rv30_89_mes_done = False
                rv30_realtime_ng = False
                _notify_mes_pass_wait_fixture(sn)
            else:
                fixture_gate_fail_burst(50, str_list)
            check_sn_enable = False
            return
        elif int(load_cfg.dev) == 19:  # [WSXQMX-019] 扫码门闸：0x57/0x58 三连发，不发 0x67
            print("[WSXQMX-019] check sn: " + sn)
            encode_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn))
            if encode_res is not True:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="SN码异常，请检测：" + str(sn),
                             color=wx.RED)
                fixture_gate_fail_burst(19, str_list)
                check_sn_enable = False
                return
            res = mes_run.check_sn_is_ok(sn)
            check_sn_str = sn
            if res:
                fixture_gate_pass_burst(19, str_list)
                wsxqmx_session_state = WSXQMX_SESS_RUNNING
                wsxqmx_last_step = -1
                wsxqmx_got_step3 = False
                wsxqmx_finalize_done = False
                _notify_mes_pass_wait_fixture(sn)
            else:
                fixture_gate_fail_burst(19, str_list)
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="MES过站失败", color=wx.RED)
            check_sn_enable = False
            return
        elif int(load_cfg.dev) in (15, 21):  # #[RV50-OMINI-AIR-CONFIG-PUSH] 0x57+配置码；015 失败 0x58×3
            print("check sn: " + sn)
            encode_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn))
            if encode_res is not True:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="SN码异常，请检测：" + str(sn),
                             color=wx.RED)
                if int(load_cfg.dev) == 15:
                    fixture_gate_fail_burst(15, str_list)
                else:
                    ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
                check_sn_enable = False
                return
            res = mes_run.check_sn_is_ok(sn)
            check_sn_str = sn
            if res:
                if rv50_omini_air_on_scan_pass(int(load_cfg.dev), str_list):
                    _notify_mes_pass_wait_fixture(sn)
            else:
                if int(load_cfg.dev) == 15:
                    fixture_gate_fail_burst(15, str_list)
                else:
                    ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
            check_sn_enable = False
            return
        elif 0 < int(load_cfg.dev) < 100:

            print("check sn: " + sn)
            encode_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn))
            if encode_res is not True:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="SN码异常，请检测：" + str(sn),
                             color=wx.RED)
                if int(load_cfg.dev) == 16:
                    fixture_gate_fail_burst(16, str_list)
                else:
                    ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
                check_sn_enable = False
                return

        res = mes_run.check_sn_is_ok(sn)

        check_sn_str = sn
        if int(load_cfg.dev) < 100 and int(load_cfg.dev) != 5:  # 只处理夹具
            if res:
                if int(load_cfg.dev) == 16:
                    fixture_gate_pass_burst(16, str_list)
                else:
                    ser_send_data(dev=int(load_cfg.dev), cmd=0x57, data=str_list)
                _notify_mes_pass_wait_fixture(sn)
                if int(load_cfg.dev) == 22:  # #[OMINIWATER-022-PROTO]
                    ominiwater_session_state = OMINIWATER_SESS_RUNNING
                    ominiwater_last_step = -1
                    ominiwater_got_step3 = False
                    ominiwater_last_level_notify = -1
                    ominiwater_finalize_done = False
                elif int(load_cfg.dev) == 16:  # #[RV50-016-WATER-PROTO]
                    rv50water_session_state = RV50WATER_SESS_RUNNING
                    rv50water_last_step = -1
                    rv50water_got_step3 = False
                    rv50water_last_level_notify = -1
                    rv50water_finalize_done = False
            else:
                if int(load_cfg.dev) == 16:
                    fixture_gate_fail_burst(16, str_list)
                else:
                    ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)

        check_sn_enable = False


def check_process_run_state():
    # [WEIGH-106] idle 下 dev==106 与 101 等同：barcode_msg_update 进入 running + start_sn_collect
    global test_work_state
    global barcode_msg_update
    global check_sn_str
    global test_start_time

    # 如果测试状态是空闲，打高压或绑码，扫码触发测试，
    # 如果是海能治具，由下位命令机触发
    if test_work_state == "idle":
        dev = int(load_cfg.dev)
        # [WEIGH-106] 106 与 101 等相同：扫码进入 running
        if dev == 100 or dev == 101 or dev == 102 or dev == 103 or dev == 104 or dev == 105 or dev == 106:
            if barcode_msg_update:  # 如果扫码枪收到条码，则进入运行状态
                test_start_time = datetime.now()
                test_work_state = "running"
                barcode_msg_update = False
                if barcode_q.qsize() == 1:
                    sn = barcode_q.get()
                else:
                    tool.clear_queue(barcode_q)
                    sn = ""
                if int(load_cfg.dev) == 100:
                    start_sn_collect(first="请扫主机条码：", second="请扫电池条码：",
                                     third="请扫前撞条码：", start_sn=sn)
                elif dev == 101 or dev == 104 or dev == 105:
                    start_sn_collect(first="请扫集尘桶条码：", start_sn=sn)
                    print("请扫集尘桶条码")
                elif dev == 106:  # [WEIGH-106] 单次扫码
                    start_sn_collect(first="请扫产品 SN：", start_sn=sn)
                elif int(load_cfg.dev) == 102:
                    start_sn_collect(first="请输入条码一：", second="请输入条码二：", start_sn=sn)
                elif int(load_cfg.dev) == 103:
                    start_sn_collect(first="请输入条码：", start_sn=sn)


# 串口打开、扫码枪收到,一帧数据,下位机发送开始测试命令


def read_yaml(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        config = yaml.safe_load(file)
    return config



def get_config_path():
    """获取 config.yaml 的绝对路径（exe 同级目录或开发环境项目根目录）"""
    if getattr(sys, 'frozen', False):
        # 打包后，sys.executable 是 exe 的完整路径
        base_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境，取当前工作目录（通常为项目根目录）
        base_dir = os.path.abspath(".")
    return os.path.join(base_dir, "config.yaml")


def normalize_ver_string(s):
    """将 N.N.N / NNN.NNN.NNN 规范为三位段格式；非法则返回空字符串。"""
    raw = (s or "").strip()
    if not raw:
        return ""
    parts = raw.split(".")
    if len(parts) != 3:
        return ""
    try:
        vals = [int(p) for p in parts]
    except ValueError:
        return ""
    if any(v < 0 or v > 255 for v in vals):
        return ""
    return ".".join(format(v, "03d") for v in vals)


def ver_triplet_matches(actual, expect):
    """三段版本/配置码比对；期望值为空时返回 None（跳过该项）。"""
    e = normalize_ver_string(expect)
    if not e:
        return None
    a = normalize_ver_string(actual)
    if not a:
        return False
    return a == e


def normalize_config_triplet_hex(s):
    """将配置码规范为 XX.XX.XX（每段两位小写十六进制）；非法则返回空字符串。"""
    raw = (s or "").strip()
    if not raw:
        return ""
    parts = raw.split(".")
    if len(parts) != 3:
        return ""
    vals = []
    for p in parts:
        p = p.strip()
        if p.lower().startswith("0x"):
            p = p[2:]
        if not p or len(p) > 2:
            return ""
        try:
            v = int(p, 16)
        except ValueError:
            return ""
        if v < 0 or v > 255:
            return ""
        vals.append(v)
    return ".".join(format(v, "02x") for v in vals)


def config_triplet_matches(actual, expect):
    """三段配置码比对（十六进制）；期望值为空时返回 None（跳过该项）。"""
    e = normalize_config_triplet_hex(expect)
    if not e:
        return None
    a = normalize_config_triplet_hex(actual)
    if not a:
        return False
    return a == e


def base_station_config_ui_enabled():
    """公共 show_base_station_config_ui：1=显示测试格，0=隐藏（不影响 MES/协议逻辑）。"""
    return int(getattr(load_cfg, "show_base_station_config_ui", 1)) != 0


# 加载配置文件
def load_config():
    # [WEIGH-106] 读取 weight_min_kg / weight_max_kg / weight_read_*（见文件内 YAML 赋值处）
    # 读配置文件

    config_path = get_config_path()
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在：{config_path}")
    config = read_yaml(config_path)

    # # yaml_file_path = 'config.yaml'
    # # 读取并打印YAML文件内容
    # yaml_file_path = resource_path('config.yaml')   # 使用 resource_path
    # config = read_yaml(yaml_file_path)
    print(type(config), config)
    load_cfg.com = config.get('user_com', "")  # config['user_com']
    load_cfg.dev = config['device_type']
    _raw_mcu_ver = str(config.get('mcu_version', "")).strip()
    _norm_mcu_ver = normalize_ver_string(_raw_mcu_ver)
    load_cfg.mcu_ver = _norm_mcu_ver if _norm_mcu_ver else _raw_mcu_ver
    load_cfg.test_tool = config.get('test_tool', "治具未编码")  # 测试工具编码，暂不使用（海能mes）
    load_cfg.mes = config.get('use_mes', "3")  # 使用安克mes
    load_cfg.parts_sn_head = config.get('parts_sn_head', "")  # config['parts_sn_head']
    load_cfg.project_name = config.get('project_name', "C10B ")
    print(load_cfg.parts_sn_head)
    # [WEIGH-106] 称重上下限与读数时序（config.yaml 可选）
    load_cfg.weight_min_kg = float(config.get("weight_min_kg", load_cfg.weight_min_kg))
    load_cfg.weight_max_kg = float(config.get("weight_max_kg", load_cfg.weight_max_kg))
    load_cfg.weight_read_delay_sec = float(
        config.get("weight_read_delay_sec", load_cfg.weight_read_delay_sec))
    load_cfg.weight_read_timeout_sec = float(
        config.get("weight_read_timeout_sec", load_cfg.weight_read_timeout_sec))
    load_cfg.weigh_scheme = str(
        config.get("weigh_scheme", getattr(load_cfg, "weigh_scheme", "1"))
    ).strip() or "1"
    load_cfg.weigh_pass_first_n = int(
        config.get("weigh_pass_first_n", getattr(load_cfg, "weigh_pass_first_n", 5))
    )
    if load_cfg.weigh_pass_first_n < 3:
        load_cfg.weigh_pass_first_n = 3
    _wsk = float(
        config.get("weigh_sigma_k", getattr(load_cfg, "weigh_sigma_k", 1.0))
    )
    load_cfg.weigh_sigma_k = round(_wsk, 1)
    if load_cfg.weigh_sigma_k <= 0:
        load_cfg.weigh_sigma_k = 1.0
    _whp = str(
        config.get(
            "weigh_history_json_path",
            getattr(load_cfg, "weigh_history_json_path", "weigh_106_history.json"),
        )
    ).strip()
    load_cfg.weigh_history_json_path = _whp or "weigh_106_history.json"

    # #[RV30-PROTO] 从 config.yaml 读取 RV30 判据（缺省 0 表示不启用该项比较）
    chg_min, chg_max = _rv30_config_u16(
        config,
        "rv30_charge_min", "rv30_charge_max",
        "rv30_charge_Hmin", "rv30_charge_Lmin", "rv30_charge_Hmax", "rv30_charge_Lmax",
    )
    load_cfg.rv30_charge_Hmin, load_cfg.rv30_charge_Lmin = _rv30_u16_to_hl(chg_min)
    load_cfg.rv30_charge_Hmax, load_cfg.rv30_charge_Lmax = _rv30_u16_to_hl(chg_max)
    suction_min, suction_max = _rv30_config_suction_10pa(config)
    load_cfg.rv30_suction_10pa_Hmin, load_cfg.rv30_suction_10pa_Lmin = _rv30_u16_to_hl(suction_min)
    load_cfg.rv30_suction_10pa_Hmax, load_cfg.rv30_suction_10pa_Lmax = _rv30_u16_to_hl(suction_max)

    # load_cfg.rv30_freq_min = int(config.get("rv30_freq_min", getattr(load_cfg, "rv30_freq_min", 0)))
    # load_cfg.rv30_freq_max = int(config.get("rv30_freq_max", getattr(load_cfg, "rv30_freq_max", 0)))
    load_cfg.rv30_freq_expected = int(
    config.get("rv30_freq_expected", getattr(load_cfg, "rv30_freq_expected", 0)))

    load_cfg.rv30_ir_l = int(config.get("rv30_ir_l", getattr(load_cfg, "rv30_ir_l", 0)))
    load_cfg.rv30_ir_lc = int(config.get("rv30_ir_lc", getattr(load_cfg, "rv30_ir_lc", 0)))
    load_cfg.rv30_ir_rc = int(config.get("rv30_ir_rc", getattr(load_cfg, "rv30_ir_rc", 0)))
    load_cfg.rv30_ir_r = int(config.get("rv30_ir_r", getattr(load_cfg, "rv30_ir_r", 0)))
    load_cfg.rv30_dust_bag_expected = int(
        config.get("rv30_dust_bag_expected", getattr(load_cfg, "rv30_dust_bag_expected", 0)))
    load_cfg.rv30_led_expected = int(
        config.get("rv30_led_expected", getattr(load_cfg, "rv30_led_expected", 0)))

    # [WSXQMX-019] 保压结束气压阈值（kPa）
    load_cfg.wsxqmx_hold_kpa_min = float(
        config.get("wsxqmx_hold_kpa_min", getattr(load_cfg, "wsxqmx_hold_kpa_min", -20.0)))
    load_cfg.wsxqmx_hold_kpa_max = float(
        config.get("wsxqmx_hold_kpa_max", getattr(load_cfg, "wsxqmx_hold_kpa_max", -17.0)))

    # #[RV50-015-AIR-PROTO] 三路气压阈值（kPa）
    load_cfg.rv50air_clear_kpa_min = float(
        config.get("rv50air_clear_kpa_min", getattr(load_cfg, "rv50air_clear_kpa_min", 20.0)))
    load_cfg.rv50air_clear_kpa_max = float(
        config.get("rv50air_clear_kpa_max", getattr(load_cfg, "rv50air_clear_kpa_max", 80.0)))
    load_cfg.rv50air_mop_kpa_min = float(
        config.get("rv50air_mop_kpa_min", getattr(load_cfg, "rv50air_mop_kpa_min", 20.0)))
    load_cfg.rv50air_mop_kpa_max = float(
        config.get("rv50air_mop_kpa_max", getattr(load_cfg, "rv50air_mop_kpa_max", 230.0)))
    load_cfg.rv50air_duty_kpa_min = float(
        config.get("rv50air_duty_kpa_min", getattr(load_cfg, "rv50air_duty_kpa_min", -30.0)))
    load_cfg.rv50air_duty_kpa_max = float(
        config.get("rv50air_duty_kpa_max", getattr(load_cfg, "rv50air_duty_kpa_max", -18.0)))

    _raw_base_cfg = str(
        config.get("base_station_config_expected",
                   getattr(load_cfg, "base_station_config_expected", ""))).strip()
    _norm_base_cfg = normalize_config_triplet_hex(_raw_base_cfg)
    load_cfg.base_station_config_expected = _norm_base_cfg if _norm_base_cfg else _raw_base_cfg
    load_cfg.show_base_station_config_ui = int(
        config.get("show_base_station_config_ui",
                   getattr(load_cfg, "show_base_station_config_ui", 1)))

    # #[OMINIAIR-021-PROTO] 三路气压阈值（kPa）；缺省 0 表示不参与比较
    load_cfg.ominiair_clear_kpa_min = float(
        config.get("ominiair_clear_kpa_min", getattr(load_cfg, "ominiair_clear_kpa_min", 0.0)))
    load_cfg.ominiair_clear_kpa_max = float(
        config.get("ominiair_clear_kpa_max", getattr(load_cfg, "ominiair_clear_kpa_max", 0.0)))
    load_cfg.ominiair_mop_kpa_min = float(
        config.get("ominiair_mop_kpa_min", getattr(load_cfg, "ominiair_mop_kpa_min", 0.0)))
    load_cfg.ominiair_mop_kpa_max = float(
        config.get("ominiair_mop_kpa_max", getattr(load_cfg, "ominiair_mop_kpa_max", 0.0)))
    load_cfg.ominiair_duty_kpa_min = float(
        config.get("ominiair_duty_kpa_min", getattr(load_cfg, "ominiair_duty_kpa_min", 0.0)))
    load_cfg.ominiair_duty_kpa_max = float(
        config.get("ominiair_duty_kpa_max", getattr(load_cfg, "ominiair_duty_kpa_max", 0.0)))

    # #[OMINIWATER-022-PROTO] 过水判据；-1 表示不参与比较
    load_cfg.ominiwater_clear_volume_expected = int(
        config.get("ominiwater_clear_volume_expected",
                   getattr(load_cfg, "ominiwater_clear_volume_expected", -1)))
    load_cfg.ominiwater_duty_volume_expected = int(
        config.get("ominiwater_duty_volume_expected",
                   getattr(load_cfg, "ominiwater_duty_volume_expected", -1)))
    load_cfg.ominiwater_left_mop_volume_expected = int(
        config.get("ominiwater_left_mop_volume_expected",
                   getattr(load_cfg, "ominiwater_left_mop_volume_expected", -1)))
    load_cfg.ominiwater_right_mop_volume_expected = int(
        config.get("ominiwater_right_mop_volume_expected",
                   getattr(load_cfg, "ominiwater_right_mop_volume_expected", -1)))
    load_cfg.ominiwater_cleaner_level_expected = int(
        config.get("ominiwater_cleaner_level_expected",
                   getattr(load_cfg, "ominiwater_cleaner_level_expected", -1)))
    load_cfg.ominiwater_left_mop_temp_min = int(
        config.get("ominiwater_left_mop_temp_min",
                   getattr(load_cfg, "ominiwater_left_mop_temp_min", 0)))
    load_cfg.ominiwater_left_mop_temp_max = int(
        config.get("ominiwater_left_mop_temp_max",
                   getattr(load_cfg, "ominiwater_left_mop_temp_max", 0)))
    load_cfg.ominiwater_right_mop_temp_min = int(
        config.get("ominiwater_right_mop_temp_min",
                   getattr(load_cfg, "ominiwater_right_mop_temp_min", 0)))
    load_cfg.ominiwater_right_mop_temp_max = int(
        config.get("ominiwater_right_mop_temp_max",
                   getattr(load_cfg, "ominiwater_right_mop_temp_max", 0)))
    load_cfg.ominiwater_base_hot_temp_min = int(
        config.get("ominiwater_base_hot_temp_min",
                   getattr(load_cfg, "ominiwater_base_hot_temp_min", 0)))
    load_cfg.ominiwater_base_hot_temp_max = int(
        config.get("ominiwater_base_hot_temp_max",
                   getattr(load_cfg, "ominiwater_base_hot_temp_max", 0)))

    # #[RV50-016-WATER-PROTO] 过水判据；-1 表示不参与比较
    load_cfg.rv50water_clear_volume_expected = int(
        config.get("rv50water_clear_volume_expected",
                   getattr(load_cfg, "rv50water_clear_volume_expected", -1)))
    load_cfg.rv50water_duty_volume_expected = int(
        config.get("rv50water_duty_volume_expected",
                   getattr(load_cfg, "rv50water_duty_volume_expected", -1)))
    load_cfg.rv50water_left_mop_volume_expected = int(
        config.get("rv50water_left_mop_volume_expected",
                   getattr(load_cfg, "rv50water_left_mop_volume_expected", -1)))
    load_cfg.rv50water_right_mop_volume_expected = int(
        config.get("rv50water_right_mop_volume_expected",
                   getattr(load_cfg, "rv50water_right_mop_volume_expected", -1)))
    load_cfg.rv50water_cleaner_level_expected = int(
        config.get("rv50water_cleaner_level_expected",
                   getattr(load_cfg, "rv50water_cleaner_level_expected", -1)))
    load_cfg.rv50water_left_mop_temp_min = int(
        config.get("rv50water_left_mop_temp_min",
                   getattr(load_cfg, "rv50water_left_mop_temp_min", 800)))
    load_cfg.rv50water_left_mop_temp_max = int(
        config.get("rv50water_left_mop_temp_max",
                   getattr(load_cfg, "rv50water_left_mop_temp_max", 1800)))
    load_cfg.rv50water_right_mop_temp_min = int(
        config.get("rv50water_right_mop_temp_min",
                   getattr(load_cfg, "rv50water_right_mop_temp_min", 800)))
    load_cfg.rv50water_right_mop_temp_max = int(
        config.get("rv50water_right_mop_temp_max",
                   getattr(load_cfg, "rv50water_right_mop_temp_max", 1800)))
    load_cfg.rv50water_base_hot_temp_min = int(
        config.get("rv50water_base_hot_temp_min",
                   getattr(load_cfg, "rv50water_base_hot_temp_min", 600)))
    load_cfg.rv50water_base_hot_temp_max = int(
        config.get("rv50water_base_hot_temp_max",
                   getattr(load_cfg, "rv50water_base_hot_temp_max", 1300)))
    load_cfg.rv50water_host_hot_temp_min = int(
        config.get("rv50water_host_hot_temp_min",
                   getattr(load_cfg, "rv50water_host_hot_temp_min", 0)))
    load_cfg.rv50water_host_hot_temp_max = int(
        config.get("rv50water_host_hot_temp_max",
                   getattr(load_cfg, "rv50water_host_hot_temp_max", 0)))

    # #[RV50-017-PROTO] device_type=017 判据（0=不参与比较）
    rv50_chg_min, rv50_chg_max = _rv30_config_u16(
        config,
        "rv50_charge_min", "rv50_charge_max",
        "rv50_charge_Hmin", "rv50_charge_Lmin", "rv50_charge_Hmax", "rv50_charge_Lmax",
    )
    load_cfg.rv50_charge_Hmin, load_cfg.rv50_charge_Lmin = _rv30_u16_to_hl(rv50_chg_min)
    load_cfg.rv50_charge_Hmax, load_cfg.rv50_charge_Lmax = _rv30_u16_to_hl(rv50_chg_max)
    rv50_suct_min, rv50_suct_max = _rv50_config_suction_10pa(config)
    load_cfg.rv50_suction_10pa_Hmin, load_cfg.rv50_suction_10pa_Lmin = _rv30_u16_to_hl(rv50_suct_min)
    load_cfg.rv50_suction_10pa_Hmax, load_cfg.rv50_suction_10pa_Lmax = _rv30_u16_to_hl(rv50_suct_max)
    load_cfg.rv50_ir_l = int(config.get("rv50_ir_l", getattr(load_cfg, "rv50_ir_l", 0)))
    load_cfg.rv50_ir_r = int(config.get("rv50_ir_r", getattr(load_cfg, "rv50_ir_r", 0)))
    load_cfg.rv50_ir_n = int(config.get("rv50_ir_n", getattr(load_cfg, "rv50_ir_n", 0)))
    load_cfg.rv50_clear_tank_expected = int(
        config.get("rv50_clear_tank_expected", getattr(load_cfg, "rv50_clear_tank_expected", 0)))
    load_cfg.rv50_duty_tank_expected = int(
        config.get("rv50_duty_tank_expected", getattr(load_cfg, "rv50_duty_tank_expected", 0)))
    load_cfg.rv50_dust_expected = int(
        config.get("rv50_dust_expected", getattr(load_cfg, "rv50_dust_expected", 0)))
    load_cfg.rv50_clean_base_expected = int(
        config.get("rv50_clean_base_expected", getattr(load_cfg, "rv50_clean_base_expected", 0)))
    load_cfg.rv50_clean_pump_min = int(
        config.get("rv50_clean_pump_min", getattr(load_cfg, "rv50_clean_pump_min", 0)))
    load_cfg.rv50_clean_pump_max = int(
        config.get("rv50_clean_pump_max", getattr(load_cfg, "rv50_clean_pump_max", 0)))
    load_cfg.rv50_vacuum_pump_min = int(
        config.get("rv50_vacuum_pump_min", getattr(load_cfg, "rv50_vacuum_pump_min", 0)))
    load_cfg.rv50_vacuum_pump_max = int(
        config.get("rv50_vacuum_pump_max", getattr(load_cfg, "rv50_vacuum_pump_max", 0)))
    load_cfg.rv50_base_level_up_min = int(
        config.get("rv50_base_level_up_min", getattr(load_cfg, "rv50_base_level_up_min", 0)))
    load_cfg.rv50_base_level_up_max = int(
        config.get("rv50_base_level_up_max", getattr(load_cfg, "rv50_base_level_up_max", 0)))
    load_cfg.rv50_base_level_down_min = int(
        config.get("rv50_base_level_down_min", getattr(load_cfg, "rv50_base_level_down_min", 0)))
    load_cfg.rv50_base_level_down_max = int(
        config.get("rv50_base_level_down_max", getattr(load_cfg, "rv50_base_level_down_max", 0)))
    load_cfg.rv50_em_valve_min = int(
        config.get("rv50_em_valve_min", getattr(load_cfg, "rv50_em_valve_min", 0)))
    load_cfg.rv50_em_valve_max = int(
        config.get("rv50_em_valve_max", getattr(load_cfg, "rv50_em_valve_max", 0)))
    load_cfg.rv50_wash_pump_min = int(
        config.get("rv50_wash_pump_min", getattr(load_cfg, "rv50_wash_pump_min", 0)))
    load_cfg.rv50_wash_pump_max = int(
        config.get("rv50_wash_pump_max", getattr(load_cfg, "rv50_wash_pump_max", 0)))
    load_cfg.rv50_turbidity_min = int(
        config.get("rv50_turbidity_min", getattr(load_cfg, "rv50_turbidity_min", 0)))
    load_cfg.rv50_turbidity_max = int(
        config.get("rv50_turbidity_max", getattr(load_cfg, "rv50_turbidity_max", 0)))
    load_cfg.rv50_hot_diff_min = int(
        config.get("rv50_hot_diff_min", getattr(load_cfg, "rv50_hot_diff_min", 0)))
    load_cfg.rv50_hot_diff_max = int(
        config.get("rv50_hot_diff_max", getattr(load_cfg, "rv50_hot_diff_max", 0)))

    # #[OMINI-020-PROTO] device_type=020 判据（0=不参与比较）
    omini_chg_min, omini_chg_max = _rv30_config_u16(
        config,
        "omini_charge_min", "omini_charge_max",
        "omini_charge_Hmin", "omini_charge_Lmin", "omini_charge_Hmax", "omini_charge_Lmax",
    )
    load_cfg.omini_charge_min = omini_chg_min
    load_cfg.omini_charge_max = omini_chg_max
    omini_suct_min, omini_suct_max = _omini_config_suction_10pa(config)
    load_cfg.omini_suction_10pa_Hmin, load_cfg.omini_suction_10pa_Lmin = _rv30_u16_to_hl(omini_suct_min)
    load_cfg.omini_suction_10pa_Hmax, load_cfg.omini_suction_10pa_Lmax = _rv30_u16_to_hl(omini_suct_max)
    load_cfg.omini_ir_l = int(config.get("omini_ir_l", getattr(load_cfg, "omini_ir_l", 0)))
    load_cfg.omini_ir_r = int(config.get("omini_ir_r", getattr(load_cfg, "omini_ir_r", 0)))
    load_cfg.omini_ir_n = int(config.get("omini_ir_n", getattr(load_cfg, "omini_ir_n", 0)))
    load_cfg.omini_clear_tank_expected = int(
        config.get("omini_clear_tank_expected", getattr(load_cfg, "omini_clear_tank_expected", 0)))
    load_cfg.omini_duty_tank_expected = int(
        config.get("omini_duty_tank_expected", getattr(load_cfg, "omini_duty_tank_expected", 0)))
    load_cfg.omini_dust_expected = int(
        config.get("omini_dust_expected", getattr(load_cfg, "omini_dust_expected", 0)))
    load_cfg.omini_clean_base_expected = int(
        config.get("omini_clean_base_expected", getattr(load_cfg, "omini_clean_base_expected", 0)))
    load_cfg.omini_clean_pump_min = int(
        config.get("omini_clean_pump_min", getattr(load_cfg, "omini_clean_pump_min", 0)))
    load_cfg.omini_clean_pump_max = int(
        config.get("omini_clean_pump_max", getattr(load_cfg, "omini_clean_pump_max", 0)))
    load_cfg.omini_vacuum_pump_min = int(
        config.get("omini_vacuum_pump_min", getattr(load_cfg, "omini_vacuum_pump_min", 0)))
    load_cfg.omini_vacuum_pump_max = int(
        config.get("omini_vacuum_pump_max", getattr(load_cfg, "omini_vacuum_pump_max", 0)))
    load_cfg.omini_base_level_up_min = int(
        config.get("omini_base_level_up_min", getattr(load_cfg, "omini_base_level_up_min", 0)))
    load_cfg.omini_base_level_up_max = int(
        config.get("omini_base_level_up_max", getattr(load_cfg, "omini_base_level_up_max", 0)))
    load_cfg.omini_base_level_down_min = int(
        config.get("omini_base_level_down_min", getattr(load_cfg, "omini_base_level_down_min", 0)))
    load_cfg.omini_base_level_down_max = int(
        config.get("omini_base_level_down_max", getattr(load_cfg, "omini_base_level_down_max", 0)))
    load_cfg.omini_em_valve_min = int(
        config.get("omini_em_valve_min", getattr(load_cfg, "omini_em_valve_min", 0)))
    load_cfg.omini_em_valve_max = int(
        config.get("omini_em_valve_max", getattr(load_cfg, "omini_em_valve_max", 0)))
    load_cfg.omini_wash_pump_min = int(
        config.get("omini_wash_pump_min", getattr(load_cfg, "omini_wash_pump_min", 0)))
    load_cfg.omini_wash_pump_max = int(
        config.get("omini_wash_pump_max", getattr(load_cfg, "omini_wash_pump_max", 0)))
    load_cfg.omini_turbidity_min = int(
        config.get("omini_turbidity_min", getattr(load_cfg, "omini_turbidity_min", 0)))
    load_cfg.omini_turbidity_max = int(
        config.get("omini_turbidity_max", getattr(load_cfg, "omini_turbidity_max", 0)))
    load_cfg.omini_hot_diff_min = int(
        config.get("omini_hot_diff_min", getattr(load_cfg, "omini_hot_diff_min", 0)))
    load_cfg.omini_hot_diff_max = int(
        config.get("omini_hot_diff_max", getattr(load_cfg, "omini_hot_diff_max", 0)))

    # #[RV50-018-PCBA-PROTO] device_type=018 判据（0=不参与比较）
    rv50pcba_chg_min, rv50pcba_chg_max = _rv30_config_u16(
        config,
        "rv50pcba_charge_min", "rv50pcba_charge_max",
        "rv50pcba_charge_Hmin", "rv50pcba_charge_Lmin",
        "rv50pcba_charge_Hmax", "rv50pcba_charge_Lmax",
    )
    load_cfg.rv50pcba_charge_min = rv50pcba_chg_min
    load_cfg.rv50pcba_charge_max = rv50pcba_chg_max
    load_cfg.rv50pcba_ir_l = int(
        config.get("rv50pcba_ir_l", getattr(load_cfg, "rv50pcba_ir_l", 0)))
    load_cfg.rv50pcba_ir_r = int(
        config.get("rv50pcba_ir_r", getattr(load_cfg, "rv50pcba_ir_r", 0)))
    load_cfg.rv50pcba_ir_n = int(
        config.get("rv50pcba_ir_n", getattr(load_cfg, "rv50pcba_ir_n", 0)))
    load_cfg.rv50pcba_clear_tank_expected = int(
        config.get("rv50pcba_clear_tank_expected",
                    getattr(load_cfg, "rv50pcba_clear_tank_expected", 0)))
    load_cfg.rv50pcba_duty_tank_expected = int(
        config.get("rv50pcba_duty_tank_expected",
                    getattr(load_cfg, "rv50pcba_duty_tank_expected", 0)))
    load_cfg.rv50pcba_dust_expected = int(
        config.get("rv50pcba_dust_expected", getattr(load_cfg, "rv50pcba_dust_expected", 0)))
    load_cfg.rv50pcba_clean_base_expected = int(
        config.get("rv50pcba_clean_base_expected",
                    getattr(load_cfg, "rv50pcba_clean_base_expected", 0)))
    load_cfg.rv50pcba_clean_pump_min = int(
        config.get("rv50pcba_clean_pump_min", getattr(load_cfg, "rv50pcba_clean_pump_min", 0)))
    load_cfg.rv50pcba_clean_pump_max = int(
        config.get("rv50pcba_clean_pump_max", getattr(load_cfg, "rv50pcba_clean_pump_max", 0)))
    load_cfg.rv50pcba_vacuum_pump_min = int(
        config.get("rv50pcba_vacuum_pump_min", getattr(load_cfg, "rv50pcba_vacuum_pump_min", 0)))
    load_cfg.rv50pcba_vacuum_pump_max = int(
        config.get("rv50pcba_vacuum_pump_max", getattr(load_cfg, "rv50pcba_vacuum_pump_max", 0)))
    load_cfg.rv50pcba_base_level_up_min = int(
        config.get("rv50pcba_base_level_up_min",
                    getattr(load_cfg, "rv50pcba_base_level_up_min", 0)))
    load_cfg.rv50pcba_base_level_up_max = int(
        config.get("rv50pcba_base_level_up_max",
                    getattr(load_cfg, "rv50pcba_base_level_up_max", 0)))
    load_cfg.rv50pcba_base_level_down_min = int(
        config.get("rv50pcba_base_level_down_min",
                    getattr(load_cfg, "rv50pcba_base_level_down_min", 0)))
    load_cfg.rv50pcba_base_level_down_max = int(
        config.get("rv50pcba_base_level_down_max",
                    getattr(load_cfg, "rv50pcba_base_level_down_max", 0)))
    load_cfg.rv50pcba_em_valve_min = int(
        config.get("rv50pcba_em_valve_min", getattr(load_cfg, "rv50pcba_em_valve_min", 0)))
    load_cfg.rv50pcba_em_valve_max = int(
        config.get("rv50pcba_em_valve_max", getattr(load_cfg, "rv50pcba_em_valve_max", 0)))
    load_cfg.rv50pcba_wash_pump_min = int(
        config.get("rv50pcba_wash_pump_min", getattr(load_cfg, "rv50pcba_wash_pump_min", 0)))
    load_cfg.rv50pcba_wash_pump_max = int(
        config.get("rv50pcba_wash_pump_max", getattr(load_cfg, "rv50pcba_wash_pump_max", 0)))
    load_cfg.rv50pcba_turbidity_min = int(
        config.get("rv50pcba_turbidity_min", getattr(load_cfg, "rv50pcba_turbidity_min", 0)))
    load_cfg.rv50pcba_turbidity_max = int(
        config.get("rv50pcba_turbidity_max", getattr(load_cfg, "rv50pcba_turbidity_max", 0)))
    load_cfg.rv50pcba_hot_diff_min = int(
        config.get("rv50pcba_hot_diff_min", getattr(load_cfg, "rv50pcba_hot_diff_min", 0)))
    load_cfg.rv50pcba_hot_diff_max = int(
        config.get("rv50pcba_hot_diff_max", getattr(load_cfg, "rv50pcba_hot_diff_max", 0)))
    load_cfg.rv50pcba_blower_freq_min = int(
        config.get("rv50pcba_blower_freq_min", getattr(load_cfg, "rv50pcba_blower_freq_min", 0)))
    load_cfg.rv50pcba_blower_freq_max = int(
        config.get("rv50pcba_blower_freq_max", getattr(load_cfg, "rv50pcba_blower_freq_max", 0)))

    if is_com_port(load_cfg.com) is False:
        print("配置串口端口非法：" + load_cfg.com)
        load_cfg.com = ""
    else:
        print("配置串口端口为：" + load_cfg.com)

    if int(load_cfg.mes) < 1 or int(load_cfg.mes) > 3:
        print("mes配置异常：" + str(load_cfg.mes))
        load_cfg.mes = str(load_cfg.mes)
    else:
        load_cfg.mes = '002'


def is_com_port(port_name):
    # 定义正则表达式：COM 后跟 1 个或多个数字
    pattern = r"^COM\d+$"
    return re.match(pattern, port_name) is not None


def is_no_use_ser_dev(dev=0):
    if int(dev) == 100 or int(dev) == 102:
        return True
    else:
        return False


def check_ser_connect_and_up_ui():
    global test_ser_connect
    state_change = False

    # 没使用串口设备
    if is_no_use_ser_dev(int(load_cfg.dev)):
        return
    if test_ser_connect:
        if test_serial.test_ser.is_open is not True:
            state_change = True
            test_ser_connect = False
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="串口断开连接", color=wx.RED)
    else:
        if test_serial.test_ser.is_open is True:
            state_change = True
            test_ser_connect = True
            if int(load_cfg.dev) >= 100:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码，启动测试", color=wx.RED)
            else:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请启动治具开始测试", color=wx.RED)
    if state_change:
        wx.CallAfter(MainFrame.main_frame.up_connect_ui, "com_connect", test_ser_connect)
        if test_ser_connect:
            wx.CallAfter(MainFrame.main_frame.up_open_ser_button_text, "关闭串口")
        else:
            wx.CallAfter(MainFrame.main_frame.up_open_ser_button_text, "打开串口")


def test_serial_rx_data_handle():
    if test_serial.test_rx_q.empty() is not True:
        dat = test_serial.test_rx_q.get()
        log = None
        dis_str = "rx: "
        if MainFrame.main_frame.logger:
            log = MainFrame.main_frame.logger.get_logger()
        for hex_dat in dat:
            # print(hex_dat)
            dis_str += str(hex(hex_dat)) + " "
            test_rx_data_handle(hex_dat)
        if log:
            log.info(dis_str)
    # 模拟串口命令，方便所有逻辑都在一个函数里执行
    elif rx_sn_cmd_q.empty() is not True:
        sn_cmd = rx_sn_cmd_q.get()
        dev = load_cfg.dev
        cmd = sn_cmd.get("cmd", "")
        data = sn_cmd.get("msg", "")
        test_cmd_handle(dev, cmd, data)


pack_data_len = 0
check_dev = 0
check_cmd = 0
check_sum = 0
pack_data = []
check_data = []


# 检测数据合法性，并提取，设备、命令、数据，三个字段
def test_rx_data_handle(hex_dat):
    global pack_data
    global pack_data_len
    global check_dev
    global check_cmd
    global check_data
    global check_sum

    pack_data.append(hex_dat)

    if len(pack_data) == 1:
        if hex_dat == 0xA5:  # 帧头 A
            pack_data_len = 0
            check_dev = 0
            check_cmd = 0
            check_sum = 0
            check_data = []
        else:
            pack_data = []
    elif len(pack_data) == 2:  # 帧头 B
        if hex_dat == 0x5A:
            check_sum = 0
        else:
            pack_data = []
    elif len(pack_data) == 3:  # 数据长度
        pack_data_len = hex_dat
        check_sum += hex_dat
    elif len(pack_data) == 4:  # 设备类型
        check_dev = hex_dat
        check_sum += hex_dat
    elif len(pack_data) == 5:  # 命令字
        check_cmd = hex_dat
        check_sum += hex_dat
        check_data = []
    elif (len(pack_data) > 5) and (len(pack_data) <= pack_data_len + 3):
        check_data.append(hex_dat)
        check_sum += hex_dat
    elif len(pack_data) >= pack_data_len + 3:
        if check_sum % 256 == hex_dat:
            print("读取到一帧数据: ", end='')
            print(str(check_data))
            for d in pack_data:
                print(str(hex(d)), end=' ')
            print("")
            test_cmd_handle(check_dev, check_cmd, check_data)
            pack_data = []
        else:
            print("check sum error", hex(check_sum % 256), hex(hex_dat))
            print(hex(pack_data_len), hex(check_dev), hex(check_cmd))
            pack_data = []


def check_cfg_dev(dev):
    global error_display_str

    if int(load_cfg.dev) != int(dev):
        print("配置设备类型：" + str(int(load_cfg.dev)) + " 上传的设备类型：" + str(int(dev)))
        error_display_str = "设备类型不匹配"


def test_cmd_handle(dev, cmd, dat):
    if len(dat) < 1:
        print("设备数据异常")
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具数据异常",
                     color=wx.RED)
        return
    # #[RV30-PROTO] device_type=050 时治具设备字节为 50（0x32），与 YAML 中 50 一致
    _dev_match = int(load_cfg.dev) == int(dev)
    if not _dev_match:
        print("配置设备类型：" + str(int(load_cfg.dev)) + " 上传的设备类型：" + str(int(dev)))
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具类型不匹配", color=wx.RED)
    else:
        if int(dev) == 1 or int(dev) == 6:  # 集尘桶设备
            dust_collector_mode(dev, cmd, dat)
        elif int(dev) == 3 or int(dev) == 4:  # 前撞设备
            lt_bump_mode(dev, cmd, dat)
        elif int(dev) == 5:  # 地检组件
            cliff_tool_mode(dev, cmd, dat)
        elif int(dev) == 7:  # 静态电流治具
            robot_static_current_mode(dev, cmd, dat)
        elif int(dev) == 10 or int(dev) == 11:  # 左右轮治具
            left_right_wheel_mode(dev, cmd, dat)
        elif int(dev) == 12:  # 边刷摆臂治具
            side_brush_mode(dev, cmd, dat)
        elif int(dev) == 13:  # 中扫治具
            main_brush_mode(dev, cmd, dat)
        elif int(dev) == 16:  # #[RV50-016-WATER-PROTO] 帧设备字节 0x10
            RV50_water_mode(dev, cmd, dat)
        elif int(dev) == 15:  # #[RV50-015-AIR-PROTO] 帧设备字节 0x0F
            RV50_air_mode(dev, cmd, dat)
        elif int(dev) == 21:  # #[OMINIAIR-021-PROTO] 帧设备字节 0x15
            Omini_air_mode(dev, cmd, dat)
        elif int(dev) == 22:  # #[OMINIWATER-022-PROTO] 帧设备字节 0x16
            Omini_water_mode(dev, cmd, dat)
        elif int(dev) == 20:  # #[OMINI-020-PROTO] 帧设备字节 0x14
            Omini_finished_product_mode(dev, cmd, dat)
        elif int(dev) == 17:  # #[RV50-017-PROTO]
            RV50_finished_product_mode(dev, cmd, dat)
        elif int(dev) == 18:  # #[RV50-018-PCBA-PROTO] 帧设备字节 0x12
            RV50_pcba_mode(dev, cmd, dat)
        elif int(dev) == 19:  # [WSXQMX-019] RV50 污水箱气密性，帧设备字节 0x13
            wsxqmx_mode(dev, cmd, dat)
        #[FX_TODO]
        elif int(dev) == 50:  # #[RV30-PROTO] 帧设备字节 50（0x32）
           RV30_finished_product_mode(dev, cmd, dat)


def ser_send_cmd(dev, cmd):
    ck_sum = (0x02 + dev + cmd) % 256
    ser_dat = bytes([0xA5, 0x5A, 0x02, dev, cmd, ck_sum])
    test_serial.test_serial_send(ser_dat)


# 数据 data 是一个字节序列表
def ser_send_data(dev, cmd, data):
    data_len = len(data)
    ck_sum = tool.check_sum([0x02 + data_len, dev, cmd] + data)
    sum_list = [ck_sum]
    ser_dat = bytes([0xA5, 0x5A, 0x02 + data_len, dev, cmd] + data + sum_list)
    print("发送d: ")
    for d in ser_dat:
        print(hex(d), end=' ')
    print(" ")
    test_serial.test_serial_send(ser_dat)


# #[RV30-PROTO] 以下为 RV30 基站(device_type=50) 专用辅助函数（调优入口：hw1_bastation_finished_product_mode_FX）
def rv30_proto_reset_to_idle():
    # #[RV30-PROTO] 一轮测试完全结束后恢复空闲，便于下一轮 0x66
    global rv30_session_state, rv30_last_step, rv30_max_step, rv30_89_mes_done
    global rv30_finalize_done, rv30_realtime_ng, rv30_last_p, rv30_last_dust_notify
    rv30_session_state = RV30_SESS_IDLE
    rv30_last_step = -1
    rv30_max_step = 0
    rv30_89_mes_done = False
    rv30_finalize_done = False
    rv30_realtime_ng = False
    rv30_last_p = None  # [up_test_ui_WBH]
    rv30_last_dust_notify = -1  # [RV30-尘袋步骤3-WBH]


def rv30_proto_tx_dev_byte():
    # #[RV30-PROTO] 发往治具的设备字节与 device_type 数值一致（050 → 50 / 0x32）
    return int(load_cfg.dev)


def rv30_proto_mes_ng_once(notify_second="MES已报NG"):
    # #[RV30-PROTO] 发完 0x89 或门闸失败后立即上报 NG，防抖不重复 send_report
    global test_end_time, rv30_89_mes_done, rv30_session_state
    if rv30_89_mes_done:
        return
    rv30_89_mes_done = True
    test_end_time = datetime.now()
    rv30_session_state = RV30_SESS_ABORTED
    mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=notify_second, color=wx.RED)


def rv30_proto_abort_mes_after_gate_fail():
    # #[RV30-PROTO] 门闸阶段已发 0x58+0x89，此处只做 MES NG 与状态收尾
    rv30_proto_mes_ng_once(notify_second="门闸失败，MES已报NG")


def rv30_proto_realtime_fail(dev, reason):
    # #[RV30-PROTO] 实时阶段 0x89[0x03] 三连发；MES NG 仅一次
    global rv30_realtime_ng
    if rv30_89_mes_done:
        return
    rv30_realtime_ng = True
    fixture_89_burst_start(50)
    mes_run.add_report(name="RV30实时判据", result="NG", value=str(reason))
    rv30_proto_mes_ng_once(notify_second="实时判据失败：" + str(reason))


def rv30_proto_parse_68_dat(dat):
    # #[RV30-PROTO-68-MOD] 解析治具 0x68「阈值上传」→ 写入 load_cfg.rv30_*（供 0x77 与 rv30_proto_yaml_realtime_ok 比对）
    # 布局 doc/MES协议.csv「阈值上传」： [0-3]回充 [4-7]版本 [8]频率 [9]尘袋 [10-11]充电min [12-13]充电max [14]LED [15-18]集尘min/max
    global load_cfg

    if len(dat) < RV30_68_DATA_LEN:
        print("[RV30-PROTO-68-MOD] 0x68 数据区长度不足: got", len(dat), "need", RV30_68_DATA_LEN)
        return False

    ir_l, ir_lc, ir_rc, ir_r = (int(dat[i]) for i in range(4))
    ver_raw = ".".join(format(int(dat[i]), "03d") for i in range(4, 8))
    freq = int(dat[8])
    dust_bag = int(dat[9])
    chg_min = _rv30_u16_be(dat[10], dat[11])
    chg_max = _rv30_u16_be(dat[12], dat[13])
    led = int(dat[14])
    suction_min = _rv30_u16_be(dat[15], dat[16])
    suction_max = _rv30_u16_be(dat[17], dat[18])

    # #[RV30-PROTO-68-MOD] 与 rv30_proto_yaml_realtime_ok 四字节 H/L 编码一致（覆盖运行时阈值，yaml 启动值可被治具刷新）
    load_cfg.rv30_ir_l = ir_l
    load_cfg.rv30_ir_lc = ir_lc
    load_cfg.rv30_ir_rc = ir_rc
    load_cfg.rv30_ir_r = ir_r
    load_cfg.rv30_charge_Hmin = (chg_min >> 8) & 0xFF
    load_cfg.rv30_charge_Lmin = chg_min & 0xFF
    load_cfg.rv30_charge_Hmax = (chg_max >> 8) & 0xFF
    load_cfg.rv30_charge_Lmax = chg_max & 0xFF
    load_cfg.rv30_suction_10pa_Hmin = (suction_min >> 8) & 0xFF
    load_cfg.rv30_suction_10pa_Lmin = suction_min & 0xFF
    load_cfg.rv30_suction_10pa_Hmax = (suction_max >> 8) & 0xFF
    load_cfg.rv30_suction_10pa_Lmax = suction_max & 0xFF


    # load_cfg.rv30_freq_min = freq
    # load_cfg.rv30_freq_max = freq
    load_cfg.rv30_freq_expected = freq

    load_cfg.rv30_dust_bag_expected = dust_bag
    load_cfg.rv30_led_expected = led

    # #[RV30-PROTO-68-MOD] 兼容旧 dust_th 字段（频率→ac_lv，集尘→barometer/out_barometer，勿再误用气压语义）
    dust_th.cc_min = chg_min
    dust_th.cc_max = chg_max
    dust_th.ac_lv_min = freq
    dust_th.ac_lv_max = freq
    dust_th.barometer_min = suction_min
    dust_th.barometer_max = suction_max
    dust_th.out_barometer_min = suction_min
    dust_th.out_barometer_max = suction_max

    print(
        "[RV30-PROTO-68-MOD] 阈值已加载 ir=%s,%s,%s,%s ver=%s freq=%s dust=%s "
        "chg=[%02X,%02X]-[%02X,%02X] led=%s suction=[%02X,%02X]-[%02X,%02X]"
        % (ir_l, ir_lc, ir_rc, ir_r, ver_raw, freq, dust_bag,
           dat[10], dat[11], dat[12], dat[13], led,
           dat[15], dat[16], dat[17], dat[18])
    )
    return True


def rv30_proto_parse_77_apply_globals(dat):
    # #[RV30-PROTO-77-MOD] 0x77 数据区固定 15 字节（帧长字段=17=设备+命令+数据区）：
    # [0步骤,1左红外,2左中,3右中,4右红外,5~7版本3B,8频率,9尘袋,10~11充电ADC,12LED灯,13~14集尘吸力]；集尘×10Pa
    global charge_value, dev_ver, ver_res
    global ir_code_left, ir_code_lc, ir_code_right, ir_code_rc
    global dust_bug_install, dust_collection_suction
    if len(dat) < 15:
        print("[RV30-PROTO-77-MOD] 0x77 数据区长度不足:", len(dat))
        return None
    step = int(dat[0])
    ir_code_left = int(dat[1])
    ir_code_lc = int(dat[2])
    ir_code_rc = int(dat[3])   # 右中红外（变量名保留，兼容 UI/MES 键）
    ir_code_right = int(dat[4])
    dev_ver = ".".join(format(int(dat[i]), "03d") for i in range(5, 8))
    freq = int(dat[8])
    dust_bug_install = int(dat[9])
    charge_value = int(dat[10]) << 8 | int(dat[11])
    led = int(dat[12])
    dust_collection_suction = (int(dat[13]) << 8 | int(dat[14]))


    if dev_ver == load_cfg.mcu_ver:
        ver_res = "OK"
    else:
        ver_res = "NG"


    return {
        "step": step,
        "ir_l": ir_code_left,
        "ir_lc": ir_code_lc,
        "ir_rc": ir_code_rc,
        "ir_r": ir_code_right,
        "dev_ver": dev_ver,
        "freq": freq,
        "dust": dust_bug_install,
        "charge": charge_value,
        "led": led,
        "suction_pa": dust_collection_suction,
    }


def rv30_field_active(step, field):
    # [RV30-测试项分步报错-WBH] 步骤1回充码；2+版本/频率；3+充电/尘袋/LED(不含集尘)；4+集尘吸力
    st = int(step) if step is not None else 0
    if st < 1:
        return False
    if field in ("ir_l", "ir_lc", "ir_rc", "ir_r"):
        return st >= 1
    if field in ("dev_ver", "freq"):
        return st >= 2
    if field in ("charge", "dust", "led"):
        return st >= 3
    if field == "suction_pa":
        return st >= 4
    return False


# [RV30-步骤3监视-WBH] 步骤3仅监视/尘袋提示，不参与 yaml 实时 NG
RV30_STEP3_MONITOR_FIELDS = ("charge", "dust", "led")


def rv30_step3_monitor_phase(p):
    # [RV30-步骤3监视-WBH]
    return p is not None and int(p.get("step", 0)) == 3


def rv30_dust_step3_ui(p):
    # [RV30-尘袋步骤3-WBH] 0/1/2/3 → 未测试/红+文案/绿；步骤3不打断流程
    d = int(p.get("dust", 0))
    if d == 0:
        return "untested", ""
    if d == 1:
        return "fail", "取出尘袋"
    if d == 2:
        return "fail", "放入尘袋"
    if d == 3:
        return "pass", str(d)
    return "fail", str(d)


def rv30_dust_step3_notify(p):
    # [RV30-尘袋步骤3-WBH] 顶部提示：1 取出 / 2 放入 / 3 通过；0 不改动
    global rv30_last_dust_notify
    if p is None or int(p.get("step", 0)) != 3:
        return
    d = int(p.get("dust", 0))
    if d == rv30_last_dust_notify:
        return
    rv30_last_dust_notify = d
    mf = MainFrame.main_frame
    if mf is None:
        return
    if d == 1:
        mf.up_notification_ui(second="取出尘袋", color=wx.RED)
    elif d == 2:
        mf.up_notification_ui(second="放入尘袋", color=wx.RED)
    elif d == 3:
        mf.up_notification_ui(second="请工人观察LED灯显示，正常按开始键，异常按结束键", color=wx.RED)


def rv30_dust_field_status(p):
    # [RV30-尘袋步骤3-WBH] 步骤3用状态机；步骤>3 仍用 yaml 期望(通常为3)
    if p is None:
        return "untested"
    step = int(p.get("step", 0))
    if step < 3:
        return "untested"
    if step == 3:
        d = int(p.get("dust", 0))
        if d == 0:
            return "untested"
        if d in (1, 2):
            return False
        if d == 3:
            return True
        return False
    return rv30_field_ok(p, "dust")


def rv30_dust_flow_complete(p):
    # [RV30-尘袋步骤3-WBH] 曾到步骤3则结束帧要求 dust==3
    if p is None:
        return True
    if int(p.get("step", 0)) < 3:
        return True
    return int(p.get("dust", 0)) == 3


def rv30_field_status(p, field):
    # [RV30-测试项分步报错-WBH] 未到测试本项的步骤→"untested"；到步骤后同 rv30_field_ok(True/False/None)
    # [RV30-步骤3监视-WBH] 步骤3：charge/led 仅 monitor；dust 走状态机
    if p is None:
        return "untested"
    step = int(p.get("step", 0))
    if field == "dust":
        return rv30_dust_field_status(p)
    if step == 3 and field in ("charge", "led"):
        return None
    if not rv30_field_active(step, field):
        return "untested"
    return rv30_field_ok(p, field)


def rv30_field_status_finalize(p, field):
    # [RV30-步骤3监视-WBH] 0x88 终态：step>=4 按 yaml 全量判；step==3 仍用尘袋状态机
    if p is None:
        return "untested"
    step = int(p.get("step", 0))
    if step == 3:
        if field == "dust":
            return rv30_dust_field_status(p)
        if field in ("charge", "led"):
            return None
        if not rv30_field_active(step, field):
            return "untested"
        return rv30_field_ok(p, field)
    if step < 4:
        return rv30_field_status(p, field)
    if field == "dust":
        d = int(p.get("dust", 0))
        return True if d == 3 else False
    if not rv30_field_active(step, field):
        return "untested"
    return rv30_field_ok(p, field)


def rv30_proto_yaml_all_items_ok(p):
    # [RV30-步骤4终判-WBH] 步骤4：对已开放项做全量 yaml 比对（False=NG；None=未配置跳过）
    if p is None:
        return False
    step = int(p.get("step", 0))
    if step < 4:
        return False
    for field in (
        "dev_ver", "charge", "suction_pa", "freq",
        "ir_l", "ir_lc", "ir_rc", "ir_r", "dust", "led",
    ):
        if not rv30_field_active(step, field):
            continue
        if field == "dust":
            if int(p.get("dust", 0)) != 3:
                return False
            continue
        ok = rv30_field_ok(p, field)
        if ok is False:
            return False
    return True


def rv30_proto_yaml_finalize_ok(p):
    # [RV30-步骤4终判-WBH] 0x88 综合 PASS：本轮须到过步骤4，且最后一帧在步骤4+且全项达标
    global rv30_max_step
    if rv30_max_step < 4:
        return False
    if p is None:
        return False
    if int(p.get("step", 0)) < 4:
        return False
    return rv30_proto_yaml_all_items_ok(p)


def rv30_field_ok(p, field):
    # [up_test_ui_WBH] 单项判据：True/False=参与比较；None=yaml 未配置该项
    if p is None:
        return None
    if field == "dev_ver":
        expect_ver = (load_cfg.mcu_ver or "").strip() # 整数0/空字符串/没有配置 会被当作假值，返回右边
        if not expect_ver: # 字符串0也不会走这一个分支
            return None
        return p.get("dev_ver") == expect_ver
    if field == "charge":
        ch = (
            load_cfg.rv30_charge_Hmin, load_cfg.rv30_charge_Lmin,
            load_cfg.rv30_charge_Hmax, load_cfg.rv30_charge_Lmax,
        )
        if ch == (0, 0, 0, 0):
            return None
        lo = (ch[0] << 8) | (ch[1] & 0xFF)
        hi = (ch[2] << 8) | (ch[3] & 0xFF)
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["charge"] <= hi
    if field == "suction_pa":
        su = (
            load_cfg.rv30_suction_10pa_Hmin, load_cfg.rv30_suction_10pa_Lmin,
            load_cfg.rv30_suction_10pa_Hmax, load_cfg.rv30_suction_10pa_Lmax,
        )
        if su == (0, 0, 0, 0):
            return None
        slo = (su[0] << 8) | (su[1] & 0xFF)
        shi = (su[2] << 8) | (su[3] & 0xFF)
        if slo > shi:
            slo, shi = shi, slo
        return slo <= p["suction_pa"] <= shi


    # if field == "freq":
    #     fmin, fmax = load_cfg.rv30_freq_min, load_cfg.rv30_freq_max
    #     if fmin == 0 and fmax == 0:
    #         return None
    #     flo, fhi = (fmin, fmax) if fmin <= fmax else (fmax, fmin)
    #     return flo <= p["freq"] <= fhi
    if field == "freq":
        if not load_cfg.rv30_freq_expected:
            return None
        return p["freq"] == load_cfg.rv30_freq_expected    


    if field == "ir_l":
        if not load_cfg.rv30_ir_l:
            return None
        return p["ir_l"] == load_cfg.rv30_ir_l
    if field == "ir_lc":
        if not load_cfg.rv30_ir_lc:
            return None
        return p["ir_lc"] == load_cfg.rv30_ir_lc
    if field == "ir_rc":
        if not load_cfg.rv30_ir_rc:
            return None
        return p["ir_rc"] == load_cfg.rv30_ir_rc
    if field == "ir_r":
        if not load_cfg.rv30_ir_r:
            return None
        return p["ir_r"] == load_cfg.rv30_ir_r
    if field == "dust":
        if not load_cfg.rv30_dust_bag_expected:
            return None
        return p["dust"] == load_cfg.rv30_dust_bag_expected
    if field == "led":
        if not load_cfg.rv30_led_expected:
            return None
        return p["led"] == load_cfg.rv30_led_expected
    return None


def rv30_proto_yaml_realtime_ok(p):
    # #[RV30-PROTO] 以 config.yaml 为主与 0x77 解析结果比对；返回 False 表示应走实时异常
    # [up_test_ui_WBH] 汇总单项 rv30_field_ok
    # [RV30-测试项分步报错-WBH] 仅当前治具步骤已开放的项参与实时 NG
    # [RV30-步骤3监视-WBH] 步骤3整帧不实时 NG（尘袋提示+充电/LED 监视），步骤4再判
    if p is None:
        return True
    step = int(p.get("step", 0))
    if step == 3:
        return True
    for field in (
        "dev_ver", "charge", "suction_pa", "freq",
        "ir_l", "ir_lc", "ir_rc", "ir_r", "dust", "led",
    ):
        if not rv30_field_active(step, field):
            continue
        ok = rv30_field_ok(p, field) # 捕捉的值与配置的值进行比较，有错误就进行报错
        if ok is False:
            return False
    return True


def rv30_proto_ui_result_str(ok):
    # [up_test_ui_WBH] 单项判据 → up_test_ui 的 result 参数
    # [RV30-测试项分步报错-WBH]
    if ok == "untested":
        return "untested"
    if ok is True:
        return "pass"
    if ok is False:
        return "fail"
    return "monitor"


def rv30_proto_apply_test_ui_row(p, ui_name, field, val, finalize=False):
    # [RV30-步骤3监视-WBH] 统一刷新单行；finalize 用终态判据


    # 步骤四，最终态处理
    if finalize: # 这个参数决定是不是终态刷新
        st = rv30_field_status_finalize(p, field)
    else:

        # 步骤三，分别处理尘袋的显示，充电和led的显示
        if field == "dust" and rv30_step3_monitor_phase(p): # 尘袋测试项，并且是步骤三
            res, show_val = rv30_dust_step3_ui(p) # 尘袋项的状态机决定尘袋项的显示
            MainFrame.main_frame.up_test_ui(name=ui_name, result=res, value=show_val)
            # ui_name决定是哪一个键，result决定是键值的颜色，val是字符串，在对应位置显示
            return
        if rv30_step3_monitor_phase(p) and field in ("charge", "led"):
            MainFrame.main_frame.up_test_ui(name=ui_name, result="monitor", value=val)
            return

        # 排除步骤三与步骤四的情况，下面是步骤一和步骤二
        st = rv30_field_status(p, field)
    if st == "untested":
        res, show_val = "untested", ""
    elif st is False:
        res, show_val = "fail", val
    elif st is True:
        res, show_val = "pass", val
    else:
        res, show_val = "monitor", val
    # rv30_field_status 返回一个状态，根据返回的状态更新测试ui（field是指定的测试项）
    MainFrame.main_frame.up_test_ui(name=ui_name, result=res, value=show_val)


def _rv30_proto_ui_rows(p):
    # #[RV30-DISPLAY] 测试格中间列：回充码 0xNN、集尘吸力 kPa（与 config.yaml 单位一致）
    return [
        ("mcu_ver", "dev_ver", p["dev_ver"]),
        ("ir_code_left", "ir_l", _rv30_fmt_ir_byte(p["ir_l"])),
        ("ir_code_lc", "ir_lc", _rv30_fmt_ir_byte(p["ir_lc"])),
        ("ir_code_rc", "ir_rc", _rv30_fmt_ir_byte(p["ir_rc"])),
        ("ir_code_right", "ir_r", _rv30_fmt_ir_byte(p["ir_r"])),
        ("charge_value", "charge", str(p["charge"])),
        ("rv30_freq", "freq", str(p["freq"])),
        ("dust_bug_install", "dust", str(p["dust"])),
        ("rv30_led", "led", str(p["led"])),
        ("dust_collection_suction", "suction_pa", _rv30_fmt_suction_kpa(p["suction_pa"])),
    ]


def rv30_proto_refresh_test_ui(p, finalize=False):
    # [up_test_ui_WBH] 0x77 实时刷新 test_static_box（须在 UI 线程 CallAfter 调用）
    # [RV30-测试项分步报错-WBH] 未到步骤显示未测试，到步骤后再判 pass/fail/monitor
    # [RV30-步骤3监视-WBH] 步骤3 charge/led 仅 monitor；0x88 且 step>=4 时 finalize=True 全量判
    if p is None or MainFrame.main_frame is None:
        return
    rows = _rv30_proto_ui_rows(p)
    for ui_name, field, val in rows:
        rv30_proto_apply_test_ui_row(p, ui_name, field, val, finalize=finalize)
    if not finalize and rv30_step3_monitor_phase(p):
        rv30_dust_step3_notify(p)


def rv30_proto_refresh_test_ui_callafter(p):
    # [up_test_ui_WBH] 从串口线程安全投递到 UI 线程
    wx.CallAfter(rv30_proto_refresh_test_ui, p)


def rv30_proto_add_fx_reports():
    # #[RV30-PROTO] 上报 MES 明细项（与旧 hw1 FX 列表对齐，便于调优对比历史）
    # #[RV30-DISPLAY] 回充码 0xNN、集尘吸力 kPa，阈值与 config rv30_suction_kpa_* 一致
    mes_run.add_report(name="mcu软件版本", result=ver_res, value=dev_ver, val_max=load_cfg.mcu_ver, val_min=load_cfg.mcu_ver)
    mes_run.add_report(name="充电电流", result="", value=str(charge_value))
    mes_run.add_report(name="左回充码", result="", value=_rv30_fmt_ir_byte(ir_code_left))
    # #[RV30-PROTO-77-MOD] 四路红外与 0x77 下标 1~4 对齐
    mes_run.add_report(name="左中回充码", result="", value=_rv30_fmt_ir_byte(ir_code_lc))
    mes_run.add_report(name="右中回充码", result="", value=_rv30_fmt_ir_byte(ir_code_rc))
    mes_run.add_report(name="右回充码", result="", value=_rv30_fmt_ir_byte(ir_code_right))
    mes_run.add_report(name="尘袋在位", result="", value=str(dust_bug_install))
    su_cfg = (
        load_cfg.rv30_suction_10pa_Hmin, load_cfg.rv30_suction_10pa_Lmin,
        load_cfg.rv30_suction_10pa_Hmax, load_cfg.rv30_suction_10pa_Lmax,
    )
    if su_cfg == (0, 0, 0, 0):
        suction_val_min, suction_val_max = "", ""
    else:
        slo, shi = _rv30_suction_threshold_10pa()
        suction_val_min = _rv30_fmt_suction_kpa(slo)
        suction_val_max = _rv30_fmt_suction_kpa(shi)
    mes_run.add_report(
        name="集尘吸力kPa",
        result="",
        value=_rv30_fmt_suction_kpa(dust_collection_suction),
        val_min=suction_val_min,
        val_max=suction_val_max,
    )


def rv30_proto_finalize_88(dev, dat):
    # #[RV30-PROTO] 收到 0x88：dat[0]=03 治具正常结束（再综合判定）；04 治具与基站通讯失败
    global test_end_time, rv30_session_state, rv30_89_mes_done, rv30_finalize_done
    if rv30_finalize_done:
        print("[RV30-050] 重复 0x88，忽略")
        return

    test_end_time = datetime.now()

    res_byte = dat[0] if len(dat) else 0xFF
    if res_byte == 0x04:
        if not rv30_89_mes_done:
            mes_run.add_report(name="基站通讯", result="NG", value="治具与基站通讯失败")
            mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
            rv30_89_mes_done = True
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second="治具与基站通讯失败", color=wx.RED)
        rv30_session_state = RV30_SESS_FINISHED
        rv30_finalize_done = True
        clear_sn_save_list()
        return

    if rv30_89_mes_done:
        rv30_session_state = RV30_SESS_FINISHED
        rv30_finalize_done = True
        clear_sn_save_list()
        return

    normal_end = res_byte == 0x03
    global rv30_last_p
    # [RV30-步骤4终判-WBH] 须到过步骤4且最后一帧全项达标；步骤3不 fail，步骤1/2 仍走实时 NG

    mes_ok = (normal_end and (not rv30_realtime_ng) and (ver_res == "OK")
              and rv30_proto_yaml_finalize_ok(rv30_last_p))

    # [RV30-步骤3监视-WBH] MES 明细仅在 0x88 统一写入（步骤3不上传）
    rv30_proto_add_fx_reports()
    if mes_ok:
        mes_run.add_report(name="led", result="OK")
        res_display_str = "测试完成(综合判定 PASS)"
        text_color = wx.GREEN
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
    else:
        mes_run.add_report(name="led", result="NG")
        res_display_str = "测试结束(综合判定 NG)"
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
    rv30_89_mes_done = True

    # [up_test_ui_WBH] 结束帧用最后一帧 0x77 刷新测试格；综合 NG 时未配置阈值的项也标 fail
    # [RV30-测试项分步报错-WBH] 结束刷新同样按最后一帧 step 分步；未到步骤保持未测试
    if rv30_last_p is not None:
        use_finalize_ui = int(rv30_last_p.get("step", 0)) >= 4
        if mes_ok:
            wx.CallAfter(
                rv30_proto_refresh_test_ui, rv30_last_p, use_finalize_ui)
        else:


            def _finalize_ui_refresh():
                p = rv30_last_p
                if p is None:
                    return


                rows = _rv30_proto_ui_rows(p)
                fin = int(p.get("step", 0)) >= 4
                for ui_name, field, val in rows:
                    if not fin and field == "dust" and int(p.get("step", 0)) == 3:
                        res, show_val = rv30_dust_step3_ui(p)
                        MainFrame.main_frame.up_test_ui(
                            name=ui_name, result=res, value=show_val)
                        continue
                    if fin:
                        rv30_proto_apply_test_ui_row(
                            p, ui_name, field, val, finalize=True)
                        continue
                    st = rv30_field_status(p, field)
                    if st == "untested":
                        res, show_val = "untested", ""
                    elif st is False or (rv30_realtime_ng and st is not True):
                        res, show_val = "fail", val
                    elif st is True:
                        res, show_val = "pass", val
                    else:
                        res, show_val = "monitor", val
                    MainFrame.main_frame.up_test_ui(
                        name=ui_name, result=res, value=show_val)

            wx.CallAfter(_finalize_ui_refresh)
    if mes_ret:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=res_display_str, color=text_color)
    rv30_session_state = RV30_SESS_FINISHED
    rv30_finalize_done = True
    clear_sn_save_list()


# #[RV50-017-PROTO] RV50 基站全功能 device_type=017（见 doc/ce_mes_iteration/RV50_017_AI_PROMPT_GUIDE.md）
def rv50_proto_reset_to_idle():
    global rv50_session_state, rv50_last_step, rv50_max_step, rv50_last_p, rv50_last_step4_notify_key
    global rv50_89_mes_done, rv50_finalize_done, rv50_realtime_ng
    rv50_session_state = RV50_SESS_IDLE
    rv50_last_step = -1
    rv50_max_step = 0
    rv50_last_p = None
    rv50_last_step4_notify_key = ""
    rv50_89_mes_done = False
    rv50_finalize_done = False
    rv50_realtime_ng = False


def rv50_proto_mes_ng_once(notify_second="MES已报NG"):
    global test_end_time, rv50_89_mes_done, rv50_session_state
    if rv50_89_mes_done:
        return
    rv50_89_mes_done = True
    test_end_time = datetime.now()
    rv50_session_state = RV50_SESS_ABORTED
    mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=notify_second, color=wx.RED)


def rv50_proto_realtime_fail(dev, reason):
    global rv50_realtime_ng
    if rv50_89_mes_done:
        return
    rv50_realtime_ng = True
    fixture_89_burst_start(dev)
    mes_run.add_report(name="RV50实时判据", result="NG", value=str(reason))
    rv50_proto_mes_ng_once(notify_second="实时判据失败：" + str(reason))


def rv50_proto_parse_77_apply_globals(dat):
    global charge_value, dev_ver, ver_res
    global ir_code_left, ir_code_right, ir_code_near
    global clear_tank_install, duty_tank_install, dust_bug_install, clean_base_install
    global dust_collection_suction, clean_water_pump_current, duty_water_pump_current
    global cleaner_pump_current, electromagnetic_three_way_current
    global turbidity_data
    global rv50_base_level_up_adc, rv50_base_level_down_adc
    global rv50_hot_start_adc, rv50_hot_end_adc, rv50_hot_diff_adc
    if len(dat) < RV50_77_DATA_LEN:
        print("[RV50-017] 0x77 数据区长度不足: got", len(dat), "need", RV50_77_DATA_LEN)
        return None
    step = int(dat[0])
    charge_value = _rv30_u16_be(dat[1], dat[2])
    ir_code_left = int(dat[3])
    ir_code_right = int(dat[4])
    ir_code_near = int(dat[5])
    clear_tank_install = int(dat[6])
    duty_tank_install = int(dat[7])
    dust_bug_install = int(dat[8])
    clean_base_install = int(dat[9])
    dev_ver = ".".join(format(int(dat[i]), "03d") for i in range(10, 13))
    base_config = rv50_fmt_config_3bytes(dat, 13)  # #[RV50-017-CONFIG-DISPLAY] 原保留位
    dust_collection_suction = _rv30_u16_be(dat[16], dat[17])
    clean_water_pump_current = _rv30_u16_be(dat[18], dat[19])
    duty_water_pump_current = _rv30_u16_be(dat[20], dat[21])
    rv50_base_level_up_adc = _rv30_u16_be(dat[22], dat[23])
    rv50_base_level_down_adc = _rv30_u16_be(dat[24], dat[25])
    electromagnetic_three_way_current = _rv30_u16_be(dat[26], dat[27])
    cleaner_pump_current = _rv30_u16_be(dat[28], dat[29])
    turbidity_data = _rv30_u16_be(dat[30], dat[31])
    rv50_hot_start_adc = _rv30_u16_be(dat[32], dat[33])
    rv50_hot_end_adc = _rv30_u16_be(dat[34], dat[35])
    rv50_hot_diff_adc = _rv30_u16_be(dat[36], dat[37])
    if dev_ver == load_cfg.mcu_ver:
        ver_res = "OK"
    else:
        ver_res = "NG"
    return {
        "step": step,
        "charge": charge_value,
        "ir_l": ir_code_left,
        "ir_r": ir_code_right,
        "ir_n": ir_code_near,
        "clear_tank": clear_tank_install,
        "duty_tank": duty_tank_install,
        "dust": dust_bug_install,
        "clean_base": clean_base_install,
        "dev_ver": dev_ver,
        "base_config": base_config,
        "suction_10pa": dust_collection_suction,
        "clean_pump": clean_water_pump_current,
        "vacuum_pump": duty_water_pump_current,
        "base_level_up": rv50_base_level_up_adc,
        "base_level_down": rv50_base_level_down_adc,
        "em_valve": electromagnetic_three_way_current,
        "wash_pump": cleaner_pump_current,
        "turbidity": turbidity_data,
        "hot_start": rv50_hot_start_adc,
        "hot_end": rv50_hot_end_adc,
        "hot_diff": rv50_hot_diff_adc,
    }


def _rv50_registry_entry(field):
    for entry in RV50_FIELD_REGISTRY:
        if entry["field"] == field:
            return entry
    return None


def _rv50_range_enabled(lo, hi):
    return not (int(lo) == 0 and int(hi) == 0)


def rv50_field_enabled(field):
    entry = _rv50_registry_entry(field)
    if entry is None:
        return False
    kind = entry["kind"]
    if kind == "monitor":
        return rv50_field_enabled("hot_diff")
    if kind == "version":
        return bool((load_cfg.mcu_ver or "").strip())
    if kind == "string":
        expect = getattr(load_cfg, entry.get("expect_attr", ""), "")
        return bool(str(expect).strip())
    if kind == "expected":
        expect = getattr(load_cfg, entry.get("expect_attr", ""), 0)
        return bool(int(expect))
    if kind == "range":
        lo = getattr(load_cfg, entry["min_attr"], 0)
        hi = getattr(load_cfg, entry["max_attr"], 0)
        return _rv50_range_enabled(lo, hi)
    if kind == "range_charge":
        ch = (
            load_cfg.rv50_charge_Hmin, load_cfg.rv50_charge_Lmin,
            load_cfg.rv50_charge_Hmax, load_cfg.rv50_charge_Lmax,
        )
        return ch != (0, 0, 0, 0)
    if kind == "range_suction":
        slo, shi = _rv50_suction_threshold_10pa()
        return not (slo == 0 and shi == 0)
    return False


def rv50_field_active(step, field):
    entry = _rv50_registry_entry(field)
    if entry is None:
        return False
    st = int(step) if step is not None else 0
    if st < 1:
        return False
    return st >= int(entry.get("active_from_step", 1))


def rv50_step4_enabled_modules():
    return tuple(
        f for f in RV50_STEP4_MODULE_FIELDS
        if rv50_field_enabled(f)
    )


def rv50_build_item_result():
    items = []
    for entry in RV50_FIELD_REGISTRY:
        if entry["ui"] == "base_station_config" and not base_station_config_ui_enabled():
            continue
        if rv50_field_enabled(entry["field"]):
            ui = entry["ui"]
            items.append({ui: [RV50_UI_LABELS[ui], "", "white"]})
    return items


def rv50_proto_yaml_realtime_ok(p):
    if p is None or rv50_89_mes_done or rv50_realtime_ng:
        return True
    step = int(p.get("step", 0))
    if step == 4:
        return True
    for entry in RV50_FIELD_REGISTRY:
        field = entry["field"]
        if entry["kind"] in ("monitor",):
            continue
        if entry.get("step4_module"):
            continue
        if not rv50_field_enabled(field):
            continue
        if not rv50_field_active(step, field):
            continue
        ok = rv50_field_ok(p, field)
        if ok is False:
            return False
    return True


def rv50_step4_monitor_phase(p):
    return p is not None and int(p.get("step", 0)) == 4


def rv50_step4_substep_index(field):
    enabled = rv50_step4_enabled_modules()
    idx = 0
    for f, *_rest in RV50_STEP4_SUBSTEPS:
        if f not in enabled:
            continue
        if f == field:
            return idx
        idx += 1
    return -1


def rv50_step4_current_substep(p):
    for field, *_rest in RV50_STEP4_SUBSTEPS:
        if field not in rv50_step4_enabled_modules():
            continue
        if int(p.get(field, 0)) != 3:
            return field
    return None


def rv50_module_step4_ui(p, field):
    meta = next(x for x in RV50_STEP4_SUBSTEPS if x[0] == field)
    v = int(p.get(field, 0))
    if v == 0:
        return "untested", ""
    if v == 1:
        return "fail", meta[2]
    if v == 2:
        return "fail", meta[3]
    if v == 3:
        return "pass", str(v)
    return "fail", str(v)


def rv50_module_field_status(p, field):
    if p is None:
        return "untested"
    step = int(p.get("step", 0))
    if step < 4:
        return "untested"
    v = int(p.get(field, 0))
    if step == 4:
        if v == 0:
            return "untested"
        if v in (1, 2):
            return False
        if v == 3:
            return True
        return False
    return True if v == 3 else False


def rv50_step4_flow_complete():
    global rv50_max_step, rv50_last_p
    mods = rv50_step4_enabled_modules()
    if not mods:
        return True
    if rv50_max_step < 4:
        return True
    if rv50_last_p is None:
        return False
    return all(int(rv50_last_p.get(f, 0)) == 3 for f in mods)


def rv50_step4_notify(p):
    global rv50_last_step4_notify_key
    if not rv50_step4_monitor_phase(p):
        return
    if not rv50_step4_enabled_modules():
        return
    mf = MainFrame.main_frame
    if mf is None:
        return
    cur = rv50_step4_current_substep(p)
    if cur is None:
        notify_key = "led"
        second = RV50_STEP4_LED_HINT
    else:
        v = int(p.get(cur, 0))
        meta = next(x for x in RV50_STEP4_SUBSTEPS if x[0] == cur)
        if v == 1:
            second = meta[2]
        elif v == 2:
            second = meta[3]
        else:
            second = meta[4]
        notify_key = "{}:{}".format(cur, v)
    if notify_key == rv50_last_step4_notify_key:
        return
    rv50_last_step4_notify_key = notify_key
    mf.up_notification_ui(second=second, third=RV50_STEP4_ORDER_HINT, color=wx.RED)


def rv50_field_ok(p, field):
    if not rv50_field_enabled(field):
        return None
    if p is None:
        return False
    entry = _rv50_registry_entry(field)
    if entry is None:
        return None
    kind = entry["kind"]
    if kind in ("monitor",):
        return None
    if kind == "version":
        return ver_triplet_matches(p.get("dev_ver"), load_cfg.mcu_ver)
    if kind == "string":
        return config_triplet_matches(
            p.get("base_config"), load_cfg.base_station_config_expected)
    if kind == "expected":
        if entry.get("step4_module"):
            return None
        expect = int(getattr(load_cfg, entry.get("expect_attr", ""), 0))
        return int(p.get(field, -1)) == expect
    if kind == "range_charge":
        ch = (
            load_cfg.rv50_charge_Hmin, load_cfg.rv50_charge_Lmin,
            load_cfg.rv50_charge_Hmax, load_cfg.rv50_charge_Lmax,
        )
        lo = (ch[0] << 8) | (ch[1] & 0xFF)
        hi = (ch[2] << 8) | (ch[3] & 0xFF)
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["charge"] <= hi
    if kind == "range":
        lo = int(getattr(load_cfg, entry["min_attr"], 0))
        hi = int(getattr(load_cfg, entry["max_attr"], 0))
        if lo > hi:
            lo, hi = hi, lo
        val = p.get(field)
        if val is None:
            return False
        return lo <= int(val) <= hi
    if kind == "range_suction":
        slo, shi = _rv50_suction_threshold_10pa()
        val = p.get("suction_10pa")
        if val is None:
            return False
        return slo <= int(val) <= shi
    return None


def rv50_field_status(p, field):
    if p is None:
        return "untested"
    entry = _rv50_registry_entry(field)
    if entry is None:
        return "untested"
    if entry.get("step4_module"):
        return rv50_module_field_status(p, field)
    if entry["kind"] == "monitor":
        if not rv50_field_active(p.get("step"), field):
            return "untested"
        return None
    if not rv50_field_active(p.get("step"), field):
        return "untested"
    return rv50_field_ok(p, field)


def rv50_field_status_finalize(p, field):
    if p is None:
        return "untested"
    step = int(p.get("step", 0))
    entry = _rv50_registry_entry(field)
    if entry is None:
        return "untested"
    if step < 7:
        return rv50_field_status(p, field)
    if entry.get("step4_module"):
        return True if int(p.get(field, 0)) == 3 else False
    if entry["kind"] == "monitor":
        return None
    if not rv50_field_active(step, field):
        return "untested"
    return rv50_field_ok(p, field)


def rv50_proto_yaml_all_items_ok(p):
    if p is None:
        return False
    if int(p.get("step", 0)) < 7:
        return False
    for entry in RV50_FIELD_REGISTRY:
        field = entry["field"]
        if entry["kind"] in ("monitor",):
            continue
        if entry.get("step4_module"):
            continue
        if not rv50_field_enabled(field):
            continue
        if not rv50_field_active(7, field):
            continue
        ok = rv50_field_ok(p, field)
        if ok is False:
            return False
    if rv50_max_step >= 4:
        for f in rv50_step4_enabled_modules():
            if int(p.get(f, 0)) != 3:
                return False
    return True


def rv50_proto_yaml_finalize_ok(p):
    global rv50_max_step
    if rv50_max_step < 7:
        return False
    if p is None:
        return False
    if int(p.get("step", 0)) < 7:
        return False
    return rv50_proto_yaml_all_items_ok(p)


def rv50_proto_apply_test_ui_row(p, ui_name, field, val, finalize=False):
    entry = _rv50_registry_entry(field)
    if finalize:
        st = rv50_field_status_finalize(p, field)
    else:
        if rv50_step4_monitor_phase(p) and entry and entry.get("step4_module"):
            cur = rv50_step4_current_substep(p)
            enabled = rv50_step4_enabled_modules()
            cur_idx = len(enabled) if cur is None else rv50_step4_substep_index(cur)
            my_idx = rv50_step4_substep_index(field)
            if my_idx <= cur_idx or int(p.get(field, 0)) == 3:
                res, show_val = rv50_module_step4_ui(p, field)
            else:
                res, show_val = "untested", ""
            MainFrame.main_frame.up_test_ui(name=ui_name, result=res, value=show_val)
            return
        if entry and entry["kind"] == "monitor" and rv50_field_active(p.get("step"), field):
            MainFrame.main_frame.up_test_ui(name=ui_name, result="monitor", value=val)
            return
        st = rv50_field_status(p, field)
    if st == "untested":
        res, show_val = "untested", ""
    elif st is False:
        res, show_val = "fail", val
    elif st is True:
        res, show_val = "pass", val
    else:
        res, show_val = "monitor", val
    MainFrame.main_frame.up_test_ui(name=ui_name, result=res, value=show_val)


def _rv50_format_field_value(p, field):
    if field == "dev_ver":
        return p.get("dev_ver") or ""
    if field == "base_config":
        return p.get("base_config") or ""
    if field == "suction_10pa":
        return _rv30_fmt_suction_kpa(p.get("suction_10pa"))
    if field in ("ir_l", "ir_r", "ir_n"):
        return _rv30_fmt_ir_byte(p.get(field))
    return str(p.get(field, ""))


def _rv50_proto_ui_rows(p):
    rows = []
    for entry in RV50_FIELD_REGISTRY:
        if not rv50_field_enabled(entry["field"]):
            continue
        field = entry["field"]
        rows.append((entry["ui"], field, _rv50_format_field_value(p, field)))
    return rows


def rv50_proto_refresh_test_ui(p, finalize=False):
    if p is None or MainFrame.main_frame is None:
        return
    for ui_name, field, val in _rv50_proto_ui_rows(p):
        rv50_proto_apply_test_ui_row(p, ui_name, field, val, finalize=finalize)
    if not finalize and rv50_step4_monitor_phase(p):
        rv50_step4_notify(p)


def rv50_proto_refresh_test_ui_callafter(p):
    wx.CallAfter(rv50_proto_refresh_test_ui, p)


def rv50_proto_add_reports():
    for entry in RV50_FIELD_REGISTRY:
        if not rv50_field_enabled(entry["field"]):
            continue
        field = entry["field"]
        kind = entry["kind"]
        name = entry["mes"]
        if rv50_last_p is None:
            mes_run.add_report(name=name, result="NG", value="")
            continue
        if kind == "version":
            ok = rv50_field_ok(rv50_last_p, field)
            mes_run.add_report(
                name=name, result="OK" if ok else "NG", value=rv50_last_p.get("dev_ver") or "",
                val_min=load_cfg.mcu_ver, val_max=load_cfg.mcu_ver)
            continue
        if kind == "string":
            ok = rv50_field_ok(rv50_last_p, field)
            expect = str(getattr(load_cfg, entry.get("expect_attr", ""), "")).strip()
            mes_run.add_report(
                name=name, result="OK" if ok else "NG",
                value=rv50_last_p.get("base_config") or "",
                val_min=expect, val_max=expect)
            continue
        if kind == "expected":
            if entry.get("step4_module"):
                ok = True if int(rv50_last_p.get(field, 0)) == 3 else False
                val = str(rv50_last_p.get(field, ""))
                expect = str(int(getattr(load_cfg, entry.get("expect_attr", ""), 0)))
                mes_run.add_report(name=name, result="OK" if ok else "NG",
                                   value=val, val_min=expect, val_max=expect)
            else:
                ok = rv50_field_ok(rv50_last_p, field)
                expect = int(getattr(load_cfg, entry.get("expect_attr", ""), 0))
                val = rv50_last_p.get(field)
                mes_run.add_report(name=name, result="OK" if ok else "NG",
                                   value=_rv30_fmt_ir_byte(val) if field.startswith("ir_") else str(val),
                                   val_min=str(expect), val_max=str(expect))
            continue
        if kind == "range_suction":
            ok = rv50_field_ok(rv50_last_p, field)
            slo, shi = _rv50_suction_threshold_10pa()
            mes_run.add_report(
                name=name, result="OK" if ok else "NG",
                value=_rv30_fmt_suction_kpa(rv50_last_p.get("suction_10pa")),
                val_min=_rv30_fmt_suction_kpa(slo), val_max=_rv30_fmt_suction_kpa(shi))
            continue
        if kind == "range_charge":
            ok = rv50_field_ok(rv50_last_p, field)
            ch = (
                load_cfg.rv50_charge_Hmin, load_cfg.rv50_charge_Lmin,
                load_cfg.rv50_charge_Hmax, load_cfg.rv50_charge_Lmax,
            )
            lo = (ch[0] << 8) | (ch[1] & 0xFF)
            hi = (ch[2] << 8) | (ch[3] & 0xFF)
            if lo > hi:
                lo, hi = hi, lo
            mes_run.add_report(
                name=name, result="OK" if ok else "NG",
                value=str(rv50_last_p.get("charge", "")),
                val_min=str(lo), val_max=str(hi))
            continue
        if kind == "range":
            ok = rv50_field_ok(rv50_last_p, field)
            lo = int(getattr(load_cfg, entry["min_attr"], 0))
            hi = int(getattr(load_cfg, entry["max_attr"], 0))
            if lo > hi:
                lo, hi = hi, lo
            mes_run.add_report(
                name=name, result="OK" if ok else "NG",
                value=str(rv50_last_p.get(field, "")),
                val_min=str(lo), val_max=str(hi))
            continue
        if kind == "monitor":
            mes_run.add_report(name=name, result="", value=str(rv50_last_p.get(field, "")))


def rv50_proto_finalize_88(dev, dat):
    global test_end_time, rv50_session_state, rv50_last_p, rv50_89_mes_done, rv50_finalize_done
    if rv50_finalize_done:
        print("[RV50-017] 重复 0x88，忽略")
        return

    test_end_time = datetime.now()
    res_byte = dat[0] if len(dat) else 0xFF
    if res_byte == 0x04:
        if not rv50_89_mes_done:
            mes_run.add_report(name="基站通讯", result="NG", value="治具与基站通讯失败")
            mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
            rv50_89_mes_done = True
        else:
            mes_ret = False
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="治具与基站通讯失败", color=wx.RED)
        clear_sn_save_list()
        rv50_session_state = RV50_SESS_FINISHED
        rv50_finalize_done = True
        return
    if rv50_89_mes_done:
        rv50_session_state = RV50_SESS_FINISHED
        rv50_finalize_done = True
        clear_sn_save_list()
        return
    if res_byte != 0x03:
        mes_run.add_report(name="结束码", result="NG", value=hex(res_byte))
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        rv50_89_mes_done = True
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="测试结束 NG（结束码 {}）".format(hex(res_byte)), color=wx.RED)
        clear_sn_save_list()
        rv50_session_state = RV50_SESS_FINISHED
        rv50_finalize_done = True
        return
    p = rv50_last_p
    mes_ok = (
        p is not None
        and not rv50_realtime_ng
        and rv50_proto_yaml_finalize_ok(p)
        and rv50_step4_flow_complete()
    )
    rv50_proto_add_reports()
    if mes_ok:
        res_display_str = "测试完成(综合判定 PASS)"
        text_color = wx.GREEN
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
    else:
        res_display_str = "测试结束(综合判定 NG)"
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
    rv50_89_mes_done = True
    if p is not None:
        def _finalize_ui_refresh():
            for ui_name, field, val in _rv50_proto_ui_rows(p):
                entry = _rv50_registry_entry(field)
                if (entry and entry.get("step4_module")
                        and int(p.get("step", 0)) == 4 and not mes_ok):
                    res, show_val = rv50_module_step4_ui(p, field)
                    MainFrame.main_frame.up_test_ui(name=ui_name, result=res, value=show_val)
                    continue
                if mes_ok and entry and entry["kind"] == "monitor":
                    MainFrame.main_frame.up_test_ui(name=ui_name, result="pass", value=val)
                    continue
                rv50_proto_apply_test_ui_row(p, ui_name, field, val, finalize=True)
        wx.CallAfter(_finalize_ui_refresh)
    if mes_ret:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=res_display_str, color=text_color)
    rv50_session_state = RV50_SESS_FINISHED
    rv50_finalize_done = True
    clear_sn_save_list()


def RV50_finished_product_mode(dev, cmd, dat):
    global test_start_time, check_sn_enable, ver_res, dev_ver
    global rv50_session_state, rv50_last_step, rv50_max_step, rv50_last_p, rv50_last_step4_notify_key
    global rv50_89_mes_done, rv50_finalize_done, rv50_realtime_ng
    if len(dat) <= 0:
        print("[RV50-017] len=0 无有效数据")
        return
    if cmd == 0x66:
        if dat[0] == 0x00:
            fixture_all_reply_bursts_stop()
            test_start_time = datetime.now()
            mes_run.clear_report()
            tool.clear_queue(barcode_q)
            check_sn_enable = True
            rv50_last_step = -1
            rv50_max_step = 0
            rv50_last_step4_notify_key = ""
            rv50_last_p = None
            rv50_89_mes_done = False
            rv50_finalize_done = False
            rv50_realtime_ng = False
            rv50_session_state = RV50_SESS_WAIT_SN
            print("[RV50-017] 请扫码")
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
    elif cmd == 0x77:
        if rv50_session_state != RV50_SESS_RUNNING:
            return
        fixture_gate_burst_cancel_on_first_77()
        print("[RV50-017] 0x77 len=" + str(len(dat)))
        p = rv50_proto_parse_77_apply_globals(dat)
        wx.CallAfter(MainFrame.main_frame.up_ver_ui, dev_ver)
        if p is None:
            return
        rv50_last_p = p
        st = int(p["step"])
        if st > rv50_max_step:
            rv50_max_step = st
        if st != rv50_last_step:
            rv50_last_step = st
            if st == 4:
                rv50_last_step4_notify_key = ""
            else:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="治具步骤：" + str(st), color=wx.BLUE)
        rv50_proto_refresh_test_ui_callafter(p)
        if not rv50_proto_yaml_realtime_ok(p):
            rv50_proto_realtime_fail(dev, "yaml阈值:" + str(p))
            return
    elif cmd == 0x88:
        print("[RV50-017] 测试结束帧 dat[0]=" + str(dat[0] if dat else None))
        rv50_proto_finalize_88(dev, dat)
    elif cmd == 0x68:
        print("[RV50-017] 忽略 0x68 阈值上传 len=" + str(len(dat)))
    else:
        print("[RV50-017] 未处理命令 cmd=" + hex(cmd))


# ---------- #[OMINI-020-PROTO] Omini 基站全功能（device_type=020，帧 dev=0x14）----------
OMINI_UI_LABELS = {
    "mcu_ver": "MCU版本：",
    "base_station_config": "基站配置码：",
    "charge_value": "充电电流：",
    "omini_hot_start": "热风开始：",
    "ir_code_left": "左回充码：",
    "ir_code_right": "右回充码：",
    "ir_code_near": "近卫回充码：",
    "clear_tank_install": "清水箱在位：",
    "duty_tank_install": "污水箱在位：",
    "dust_bug_install": "尘袋：",
    "clean_base_install": "清洁底座在位：",
    "dust_collection_suction": "集尘吸力(kPa)：",
    "clean_water_pump_current": "清水泵电流：",
    "duty_water_pump_current": "真空泵电流：",
    "omini_base_level_up": "底座液位(抬起)：",
    "omini_base_level_down": "底座液位(按下)：",
    "electromagnetic_three_way_current": "电磁三通电流：",
    "omini_hot_end": "热风结束：",
    "cleaner_pump_current": "清洁泵电流：",
    "turbidity_data": "浊度：",
    "omini_hot_diff": "热风差值：",
}

OMINI_FIELD_REGISTRY = [
    {"field": "dev_ver", "kind": "version", "ui": "mcu_ver", "mes": "MCU版本", "active_from_step": 4},
    {"field": "base_config", "kind": "string", "ui": "base_station_config", "mes": "基站配置码",
     "expect_attr": "base_station_config_expected", "active_from_step": 4},
    {"field": "charge", "kind": "range", "ui": "charge_value", "mes": "充电电流",
     "min_attr": "omini_charge_min", "max_attr": "omini_charge_max", "active_from_step": 1},
    {"field": "ir_l", "kind": "expected", "ui": "ir_code_left", "mes": "左回充码",
     "expect_attr": "omini_ir_l", "active_from_step": 3},
    {"field": "ir_r", "kind": "expected", "ui": "ir_code_right", "mes": "右回充码",
     "expect_attr": "omini_ir_r", "active_from_step": 3},
    {"field": "ir_n", "kind": "expected", "ui": "ir_code_near", "mes": "近卫回充码",
     "expect_attr": "omini_ir_n", "active_from_step": 3},
    {"field": "clear_tank", "kind": "expected", "ui": "clear_tank_install", "mes": "清水箱在位",
     "expect_attr": "omini_clear_tank_expected", "active_from_step": 4, "step4_module": True},
    {"field": "duty_tank", "kind": "expected", "ui": "duty_tank_install", "mes": "污水箱在位",
     "expect_attr": "omini_duty_tank_expected", "active_from_step": 4, "step4_module": True},
    {"field": "dust", "kind": "expected", "ui": "dust_bug_install", "mes": "尘袋",
     "expect_attr": "omini_dust_expected", "active_from_step": 4, "step4_module": True},
    {"field": "clean_base", "kind": "expected", "ui": "clean_base_install", "mes": "清洁底座在位",
     "expect_attr": "omini_clean_base_expected", "active_from_step": 4, "step4_module": True},
    {"field": "suction_10pa", "kind": "range_suction", "ui": "dust_collection_suction", "mes": "集尘吸力kPa",
     "active_from_step": 5},
    {"field": "clean_pump", "kind": "range", "ui": "clean_water_pump_current", "mes": "清水泵电流",
     "min_attr": "omini_clean_pump_min", "max_attr": "omini_clean_pump_max", "active_from_step": 6},
    {"field": "vacuum_pump", "kind": "range", "ui": "duty_water_pump_current", "mes": "真空泵电流",
     "min_attr": "omini_vacuum_pump_min", "max_attr": "omini_vacuum_pump_max", "active_from_step": 6},
    {"field": "base_level_up", "kind": "range", "ui": "omini_base_level_up", "mes": "底座液位(抬起)",
     "min_attr": "omini_base_level_up_min", "max_attr": "omini_base_level_up_max", "active_from_step": 6},
    {"field": "base_level_down", "kind": "range", "ui": "omini_base_level_down", "mes": "底座液位(按下)",
     "min_attr": "omini_base_level_down_min", "max_attr": "omini_base_level_down_max", "active_from_step": 6},
    {"field": "em_valve", "kind": "range", "ui": "electromagnetic_three_way_current", "mes": "电磁三通电流",
     "min_attr": "omini_em_valve_min", "max_attr": "omini_em_valve_max", "active_from_step": 6},
    {"field": "wash_pump", "kind": "range", "ui": "cleaner_pump_current", "mes": "清洁泵电流",
     "min_attr": "omini_wash_pump_min", "max_attr": "omini_wash_pump_max", "active_from_step": 7},
    {"field": "turbidity", "kind": "range", "ui": "turbidity_data", "mes": "浊度数据",
     "min_attr": "omini_turbidity_min", "max_attr": "omini_turbidity_max", "active_from_step": 7},
    {"field": "hot_diff", "kind": "range", "ui": "omini_hot_diff", "mes": "热风差值",
     "min_attr": "omini_hot_diff_min", "max_attr": "omini_hot_diff_max", "active_from_step": 7},
    {"field": "hot_start", "kind": "monitor", "ui": "omini_hot_start", "mes": "热风开始", "active_from_step": 7},
    {"field": "hot_end", "kind": "monitor", "ui": "omini_hot_end", "mes": "热风结束", "active_from_step": 7},
]


def _omini_range_enabled(lo, hi):
    return not (int(lo) == 0 and int(hi) == 0)


def _omini_registry_entry(field):
    for entry in OMINI_FIELD_REGISTRY:
        if entry["field"] == field:
            return entry
    return None


def omini_field_enabled(field):
    entry = _omini_registry_entry(field)
    if entry is None:
        return False
    kind = entry["kind"]
    if kind == "monitor":
        return omini_field_enabled("hot_diff")
    if kind == "version":
        return bool((load_cfg.mcu_ver or "").strip())
    if kind == "string":
        expect = getattr(load_cfg, entry.get("expect_attr", ""), "")
        return bool(str(expect).strip())
    if kind == "expected":
        expect = getattr(load_cfg, entry.get("expect_attr", ""), 0)
        return bool(int(expect))
    if kind == "range":
        lo = getattr(load_cfg, entry["min_attr"], 0)
        hi = getattr(load_cfg, entry["max_attr"], 0)
        return _omini_range_enabled(lo, hi)
    if kind == "range_suction":
        slo, shi = _omini_suction_threshold_10pa()
        return not (slo == 0 and shi == 0)
    return False


def omini_field_active(step, field):
    entry = _omini_registry_entry(field)
    if entry is None:
        return False
    st = int(step) if step is not None else 0
    if st < 1:
        return False
    return st >= int(entry.get("active_from_step", 1))


def omini_step4_enabled_modules():
    return tuple(
        f for f in OMINI_STEP4_MODULE_FIELDS
        if omini_field_enabled(f)
    )


def omini_build_item_result():
    items = []
    for entry in OMINI_FIELD_REGISTRY:
        if entry["ui"] == "base_station_config" and not base_station_config_ui_enabled():
            continue
        if omini_field_enabled(entry["field"]):
            ui = entry["ui"]
            items.append({ui: [OMINI_UI_LABELS[ui], "", "white"]})
    return items


def omini_proto_reset_to_idle():
    global omini_session_state, omini_last_step, omini_max_step, omini_last_p
    global omini_last_step4_notify_key, omini_89_mes_done, omini_finalize_done, omini_realtime_ng
    omini_session_state = OMINI_SESS_IDLE
    omini_last_step = -1
    omini_max_step = 0
    omini_last_p = None
    omini_last_step4_notify_key = ""
    omini_89_mes_done = False
    omini_finalize_done = False
    omini_realtime_ng = False


def omini_proto_mes_ng_once(notify_second="MES已报NG"):
    global test_end_time, omini_89_mes_done, omini_session_state
    if omini_89_mes_done:
        return
    omini_89_mes_done = True
    test_end_time = datetime.now()
    omini_session_state = OMINI_SESS_ABORTED
    mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=notify_second, color=wx.RED)


def omini_proto_realtime_fail(dev, reason):
    global omini_realtime_ng
    if omini_89_mes_done:
        return
    omini_realtime_ng = True
    ser_send_data(dev, 0x89, data=[0x03])
    mes_run.add_report(name="Omini实时判据", result="NG", value=str(reason))
    omini_proto_mes_ng_once(notify_second="实时判据失败：" + str(reason))


def omini_proto_parse_77_apply_globals(dat):
    global charge_value, dev_ver, ver_res
    global ir_code_left, ir_code_right, ir_code_near
    global clear_tank_install, duty_tank_install, dust_bug_install, clean_base_install
    global dust_collection_suction, clean_water_pump_current, duty_water_pump_current
    global cleaner_pump_current, electromagnetic_three_way_current
    global turbidity_data
    global rv50_base_level_up_adc, rv50_base_level_down_adc
    global rv50_hot_start_adc, rv50_hot_end_adc, rv50_hot_diff_adc
    if len(dat) < OMINI_77_DATA_LEN:
        print("[OMINI-020] 0x77 数据区长度不足: got", len(dat), "need", OMINI_77_DATA_LEN)
        return None
    step = int(dat[0])
    charge_value = _rv30_u16_be(dat[1], dat[2])
    ir_code_left = int(dat[3])
    ir_code_right = int(dat[4])
    ir_code_near = int(dat[5])
    clear_tank_install = int(dat[6])
    duty_tank_install = int(dat[7])
    dust_bug_install = int(dat[8])
    clean_base_install = int(dat[9])
    dev_ver = ".".join(format(int(dat[i]), "03d") for i in range(10, 13))
    base_config = rv50_fmt_config_3bytes(dat, 13)
    dust_collection_suction = _rv30_u16_be(dat[16], dat[17])
    clean_water_pump_current = _rv30_u16_be(dat[18], dat[19])
    duty_water_pump_current = _rv30_u16_be(dat[20], dat[21])
    rv50_base_level_up_adc = _rv30_u16_be(dat[22], dat[23])
    rv50_base_level_down_adc = _rv30_u16_be(dat[24], dat[25])
    electromagnetic_three_way_current = _rv30_u16_be(dat[26], dat[27])
    cleaner_pump_current = _rv30_u16_be(dat[28], dat[29])
    turbidity_data = _rv30_u16_be(dat[30], dat[31])
    rv50_hot_start_adc = _rv30_u16_be(dat[32], dat[33])
    rv50_hot_end_adc = _rv30_u16_be(dat[34], dat[35])
    rv50_hot_diff_adc = _rv30_u16_be(dat[36], dat[37])
    if dev_ver == load_cfg.mcu_ver:
        ver_res = "OK"
    else:
        ver_res = "NG"
    return {
        "step": step,
        "charge": charge_value,
        "ir_l": ir_code_left,
        "ir_r": ir_code_right,
        "ir_n": ir_code_near,
        "clear_tank": clear_tank_install,
        "duty_tank": duty_tank_install,
        "dust": dust_bug_install,
        "clean_base": clean_base_install,
        "dev_ver": dev_ver,
        "base_config": base_config,
        "suction_10pa": dust_collection_suction,
        "clean_pump": clean_water_pump_current,
        "vacuum_pump": duty_water_pump_current,
        "base_level_up": rv50_base_level_up_adc,
        "base_level_down": rv50_base_level_down_adc,
        "em_valve": electromagnetic_three_way_current,
        "wash_pump": cleaner_pump_current,
        "turbidity": turbidity_data,
        "hot_start": rv50_hot_start_adc,
        "hot_end": rv50_hot_end_adc,
        "hot_diff": rv50_hot_diff_adc,
    }


def omini_field_ok(p, field):
    if not omini_field_enabled(field):
        return None
    if p is None:
        return False
    entry = _omini_registry_entry(field)
    if entry is None:
        return None
    kind = entry["kind"]
    if kind in ("monitor",):
        return None
    if kind == "version":
        return ver_triplet_matches(p.get("dev_ver"), load_cfg.mcu_ver)
    if kind == "string":
        return config_triplet_matches(
            p.get("base_config"), load_cfg.base_station_config_expected)
    if kind == "expected":
        if entry.get("step4_module"):
            return None
        expect = int(getattr(load_cfg, entry.get("expect_attr", ""), 0))
        return int(p.get(field, -1)) == expect
    if kind == "range":
        lo = int(getattr(load_cfg, entry["min_attr"], 0))
        hi = int(getattr(load_cfg, entry["max_attr"], 0))
        if lo > hi:
            lo, hi = hi, lo
        val = p.get(field)
        if val is None:
            return False
        return lo <= int(val) <= hi
    if kind == "range_suction":
        slo, shi = _omini_suction_threshold_10pa()
        val = p.get("suction_10pa")
        if val is None:
            return False
        return slo <= int(val) <= shi
    return None


def omini_step4_monitor_phase(p):
    return p is not None and int(p.get("step", 0)) == 4


def omini_step4_substep_index(field):
    enabled = omini_step4_enabled_modules()
    idx = 0
    for f, *_rest in OMINI_STEP4_SUBSTEPS:
        if f not in enabled:
            continue
        if f == field:
            return idx
        idx += 1
    return -1


def omini_step4_current_substep(p):
    for field, *_rest in OMINI_STEP4_SUBSTEPS:
        if field not in omini_step4_enabled_modules():
            continue
        if int(p.get(field, 0)) != 3:
            return field
    return None


def omini_module_step4_ui(p, field):
    meta = next(x for x in OMINI_STEP4_SUBSTEPS if x[0] == field)
    v = int(p.get(field, 0))
    if v == 0:
        return "untested", ""
    if v == 1:
        return "fail", meta[2]
    if v == 2:
        return "fail", meta[3]
    if v == 3:
        return "pass", str(v)
    return "fail", str(v)


def omini_module_field_status(p, field):
    if p is None:
        return "untested"
    step = int(p.get("step", 0))
    if step < 4:
        return "untested"
    v = int(p.get(field, 0))
    if step == 4:
        if v == 0:
            return "untested"
        if v in (1, 2):
            return False
        if v == 3:
            return True
        return False
    return True if v == 3 else False


def omini_step4_flow_complete():
    global omini_max_step, omini_last_p
    mods = omini_step4_enabled_modules()
    if not mods:
        return True
    if omini_max_step < 4:
        return True
    if omini_last_p is None:
        return False
    return all(int(omini_last_p.get(f, 0)) == 3 for f in mods)


def omini_step4_notify(p):
    global omini_last_step4_notify_key
    if not omini_step4_monitor_phase(p):
        return
    if not omini_step4_enabled_modules():
        return
    mf = MainFrame.main_frame
    if mf is None:
        return
    cur = omini_step4_current_substep(p)
    if cur is None:
        notify_key = "led"
        second = OMINI_STEP4_LED_HINT
    else:
        v = int(p.get(cur, 0))
        meta = next(x for x in OMINI_STEP4_SUBSTEPS if x[0] == cur)
        if v == 1:
            second = meta[2]
        elif v == 2:
            second = meta[3]
        else:
            second = meta[4]
        notify_key = "{}:{}".format(cur, v)
    if notify_key == omini_last_step4_notify_key:
        return
    omini_last_step4_notify_key = notify_key
    mf.up_notification_ui(second=second, third=OMINI_STEP4_ORDER_HINT, color=wx.RED)


def omini_field_status(p, field):
    if p is None:
        return "untested"
    entry = _omini_registry_entry(field)
    if entry is None:
        return "untested"
    if entry.get("step4_module"):
        return omini_module_field_status(p, field)
    if entry["kind"] == "monitor":
        if not omini_field_active(p.get("step"), field):
            return "untested"
        return None
    if not omini_field_active(p.get("step"), field):
        return "untested"
    return omini_field_ok(p, field)


def omini_field_status_finalize(p, field):
    if p is None:
        return "untested"
    step = int(p.get("step", 0))
    entry = _omini_registry_entry(field)
    if entry is None:
        return "untested"
    if step < 7:
        return omini_field_status(p, field)
    if entry.get("step4_module"):
        return True if int(p.get(field, 0)) == 3 else False
    if entry["kind"] == "monitor":
        return None
    if not omini_field_active(step, field):
        return "untested"
    return omini_field_ok(p, field)


def omini_proto_yaml_realtime_ok(p):
    if p is None or omini_89_mes_done or omini_realtime_ng:
        return True
    step = int(p.get("step", 0))
    if step == 4:
        return True
    for entry in OMINI_FIELD_REGISTRY:
        field = entry["field"]
        if entry["kind"] in ("monitor",):
            continue
        if entry.get("step4_module"):
            continue
        if not omini_field_enabled(field):
            continue
        if not omini_field_active(step, field):
            continue
        ok = omini_field_ok(p, field)
        if ok is False:
            return False
    return True


def omini_proto_yaml_all_items_ok(p):
    if p is None:
        return False
    if int(p.get("step", 0)) < 7:
        return False
    for entry in OMINI_FIELD_REGISTRY:
        field = entry["field"]
        if entry["kind"] in ("monitor",):
            continue
        if entry.get("step4_module"):
            continue
        if not omini_field_enabled(field):
            continue
        if not omini_field_active(7, field):
            continue
        ok = omini_field_ok(p, field)
        if ok is False:
            return False
    if omini_max_step >= 4:
        for f in omini_step4_enabled_modules():
            if int(p.get(f, 0)) != 3:
                return False
    return True


def omini_proto_yaml_finalize_ok(p):
    global omini_max_step
    if omini_max_step < 7:
        return False
    if p is None:
        return False
    if int(p.get("step", 0)) < 7:
        return False
    return omini_proto_yaml_all_items_ok(p)


def _omini_format_field_value(p, field):
    if field == "dev_ver":
        return p.get("dev_ver") or ""
    if field == "base_config":
        return p.get("base_config") or ""
    if field == "suction_10pa":
        return _rv30_fmt_suction_kpa(p.get("suction_10pa"))
    if field in ("ir_l", "ir_r", "ir_n"):
        return _rv30_fmt_ir_byte(p.get(field))
    return str(p.get(field, ""))


def _omini_proto_ui_rows(p):
    rows = []
    for entry in OMINI_FIELD_REGISTRY:
        if not omini_field_enabled(entry["field"]):
            continue
        field = entry["field"]
        rows.append((entry["ui"], field, _omini_format_field_value(p, field)))
    return rows


def omini_proto_apply_test_ui_row(p, ui_name, field, val, finalize=False):
    entry = _omini_registry_entry(field)
    if finalize:
        st = omini_field_status_finalize(p, field)
    else:
        if omini_step4_monitor_phase(p) and entry and entry.get("step4_module"):
            cur = omini_step4_current_substep(p)
            enabled = omini_step4_enabled_modules()
            cur_idx = len(enabled) if cur is None else omini_step4_substep_index(cur)
            my_idx = omini_step4_substep_index(field)
            if my_idx <= cur_idx or int(p.get(field, 0)) == 3:
                res, show_val = omini_module_step4_ui(p, field)
            else:
                res, show_val = "untested", ""
            MainFrame.main_frame.up_test_ui(name=ui_name, result=res, value=show_val)
            return
        if entry and entry["kind"] == "monitor" and omini_field_active(p.get("step"), field):
            MainFrame.main_frame.up_test_ui(name=ui_name, result="monitor", value=val)
            return
        st = omini_field_status(p, field)
    if st == "untested":
        res, show_val = "untested", ""
    elif st is False:
        res, show_val = "fail", val
    elif st is True:
        res, show_val = "pass", val
    else:
        res, show_val = "monitor", val
    MainFrame.main_frame.up_test_ui(name=ui_name, result=res, value=show_val)


def omini_proto_refresh_test_ui(p, finalize=False):
    if p is None or MainFrame.main_frame is None:
        return
    for ui_name, field, val in _omini_proto_ui_rows(p):
        omini_proto_apply_test_ui_row(p, ui_name, field, val, finalize=finalize)
    if not finalize and omini_step4_monitor_phase(p):
        omini_step4_notify(p)


def omini_proto_refresh_test_ui_callafter(p):
    wx.CallAfter(omini_proto_refresh_test_ui, p)


def omini_proto_add_reports():
    for entry in OMINI_FIELD_REGISTRY:
        if not omini_field_enabled(entry["field"]):
            continue
        field = entry["field"]
        kind = entry["kind"]
        name = entry["mes"]
        if omini_last_p is None:
            mes_run.add_report(name=name, result="NG", value="")
            continue
        if kind == "version":
            ok = omini_field_ok(omini_last_p, field)
            mes_run.add_report(
                name=name, result="OK" if ok else "NG", value=omini_last_p.get("dev_ver") or "",
                val_min=load_cfg.mcu_ver, val_max=load_cfg.mcu_ver)
            continue
        if kind == "string":
            ok = omini_field_ok(omini_last_p, field)
            expect = str(getattr(load_cfg, entry.get("expect_attr", ""), "")).strip()
            mes_run.add_report(
                name=name, result="OK" if ok else "NG",
                value=omini_last_p.get("base_config") or "",
                val_min=expect, val_max=expect)
            continue
        if kind == "expected":
            ok = omini_field_ok(omini_last_p, field) if not entry.get("step4_module") else (
                True if int(omini_last_p.get(field, 0)) == 3 else False)
            if entry.get("step4_module"):
                ok = True if int(omini_last_p.get(field, 0)) == 3 else False
                val = str(omini_last_p.get(field, ""))
                expect = str(int(getattr(load_cfg, entry.get("expect_attr", ""), 0)))
                mes_run.add_report(name=name, result="OK" if ok else "NG",
                                   value=val, val_min=expect, val_max=expect)
            else:
                expect = int(getattr(load_cfg, entry.get("expect_attr", ""), 0))
                val = omini_last_p.get(field)
                mes_run.add_report(name=name, result="OK" if ok else "NG",
                                   value=_rv30_fmt_ir_byte(val) if field.startswith("ir_") else str(val),
                                   val_min=str(expect), val_max=str(expect))
            continue
        if kind == "range_suction":
            ok = omini_field_ok(omini_last_p, field)
            slo, shi = _omini_suction_threshold_10pa()
            mes_run.add_report(
                name=name, result="OK" if ok else "NG",
                value=_rv30_fmt_suction_kpa(omini_last_p.get("suction_10pa")),
                val_min=_rv30_fmt_suction_kpa(slo), val_max=_rv30_fmt_suction_kpa(shi))
            continue
        if kind == "range":
            ok = omini_field_ok(omini_last_p, field)
            lo = int(getattr(load_cfg, entry["min_attr"], 0))
            hi = int(getattr(load_cfg, entry["max_attr"], 0))
            if lo > hi:
                lo, hi = hi, lo
            mes_run.add_report(
                name=name, result="OK" if ok else "NG",
                value=str(omini_last_p.get(field, "")),
                val_min=str(lo), val_max=str(hi))
            continue
        if kind == "monitor":
            mes_run.add_report(name=name, result="", value=str(omini_last_p.get(field, "")))


def omini_proto_finalize_88(dev, dat):
    global test_end_time, omini_session_state, omini_last_p, omini_89_mes_done, omini_finalize_done
    if omini_finalize_done:
        print("[OMINI-020] 重复 0x88，忽略")
        return

    test_end_time = datetime.now()
    res_byte = dat[0] if len(dat) else 0xFF
    if res_byte == 0x04:
        if not omini_89_mes_done:
            mes_run.add_report(name="基站通讯", result="NG", value="治具与基站通讯失败")
            mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
            omini_89_mes_done = True
        else:
            mes_ret = False
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="治具与基站通讯失败", color=wx.RED)
        clear_sn_save_list()
        omini_session_state = OMINI_SESS_FINISHED
        omini_finalize_done = True
        return
    if omini_89_mes_done:
        omini_session_state = OMINI_SESS_FINISHED
        omini_finalize_done = True
        clear_sn_save_list()
        return
    if res_byte != 0x03:
        mes_run.add_report(name="结束码", result="NG", value=hex(res_byte))
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        omini_89_mes_done = True
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="测试结束 NG（结束码 {}）".format(hex(res_byte)), color=wx.RED)
        clear_sn_save_list()
        omini_session_state = OMINI_SESS_FINISHED
        omini_finalize_done = True
        return
    p = omini_last_p
    mes_ok = (
        p is not None
        and not omini_realtime_ng
        and omini_proto_yaml_finalize_ok(p)
        and omini_step4_flow_complete()
    )
    omini_proto_add_reports()
    if mes_ok:
        res_display_str = "测试完成(综合判定 PASS)"
        text_color = wx.GREEN
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
    else:
        res_display_str = "测试结束(综合判定 NG)"
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
    omini_89_mes_done = True
    if p is not None:
        def _finalize_ui_refresh():
            for ui_name, field, val in _omini_proto_ui_rows(p):
                entry = _omini_registry_entry(field)
                if (entry and entry.get("step4_module")
                        and int(p.get("step", 0)) == 4 and not mes_ok):
                    res, show_val = omini_module_step4_ui(p, field)
                    MainFrame.main_frame.up_test_ui(name=ui_name, result=res, value=show_val)
                    continue
                if mes_ok and entry and entry["kind"] == "monitor":
                    MainFrame.main_frame.up_test_ui(name=ui_name, result="pass", value=val)
                    continue
                omini_proto_apply_test_ui_row(p, ui_name, field, val, finalize=True)
        wx.CallAfter(_finalize_ui_refresh)
    if mes_ret:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=res_display_str, color=text_color)
    omini_session_state = OMINI_SESS_FINISHED
    omini_finalize_done = True
    clear_sn_save_list()


def Omini_finished_product_mode(dev, cmd, dat):
    global test_start_time, check_sn_enable, ver_res, dev_ver
    global omini_session_state, omini_last_step, omini_max_step, omini_last_p
    global omini_last_step4_notify_key, omini_89_mes_done, omini_finalize_done, omini_realtime_ng
    if len(dat) <= 0:
        print("[OMINI-020] len=0 无有效数据")
        return
    if cmd == 0x66:
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()
            tool.clear_queue(barcode_q)
            check_sn_enable = True
            omini_last_step = -1
            omini_max_step = 0
            omini_last_step4_notify_key = ""
            omini_last_p = None
            omini_89_mes_done = False
            omini_finalize_done = False
            omini_realtime_ng = False
            omini_session_state = OMINI_SESS_WAIT_SN
            print("[OMINI-020] 请扫码")
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
    elif cmd == 0x77:
        if omini_session_state != OMINI_SESS_RUNNING:
            return
        print("[OMINI-020] 0x77 len=" + str(len(dat)))
        p = omini_proto_parse_77_apply_globals(dat)
        wx.CallAfter(MainFrame.main_frame.up_ver_ui, dev_ver)
        if p is None:
            return
        omini_last_p = p
        st = int(p["step"])
        if st > omini_max_step:
            omini_max_step = st
        if st != omini_last_step:
            omini_last_step = st
            if st == 4:
                omini_last_step4_notify_key = ""
            else:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             second="治具步骤：" + str(st), color=wx.BLUE)
        omini_proto_refresh_test_ui_callafter(p)
        if not omini_proto_yaml_realtime_ok(p):
            omini_proto_realtime_fail(dev, "yaml阈值:" + str(p))
            return
    elif cmd == 0x88:
        print("[OMINI-020] 测试结束帧 dat[0]=" + str(dat[0] if dat else None))
        omini_proto_finalize_88(dev, dat)
    elif cmd == 0x68:
        print("[OMINI-020] 忽略 0x68 阈值上传 len=" + str(len(dat)))
    else:
        print("[OMINI-020] 未处理命令 cmd=" + hex(cmd))


# ---------- #[RV50-018-PCBA-PROTO] RV50 基站 PCBA（device_type=018，帧 dev=0x12）----------
def rv50pcba_proto_reset_to_idle():
    global rv50pcba_session_state, rv50pcba_last_step, rv50pcba_max_step
    global rv50pcba_89_mes_done, rv50pcba_realtime_ng, rv50pcba_last_p
    rv50pcba_session_state = RV50PCBA_SESS_IDLE
    rv50pcba_last_step = -1
    rv50pcba_max_step = 0
    rv50pcba_89_mes_done = False
    rv50pcba_realtime_ng = False
    rv50pcba_last_p = None


def rv50pcba_proto_mes_ng_once(notify_second="MES已报NG"):
    global test_end_time, rv50pcba_89_mes_done, rv50pcba_session_state
    if rv50pcba_89_mes_done:
        return
    test_end_time = datetime.now()
    rv50pcba_89_mes_done = True
    rv50pcba_session_state = RV50PCBA_SESS_ABORTED
    mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=notify_second, color=wx.RED)


def rv50pcba_proto_realtime_fail(dev, reason):
    global rv50pcba_realtime_ng
    if rv50pcba_89_mes_done:
        return
    rv50pcba_realtime_ng = True
    ser_send_data(dev, 0x89, data=[0x02])
    mes_run.add_report(name="RV50PCBA实时判据", result="NG", value=str(reason))
    rv50pcba_proto_mes_ng_once(notify_second="实时判据失败：" + str(reason))


def rv50pcba_proto_parse_77_apply_globals(dat):
    global charge_value, dev_ver, ver_res
    global ir_code_left, ir_code_right, ir_code_near
    global clear_tank_install, duty_tank_install, dust_bug_install, clean_base_install
    global clean_water_pump_current, duty_water_pump_current
    global cleaner_pump_current, electromagnetic_three_way_current
    global turbidity_data
    global rv50_base_level_up_adc, rv50_base_level_down_adc
    global rv50_hot_start_adc, rv50_hot_end_adc, rv50_hot_diff_adc
    global rv50pcba_blower_freq
    if len(dat) < RV50PCBA_77_DATA_LEN:
        print("[RV50-018-PCBA] 0x77 数据区长度不足: got", len(dat), "need", RV50PCBA_77_DATA_LEN)
        return None
    step = int(dat[0])
    ir_code_left = int(dat[1])
    ir_code_right = int(dat[2])
    ir_code_near = int(dat[3])
    clear_tank_install = int(dat[4])
    duty_tank_install = int(dat[5])
    dust_bug_install = int(dat[6])
    clean_base_install = int(dat[7])
    dev_ver = ".".join(format(int(dat[i]), "03d") for i in range(8, 11))
    clean_water_pump_current = _rv30_u16_be(dat[14], dat[15])
    duty_water_pump_current = _rv30_u16_be(dat[16], dat[17])
    rv50_base_level_up_adc = _rv30_u16_be(dat[18], dat[19])
    rv50_base_level_down_adc = _rv30_u16_be(dat[20], dat[21])
    electromagnetic_three_way_current = _rv30_u16_be(dat[22], dat[23])
    cleaner_pump_current = _rv30_u16_be(dat[24], dat[25])
    turbidity_data = _rv30_u16_be(dat[26], dat[27])
    rv50_hot_start_adc = _rv30_u16_be(dat[28], dat[29])
    rv50_hot_end_adc = _rv30_u16_be(dat[30], dat[31])
    rv50_hot_diff_adc = _rv30_u16_be(dat[32], dat[33])
    charge_value = _rv30_u16_be(dat[34], dat[35])
    rv50pcba_blower_freq = _rv30_u16_be(dat[36], dat[37])
    if dev_ver == load_cfg.mcu_ver:
        ver_res = "OK"
    else:
        ver_res = "NG"
    return {
        "step": step,
        "ir_l": ir_code_left,
        "ir_r": ir_code_right,
        "ir_n": ir_code_near,
        "clear_tank": clear_tank_install,
        "duty_tank": duty_tank_install,
        "dust": dust_bug_install,
        "clean_base": clean_base_install,
        "dev_ver": dev_ver,
        "clean_pump": clean_water_pump_current,
        "vacuum_pump": duty_water_pump_current,
        "base_level_up": rv50_base_level_up_adc,
        "base_level_down": rv50_base_level_down_adc,
        "em_valve": electromagnetic_three_way_current,
        "wash_pump": cleaner_pump_current,
        "turbidity": turbidity_data,
        "hot_start": rv50_hot_start_adc,
        "hot_end": rv50_hot_end_adc,
        "hot_diff": rv50_hot_diff_adc,
        "charge": charge_value,
        "blower_freq": rv50pcba_blower_freq,
    }


def rv50pcba_field_active(step, field):
    st = int(step) if step is not None else 0
    if st < 2:
        return False
    if field in ("ir_l", "ir_r", "ir_n"):
        return st >= 2
    if field in ("clear_tank", "duty_tank", "dust", "clean_base", "dev_ver"):
        return st >= 3
    if field in ("clean_pump", "vacuum_pump", "base_level_up", "base_level_down", "em_valve"):
        return st >= 4
    if field in ("wash_pump", "turbidity", "hot_diff", "charge", "blower_freq"):
        return st >= 5
    if field in ("hot_start", "hot_end"):
        return st >= 5
    return False


def rv50pcba_field_ok(p, field):
    if p is None:
        return None
    if field == "dev_ver":
        expect_ver = (load_cfg.mcu_ver or "").strip()
        if not expect_ver:
            return None
        return p.get("dev_ver") == expect_ver
    if field == "charge":
        if load_cfg.rv50pcba_charge_min == 0 and load_cfg.rv50pcba_charge_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_charge_min, load_cfg.rv50pcba_charge_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["charge"] <= hi
    if field == "ir_l":
        if not load_cfg.rv50pcba_ir_l:
            return None
        return p["ir_l"] == load_cfg.rv50pcba_ir_l
    if field == "ir_r":
        if not load_cfg.rv50pcba_ir_r:
            return None
        return p["ir_r"] == load_cfg.rv50pcba_ir_r
    if field == "ir_n":
        if not load_cfg.rv50pcba_ir_n:
            return None
        return p["ir_n"] == load_cfg.rv50pcba_ir_n
    if field == "clear_tank":
        if not load_cfg.rv50pcba_clear_tank_expected:
            return None
        return p["clear_tank"] == load_cfg.rv50pcba_clear_tank_expected
    if field == "duty_tank":
        if not load_cfg.rv50pcba_duty_tank_expected:
            return None
        return p["duty_tank"] == load_cfg.rv50pcba_duty_tank_expected
    if field == "dust":
        if not load_cfg.rv50pcba_dust_expected:
            return None
        return p["dust"] == load_cfg.rv50pcba_dust_expected
    if field == "clean_base":
        if not load_cfg.rv50pcba_clean_base_expected:
            return None
        return p["clean_base"] == load_cfg.rv50pcba_clean_base_expected
    if field == "clean_pump":
        if load_cfg.rv50pcba_clean_pump_min == 0 and load_cfg.rv50pcba_clean_pump_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_clean_pump_min, load_cfg.rv50pcba_clean_pump_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["clean_pump"] <= hi
    if field == "vacuum_pump":
        if load_cfg.rv50pcba_vacuum_pump_min == 0 and load_cfg.rv50pcba_vacuum_pump_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_vacuum_pump_min, load_cfg.rv50pcba_vacuum_pump_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["vacuum_pump"] <= hi
    if field == "base_level_up":
        if load_cfg.rv50pcba_base_level_up_min == 0 and load_cfg.rv50pcba_base_level_up_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_base_level_up_min, load_cfg.rv50pcba_base_level_up_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["base_level_up"] <= hi
    if field == "base_level_down":
        if load_cfg.rv50pcba_base_level_down_min == 0 and load_cfg.rv50pcba_base_level_down_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_base_level_down_min, load_cfg.rv50pcba_base_level_down_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["base_level_down"] <= hi
    if field == "em_valve":
        if load_cfg.rv50pcba_em_valve_min == 0 and load_cfg.rv50pcba_em_valve_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_em_valve_min, load_cfg.rv50pcba_em_valve_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["em_valve"] <= hi
    if field == "wash_pump":
        if load_cfg.rv50pcba_wash_pump_min == 0 and load_cfg.rv50pcba_wash_pump_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_wash_pump_min, load_cfg.rv50pcba_wash_pump_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["wash_pump"] <= hi
    if field == "turbidity":
        if load_cfg.rv50pcba_turbidity_min == 0 and load_cfg.rv50pcba_turbidity_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_turbidity_min, load_cfg.rv50pcba_turbidity_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["turbidity"] <= hi
    if field == "hot_diff":
        if load_cfg.rv50pcba_hot_diff_min == 0 and load_cfg.rv50pcba_hot_diff_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_hot_diff_min, load_cfg.rv50pcba_hot_diff_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["hot_diff"] <= hi
    if field == "blower_freq":
        if load_cfg.rv50pcba_blower_freq_min == 0 and load_cfg.rv50pcba_blower_freq_max == 0:
            return None
        lo, hi = load_cfg.rv50pcba_blower_freq_min, load_cfg.rv50pcba_blower_freq_max
        if lo > hi:
            lo, hi = hi, lo
        return lo <= p["blower_freq"] <= hi
    if field in ("hot_start", "hot_end"):
        return None
    return None


def rv50pcba_field_status(p, field):
    if p is None:
        return "untested"
    if field in ("hot_start", "hot_end"):
        if not rv50pcba_field_active(p.get("step"), field):
            return "untested"
        return None
    if not rv50pcba_field_active(p.get("step"), field):
        return "untested"
    return rv50pcba_field_ok(p, field)


def rv50pcba_field_status_finalize(p, field):
    if p is None:
        return "untested"
    step = int(p.get("step", 0))
    if step < 5:
        return rv50pcba_field_status(p, field)
    if field in ("hot_start", "hot_end"):
        return None
    if not rv50pcba_field_active(step, field):
        return "untested"
    return rv50pcba_field_ok(p, field)


def rv50pcba_proto_yaml_realtime_ok(p):
    if p is None or rv50pcba_89_mes_done or rv50pcba_realtime_ng:
        return True
    step = int(p.get("step", 0))
    for field in RV50PCBA_REALTIME_FIELDS:
        if not rv50pcba_field_active(step, field):
            continue
        ok = rv50pcba_field_ok(p, field)
        if ok is False:
            return False
    return True


def rv50pcba_proto_yaml_all_items_ok(p):
    if p is None:
        return False
    if int(p.get("step", 0)) < 5:
        return False
    for field in RV50PCBA_FINALIZE_FIELDS:
        if not rv50pcba_field_active(5, field):
            continue
        ok = rv50pcba_field_ok(p, field)
        if ok is False:
            return False
    return True


def rv50pcba_proto_yaml_finalize_ok(p):
    global rv50pcba_max_step
    if rv50pcba_max_step < 5:
        return False
    if p is None:
        return False
    if int(p.get("step", 0)) < 5:
        return False
    return rv50pcba_proto_yaml_all_items_ok(p)


def rv50pcba_proto_apply_test_ui_row(p, ui_name, field, val, finalize=False):
    if finalize:
        st = rv50pcba_field_status_finalize(p, field)
    else:
        if field in ("hot_start", "hot_end") and rv50pcba_field_active(p.get("step"), field):
            MainFrame.main_frame.up_test_ui(name=ui_name, result="monitor", value=val)
            return
        st = rv50pcba_field_status(p, field)
    if st == "untested":
        res, show_val = "untested", ""
    elif st is False:
        res, show_val = "fail", val
    elif st is True:
        res, show_val = "pass", val
    else:
        res, show_val = "monitor", val
    MainFrame.main_frame.up_test_ui(name=ui_name, result=res, value=show_val)


def _rv50pcba_proto_ui_rows(p):
    return [
        ("mcu_ver", "dev_ver", p["dev_ver"]),
        ("ir_code_left", "ir_l", _rv30_fmt_ir_byte(p["ir_l"])),
        ("ir_code_right", "ir_r", _rv30_fmt_ir_byte(p["ir_r"])),
        ("ir_code_near", "ir_n", _rv30_fmt_ir_byte(p["ir_n"])),
        ("clear_tank_install", "clear_tank", str(p["clear_tank"])),
        ("duty_tank_install", "duty_tank", str(p["duty_tank"])),
        ("dust_bug_install", "dust", str(p["dust"])),
        ("clean_base_install", "clean_base", str(p["clean_base"])),
        ("clean_water_pump_current", "clean_pump", str(p["clean_pump"])),
        ("duty_water_pump_current", "vacuum_pump", str(p["vacuum_pump"])),
        ("rv50pcba_base_level_up", "base_level_up", str(p["base_level_up"])),
        ("rv50pcba_base_level_down", "base_level_down", str(p["base_level_down"])),
        ("electromagnetic_three_way_current", "em_valve", str(p["em_valve"])),
        ("rv50pcba_hot_start", "hot_start", str(p["hot_start"])),
        ("rv50pcba_hot_end", "hot_end", str(p["hot_end"])),
        ("cleaner_pump_current", "wash_pump", str(p["wash_pump"])),
        ("turbidity_data", "turbidity", str(p["turbidity"])),
        ("rv50pcba_hot_diff", "hot_diff", str(p["hot_diff"])),
        ("charge_value", "charge", str(p["charge"])),
        ("rv50pcba_blower_freq", "blower_freq", str(p["blower_freq"])),
    ]


def rv50pcba_proto_refresh_test_ui(p, finalize=False):
    if p is None or MainFrame.main_frame is None:
        return
    for ui_name, field, val in _rv50pcba_proto_ui_rows(p):
        rv50pcba_proto_apply_test_ui_row(p, ui_name, field, val, finalize=finalize)


def rv50pcba_proto_refresh_test_ui_callafter(p):
    wx.CallAfter(rv50pcba_proto_refresh_test_ui, p)


def rv50pcba_proto_add_reports():
    mes_run.add_report(
        name="mcu软件版本", result=ver_res, value=dev_ver,
        val_max=load_cfg.mcu_ver, val_min=load_cfg.mcu_ver)
    mes_run.add_report(name="左回充码", result="", value=_rv30_fmt_ir_byte(ir_code_left))
    mes_run.add_report(name="右回充码", result="", value=_rv30_fmt_ir_byte(ir_code_right))
    mes_run.add_report(name="近卫回充码", result="", value=_rv30_fmt_ir_byte(ir_code_near))
    mes_run.add_report(name="清水箱在位", result="", value=str(clear_tank_install))
    mes_run.add_report(name="污水箱在位", result="", value=str(duty_tank_install))
    mes_run.add_report(name="尘袋", result="", value=str(dust_bug_install))
    mes_run.add_report(name="清洁底座在位", result="", value=str(clean_base_install))
    mes_run.add_report(name="清水泵电流", result="", value=str(clean_water_pump_current))
    mes_run.add_report(name="真空泵电流", result="", value=str(duty_water_pump_current))
    mes_run.add_report(name="底座液位(抬起)", result="", value=str(rv50_base_level_up_adc))
    mes_run.add_report(name="底座液位(按下)", result="", value=str(rv50_base_level_down_adc))
    mes_run.add_report(name="电磁三通电流", result="", value=str(electromagnetic_three_way_current))
    mes_run.add_report(name="热风开始", result="", value=str(rv50_hot_start_adc))
    mes_run.add_report(name="热风结束", result="", value=str(rv50_hot_end_adc))
    mes_run.add_report(name="清洁泵电流", result="", value=str(cleaner_pump_current))
    mes_run.add_report(name="浊度数据", result="", value=str(turbidity_data))
    mes_run.add_report(name="热风差值", result="", value=str(rv50_hot_diff_adc))
    mes_run.add_report(name="充电电流", result="", value=str(charge_value))
    mes_run.add_report(name="鼓风机频率", result="", value=str(rv50pcba_blower_freq))


def rv50pcba_proto_finalize_88(dev, dat):
    global test_end_time, rv50pcba_session_state, rv50pcba_last_p, rv50pcba_89_mes_done
    test_end_time = datetime.now()
    res_byte = dat[0] if len(dat) else 0xFF
    if res_byte == 0x04:
        if not rv50pcba_89_mes_done:
            mes_run.add_report(name="基站通讯", result="NG", value="治具与基站通讯失败")
            mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
            rv50pcba_89_mes_done = True
        else:
            mes_ret = False
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="治具与基站通讯失败", color=wx.RED)
        clear_sn_save_list()
        rv50pcba_session_state = RV50PCBA_SESS_FINISHED
        rv50pcba_proto_reset_to_idle()
        return
    if rv50pcba_89_mes_done:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试失败", color=wx.RED)
        rv50pcba_session_state = RV50PCBA_SESS_FINISHED
        clear_sn_save_list()
        rv50pcba_proto_reset_to_idle()
        return
    if res_byte != 0x03:
        mes_run.add_report(name="结束码", result="NG", value=hex(res_byte))
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        rv50pcba_89_mes_done = True
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="测试结束 NG（结束码 {}）".format(hex(res_byte)), color=wx.RED)
        clear_sn_save_list()
        rv50pcba_session_state = RV50PCBA_SESS_FINISHED
        rv50pcba_proto_reset_to_idle()
        return
    p = rv50pcba_last_p
    mes_ok = (
        p is not None
        and not rv50pcba_realtime_ng
        and ver_res == "OK"
        and rv50pcba_proto_yaml_finalize_ok(p)
    )
    rv50pcba_proto_add_reports()
    if mes_ok:
        res_display_str = "测试完成(综合判定 PASS)"
        text_color = wx.GREEN
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
    else:
        res_display_str = "测试结束(综合判定 NG)"
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
    rv50pcba_89_mes_done = True
    if p is not None:
        def _finalize_ui_refresh():
            for ui_name, field, val in _rv50pcba_proto_ui_rows(p):
                rv50pcba_proto_apply_test_ui_row(p, ui_name, field, val, finalize=True)
        wx.CallAfter(_finalize_ui_refresh)
    if mes_ret:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=res_display_str, color=text_color)
    rv50pcba_session_state = RV50PCBA_SESS_FINISHED
    clear_sn_save_list()
    rv50pcba_proto_reset_to_idle()


def RV50_pcba_mode(dev, cmd, dat):
    global test_start_time, check_sn_enable, ver_res, dev_ver
    global rv50pcba_session_state, rv50pcba_last_step, rv50pcba_max_step, rv50pcba_last_p
    global rv50pcba_89_mes_done, rv50pcba_realtime_ng
    if len(dat) <= 0:
        print("[RV50-018-PCBA] len=0 无有效数据")
        return
    if cmd == 0x66:
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()
            tool.clear_queue(barcode_q)
            check_sn_enable = True
            rv50pcba_last_step = -1
            rv50pcba_max_step = 0
            rv50pcba_last_p = None
            rv50pcba_89_mes_done = False
            rv50pcba_realtime_ng = False
            rv50pcba_session_state = RV50PCBA_SESS_WAIT_SN
            print("[RV50-018-PCBA] 请扫码")
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
    elif cmd == 0x77:
        if rv50pcba_session_state != RV50PCBA_SESS_RUNNING:
            return
        print("[RV50-018-PCBA] 0x77 len=" + str(len(dat)))
        p = rv50pcba_proto_parse_77_apply_globals(dat)
        wx.CallAfter(MainFrame.main_frame.up_ver_ui, dev_ver)
        if p is None:
            return
        rv50pcba_last_p = p
        rv50pcba_proto_refresh_test_ui_callafter(p)
        st = int(p["step"])
        if st > rv50pcba_max_step:
            rv50pcba_max_step = st
        if st != rv50pcba_last_step:
            rv50pcba_last_step = st
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="治具步骤：" + str(st), color=wx.BLUE)
        if not rv50pcba_proto_yaml_realtime_ok(p):
            rv50pcba_proto_realtime_fail(dev, "yaml阈值:" + str(p))
            return
    elif cmd == 0x88:
        print("[RV50-018-PCBA] 测试结束帧 dat[0]=" + str(dat[0] if dat else None))
        rv50pcba_proto_finalize_88(dev, dat)
    else:
        print("[RV50-018-PCBA] 未处理命令 cmd=" + hex(cmd))


# 静态电流测试
def robot_static_current_mode(dev, cmd, dat):
    global check_sn_enable
    global test_start_time
    global test_end_time

    if len(dat) <= 0:
        print("len=0 无有效数据")
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具数据异常",
                     color=wx.RED)
        return

    if cmd == 0x66:  # 命令帧：夹具上传开始测试
        ser_send_cmd(dev, 0x67)  # # 回复夹具开始测试
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()  # 清除mes待上传记录
            tool.clear_queue(barcode_q)  # 清空扫码枪数据
            check_sn_enable = True  # 使能SN号过站检测
            print('扫描枪扫描二维码')
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
        elif dat[0] == 0x02:  # 开始测试
            print('开始测试')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="开始测试")
    elif cmd == 0x02:  # 测试记录
        ser_send_cmd(dev, cmd)  # # 回复夹具开始测试
        if dat[0] == 0x01:
            static_cur_res = 'OK'
        elif dat[0] == 0x02:
            static_cur_res = 'NG'
        else:
            static_cur_res = 'un_test'
        if len(dat) >= 13:
            cur_res = (int(dat[1]) * 256 + int(dat[2]))
            cur_res = cur_res * 256 + int(dat[3])
            cur_res = cur_res * 256 + int(dat[4])
            vol_res = (int(dat[5]) * 256 + int(dat[6]))
            p_res = (int(dat[7]) * 256 + int(dat[8]))
            cur_max = (int(dat[9]) * 256 + int(dat[10]))
            cur_min = (int(dat[11]) * 256 + int(dat[12]))
            print("静态电流 vol：" + str(vol_res) + " p: " + "p_res")

            mes_run.add_report(name="静态电流测试", result=static_cur_res,
                               value=str(cur_res),
                               val_max=str(cur_max),
                               val_min=str(cur_min))
    elif cmd == 0x88:  # 测试结束
        test_end_time = datetime.now()
        static_cur_res = "NG"
        if dat[0] == 0x01:    # 测试成功
            static_cur_res = "OK"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试  PASS",
                         color=wx.GREEN)
        elif dat[0] == 0x02:  # 测试失败
            static_cur_res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试  NG",
                         color=wx.RED)
        elif dat[0] == 0x0A:  # 停止测试
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试停止",
                         color=wx.RED)
        elif dat[0] == 0x0E:  # 扫码异常，check sn 出错
            pass
        if dat[0] == 0x01 or dat[0] == 0x02:
            mes_run.send_report(test_start_time, test_end_time, check_sn_str, static_cur_res)


def left_right_wheel_mode(dev, cmd, dat):
    global check_sn_enable
    global test_start_time
    global test_end_time

    if len(dat) <= 0:
        print("len=0 无有效数据")
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具数据异常",
                     color=wx.RED)
        return

    if cmd == 0x66:  # 命令帧：夹具上传开始测试
        ser_send_cmd(dev, 0x67)  # # 回复夹具开始测试
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()  # 清除mes待上传记录
            tool.clear_queue(barcode_q)  # 清空扫码枪数据
            check_sn_enable = True  # 使能SN号过站检测
            print('扫描枪扫描二维码')
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
        elif dat[0] == 0x02 or dat[0] == 0x01:  # 开始测试
            print('开始测试')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="开始测试")
    elif cmd == 0x02:  # 测试记录
        ser_send_cmd(dev, cmd)  # # 回复夹具开始测试
        if len(dat) >= 24:
            forward_current = (int(dat[1]) * 256 + int(dat[2]))  # 正转电流
            byte_data = bytes([dat[3], dat[4]])
            forward_speed = int.from_bytes(byte_data, byteorder="big", signed=True)  # 正转速度
            reverse_current = (int(dat[5]) * 256 + int(dat[6]))  # 反转电流
            byte_data = bytes([dat[7], dat[8]])
            reverse_speed = int.from_bytes(byte_data, byteorder="big", signed=True)  # 反转速度
            locked_current = (int(dat[9]) * 256 + int(dat[10]))  # 堵转电流
            current_unit = int(dat[11])  # 电流单位 01 A, 02 mA, 03 uA
            current_min = (int(dat[12]) * 256 + int(dat[13]))  # 空载电流下限
            current_max = (int(dat[14]) * 256 + int(dat[15]))  # 空载电流上限
            speed_min = (int(dat[16]) * 256 + int(dat[17]))  # 空载速度下限
            speed_max = (int(dat[18]) * 256 + int(dat[19]))  # 空载速度上限
            locked_min = (int(dat[20]) * 256 + int(dat[21]))  # 堵转电流下限
            locked_max = (int(dat[22]) * 256 + int(dat[23]))  # 堵转电流上限
            if current_unit == 0x01:
                unit = "A"
            elif current_unit == 0x02:
                unit = "mA"
            elif current_unit == 0x03:
                unit = "uA"
            else:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具数据异常",
                             color=wx.RED)
                return
            print("空载电流，速度阀值，堵转阀值", current_min, current_max, speed_min, speed_max, locked_min, locked_max)
            print("空载，正反转电流，速度：", forward_current, reverse_current, forward_speed, reverse_speed)
            print("堵转电流：", str(locked_current)+unit)
            mes_run.add_report(name="正转电流", result=get_res(forward_current, current_min, current_max),
                               value=str(forward_current) + unit,
                               val_max=str(current_max) + unit,
                               val_min=str(current_min) + unit)
            mes_run.add_report(name="反转电流", result=get_res(reverse_current, current_min, current_max),
                               value=str(reverse_current) + unit,
                               val_max=str(current_max) + unit,
                               val_min=str(current_min) + unit)
            mes_run.add_report(name="堵转电流", result=get_res(locked_current, locked_min, locked_max),
                               value=str(locked_current) + unit,
                               val_max=str(locked_max) + unit,
                               val_min=str(locked_min) + unit)
            unit = "RPM"
            mes_run.add_report(name="正转速度", result=get_res(forward_speed, speed_min, speed_max),
                               value=str(forward_speed) + unit,
                               val_max=str(speed_max) + unit,
                               val_min=str(speed_min) + unit)
            mes_run.add_report(name="反转速度", result=get_res(reverse_speed, -speed_max, -speed_min),
                               value=str(reverse_speed) + unit,
                               val_max='-' + str(speed_min) + unit,
                               val_min='-' + str(speed_max) + unit)
    elif cmd == 0x88:  # 测试结束
        test_end_time = datetime.now()
        res = "NG"
        if dat[0] == 0x01:    # 测试成功
            res = "OK"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试  PASS",
                         color=wx.GREEN)
        elif dat[0] == 0x02:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="空载电流异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x03:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="堵转电流异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x04:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="堵转测试异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x05:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="速度测试异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x09:  # 测试失败，边刷治具，编码器异常
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具编码器异常，请检测  NG",
                         color=wx.RED)
        elif dat[0] == 0x0A:  # 停止测试
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试停止",
                         color=wx.RED)
        elif dat[0] == 0x0E:  # 扫码枪错误
            pass
        mes_res = True
        if 0x05 >= dat[0] >= 0x01:
            mes_res = mes_run.send_report(test_start_time, test_end_time, check_sn_str, res)
        if mes_res:
            data_list = [0x01]
        else:
            data_list = [0x02]
        ser_send_data(dev, 0x89, data_list)  # # 回复夹具开始测试


# 边刷摆臂测试治具
def side_brush_mode(dev, cmd, dat):
    global check_sn_enable
    global test_start_time
    global test_end_time
    print(dat)
    if len(dat) <= 0:
        print("len=0 无有效数据")
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具数据异常",
                     color=wx.RED)
        return

    if cmd == 0x66:  # 命令帧：夹具上传开始测试
        ser_send_cmd(dev, 0x67)  # # 回复夹具开始测试
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()  # 清除mes待上传记录
            tool.clear_queue(barcode_q)  # 清空扫码枪数据
            check_sn_enable = True  # 使能SN号过站检测
            print('扫描枪扫描二维码')
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
        elif dat[0] == 0x02 or dat[0] == 0x01:  # 开始测试
            print('开始测试')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="开始测试")
    elif cmd == 0x02:  # 测试记录
        ser_send_cmd(dev, cmd)  # # 回复夹具开始测试
        if len(dat) >= 30:
            byte_data = bytes([dat[1], dat[2]])
            forward_current = int.from_bytes(byte_data, byteorder="big", signed=True)
            byte_data = bytes([dat[3], dat[4]])
            reverse_current = int.from_bytes(byte_data, byteorder="big", signed=True)
            locked_current = (int(dat[5]) * 256 + int(dat[6]))  # 边刷，堵转电流
            motor_out_current = (int(dat[7]) * 256 + int(dat[8]))  # 摆出电流
            motor_in_current = (int(dat[9]) * 256 + int(dat[10]))  # 摆入电流
            limit_switch = int(dat[11])  # 微动开关检测
            motor_travel = int(dat[12])  # 摆臂行程
            current_unit = int(dat[13])  # 电流单位 01 A, 02 mA, 03 uA
            current_min = (int(dat[14]) * 256 + int(dat[15]))  # 空载电流下限
            current_max = (int(dat[16]) * 256 + int(dat[17]))  # 空载电流上限
            locked_min = (int(dat[18]) * 256 + int(dat[19]))  # 堵转电流下限，边刷堵转
            locked_max = (int(dat[20]) * 256 + int(dat[21]))  # 堵转电流上限，边刷堵转
            out_in_current_min = (int(dat[22]) * 256 + int(dat[23]))  # 堵转电流上限
            out_in_current_max = (int(dat[24]) * 256 + int(dat[25]))  # 堵转电流上限
            out_in_locked_min = (int(dat[26]) * 256 + int(dat[27]))  # 摆臂堵转电流上限，不测试
            out_in_locked_max = (int(dat[28]) * 256 + int(dat[29]))  # 摆臂堵转电流上限，不测试

            if current_unit == 0x01:
                unit = "A"
            elif current_unit == 0x02:
                unit = "mA"
            elif current_unit == 0x03:
                unit = "uA"
            else:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具数据异常",
                             color=wx.RED)
                return
            mes_run.add_report(name="边刷正转电流", result=get_res(forward_current, current_min, current_max),
                               value=str(forward_current) + unit,
                               val_max=str(current_max) + unit,
                               val_min=str(current_min) + unit)
            mes_run.add_report(name="边刷反转电流", result=get_res(reverse_current, -current_max, -current_min),
                               value=str(reverse_current) + unit,
                               val_max='-' + str(current_min) + unit,
                               val_min='-' + str(current_max) + unit)
            mes_run.add_report(name="边刷堵转电流", result=get_res(locked_current, locked_min, locked_max),
                               value=str(locked_current) + unit,
                               val_max=str(locked_max) + unit,
                               val_min=str(locked_min) + unit)
            mes_run.add_report(name="摆臂伸出电流", result=get_res(motor_out_current, out_in_current_min, out_in_current_max),
                               value=str(motor_out_current) + unit,
                               val_max=str(out_in_current_max) + unit,
                               val_min=str(out_in_current_min) + unit)
            mes_run.add_report(name="摆臂收回电流", result=get_res(motor_in_current, out_in_current_min, out_in_current_max),
                               value=str(motor_in_current) + unit,
                               val_max=str(out_in_current_max) + unit,
                               val_min=str(out_in_current_min) + unit)
            if motor_travel == 0xff:
                make_res = "un_test"
            elif motor_travel == 0x01:
                make_res = "OK"
            else:
                make_res = "NG"
            mes_run.add_report(name="摆臂行程", result=make_res, value=make_res)
            if limit_switch == 0xff:
                make_res = "un_test"
            elif limit_switch == 0x01:
                make_res = "OK"
            else:
                make_res = "NG"
            mes_run.add_report(name="摆臂微动开关", result=make_res, value=make_res)
    elif cmd == 0x88:  # 测试结束
        test_end_time = datetime.now()
        res = "NG"
        if dat[0] == 0x01:    # 测试成功
            res = "OK"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试  PASS",
                         color=wx.GREEN)
        elif dat[0] == 0x02:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="边刷空载电流异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x03:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="边刷堵转电流异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x04:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="边刷堵转测试异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x05:  # 测试失败，边刷速度异常，不使用
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="边刷速度测试异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x06:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="摆臂电流测试异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x07:  # 测试失败，边刷速度异常，不使用
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="摆臂手动开关测试异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x08:  # 测试失败，边刷速度异常，不使用
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="摆臂行程测试异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x09:  # 测试失败，边刷治具，编码器异常
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具编码器异常，请检测  NG",
                         color=wx.RED)
        elif dat[0] == 0x0A:  # 停止测试
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试停止",
                         color=wx.RED)
        elif dat[0] == 0x0E:  # 扫码枪错误
            pass
        mes_res = True
        if 0x08 >= dat[0] >= 0x01:
            mes_res = mes_run.send_report(test_start_time, test_end_time, check_sn_str, res)
        if mes_res:  # 上次数据私发通过
            data_list = [0x01]
        else:
            data_list = [0x02]
        ser_send_data(dev, 0x89, data_list)  # # 回复夹具开始测试


def main_brush_mode(dev, cmd, dat):
    global check_sn_enable
    global test_start_time
    global test_end_time

    if len(dat) <= 0:
        print("len=0 无有效数据")
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具数据异常",
                     color=wx.RED)
        return

    if cmd == 0x66:  # 命令帧：夹具上传开始测试
        ser_send_cmd(dev, 0x67)  # # 回复夹具开始测试
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()  # 清除mes待上传记录
            tool.clear_queue(barcode_q)  # 清空扫码枪数据
            check_sn_enable = True  # 使能SN号过站检测
            print('扫描枪扫描二维码')
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
        elif dat[0] == 0x02 or dat[0] == 0x01:  # 开始测试
            print('开始测试')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="开始测试")
    elif cmd == 0x02:  # 测试记录
        ser_send_cmd(dev, cmd)  # # 回复夹具开始测试
        if len(dat) >= 16:

            byte_data = bytes([dat[1], dat[2]])
            forward_current = int.from_bytes(byte_data, byteorder="big", signed=True)  # 正转电流
            byte_data = bytes([dat[3], dat[4]])
            reverse_current = int.from_bytes(byte_data, byteorder="big", signed=True)  # 反转电流
            locked_current = (int(dat[5]) * 256 + int(dat[6]))  # 堵转电流
            current_unit = int(dat[7])  # 电流单位 01 A, 02 mA, 03 uA
            current_min = (int(dat[8]) * 256 + int(dat[9]))  # 空载电流下限
            current_max = (int(dat[10]) * 256 + int(dat[11]))  # 空载电流上限
            locked_min = (int(dat[12]) * 256 + int(dat[13]))  # 空载速度下限
            locked_max = (int(dat[14]) * 256 + int(dat[15]))  # 空载速度上限

            if current_unit == 0x01:
                unit = "A"
            elif current_unit == 0x02:
                unit = "mA"
            elif current_unit == 0x03:
                unit = "uA"
            else:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具数据异常",
                             color=wx.RED)
                return
            mes_run.add_report(name="正转电流", result=get_res(forward_current, current_min, current_max),
                               value=str(forward_current) + unit,
                               val_max=str(current_max) + unit,
                               val_min=str(current_min) + unit)
            mes_run.add_report(name="反转电流", result=get_res(reverse_current, -current_max, -current_min),
                               value=str(reverse_current) + unit,
                               val_max='-' + str(current_min) + unit,
                               val_min='-' + str(current_max) + unit),
            mes_run.add_report(name="堵转电流", result=get_res(locked_current, locked_min, locked_max),
                               value=str(locked_current) + unit,
                               val_max=str(locked_max) + unit,
                               val_min=str(locked_min) + unit)

    elif cmd == 0x88:  # 测试结束
        test_end_time = datetime.now()
        res = "NG"
        if dat[0] == 0x01:    # 测试成功
            res = "OK"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试  PASS",
                         color=wx.GREEN)
        elif dat[0] == 0x02:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="空载电流异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x03:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="堵转电流异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x04:  # 测试失败
            res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="堵转测试异常  NG",
                         color=wx.RED)
        elif dat[0] == 0x0A:  # 停止测试
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试停止",
                         color=wx.RED)
        elif dat[0] == 0x0E:  # 扫码枪错误
            pass
        mes_res = True
        if 0x04 >= dat[0] >= 0x01:
            mes_res = mes_run.send_report(test_start_time, test_end_time, check_sn_str, res)
        if mes_res:
            data_list = [0x01]
        else:
            data_list = [0x02]
        ser_send_data(dev, 0x89, data_list)  # # 回复夹具开始测试


sn_left = ""
sn_right = ""


# 地检组件测试
def cliff_tool_mode(dev, cmd, dat):
    global check_sn_enable
    global test_start_time
    global test_end_time
    global cliff_sn_dict
    global sn_left
    global sn_right
    global check_sn_str

    if len(dat) <= 0:
        print("len=0 无有效数据")
        return

    if type(cmd) is str:
        if cmd == "sn":  # 收到SN信息
            sn_num = len(dat)
            str_list = [0x00, 0x00, 0x00, 0x00]
            if sn_num == 0 or sn_num > 2:
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             first="输入的SN数量异常: " + str(sn_num),
                             color=wx.RED)
                ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
                return
            sn_left = ""
            sn_right = ""
            match_res = False
            if sn_num == 1:
                sn_left = str(dat[0])
                match_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn_left))
                if match_res is False:
                    wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=1,
                                 text="左地检SN:" + str(sn_left) + " " + "编码异常",
                                 color=wx.RED)
            elif sn_num == 2:
                sn_left = str(dat[0])
                match_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn_left))
                if match_res is False:
                    wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=1,
                                 text="左地检SN:" + str(sn_left) + " " + "编码异常",
                                 color=wx.RED)
                sn_right = str(dat[1])
                match_res_temp = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(sn_right))
                if match_res_temp is False:
                    wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=2,
                                 text="右地检：" + str(sn_right) + " " + "编码异常",
                                 color=wx.RED)
                if match_res is False or match_res_temp is False:
                    match_res = False

            if sn_num == 2 and sn_left == sn_right:  # 左右SN相同
                wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=3,
                             text="输入的左右地检条码不能相同",
                             color=wx.RED)
                # ser_send_cmd(int(load_cfg.dev), 0x58)  # 回复夹具扫码失败
                sn_string = sn_left + '&' + sn_right
                str_list = [int(byte) for byte in sn_string.encode('utf-8')]
                ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
                return
            elif match_res is False:  # 编码异常
                # ser_send_cmd(int(load_cfg.dev), 0x58)  # 回复夹具扫码失败
                ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
                return

            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=1,
                         text="左地检SN:" + str(sn_left) + " " + "过站检测",
                         color=wx.RED)
            # mes 过站
            res = True
            res = mes_run.check_sn_is_ok(sn_left)
            # print(str_list)
            if res:
                ser_send_data(dev=int(load_cfg.dev), cmd=0x57, data=str_list)
                # ser_send_cmd(int(load_cfg.dev), 0x57)  # 回复夹具开始测试
            else:
                # ser_send_cmd(int(load_cfg.dev), 0x58)  # 回复夹具扫码失败
                ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
            check_sn_enable = False
    elif cmd == 0x66:  # 命令帧：夹具上传开始测试
        ser_send_cmd(dev, 0x67)  # # 回复夹具开始测试
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()  # 清除mes待上传记录
            tool.clear_queue(barcode_q)  # 清空扫码枪数据
            check_sn_enable = True  # 使能SN号过站检测
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            if TWO_CLIFF_SENSOR_MODE_EN is True:
                start_sn_collect(first="左地检SN：", second="右地检SN：")
            else:
                start_sn_collect(first="请输入地检SN:")
            # start_sn_collect(first="请输入左地检SN：", third="请输入右地检SN：")

        elif dat[0] == 0x02:  # 开始测试
            print('开始测试')
            # wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="开始测试")
    elif cmd == 0x02:  # 测试记录
        if dat[0] == 0x01:
            cliff_led1_res = 'OK'
        elif dat[0] == 0x02:
            cliff_led1_res = 'NG'
        else:
            cliff_led1_res = 'un_test'
        if dat[1] == 0x01:
            cliff_led2_res = 'OK'
        elif dat[1] == 0x02:
            cliff_led2_res = 'NG'
        else:
            cliff_led2_res = 'un_test'

        led_white_min = (int(dat[2]) * 256 + int(dat[3]))
        led_white_max = (int(dat[4]) * 256 + int(dat[5]))

        led_black_min = (int(dat[6]) * 256 + int(dat[7]))
        led_black_max = (int(dat[8]) * 256 + int(dat[9]))

        led1_white = (int(dat[10]) * 256 + int(dat[11]))
        led1_black = (int(dat[14]) * 256 + int(dat[15]))

        led2_white = (int(dat[12]) * 256 + int(dat[13]))
        led2_black = (int(dat[16]) * 256 + int(dat[17]))

        ser_send_cmd(dev, cmd)  # # 回复夹具开始测试

        test_end_time = datetime.now()
        check_sn_str = sn_left
        mes_run.clear_report()  # 清除mes待上传记录
        mes_run.add_report(name="地检白板-黑板-测试LED1", result=cliff_led1_res,
                           value='白板：' + str(led1_white) + ',黑板：' + str(led1_black),
                           val_max='白板：' + str(led_white_max) + ',黑板：' + str(led_black_max),
                           val_min='白板：' + str(led_white_min) + ',黑板：' + str(led_black_min))
        if TWO_CLIFF_SENSOR_MODE_EN is False:
            return
        mes_res = mes_run.send_report(test_start_time, test_end_time, check_sn_str, cliff_led1_res)
        if mes_res is not True:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=1,
                         text="左地检SN:" + str(sn_left) + " " + "NG",
                         color=wx.RED)
            str_list = [0x00, 0x00, 0x00, 0x00]
            # ser_send_cmd(int(load_cfg.dev), 0x58)  # 回复夹具扫码失败
            ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
            return
        wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=1,
                     text="左地检SN:" + str(sn_left) + " " + cliff_led1_res,
                     color=wx.RED)
        check_sn_str = sn_right
        wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=2,
                     text="右地检SN:" + str(sn_right) + " " + cliff_led1_res,
                     color=wx.RED)
        mes_run.clear_report()  # 清除mes待上传记录
        sn_res = mes_run.check_sn_is_ok(check_sn_str)
        cliff_res = cliff_led2_res
        if sn_res:
            mes_run.add_report(name="地检白板-黑板-测试LED2", result=cliff_led2_res,
                               value='白板：' + str(led2_white) + ',黑板：' + str(led2_black),
                               val_max='白板：' + str(led_white_max) + ',黑板：' + str(led_black_max),
                               val_min='白板：' + str(led_white_min) + ',黑板：' + str(led_black_min))
            mes_res = mes_run.send_report(test_start_time, test_end_time, sn_right, cliff_led2_res)
        else:
            str_list = [0x00, 0x00, 0x00, 0x00]
            # ser_send_cmd(int(load_cfg.dev), 0x58)  # 回复夹具扫码失败
            ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=2,
                         text="右地检SN:" + str(sn_right) + " " + "NG",
                         color=wx.RED)
            return
        if mes_res is not True:
            str_list = [0x00, 0x00, 0x00, 0x00]
            # ser_send_cmd(int(load_cfg.dev), 0x58)  # 回复夹具扫码失败
            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=2,
                         text="右地检SN:" + str(sn_right) + " " + "NG",
                         color=wx.RED)
            ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
            return
        else:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=2,
                         text="右地检SN:" + str(sn_right) + " " + cliff_led2_res,
                         color=wx.RED)

    elif cmd == 0x88:  # 测试结束
        test_end_time = datetime.now()

        check_sn_enable = False
        cliff_res = "NG"
        if dat[0] == 0x01:    # 测试成功
            cliff_res = "OK"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=3,
                         text="测试  PASS",
                         color=wx.GREEN)
        elif dat[0] == 0x02:  # 测试失败
            cliff_res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=3,
                         text="测试  NG",
                         color=wx.RED)
        elif dat[0] == 0x0A:  # 停止测试
            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=3,
                         text="测试停止",
                         color=wx.RED)
        elif dat[0] == 0x0E:  # 扫码异常，check sn 出错
            print("扫码枪异常")
        mes_res = True
        if dat[0] != 0x0E and dat[0] != 0x0A:
            pass
            # mes_res = mes_run.send_report(test_start_time, test_end_time, check_sn_str, cliff_res)
        if mes_res:
            data_list = [0x01]
        else:
            data_list = [0x02]
        ser_send_data(dev, 0x89, data_list)  # # 回复夹具开始测试


# 前撞设备，组件或PCB
def lt_bump_mode(dev, cmd, dat):
    global check_sn_enable
    global test_start_time
    global test_end_time

    if len(dat) <= 0:
        print("len=0 无有效数据")
        return

    if cmd == 0x66:  # 命令帧：夹具上传开始测试
        ser_send_cmd(dev, 0x67)  # # 回复夹具开始测试
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()  # 清除mes待上传记录
            tool.clear_queue(barcode_q)  # 清空扫码枪数据
            check_sn_enable = True  # 使能SN号过站检测
            print('扫描枪扫描二维码')
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
        elif dat[0] == 0x02:  # 开始测试
            print('开始测试')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="开始测试")
    elif cmd == 0x02:  # 测试记录
        ser_send_cmd(dev, cmd)  # # 回复夹具开始测试
        lt_ir_res = "un_test"
        if dat[0] == 0x01:
            lt_ir_res = "OK"
        elif dat[0] == 0x02:
            lt_ir_res = "NG"
        wx.CallAfter(MainFrame.main_frame.up_test_ui, "ir_rx", get_display_res(lt_ir_res))

        if len(dat) >= 109:  # 1 + 12 * 9
            for i in range(9):
                far_val = (int(dat[1 + i * 12]) * 256 + int(dat[2 + i * 12]))
                close_val = (int(dat[3 + i * 12]) * 256 + int(dat[4 + i * 12]))
                close_min = (int(dat[5 + i * 12]) * 256 + int(dat[6 + i * 12]))
                close_max = (int(dat[7 + i * 12]) * 256 + int(dat[8 + i * 12]))
                far_min = (int(dat[9 + i * 12]) * 256 + int(dat[10 + i * 12]))
                far_max = (int(dat[11 + i * 12]) * 256 + int(dat[12 + i * 12]))

                if far_min <= far_val <= far_max:
                    far_res = "OK"
                else:
                    far_res = "NG"

                if close_min <= close_val <= close_max:
                    close_res = "OK"
                else:
                    close_res = "NG"
                if i == 0:
                    name_str = "沿墙灯"
                else:
                    name_str = f"LED{i}"
                mes_run.add_report(name=name_str+"近值", result=close_res,
                                   value=str(close_val),
                                   val_max=str(close_max),
                                   val_min=str(close_min))
                mes_run.add_report(name=name_str+"远值", result=far_res,
                                   value=str(far_val),
                                   val_max=str(far_max),
                                   val_min=str(far_min))
    elif cmd == 0x88:  # 测试结束
        test_end_time = datetime.now()
        lt_bump_res = "NG"
        if dat[0] == 0x01:    # 测试成功
            lt_bump_res = "OK"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试  PASS",
                         color=wx.GREEN)
        elif dat[0] == 0x02:  # 测试失败
            lt_bump_res = "NG"
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试  NG",
                         color=wx.RED)
        elif dat[0] == 0x0A:  # 停止测试
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试停止",
                         color=wx.RED)
        elif dat[0] == 0x0E:  # 扫码异常，check sn 出错
            pass
        if dat[0] == 0x01 or dat[0] == 0x02:
            mes_run.send_report(test_start_time, test_end_time, check_sn_str, lt_bump_res)


# 回充座测试
def docking_station_mode(dev, cmd, dat):
    global check_sn_enable
    global test_start_time
    global test_end_time
    global cliff_sn_dict
    global left_res
    global right_res
    global check_sn_str

    if len(dat) <= 0:
        print("len=0 无有效数据")
        return
    if type(cmd) is str:
        if cmd == "sn":  # 收到SN信息
            check_sn_str = dat[0]
            match_res = encode_rules.match_sn_encoding_rules(dev=load_cfg.dev, sn=str(check_sn_str))
            # str_list_hex = [hex(byte) for byte in check_sn_str.encode('utf-8')]
            str_list = [int(byte) for byte in check_sn_str.encode('utf-8')]
            # print(check_sn_str, str(str_list), str_list_hex)
            # print(str_list)
            if match_res:  # 条码规则匹配成功
                # mes 过站
                res = True
                res = mes_run.check_sn_is_ok(check_sn_str)
                # print(str_list)
                if res:
                    ser_send_data(dev=int(load_cfg.dev), cmd=0x57, data=str_list)
                    # ser_send_cmd(int(load_cfg.dev), 0x57)  # 回复夹具开始测试
                else:
                    # ser_send_cmd(int(load_cfg.dev), 0x58)  # 回复夹具扫码失败
                    ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)
            else:
                ser_send_data(dev=int(load_cfg.dev), cmd=0x58, data=str_list)  # 回复夹具扫码失败
                wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                             first="请输入条码:" + str(check_sn_str),
                             third="编码规则不通过，请查")
            check_sn_enable = False
    elif cmd == 0x66:  # 命令帧：夹具上传开始测试
        ser_send_cmd(dev, 0x67)  # # 回复夹具开始测试
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()  # 清除mes待上传记录
            tool.clear_queue(barcode_q)  # 清空扫码枪数据
            check_sn_enable = True  # 使能SN号过站检测
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            start_sn_collect(first="请输入SN:")

        elif dat[0] == 0x02:  # 开始测试
            print('开始测试')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item,
                         num=2, text="开始测试", color=wx.RED)
    elif cmd == 0x02:  # 测试记录
        ser_send_cmd(dev, cmd)  # # 回复夹具开始测试
        if len(dat) < 4:
            print("回充座收到测试结果长度不对")
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试记录数据长度异常")
            return
        res = "OK"


# 积尘桶或集尘桶PCB测试
def dust_collector_mode(dev, cmd, dat):
    global test_start_time
    global test_end_time
    global check_sn_enable
    if len(dat) <= 0:
        print("len=0 无有效数据")
        return

    if cmd == 0x66:  # 命令帧：夹具上传开始测试
        ser_send_cmd(dev, 0x67)  # # 回复夹具开始测试
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()  # 清除mes待上传记录
            tool.clear_queue(barcode_q)  # 清空扫码枪数据
            check_sn_enable = True  # 使能SN号过站检测
            print('扫描枪扫描二维码')
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
        elif dat[0] == 0x01:
            print('开始测试')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="开始测试")
        elif dat[0] == 0x02:
            print('开始测试')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="开始测试")
        elif dat[0] == 0x52:
            print('请拔出尘袋')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请拔出尘袋")
        elif dat[0] == 0x51:
            print('请插入尘袋')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请插入尘袋")
        elif dat[0] == 0x05:
            print('请观察灯效是否正常')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请观察灯效是否正常")
        else:
            print('其他开始测试')
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="继续测试")
    elif cmd == 0x68:
        print('所有阀值：' + str(dat))
        # 阈值 充电电流
        dust_th.cc_max = (int(dat[0]) * 256 + int(dat[1]))
        dust_th.cc_min = (int(dat[2]) * 256 + int(dat[3]))
        # 阈值 ac 过载频率
        dust_th.ac_lv_max = int(dat[4])
        dust_th.ac_lv_min = int(dat[5])
        # 阈值 外接气压计 上线下线；吸力值
        dust_th.out_barometer_max = (int(dat[6]) * 256 + int(dat[7]))
        dust_th.out_barometer_min = (int(dat[8]) * 256 + int(dat[9]))
        # 阈值 气压值小板 上线下线；检测尘满
        dust_th.barometer_max = (int(dat[10]) * 256 + int(dat[11]))
        dust_th.barometer_min = (int(dat[12]) * 256 + int(dat[13]))
        wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码", color=wx.RED)
    elif cmd == 0x01:  # 命令帧：红外收发和集尘宝版本号
        print("红外收发码:" + str(dat))
        infrared_code = int(dat[0])

        dev_ver = format(int(dat[1]), '03d') + '.'
        dev_ver += (format(int(dat[2]), '03d') + '.' + format(int(dat[3]), '03d'))
        wx.CallAfter(MainFrame.main_frame.up_ver_ui, dev_ver)
        if dev_ver == load_cfg.mcu_ver:
            ver_res = "OK"
        else:
            ver_res = "NG"
        mes_run.add_report(name="mcu软件版本", result=ver_res,
                           value=dev_ver,
                           val_max=load_cfg.mcu_ver,
                           val_min=load_cfg.mcu_ver)
        res = ""
        display_str = "pass"
        if infrared_code == 1:
            res = "OK"
            display_str = "pass"
        elif infrared_code == 2:
            res = "NG"
            display_str = "fail"

        mes_run.add_report(name="红外通讯，收发码", result=res)
        wx.CallAfter(MainFrame.main_frame.up_test_ui, "ir_rx", display_str)

        # 版本号异常，不进行后续测试
        if res == "OK" and dev_ver != load_cfg.mcu_ver:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="测试失败：软件版本号不匹配", color=wx.RED)
            return
        ser_send_cmd(dev, cmd)  # 回复夹具开始测试
    elif cmd == 0x02:  # 命令帧：回充红外灯，x 右 左 近卫
        print('四路红外灯发送测试' + str(dat))
        ser_send_cmd(dev, cmd)  # 回复夹具开始测试
        ir1 = int(dat[0])
        ir2 = int(dat[1])
        ir3 = int(dat[2])
        ir4 = int(dat[3])

        res_str_value = ""
        if ir2 == 1 and ir3 == 1 and ir4 == 1:
            res = "OK"
        else:
            res = "NG"
        if ir2 == 1:
            ir2_res = "OK"
            res_str_value += "右红外-OK "
        else:
            ir2_res = "NG"
            res_str_value += "右红外-NG "
        if ir3 == 1:
            ir3_res = "OK"
            res_str_value += "左红外-OK "
        else:
            ir3_res = "NG"
            res_str_value += "左红外-NG "
        if ir4 == 1:
            ir4_res = "OK"
            res_str_value += "近卫红外-OK "
        else:
            ir4_res = "NG"
            res_str_value += "近卫红外-NG "
        # wx.CallAfter(MainFrame.main_frame.up_test_ui, "right_ir", get_display_res(ir1))
        wx.CallAfter(MainFrame.main_frame.up_test_ui, "right_ir", get_display_res(ir2_res))
        wx.CallAfter(MainFrame.main_frame.up_test_ui, "left_ir", get_display_res(ir3_res))
        wx.CallAfter(MainFrame.main_frame.up_test_ui, "guard_light", get_display_res(ir4_res))

        mes_run.add_report(name="回充红外发码测试", result=res, value=res_str_value)

    elif cmd == 0x03:  # 尘袋在位测试
        print('尘袋在位测试' + str(dat))
        res_str = "NG"
        ser_send_cmd(dev, cmd)  # 回复夹具开始测试
        if dat[0] == 0x01:  # 尘袋在位，用于显示
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="尘袋在位")
        elif dat[0] == 0x02:  # 尘袋不在位，用于显示
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="尘袋不在位")
        elif dat[0] == 0x81:  # 尘袋测试通过
            res_str = "OK"
        elif dat[0] == 0x82:  # 尘袋测试不通过
            res_str = "NG"
        if dat[0] == 0x81 or dat[0] == 0x82:
            wx.CallAfter(MainFrame.main_frame.up_test_ui, name="bag_install",
                         result=get_display_res(res_str))
            mes_run.add_report(name="回充红外发码测试", result=res_str)

    elif cmd == 0x04:
        print('负载测试' + str(dat))
        ser_send_cmd(dev, cmd)  # 回复夹具开始测试
        cur_pass = int(dat[0])
        res_cur_pass = "NG"
        if cur_pass == 1:
            res_cur_pass = "OK"
        elif cur_pass == 2:
            res_cur_pass = "NG"
        wx.CallAfter(MainFrame.main_frame.up_test_ui, name="load_current",
                     result=get_display_res(res_cur_pass))
        mes_run.add_report(name="负载电流是否通过", result=res_cur_pass)
    elif cmd == 0x05:
        print('灯显测试')
        ser_send_cmd(dev, cmd)  # 回复夹具开始测试
        if dat[0] == 0x51:
            led_pass = "OK"
            led_display = "pass"
        elif dat[0] == 0x52:
            led_pass = "NG"
            led_display = "fail"
        else:
            led_pass = "untested"
            led_display = "untested"
        if dev == 0x06:  # PCB
            led_value = f"LED1 通过次数{int(dat[1])}，LED2 通过次数{int(dat[2])}"
            min_value = str(int(dat[4]))
            max_value = "不限"
        else:
            led_value = f"LED白 通过次数{int(dat[1])}，LED红 通过次数{int(dat[2])}, LED黑 通过次数{int(dat[3])}"
            min_value = str(int(dat[4]))
            max_value = "不限"
        wx.CallAfter(MainFrame.main_frame.up_test_ui, name="led_display",
                     result=led_display)
        mes_run.add_report(name="LED灯显测试", result=led_pass,
                           value=led_value,
                           val_min=min_value,
                           val_max=max_value)

    elif cmd == 0x61:
        print('AC交流板的过零信号频率' + str(dat))
        ser_send_cmd(dev, 0x06)  # 回复夹具开始测试
        ac_pass = int(dat[0])
        ac_value = int(dat[1])
        ac_res = 'un_test'
        if ac_pass == 1:
            ac_res = 'OK'
        elif ac_pass == 2:
            ac_res = 'NG'
        
        wx.CallAfter(MainFrame.main_frame.up_test_ui, name="ac_check",
                     result=get_display_res(ac_res))
        mes_run.add_report(name="AC交流板的过零信号频率",
                           result=ac_res,
                           value=str(ac_value),
                           val_max=str(dust_th.ac_lv_max),
                           val_min=str(dust_th.ac_lv_min))
    elif cmd == 0x62:
        ser_send_cmd(dev, 0x06)  # 回复夹具
        print('外接吸力值计' + str(dat))
        res_str = 'un_test'
        out_suction = int(dat[0])
        if out_suction == 1:
            res_str = 'OK'
        elif out_suction == 2:
            res_str = 'NG'
        if dev == 0x01:
            out_suction_value = (int(dat[1]) * 256 + int(dat[2]))
        else:
            out_suction_value = "PCB人工判断 " + res_str
            dust_th.out_barometer_max = ""
            dust_th.out_barometer_min = ""
        print('外接吸力值测试值：' + str(out_suction_value))
        wx.CallAfter(MainFrame.main_frame.up_test_ui, name="suction",
                     result=get_display_res(res_str))
        mes_run.add_report(name="外接吸力计",
                           result=res_str,
                           value=str(out_suction_value),
                           val_max=str(dust_th.out_barometer_max),
                           val_min=str(dust_th.out_barometer_min))
    elif cmd == 0x63:
        ser_send_cmd(dev, 0x06)  # 回复夹具
        print('气压计小板' + str(dat))
        res_str = 'un_test'
        barometer_pass = int(dat[0])
        if barometer_pass == 1:
            res_str = 'OK'
        elif barometer_pass == 2:
            res_str = 'NG'

        barometer_value = (int(dat[1]) * 256 + int(dat[2]))
        print('气压计小板：' + str(barometer_value))
        wx.CallAfter(MainFrame.main_frame.up_test_ui, name="barometer",
                     result=get_display_res(res_str))
        mes_run.add_report(name="气压计小板",
                           result=res_str,
                           value=str(barometer_value),
                           val_max=str(dust_th.barometer_max),
                           val_min=str(dust_th.barometer_min))
    # 测试完成
    elif cmd == 0x88:
        ser_send_cmd(dev, 0x89)  # 回复夹具
        res_value = dat[0]
        res_display_str = ''
        test_end_time = datetime.now()
        print("jichentongceswanc")
        if res_value == 0x01:
            res_display_str = "测试完成  PASS"
            wx.CallAfter(MainFrame.main_frame.up_test_ui, name="led_display",
                         result="pass")
            mes_run.add_report(name="led", result="OK",)
        elif res_value == 0x00:
            res_display_str = "条码没通过  NG"
        elif res_value == 0x02:  # 需要处理，没有测试项
            res_display_str = "回充发码异常  NG"
            mes_run.add_report(name="回充发码",
                               result="NG",
                               value="NG",
                               val_max="",
                               val_min="")
        elif res_value == 0x03:
            res_display_str = "红外收发异常  NG"
        elif res_value == 0x04:
            res_display_str = "尘袋在位检测异常  NG"
        elif res_value == 0x05:
            res_display_str = "充电电流异常  NG"
        elif res_value == 0x06:
            res_display_str = "内置气压计异常  NG"
        elif res_value == 0x07:
            res_display_str = "LED灯显异常  NG"
        elif res_value == 0x08:
            res_display_str = "AC交流板的过零信号频率异常  NG"
        elif res_value == 0x09:
            res_display_str = "外部气压计异常  NG"
        elif res_value == 0x0A:
            res_display_str = "测试停止  NG"
        elif res_value == 0x0B:
            res_display_str = "没有扫码  NG"
        elif res_value == 0x0E:  # 扫码异常，check sn 出错
            pass
        else:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="测试结果异常，请检测",
                         color=wx.RED)
            return
        mes_run.add_report(name="污水通路过水",
                           result="NG",
                           value="NG",
                           )
        mes_run.add_report(name="左拖布过水",
                           result="NG",
                           value="NG",
                           )
        mes_run.add_report(name="右拖布过水",
                           result="NG",
                           value="NG",
                           )
        mes_run.add_report(name="左拖布温度adc",
                           result="NG",
                           value="NG",
                           )
        mes_run.add_report(name="右拖布温度adc",
                           result="NG",
                           value="NG",
                           )
        text_color = wx.RED
        print("测试结果：" + res_display_str)
        mes_ret = False
        if res_value == 0x01:
            text_color = wx.GREEN
            mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
        elif res_value != 0x00 and res_value != 0x0A:
            mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second=res_display_str,
                         color=text_color)


def get_display_res(value):
    ret = ""
    if value == "OK":
        ret = "pass"
    elif value == "NG":
        ret = "fail"
    else:
        ret = "untested"
    return ret


def is_sn_up_enable():
    return sn_up_enable


def clear_sn_up_enable():
    global sn_up_enable
    sn_up_enable = False
    print("clean sn up enable")


def set_sn_up_enable():
    global sn_up_enable
    sn_up_enable = True
    print("set sn up enable")


def start_sn_collect(first="", second="", third="", start_sn=""):
    global sn_up_enable
    global sn_save_list

    sn_save_list = []
    dirt = {"head": first, "sn": ""}
    sn_save_list.append(dirt)
    dirt = {"head": second, "sn": ""}
    sn_save_list.append(dirt)
    dirt = {"head": third, "sn": ""}
    sn_save_list.append(dirt)
    full = False
    if start_sn != "":
        full = save_sn_to_list(sn=start_sn)

    wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                 first=sn_save_list[0]["head"] + sn_save_list[0]["sn"],
                 second=sn_save_list[1]["head"] + sn_save_list[1]["sn"],
                 third=sn_save_list[2]["head"] + sn_save_list[2]["sn"],
                 color=wx.RED)
    if full is False:
        set_sn_up_enable()


# 模拟治具，发测试命令
def send_sn_cmd():
    full = save_sn_to_list(sn="")
    sn_list = get_sn_collect_res()
    if len(sn_list) < 1 or int(load_cfg.dev) != 5:  # 暂时只处理地检治具
        return
    if full:
        sn_cmd = {
            "cmd": "sn",
            "msg": sn_list,
        }
        tool.clear_queue(rx_sn_cmd_q)
        rx_sn_cmd_q.put(sn_cmd)


# 获取收集到的SN
def get_sn_collect_res():
    global sn_save_list

    sn_list = []

    for item in sn_save_list:
        if item["head"] != "" and item["sn"] != "":
            sn = item["sn"]
            sn_list.append(sn)

    return sn_list


def clear_sn_save_list():
    """
    清除全局变量 sn_save_list 的内容。
    将 sn_save_list 重置为空列表。
    """
    global sn_save_list
    sn_save_list = []


def save_sn_to_list(sn=""):
    global sn_save_list
    is_list_full = True
    if sn != "":
        for item in sn_save_list:
            if item["head"] != "" and item["sn"] == "":
                item["sn"] = sn
                break
    for item in sn_save_list:
        if item["head"] != "" and item["sn"] == "":
            is_list_full = False
    # print(sn_save_list)
    return is_list_full


def check_sn_num():
    global sn_save_list
    global sn_up_enable

    # SN未采集完
    if sn_up_enable:
        return -1

    sn_num = 0
    for item in sn_save_list:
        if item["head"] != "" and item["sn"] != "":
            sn_num += 1

    return sn_num


def check_barcodes_match_process():
    global test_work_state
    global barcode_msg_update
    global test_error_str

    if is_sn_up_enable() is not True:
        one_sn = ""
        tow_sn = ""
        for item in sn_save_list:
            if item["head"] == "请输入条码一：":
                one_sn = item["sn"]
            elif item["head"] == "请输入条码二：":
                tow_sn = item["sn"]
        print("字符比较", one_sn, tow_sn, str(one_sn == tow_sn))
        if one_sn == tow_sn and len(one_sn) >= 4 and len(tow_sn) >= 4:
            is_in_db = sqlite_db.is_sn_in_database(one_sn, sqlite_db.conn)
            if is_in_db is False:
                sns = [one_sn]
                sqlite_db.add_sn_record(connect=sqlite_db.conn, sns=sns, name="大货SN")
                print("测试通过，SN：" + one_sn)
                text = "比较通过    PASS"
                color = wx.GREEN
                res = "PASS"
                voice.play_voice("pass")
            elif is_in_db is True:
                text = "条码已经使用:"
                color = wx.RED
                results = sqlite_db.find_record_time_by_sn(sqlite_db.conn, one_sn)
                res = "条码已经使用:" + results[1]
                if results[0] is True:
                    text += '\n' + results[1]
                voice.play_voice("sn_is_used")
                test_error_str = "SN已使用，请检查后复位测试"

            else:
                text = "数据库操作异常"
                color = wx.RED
                res = "NG 数据库异常"
                voice.play_voice("db_error")
        else:
            print("测试失败", one_sn, tow_sn)
            text = "比较失败, 请检查后复位测试"
            color = wx.RED
            res = "NG"
            voice.play_voice("NG")
            test_error_str = "SN比较失败，请检查后复位测试"
        wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=3, text=text, color=color)
        file_path = MainFrame.heading_line_dict["102"] + "记录" + ".xlsx"
        title = ["日期", "测试结果", "SN1", "SN2"]
        now = datetime.now()
        # 格式化为字符串（默认格式）
        date_str = now.strftime("%Y-%m-%d %H:%M:%S")  # 输出示例: "2023-11-15"
        data = [date_str, res, one_sn, tow_sn]
        ret = excel.add_record_to_excel(file_path, title, data)
        print(ret[0], ret[1])
        if ret[0] is False:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui_item, num=3, text="记录文件写入异常，"+ret[1], color=wx.RED)
        test_work_state = "idle"
        barcode_msg_update = False
        tool.clear_queue(barcode_q)


def get_res(val=0xffff, val_min=0, val_max=0):
    if val == 0xffff:
        return "un_test"
    elif val_max >= val >= val_min:
        return "OK"
    else:
        return "NG"


# ---------- #[RV50-77-VER-CONFIG-EXT] 015/016/021 共用：基站版本 + 配置码 ----------
def rv50_fmt_ver_3bytes(dat, start):
    return ".".join(format(int(dat[i]), "03d") for i in range(start, start + 3))


def rv50_fmt_config_3bytes(dat, start):
    return ".".join(format(int(dat[i]) & 0xFF, "02x") for i in range(start, start + 3))


# #[RV50-OMINI-AIR-CONFIG-PUSH] 015/021：config.yaml 配置码经 0x57 下发治具
def rv50_parse_config_string_to_bytes(cfg_str):
    norm = normalize_config_triplet_hex(cfg_str)
    if not norm:
        s = (cfg_str or "").strip()
        if s:
            print("[RV50-OMINI-AIR-CONFIG-PUSH] 配置码格式错误，需 XX.XX.XX（十六进制）:", s)
        return None
    return [int(p, 16) for p in norm.split(".")]


def rv50air_get_config_str():
    return load_cfg.base_station_config_expected or ""


def rv50air_build_57_payload(sn_list):
    cfg_bytes = rv50_parse_config_string_to_bytes(rv50air_get_config_str())
    if cfg_bytes is None:
        return None
    return list(sn_list) + cfg_bytes


def rv50air_stop_config_push():
    global rv50air_config_push_active, rv50air_config_push_payload
    rv50air_config_push_active = False
    rv50air_config_push_payload = None


def rv50air_start_config_push(payload):
    global rv50air_config_push_active, rv50air_config_push_payload, rv50air_config_push_last_ms
    rv50air_config_push_payload = list(payload)
    rv50air_config_push_active = True
    rv50air_config_push_last_ms = time.time() * 1000.0
    ser_send_data(dev=15, cmd=0x57, data=rv50air_config_push_payload)


def rv50air_config_push_tick():
    global rv50air_config_push_last_ms
    if not rv50air_config_push_active or rv50air_config_push_payload is None:
        return
    if int(load_cfg.dev) != 15:
        return
    now_ms = time.time() * 1000.0
    if now_ms - rv50air_config_push_last_ms < AIR_CONFIG_PUSH_INTERVAL_MS:
        return
    rv50air_config_push_last_ms = now_ms
    ser_send_data(dev=15, cmd=0x57, data=rv50air_config_push_payload)


def ominiair_stop_config_push():
    global ominiair_config_push_active, ominiair_config_push_payload
    ominiair_config_push_active = False
    ominiair_config_push_payload = None


def ominiair_start_config_push(payload):
    global ominiair_config_push_active, ominiair_config_push_payload, ominiair_config_push_last_ms
    ominiair_config_push_payload = list(payload)
    ominiair_config_push_active = True
    ominiair_config_push_last_ms = time.time() * 1000.0
    ser_send_data(dev=21, cmd=0x57, data=ominiair_config_push_payload)


def ominiair_config_push_tick():
    global ominiair_config_push_last_ms
    if not ominiair_config_push_active or ominiair_config_push_payload is None:
        return
    if int(load_cfg.dev) != 21:
        return
    now_ms = time.time() * 1000.0
    if now_ms - ominiair_config_push_last_ms < AIR_CONFIG_PUSH_INTERVAL_MS:
        return
    ominiair_config_push_last_ms = now_ms
    ser_send_data(dev=21, cmd=0x57, data=ominiair_config_push_payload)


def rv50_omini_air_config_push_tick():
    rv50air_config_push_tick()
    ominiair_config_push_tick()


def rv50air_ui_result_for_config_readback(value, finalize):
    # #[RV50-OMINI-AIR-CONFIG-READBACK] 0x77 [10..12] 回读；未配 base_station_config_expected 时终判仍 monitor
    disp = value or ""
    if not finalize:
        return "monitor", disp
    ok = rv50_base_string_field_ok("base_config", value)
    if ok is None:
        return "monitor", disp
    if ok is True:
        return "pass", disp
    return "fail", disp


def rv50_omini_air_on_scan_pass(dev, sn_list):
    global rv50air_session_state, rv50air_last_step, rv50air_got_step3, rv50air_finalize_done
    global ominiair_session_state, ominiair_last_step, ominiair_got_step3, ominiair_finalize_done

    payload = rv50air_build_57_payload(sn_list)
    if payload is None:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second="基站配置码未配置或格式错误（需 XX.XX.XX 十六进制，如 00.00.17）",
                     color=wx.RED)
        return False
    wx.CallAfter(MainFrame.main_frame.up_test_ui,
                 name="base_station_config", result="monitor", value="")
    if dev == 15:
        rv50air_session_state = RV50AIR_SESS_RUNNING
        rv50air_last_step = -1
        rv50air_got_step3 = False
        rv50air_finalize_done = False
        rv50air_start_config_push(payload)
    elif dev == 21:
        ominiair_session_state = OMINIAIR_SESS_RUNNING
        ominiair_last_step = -1
        ominiair_got_step3 = False
        ominiair_finalize_done = False
        ominiair_start_config_push(payload)
    else:
        return False
    return True


def rv50_base_string_field_ok(field, actual):
    if field == "base_ver":
        return ver_triplet_matches(actual, load_cfg.mcu_ver)
    if field == "base_config":
        return config_triplet_matches(actual, load_cfg.base_station_config_expected)
    return False


def rv50_base_ui_result_for_string(field, value, finalize):
    disp = value or ""
    if not finalize:
        return "monitor", disp
    ok = rv50_base_string_field_ok(field, value)
    if ok is None or ok is True:
        return "pass", disp
    return "fail", disp


def rv50_base_add_string_report(name, field, value):
    ok = rv50_base_string_field_ok(field, value)
    if ok is None:
        return
    result = "OK" if ok else "NG"
    if field == "base_ver":
        expect = load_cfg.mcu_ver
    else:
        expect = load_cfg.base_station_config_expected
    mes_run.add_report(
        name=name, result=result, value=value or "",
        val_min=expect, val_max=expect,
    )


# ---------- #[RV50-016-WATER-PROTO] RV50 基站过水（device_type=016，帧 dev=0x10）----------
def rv50water_reset_session():
    global rv50water_session_state, rv50water_last_step, rv50water_last_p
    global rv50water_got_step3, rv50water_last_level_notify, rv50water_finalize_done
    rv50water_session_state = RV50WATER_SESS_IDLE
    rv50water_last_step = -1
    rv50water_last_p = None
    rv50water_got_step3 = False
    rv50water_last_level_notify = -1
    rv50water_finalize_done = False


def rv50water_u16_be(hi, lo):
    return ((int(hi) & 0xFF) << 8) | (int(lo) & 0xFF)


def rv50water_parse_77(dat, min_len=None):
    if min_len is None:
        min_len = RV50WATER_77_DATA_LEN
    if len(dat) < min_len:
        print("[RV50WATER] 0x77 数据区长度不足: got", len(dat), "need", min_len)
        return None
    p = {
        "step": int(dat[0]),
        "clear_water_volume": rv50water_u16_be(dat[1], dat[2]),
        "duty_water_volume": rv50water_u16_be(dat[3], dat[4]),
        "left_mop_water_volume": rv50water_u16_be(dat[5], dat[6]),
        "right_mop_water_volume": rv50water_u16_be(dat[7], dat[8]),
        "left_mop_temperature": rv50water_u16_be(dat[9], dat[10]),
        "right_mop_temperature": rv50water_u16_be(dat[11], dat[12]),
        "cleaner_liquid_level": int(dat[13]) & 0xFF,
        "base_hot_water_temp": rv50water_u16_be(dat[14], dat[15]),
        "base_ver": rv50_fmt_ver_3bytes(dat, 16),
        "base_config": rv50_fmt_config_3bytes(dat, 19),
    }
    if len(dat) >= RV50WATER_77_DATA_LEN:
        p["host_hot_water_temp"] = rv50water_u16_be(dat[22], dat[23])
    return p


RV50WATER_UI_LABELS = {
    "clear_water_volume": "清水通路水量：",
    "duty_water_volume": "污水通路水量：",
    "left_mop_water_volume": "左拖布水量：",
    "right_mop_water_volume": "右拖布水量：",
    "left_mop_temperature": "左拖布温度adc：",
    "right_mop_temperature": "右拖布温度adc：",
    "cleaner_liquid_level": "清洁剂液位：",
    "base_hot_water_temp": "基站热水温度adc：",
    "host_hot_water_temp": "主机注水口热水温度adc：",
    "base_station_ver": "基站版本：",
    "base_station_config": "基站配置码：",
}

RV50WATER_FIELD_REGISTRY = [
    {"field": "clear_vol", "kind": "exact_int", "ui": "clear_water_volume",
     "mes": "清水通路过水", "parse_key": "clear_water_volume",
     "expect_attr": "rv50water_clear_volume_expected"},
    {"field": "duty_vol", "kind": "exact_int", "ui": "duty_water_volume",
     "mes": "污水通路过水", "parse_key": "duty_water_volume",
     "expect_attr": "rv50water_duty_volume_expected"},
    {"field": "left_mop_vol", "kind": "exact_int", "ui": "left_mop_water_volume",
     "mes": "左拖布过水", "parse_key": "left_mop_water_volume",
     "expect_attr": "rv50water_left_mop_volume_expected"},
    {"field": "right_mop_vol", "kind": "exact_int", "ui": "right_mop_water_volume",
     "mes": "右拖布过水", "parse_key": "right_mop_water_volume",
     "expect_attr": "rv50water_right_mop_volume_expected"},
    {"field": "left_mop_temp", "kind": "range_int", "ui": "left_mop_temperature",
     "mes": "左拖布温度adc", "parse_key": "left_mop_temperature",
     "min_attr": "rv50water_left_mop_temp_min", "max_attr": "rv50water_left_mop_temp_max"},
    {"field": "right_mop_temp", "kind": "range_int", "ui": "right_mop_temperature",
     "mes": "右拖布温度adc", "parse_key": "right_mop_temperature",
     "min_attr": "rv50water_right_mop_temp_min", "max_attr": "rv50water_right_mop_temp_max"},
    {"field": "cleaner_level", "kind": "exact_int", "ui": "cleaner_liquid_level",
     "mes": "清洁剂液位", "parse_key": "cleaner_liquid_level",
     "expect_attr": "rv50water_cleaner_level_expected"},
    {"field": "base_hot_temp", "kind": "range_int", "ui": "base_hot_water_temp",
     "mes": "基站热水温度adc", "parse_key": "base_hot_water_temp",
     "min_attr": "rv50water_base_hot_temp_min", "max_attr": "rv50water_base_hot_temp_max"},
    {"field": "base_ver", "kind": "version", "ui": "base_station_ver", "mes": "基站版本",
     "parse_key": "base_ver"},
    {"field": "base_config", "kind": "string", "ui": "base_station_config", "mes": "基站配置码",
     "parse_key": "base_config", "expect_attr": "base_station_config_expected"},
    {"field": "host_hot_temp", "kind": "range_int", "ui": "host_hot_water_temp",
     "mes": "主机注水口热水温度adc", "parse_key": "host_hot_water_temp",
     "min_attr": "rv50water_host_hot_temp_min", "max_attr": "rv50water_host_hot_temp_max"},
]


def _rv50water_registry_entry(field):
    for entry in RV50WATER_FIELD_REGISTRY:
        if entry["field"] == field:
            return entry
    return None


def _rv50water_range_enabled(lo, hi):
    return not (int(lo) == 0 and int(hi) == 0)


def _rv50water_exact_enabled(expect_attr):
    return int(getattr(load_cfg, expect_attr, -1)) >= 0


def rv50water_field_enabled(field):
    entry = _rv50water_registry_entry(field)
    if entry is None:
        return False
    kind = entry["kind"]
    if kind == "exact_int":
        return _rv50water_exact_enabled(entry.get("expect_attr", ""))
    if kind == "range_int":
        lo = getattr(load_cfg, entry["min_attr"], 0)
        hi = getattr(load_cfg, entry["max_attr"], 0)
        return _rv50water_range_enabled(lo, hi)
    if kind == "version":
        return bool((load_cfg.mcu_ver or "").strip())
    if kind == "string":
        expect = getattr(load_cfg, entry.get("expect_attr", ""), "")
        return bool(str(expect).strip())
    return False


def rv50water_build_item_result():
    items = []
    for entry in RV50WATER_FIELD_REGISTRY:
        if entry["ui"] == "base_station_config" and not base_station_config_ui_enabled():
            continue
        if rv50water_field_enabled(entry["field"]):
            ui = entry["ui"]
            items.append({ui: [RV50WATER_UI_LABELS[ui], "", "white"]})
    return items


def rv50water_int_limits(field):
    entry = _rv50water_registry_entry(field)
    if entry is None:
        return 0, 0
    return (
        int(getattr(load_cfg, entry["min_attr"], 0)),
        int(getattr(load_cfg, entry["max_attr"], 0)),
    )


def rv50water_field_ok(p, field):
    if not rv50water_field_enabled(field):
        return None
    if p is None:
        return False
    entry = _rv50water_registry_entry(field)
    if entry is None:
        return None
    kind = entry["kind"]
    if kind == "exact_int":
        expect = int(getattr(load_cfg, entry.get("expect_attr", ""), -1))
        actual = p.get(entry.get("parse_key"))
        if actual is None:
            return False
        return int(actual) == expect
    if kind == "range_int":
        val = p.get(entry.get("parse_key"))
        if val is None:
            return False
        lo, hi = rv50water_int_limits(field)
        if lo > hi:
            lo, hi = hi, lo
        v = int(val)
        return lo <= v <= hi
    if kind == "version":
        return ver_triplet_matches(p.get("base_ver"), load_cfg.mcu_ver)
    if kind == "string":
        return config_triplet_matches(
            p.get("base_config"), load_cfg.base_station_config_expected)
    return None


def rv50water_all_ok(p):
    if p is None:
        return False
    for entry in RV50WATER_FIELD_REGISTRY:
        ok = rv50water_field_ok(p, entry["field"])
        if ok is False:
            return False
    return True


def rv50water_ui_result_for_field(field, p, finalize):
    entry = _rv50water_registry_entry(field)
    if entry is None:
        return "monitor", ""
    kind = entry["kind"]
    if kind in ("exact_int", "range_int"):
        val = p.get(entry.get("parse_key")) if p else None
        disp = "" if val is None else str(val)
        if not finalize:
            return "monitor", disp
        ok = rv50water_field_ok(p, field)
        if ok is None or ok is True:
            return "pass", disp
        return "fail", disp
    if kind == "version":
        return rv50water_ui_result_for_string("base_ver", p.get("base_ver") if p else None, finalize)
    if kind == "string":
        return rv50water_ui_result_for_string("base_config", p.get("base_config") if p else None, finalize)
    return "monitor", ""


def rv50water_string_field_ok(field, actual):
    if field == "base_ver":
        return ver_triplet_matches(actual, load_cfg.mcu_ver)
    if field == "base_config":
        return config_triplet_matches(actual, load_cfg.base_station_config_expected)
    return None


def rv50water_ui_result_for_string(field, value, finalize):
    disp = value or ""
    if not finalize:
        return "monitor", disp
    ok = rv50water_string_field_ok(field, value)
    if ok is None or ok is True:
        return "pass", disp
    return "fail", disp


def _rv50water_refresh_test_ui_impl(p, finalize):
    if p is None:
        return
    for entry in RV50WATER_FIELD_REGISTRY:
        field = entry["field"]
        if not rv50water_field_enabled(field):
            continue
        res, val = rv50water_ui_result_for_field(field, p, finalize)
        MainFrame.main_frame.up_test_ui(name=entry["ui"], result=res, value=val)


def rv50water_add_string_report(name, field, value):
    ok = rv50water_string_field_ok(field, value)
    if ok is None:
        return
    result = "OK" if ok else "NG"
    if field == "base_ver":
        expect = load_cfg.mcu_ver
    else:
        expect = load_cfg.base_station_config_expected
    mes_run.add_report(
        name=name, result=result, value=value or "",
        val_min=expect, val_max=expect,
    )


def rv50water_add_reports(p):
    if p is None:
        for entry in RV50WATER_FIELD_REGISTRY:
            if not rv50water_field_enabled(entry["field"]):
                continue
            mes_run.add_report(name=entry["mes"], result="NG", value="无数据")
        return
    for entry in RV50WATER_FIELD_REGISTRY:
        field = entry["field"]
        if not rv50water_field_enabled(field):
            continue
        kind = entry["kind"]
        if kind == "exact_int":
            val = p.get(entry.get("parse_key"))
            expect = int(getattr(load_cfg, entry.get("expect_attr", ""), -1))
            mes_run.add_report(
                name=entry["mes"],
                result="OK" if rv50water_field_ok(p, field) else "NG",
                value=str(val) if val is not None else "",
                val_min=expect,
                val_max=expect,
            )
        elif kind == "range_int":
            val = p.get(entry.get("parse_key"))
            lo, hi = rv50water_int_limits(field)
            mes_run.add_report(
                name=entry["mes"],
                result="OK" if rv50water_field_ok(p, field) else "NG",
                value=str(val) if val is not None else "",
                val_min=lo,
                val_max=hi,
            )
        elif field == "base_ver":
            rv50water_add_string_report(entry["mes"], "base_ver", p.get("base_ver"))
        elif field == "base_config":
            rv50water_add_string_report(entry["mes"], "base_config", p.get("base_config"))


def rv50water_refresh_test_ui_callafter(p, finalize=False):
    wx.CallAfter(_rv50water_refresh_test_ui_impl, p, finalize)


def rv50water_step_notify(step):
    st = int(step)
    if st == 1:
        msg = "进入产测"
    elif st == 3:
        msg = "最终判断结果"
    else:
        msg = "治具步骤：" + str(st)
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=msg, color=wx.BLUE)


def rv50water_level_notify(level):
    global rv50water_last_level_notify
    lv = int(level) & 0xFF
    if lv == rv50water_last_level_notify:
        return
    rv50water_last_level_notify = lv
    if lv == 0x01:
        msg = "清洁液不在位，请插入"
        color = wx.RED
    elif lv == 0x02:
        msg = "清洁液在位，请取出"
        color = wx.RED
    elif lv == 0x03:
        msg = "清洁液盒通过，请确保取出"
        color = wx.GREEN
    else:
        msg = "请注意后续操作提示"
        color = wx.RED
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=msg, color=color)


def rv50water_finalize_88(dev, dat):
    global test_end_time, rv50water_session_state, rv50water_last_p, rv50water_got_step3
    global rv50water_finalize_done
    if rv50water_finalize_done:
        print("[RV50-016-WATER] 重复 0x88，忽略")
        return

    test_end_time = datetime.now()
    print("[RV50-016-WATER] 测试结束帧 dat=" + str(dat))

    res_byte = dat[0] if len(dat) else 0xFF
    if res_byte == 0x04:
        mes_run.add_report(name="基站通讯", result="NG", value="治具与基站通讯失败")
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="治具与基站通讯失败", color=wx.RED)
        clear_sn_save_list()
        rv50water_session_state = RV50WATER_SESS_FINISHED
        rv50water_finalize_done = True
        return

    if res_byte != 0x03:
        mes_run.add_report(name="结束码", result="NG", value=hex(res_byte))
        res_display_str = "测试结束 NG（结束码 {}）".format(hex(res_byte))
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second=res_display_str, color=wx.RED)
        clear_sn_save_list()
        rv50water_session_state = RV50WATER_SESS_FINISHED
        rv50water_finalize_done = True
        return

    p = rv50water_last_p
    mes_ok = rv50water_got_step3 and p is not None and rv50water_all_ok(p)
    rv50water_add_reports(p)
    if mes_ok:
        res_display_str = "测试完成 PASS"
        text_color = wx.GREEN
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
    else:
        if not rv50water_got_step3:
            res_display_str = "测试结束 NG（未到最终判断步骤）"
        elif p is None:
            res_display_str = "测试结束 NG（无结果数据）"
        else:
            res_display_str = "测试结束 NG（测试项未达标）"
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")

    if p is not None:
        rv50water_refresh_test_ui_callafter(p, finalize=True)
    if mes_ret:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second=res_display_str, color=text_color)
    clear_sn_save_list()
    rv50water_session_state = RV50WATER_SESS_FINISHED
    rv50water_finalize_done = True


def RV50_water_mode(dev, cmd, dat):
    global test_start_time, check_sn_enable
    global rv50water_session_state, rv50water_last_step, rv50water_last_p, rv50water_got_step3

    if len(dat) <= 0:
        print("[RV50-016-WATER] len=0 无有效数据")
        return

    if cmd == 0x66:
        if dat[0] == 0x00:
            fixture_all_reply_bursts_stop()
            test_start_time = datetime.now()
            mes_run.clear_report()
            tool.clear_queue(barcode_q)
            check_sn_enable = True
            rv50water_reset_session()
            rv50water_session_state = RV50WATER_SESS_WAIT_SN
            print("[RV50-016-WATER] 请扫码")
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
    elif cmd == 0x77:
        if rv50water_session_state != RV50WATER_SESS_RUNNING:
            return
        fixture_gate_burst_cancel_on_first_77()
        p = rv50water_parse_77(dat, min_len=RV50WATER_77_DATA_LEN)
        if p is None:
            return
        rv50water_last_p = p
        st = int(p["step"])
        print("[RV50-016-WATER] 0x77 step=" + str(st) + " p=" + str(p))
        rv50water_refresh_test_ui_callafter(p, finalize=False)
        if st == 3:
            rv50water_got_step3 = True
        if st != rv50water_last_step:
            rv50water_last_step = st
            if st in (1, 3):
                rv50water_step_notify(st)
        if st == 2 and rv50water_field_enabled("cleaner_level"):
            rv50water_level_notify(p.get("cleaner_liquid_level"))
    elif cmd == 0x88:
        rv50water_finalize_88(dev, dat)
    # elif cmd == 0x68:
    #     print("[RV50-016-WATER] 忽略 0x68 len=" + str(len(dat)))
    # else:
    #     print("[RV50-016-WATER] 未处理命令 cmd=" + hex(cmd))


# ---------- #[RV50-015-AIR-PROTO] RV50 基站过气（device_type=015，帧 dev=0x0F）----------
def rv50air_reset_session():
    global rv50air_session_state, rv50air_last_step, rv50air_last_p, rv50air_got_step3
    global rv50air_finalize_done
    rv50air_stop_config_push()
    rv50air_session_state = RV50AIR_SESS_IDLE
    rv50air_last_step = -1
    rv50air_last_p = None
    rv50air_got_step3 = False
    rv50air_finalize_done = False


def rv50air_u16_be(hi, lo):
    return ((int(hi) & 0xFF) << 8) | (int(lo) & 0xFF)


def rv50air_parse_77(dat):
    if len(dat) < RV50AIR_77_DATA_LEN:
        print("[RV50-015-AIR] 0x77 数据区长度不足: got", len(dat),
              "need", RV50AIR_77_DATA_LEN)
        return None
    step = int(dat[0])
    raw_clear = rv50air_u16_be(dat[1], dat[2])
    raw_mop = rv50air_u16_be(dat[3], dat[4])
    raw_duty = wsxqmx_bytes_to_int16(dat[5], dat[6])
    return {
        "step": step,
        "clear_kpa": wsxqmx_raw_to_kpa(raw_clear),
        "mop_kpa": wsxqmx_raw_to_kpa(raw_mop),
        "duty_kpa": wsxqmx_raw_to_kpa(raw_duty),
        "base_ver": rv50_fmt_ver_3bytes(dat, 7),
        "base_config": rv50_fmt_config_3bytes(dat, 10),
    }


RV50AIR_UI_LABELS = {
    "clear_water_pressure": "清水通路气压(kPa)：",
    "duty_water_pressure": "污水通路气压(kPa)：",
    "mop_water_pressure": "拖布通路气压(kPa)：",
    "base_station_ver": "基站版本：",
    "base_station_config": "基站配置码：",
}

RV50AIR_FIELD_REGISTRY = [
    {"field": "clear", "kind": "range_kpa", "ui": "clear_water_pressure", "mes": "清水通路气压",
     "min_attr": "rv50air_clear_kpa_min", "max_attr": "rv50air_clear_kpa_max"},
    {"field": "mop", "kind": "range_kpa", "ui": "mop_water_pressure", "mes": "拖布通路气压",
     "min_attr": "rv50air_mop_kpa_min", "max_attr": "rv50air_mop_kpa_max"},
    {"field": "duty", "kind": "range_kpa", "ui": "duty_water_pressure", "mes": "污水通路气压",
     "min_attr": "rv50air_duty_kpa_min", "max_attr": "rv50air_duty_kpa_max"},
    {"field": "base_ver", "kind": "version", "ui": "base_station_ver", "mes": "基站版本"},
    {"field": "base_config", "kind": "string", "ui": "base_station_config", "mes": "基站配置码",
     "expect_attr": "base_station_config_expected"},
]


def _rv50air_kpa_range_enabled(lo, hi):
    return not (float(lo) == 0.0 and float(hi) == 0.0)


def _rv50air_registry_entry(field):
    for entry in RV50AIR_FIELD_REGISTRY:
        if entry["field"] == field:
            return entry
    return None


def rv50air_field_enabled(field):
    entry = _rv50air_registry_entry(field)
    if entry is None:
        return False
    kind = entry["kind"]
    if kind == "range_kpa":
        lo = getattr(load_cfg, entry["min_attr"], 0.0)
        hi = getattr(load_cfg, entry["max_attr"], 0.0)
        return _rv50air_kpa_range_enabled(lo, hi)
    if kind == "version":
        return bool((load_cfg.mcu_ver or "").strip())
    if kind == "string":
        expect = getattr(load_cfg, entry.get("expect_attr", ""), "")
        return bool(str(expect).strip())
    return False


def rv50air_build_item_result():
    items = []
    for entry in RV50AIR_FIELD_REGISTRY:
        field = entry["field"]
        if field == "base_config":
            if base_station_config_ui_enabled():
                items.append({entry["ui"]: [RV50AIR_UI_LABELS[entry["ui"]], "", "white"]})
        elif rv50air_field_enabled(field):
            items.append({entry["ui"]: [RV50AIR_UI_LABELS[entry["ui"]], "", "white"]})
    return items


def rv50air_kpa_limits(field):
    entry = _rv50air_registry_entry(field)
    if entry is None:
        return 0.0, 0.0
    return (
        float(getattr(load_cfg, entry["min_attr"], 0.0)),
        float(getattr(load_cfg, entry["max_attr"], 0.0)),
    )


def rv50air_field_ok(p, field):
    if not rv50air_field_enabled(field):
        return None
    if p is None:
        return False
    entry = _rv50air_registry_entry(field)
    if entry is None:
        return None
    kind = entry["kind"]
    if kind == "range_kpa":
        kpa = p.get({"clear": "clear_kpa", "mop": "mop_kpa", "duty": "duty_kpa"}.get(field))
        if kpa is None:
            return False
        lo, hi = rv50air_kpa_limits(field)
        if lo > hi:
            lo, hi = hi, lo
        return lo <= kpa <= hi
    if kind == "string" and field == "base_config":
        return rv50air_string_field_ok("base_config", p.get("base_config"))
    if kind == "version":
        return ver_triplet_matches(p.get("base_ver"), load_cfg.mcu_ver)
    return None


def rv50air_string_field_ok(field, actual):
    if field == "base_ver":
        return ver_triplet_matches(actual, load_cfg.mcu_ver)
    if field == "base_config":
        return config_triplet_matches(actual, load_cfg.base_station_config_expected)
    return None


def rv50air_all_ok(p):
    if p is None:
        return False
    for entry in RV50AIR_FIELD_REGISTRY:
        ok = rv50air_field_ok(p, entry["field"])
        if ok is False:
            return False
    return True


def rv50air_fmt_kpa(kpa):
    if kpa is None:
        return ""
    return "{:.2f}".format(kpa)


def _rv50air_kpa_field_ok(field, kpa):
    if not rv50air_field_enabled(field):
        return None
    if kpa is None:
        return False
    lo, hi = rv50air_kpa_limits(field)
    if lo > hi:
        lo, hi = hi, lo
    return lo <= kpa <= hi


def rv50air_ui_result_for_kpa(field, kpa, finalize):
    if not finalize:
        return "monitor", rv50air_fmt_kpa(kpa)
    ok = _rv50air_kpa_field_ok(field, kpa)
    if ok is None or ok is True:
        return "pass", rv50air_fmt_kpa(kpa)
    return "fail", rv50air_fmt_kpa(kpa)


def rv50air_ui_result_for_string(field, value, finalize):
    disp = value or ""
    if not finalize:
        return "monitor", disp
    ok = rv50air_string_field_ok(field, value)
    if ok is None or ok is True:
        return "pass", disp
    return "fail", disp


def _rv50air_refresh_test_ui_impl(p, finalize):
    if p is None:
        return
    _kpa_map = {
        "clear": p.get("clear_kpa"),
        "mop": p.get("mop_kpa"),
        "duty": p.get("duty_kpa"),
    }
    for entry in RV50AIR_FIELD_REGISTRY:
        field = entry["field"]
        if field == "base_config":
            continue
        if not rv50air_field_enabled(field):
            continue
        if entry["kind"] == "range_kpa":
            res, val = rv50air_ui_result_for_kpa(field, _kpa_map.get(field), finalize)
        elif field == "base_ver":
            res, val = rv50air_ui_result_for_string("base_ver", p.get("base_ver"), finalize)
        else:
            continue
        MainFrame.main_frame.up_test_ui(name=entry["ui"], result=res, value=val)
    res, val = rv50air_ui_result_for_config_readback(p.get("base_config"), finalize)
    MainFrame.main_frame.up_test_ui(name="base_station_config", result=res, value=val)


def rv50air_add_string_report(name, field, value):
    ok = rv50air_string_field_ok(field, value)
    if ok is None:
        return
    result = "OK" if ok else "NG"
    if field == "base_ver":
        expect = load_cfg.mcu_ver
    else:
        expect = load_cfg.base_station_config_expected
    mes_run.add_report(
        name=name, result=result, value=value or "",
        val_min=expect, val_max=expect,
    )


def rv50air_add_reports(p):
    if p is None:
        for entry in RV50AIR_FIELD_REGISTRY:
            if not rv50air_field_enabled(entry["field"]):
                continue
            elif entry["field"] == "base_config":
                rv50air_add_string_report(entry["mes"], "base_config", None)
            else:
                mes_run.add_report(name=entry["mes"], result="NG", value="无数据")
        return
    for entry in RV50AIR_FIELD_REGISTRY:
        field = entry["field"]
        if not rv50air_field_enabled(field):
            continue
        if entry["kind"] == "range_kpa":
            kpa_key = {"clear": "clear_kpa", "mop": "mop_kpa", "duty": "duty_kpa"}[field]
            kpa = p.get(kpa_key)
            lo, hi = rv50air_kpa_limits(field)
            mes_run.add_report(
                name=entry["mes"],
                result="OK" if _rv50air_kpa_field_ok(field, kpa) else "NG",
                value=rv50air_fmt_kpa(kpa),
                val_min=lo,
                val_max=hi,
            )
        elif field == "base_ver":
            rv50air_add_string_report(entry["mes"], "base_ver", p.get("base_ver"))
        elif field == "base_config":
            rv50air_add_string_report(entry["mes"], "base_config", p.get("base_config"))


def rv50air_refresh_test_ui_callafter(p, finalize=False):
    wx.CallAfter(_rv50air_refresh_test_ui_impl, p, finalize)


def rv50air_step_notify(step):
    st = int(step)
    if st == 1:
        msg = "进入产测"
    elif st == 2:
        msg = "测试中"
    elif st == 3:
        msg = "结果上传"
    else:
        msg = "治具步骤：" + str(st)
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=msg, color=wx.BLUE)


def rv50air_finalize_88(dev, dat):
    global test_end_time, rv50air_session_state, rv50air_last_p, rv50air_got_step3
    global rv50air_finalize_done
    if rv50air_finalize_done:
        print("[RV50-015-AIR] 重复 0x88，忽略")
        return

    test_end_time = datetime.now()
    print("[RV50-015-AIR] 测试结束帧 dat=" + str(dat))

    res_byte = dat[0] if len(dat) else 0xFF
    if res_byte == 0x04:
        mes_run.add_report(name="基站通讯", result="NG", value="治具与基站通讯失败")
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="治具与基站通讯失败", color=wx.RED)
        clear_sn_save_list()
        rv50air_session_state = RV50AIR_SESS_FINISHED
        rv50air_finalize_done = True
        return

    if res_byte != 0x03:
        mes_run.add_report(name="结束码", result="NG", value=hex(res_byte))
        res_display_str = "测试结束 NG（结束码 {}）".format(hex(res_byte))
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second=res_display_str, color=wx.RED)
        clear_sn_save_list()
        rv50air_session_state = RV50AIR_SESS_FINISHED
        rv50air_finalize_done = True
        return

    p = rv50air_last_p
    mes_ok = rv50air_got_step3 and p is not None and rv50air_all_ok(p)
    rv50air_add_reports(p)
    if mes_ok:
        res_display_str = "测试完成 PASS"
        text_color = wx.GREEN
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
    else:
        if not rv50air_got_step3:
            res_display_str = "测试结束 NG（未到结果上传步骤）"
        elif p is None:
            res_display_str = "测试结束 NG（无结果数据）"
        else:
            res_display_str = "测试结束 NG（测试项未达标）"
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")

    if p is not None:
        rv50air_refresh_test_ui_callafter(p, finalize=True)
    if mes_ret:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second=res_display_str, color=text_color)
    clear_sn_save_list()
    rv50air_session_state = RV50AIR_SESS_FINISHED
    rv50air_finalize_done = True


def RV50_air_mode(dev, cmd, dat):
    global test_start_time, check_sn_enable
    global rv50air_session_state, rv50air_last_step, rv50air_last_p, rv50air_got_step3

    if len(dat) <= 0:
        print("[RV50-015-AIR] len=0 无有效数据")
        return

    if cmd == 0x66:
        if dat[0] == 0x00:
            fixture_all_reply_bursts_stop()
            test_start_time = datetime.now()
            mes_run.clear_report()
            tool.clear_queue(barcode_q)
            check_sn_enable = True
            rv50air_reset_session()
            rv50air_session_state = RV50AIR_SESS_WAIT_SN
            print("[RV50-015-AIR] 请扫码")
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
    elif cmd == 0x77:
        if rv50air_session_state != RV50AIR_SESS_RUNNING:
            return
        rv50air_stop_config_push()
        p = rv50air_parse_77(dat)
        if p is None:
            return
        rv50air_last_p = p
        st = int(p["step"])
        print("[RV50-015-AIR] 0x77 step=" + str(st) + " p=" + str(p))
        rv50air_refresh_test_ui_callafter(p, finalize=False)
        if st == 3:
            rv50air_got_step3 = True
        if st != rv50air_last_step:
            rv50air_last_step = st
            rv50air_step_notify(st)
    elif cmd == 0x88:
        rv50air_finalize_88(dev, dat)
    # elif cmd == 0x68:
    #     print("[RV50-015-AIR] 忽略 0x68 len=" + str(len(dat)))
    # else:
    #     print("[RV50-015-AIR] 未处理命令 cmd=" + hex(cmd))


# ---------- #[OMINIAIR-021-PROTO] Omini 基站过气（device_type=021，帧 dev=0x15）----------
OMINIAIR_UI_LABELS = {
    "clear_water_pressure": "清水通路气压(kPa)：",
    "duty_water_pressure": "污水通路气压(kPa)：",
    "mop_water_pressure": "拖布通路气压(kPa)：",
    "base_station_ver": "基站版本：",
    "base_station_config": "基站配置码：",
}

OMINIAIR_FIELD_REGISTRY = [
    {"field": "clear", "kind": "range_kpa", "ui": "clear_water_pressure", "mes": "清水通路气压",
     "min_attr": "ominiair_clear_kpa_min", "max_attr": "ominiair_clear_kpa_max"},
    {"field": "mop", "kind": "range_kpa", "ui": "mop_water_pressure", "mes": "拖布通路气压",
     "min_attr": "ominiair_mop_kpa_min", "max_attr": "ominiair_mop_kpa_max"},
    {"field": "duty", "kind": "range_kpa", "ui": "duty_water_pressure", "mes": "污水通路气压",
     "min_attr": "ominiair_duty_kpa_min", "max_attr": "ominiair_duty_kpa_max"},
    {"field": "base_ver", "kind": "version", "ui": "base_station_ver", "mes": "基站版本"},
    {"field": "base_config", "kind": "string", "ui": "base_station_config", "mes": "基站配置码",
     "expect_attr": "base_station_config_expected"},
]


def _ominiair_kpa_range_enabled(lo, hi):
    return not (float(lo) == 0.0 and float(hi) == 0.0)


def _ominiair_registry_entry(field):
    for entry in OMINIAIR_FIELD_REGISTRY:
        if entry["field"] == field:
            return entry
    return None


def ominiair_field_enabled(field):
    entry = _ominiair_registry_entry(field)
    if entry is None:
        return False
    kind = entry["kind"]
    if kind == "range_kpa":
        lo = getattr(load_cfg, entry["min_attr"], 0.0)
        hi = getattr(load_cfg, entry["max_attr"], 0.0)
        return _ominiair_kpa_range_enabled(lo, hi)
    if kind == "version":
        return bool((load_cfg.mcu_ver or "").strip())
    if kind == "string":
        expect = getattr(load_cfg, entry.get("expect_attr", ""), "")
        return bool(str(expect).strip())
    return False


def ominiair_build_item_result():
    items = []
    for entry in OMINIAIR_FIELD_REGISTRY:
        field = entry["field"]
        if field == "base_config":
            if base_station_config_ui_enabled():
                items.append({entry["ui"]: [OMINIAIR_UI_LABELS[entry["ui"]], "", "white"]})
        elif ominiair_field_enabled(field):
            items.append({entry["ui"]: [OMINIAIR_UI_LABELS[entry["ui"]], "", "white"]})
    return items


def ominiair_reset_session():
    global ominiair_session_state, ominiair_last_step, ominiair_last_p, ominiair_got_step3
    global ominiair_finalize_done
    ominiair_stop_config_push()
    ominiair_session_state = OMINIAIR_SESS_IDLE
    ominiair_last_step = -1
    ominiair_last_p = None
    ominiair_got_step3 = False
    ominiair_finalize_done = False


def ominiair_parse_77(dat):
    if len(dat) < OMINIAIR_77_DATA_LEN:
        print("[OMINI-021-AIR] 0x77 数据区长度不足: got", len(dat),
              "need", OMINIAIR_77_DATA_LEN)
        return None
    raw_clear = rv50air_u16_be(dat[1], dat[2])
    raw_mop = rv50air_u16_be(dat[3], dat[4])
    raw_duty = wsxqmx_bytes_to_int16(dat[5], dat[6])
    return {
        "step": int(dat[0]),
        "clear_kpa": wsxqmx_raw_to_kpa(raw_clear),
        "mop_kpa": wsxqmx_raw_to_kpa(raw_mop),
        "duty_kpa": wsxqmx_raw_to_kpa(raw_duty),
        "base_ver": rv50_fmt_ver_3bytes(dat, 7),
        "base_config": rv50_fmt_config_3bytes(dat, 10),
    }


def ominiair_kpa_limits(field):
    entry = _ominiair_registry_entry(field)
    if entry is None:
        return 0.0, 0.0
    return (
        float(getattr(load_cfg, entry["min_attr"], 0.0)),
        float(getattr(load_cfg, entry["max_attr"], 0.0)),
    )


def ominiair_field_ok(p, field):
    if not ominiair_field_enabled(field):
        return None
    if p is None:
        return False
    entry = _ominiair_registry_entry(field)
    if entry is None:
        return None
    kind = entry["kind"]
    if kind == "range_kpa":
        kpa = p.get({"clear": "clear_kpa", "mop": "mop_kpa", "duty": "duty_kpa"}.get(field))
        if kpa is None:
            return False
        lo, hi = ominiair_kpa_limits(field)
        if lo > hi:
            lo, hi = hi, lo
        return lo <= kpa <= hi
    if kind == "string" and field == "base_config":
        return ominiair_string_field_ok("base_config", p.get("base_config"))
    if kind == "version":
        return ver_triplet_matches(p.get("base_ver"), load_cfg.mcu_ver)
    return None


def ominiair_all_ok(p):
    if p is None:
        return False
    for entry in OMINIAIR_FIELD_REGISTRY:
        ok = ominiair_field_ok(p, entry["field"])
        if ok is False:
            return False
    return True


def ominiair_fmt_kpa(kpa):
    if kpa is None:
        return ""
    return "{:.2f}".format(kpa)


def ominiair_step_notify(step):
    st = int(step)
    if st == 1:
        msg = "进入产测"
    elif st == 2:
        msg = "测试中"
    elif st == 3:
        msg = "结果上传"
    else:
        msg = "治具步骤：" + str(st)
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=msg, color=wx.BLUE)


def _ominiair_kpa_field_ok(field, kpa):
    if not ominiair_field_enabled(field):
        return None
    if kpa is None:
        return False
    lo, hi = ominiair_kpa_limits(field)
    if lo > hi:
        lo, hi = hi, lo
    return lo <= kpa <= hi


def ominiair_ui_result_for_kpa(field, kpa, finalize):
    if not finalize:
        return "monitor", ominiair_fmt_kpa(kpa)
    ok = _ominiair_kpa_field_ok(field, kpa)
    if ok is None or ok is True:
        return "pass", ominiair_fmt_kpa(kpa)
    return "fail", ominiair_fmt_kpa(kpa)


def ominiair_string_field_ok(field, actual):
    if field == "base_ver":
        return ver_triplet_matches(actual, load_cfg.mcu_ver)
    if field == "base_config":
        return config_triplet_matches(actual, load_cfg.base_station_config_expected)
    return None


def ominiair_ui_result_for_string(field, value, finalize):
    disp = value or ""
    if not finalize:
        return "monitor", disp
    ok = ominiair_string_field_ok(field, value)
    if ok is None or ok is True:
        return "pass", disp
    return "fail", disp


def _ominiair_refresh_test_ui_impl(p, finalize):
    if p is None:
        return
    _kpa_map = {
        "clear": p.get("clear_kpa"),
        "mop": p.get("mop_kpa"),
        "duty": p.get("duty_kpa"),
    }
    for entry in OMINIAIR_FIELD_REGISTRY:
        field = entry["field"]
        if field == "base_config":
            continue
        if not ominiair_field_enabled(field):
            continue
        if entry["kind"] == "range_kpa":
            res, val = ominiair_ui_result_for_kpa(field, _kpa_map.get(field), finalize)
        elif field == "base_ver":
            res, val = ominiair_ui_result_for_string("base_ver", p.get("base_ver"), finalize)
        else:
            continue
        MainFrame.main_frame.up_test_ui(name=entry["ui"], result=res, value=val)
    res, val = rv50air_ui_result_for_config_readback(p.get("base_config"), finalize)
    MainFrame.main_frame.up_test_ui(name="base_station_config", result=res, value=val)


def ominiair_refresh_test_ui_callafter(p, finalize=False):
    wx.CallAfter(_ominiair_refresh_test_ui_impl, p, finalize)


def ominiair_add_string_report(name, field, value):
    ok = ominiair_string_field_ok(field, value)
    if ok is None:
        return
    result = "OK" if ok else "NG"
    if field == "base_ver":
        expect = load_cfg.mcu_ver
    else:
        expect = load_cfg.base_station_config_expected
    mes_run.add_report(
        name=name, result=result, value=value or "",
        val_min=expect, val_max=expect,
    )


def ominiair_add_reports(p):
    if p is None:
        for entry in OMINIAIR_FIELD_REGISTRY:
            if not ominiair_field_enabled(entry["field"]):
                continue
            elif entry["field"] == "base_config":
                ominiair_add_string_report(entry["mes"], "base_config", None)
            else:
                mes_run.add_report(name=entry["mes"], result="NG", value="无数据")
        return
    for entry in OMINIAIR_FIELD_REGISTRY:
        field = entry["field"]
        if not ominiair_field_enabled(field):
            continue
        if entry["kind"] == "range_kpa":
            kpa_key = {"clear": "clear_kpa", "mop": "mop_kpa", "duty": "duty_kpa"}[field]
            kpa = p.get(kpa_key)
            lo, hi = ominiair_kpa_limits(field)
            mes_run.add_report(
                name=entry["mes"],
                result="OK" if _ominiair_kpa_field_ok(field, kpa) else "NG",
                value=ominiair_fmt_kpa(kpa),
                val_min=lo,
                val_max=hi,
            )
        elif field == "base_ver":
            ominiair_add_string_report(entry["mes"], "base_ver", p.get("base_ver"))
        elif field == "base_config":
            ominiair_add_string_report(entry["mes"], "base_config", p.get("base_config"))


def ominiair_finalize_88(dev, dat):
    global test_end_time, ominiair_session_state, ominiair_last_p, ominiair_got_step3
    global ominiair_finalize_done
    if ominiair_finalize_done:
        print("[OMINI-021-AIR] 重复 0x88，忽略")
        return

    test_end_time = datetime.now()
    print("[OMINI-021-AIR] 测试结束帧 dat=" + str(dat))

    res_byte = dat[0] if len(dat) else 0xFF
    if res_byte == 0x04:
        mes_run.add_report(name="基站通讯", result="NG", value="治具与基站通讯失败")
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="治具与基站通讯失败", color=wx.RED)
        clear_sn_save_list()
        ominiair_session_state = OMINIAIR_SESS_FINISHED
        ominiair_finalize_done = True
        return

    if res_byte != 0x03:
        mes_run.add_report(name="结束码", result="NG", value=hex(res_byte))
        res_display_str = "测试结束 NG（结束码 {}）".format(hex(res_byte))
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second=res_display_str, color=wx.RED)
        clear_sn_save_list()
        ominiair_session_state = OMINIAIR_SESS_FINISHED
        ominiair_finalize_done = True
        return

    p = ominiair_last_p
    mes_ok = ominiair_got_step3 and p is not None and ominiair_all_ok(p)
    ominiair_add_reports(p)
    if mes_ok:
        res_display_str = "测试完成 PASS"
        text_color = wx.GREEN
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
    else:
        if not ominiair_got_step3:
            res_display_str = "测试结束 NG（未到结果上传步骤）"
        elif p is None:
            res_display_str = "测试结束 NG（无结果数据）"
        else:
            res_display_str = "测试结束 NG（测试项未达标）"
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")

    if p is not None:
        ominiair_refresh_test_ui_callafter(p, finalize=True)
    if mes_ret:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second=res_display_str, color=text_color)
    clear_sn_save_list()
    ominiair_session_state = OMINIAIR_SESS_FINISHED
    ominiair_finalize_done = True


def Omini_air_mode(dev, cmd, dat):
    global test_start_time, check_sn_enable
    global ominiair_session_state, ominiair_last_step, ominiair_last_p, ominiair_got_step3

    if len(dat) <= 0:
        print("[OMINI-021-AIR] len=0 无有效数据")
        return

    if cmd == 0x66:
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()
            tool.clear_queue(barcode_q)
            check_sn_enable = True
            ominiair_reset_session()
            ominiair_session_state = OMINIAIR_SESS_WAIT_SN
            print("[OMINI-021-AIR] 请扫码")
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
    elif cmd == 0x77:
        if ominiair_session_state != OMINIAIR_SESS_RUNNING:
            return
        ominiair_stop_config_push()
        p = ominiair_parse_77(dat)
        if p is None:
            return
        ominiair_last_p = p
        st = int(p["step"])
        print("[OMINI-021-AIR] 0x77 step=" + str(st) + " p=" + str(p))
        ominiair_refresh_test_ui_callafter(p, finalize=False)
        if st == 3:
            ominiair_got_step3 = True
        if st != ominiair_last_step:
            ominiair_last_step = st
            ominiair_step_notify(st)
    elif cmd == 0x88:
        ominiair_finalize_88(dev, dat)


# ---------- #[OMINIWATER-022-PROTO] Omini 基站过水（device_type=022，帧 dev=0x16）----------
OMINIWATER_UI_LABELS = {
    "clear_water_volume": "清水通路水量：",
    "duty_water_volume": "污水通路水量：",
    "left_mop_water_volume": "左拖布水量：",
    "right_mop_water_volume": "右拖布水量：",
    "left_mop_temperature": "左拖布温度adc：",
    "right_mop_temperature": "右拖布温度adc：",
    "cleaner_liquid_level": "清洁剂液位：",
    "base_hot_water_temp": "基站热水温度adc：",
    "base_station_ver": "基站版本：",
    "base_station_config": "基站配置码：",
}

OMINIWATER_FIELD_REGISTRY = [
    {"field": "clear_vol", "kind": "exact_int", "ui": "clear_water_volume",
     "mes": "清水通路过水", "parse_key": "clear_water_volume",
     "expect_attr": "ominiwater_clear_volume_expected"},
    {"field": "duty_vol", "kind": "exact_int", "ui": "duty_water_volume",
     "mes": "污水通路过水", "parse_key": "duty_water_volume",
     "expect_attr": "ominiwater_duty_volume_expected"},
    {"field": "left_mop_vol", "kind": "exact_int", "ui": "left_mop_water_volume",
     "mes": "左拖布过水", "parse_key": "left_mop_water_volume",
     "expect_attr": "ominiwater_left_mop_volume_expected"},
    {"field": "right_mop_vol", "kind": "exact_int", "ui": "right_mop_water_volume",
     "mes": "右拖布过水", "parse_key": "right_mop_water_volume",
     "expect_attr": "ominiwater_right_mop_volume_expected"},
    {"field": "left_mop_temp", "kind": "range_int", "ui": "left_mop_temperature",
     "mes": "左拖布温度adc", "parse_key": "left_mop_temperature",
     "min_attr": "ominiwater_left_mop_temp_min", "max_attr": "ominiwater_left_mop_temp_max"},
    {"field": "right_mop_temp", "kind": "range_int", "ui": "right_mop_temperature",
     "mes": "右拖布温度adc", "parse_key": "right_mop_temperature",
     "min_attr": "ominiwater_right_mop_temp_min", "max_attr": "ominiwater_right_mop_temp_max"},
    {"field": "cleaner_level", "kind": "exact_int", "ui": "cleaner_liquid_level",
     "mes": "清洁剂液位", "parse_key": "cleaner_liquid_level",
     "expect_attr": "ominiwater_cleaner_level_expected"},
    {"field": "base_hot_temp", "kind": "range_int", "ui": "base_hot_water_temp",
     "mes": "基站热水温度adc", "parse_key": "base_hot_water_temp",
     "min_attr": "ominiwater_base_hot_temp_min", "max_attr": "ominiwater_base_hot_temp_max"},
    {"field": "base_ver", "kind": "version", "ui": "base_station_ver", "mes": "基站版本",
     "parse_key": "base_ver"},
    {"field": "base_config", "kind": "string", "ui": "base_station_config", "mes": "基站配置码",
     "parse_key": "base_config", "expect_attr": "base_station_config_expected"},
]


def _ominiwater_registry_entry(field):
    for entry in OMINIWATER_FIELD_REGISTRY:
        if entry["field"] == field:
            return entry
    return None


def _ominiwater_range_enabled(lo, hi):
    return not (int(lo) == 0 and int(hi) == 0)


def _ominiwater_exact_enabled(expect_attr):
    return int(getattr(load_cfg, expect_attr, -1)) >= 0


def ominiwater_field_enabled(field):
    entry = _ominiwater_registry_entry(field)
    if entry is None:
        return False
    kind = entry["kind"]
    if kind == "exact_int":
        return _ominiwater_exact_enabled(entry.get("expect_attr", ""))
    if kind == "range_int":
        lo = getattr(load_cfg, entry["min_attr"], 0)
        hi = getattr(load_cfg, entry["max_attr"], 0)
        return _ominiwater_range_enabled(lo, hi)
    if kind == "version":
        return bool((load_cfg.mcu_ver or "").strip())
    if kind == "string":
        expect = getattr(load_cfg, entry.get("expect_attr", ""), "")
        return bool(str(expect).strip())
    return False


def ominiwater_build_item_result():
    items = []
    for entry in OMINIWATER_FIELD_REGISTRY:
        if entry["ui"] == "base_station_config" and not base_station_config_ui_enabled():
            continue
        if ominiwater_field_enabled(entry["field"]):
            ui = entry["ui"]
            items.append({ui: [OMINIWATER_UI_LABELS[ui], "", "white"]})
    return items


def ominiwater_reset_session():
    global ominiwater_session_state, ominiwater_last_step, ominiwater_last_p, ominiwater_got_step3
    global ominiwater_last_level_notify, ominiwater_finalize_done
    ominiwater_session_state = OMINIWATER_SESS_IDLE
    ominiwater_last_step = -1
    ominiwater_last_p = None
    ominiwater_got_step3 = False
    ominiwater_last_level_notify = -1
    ominiwater_finalize_done = False


def ominiwater_int_limits(field):
    entry = _ominiwater_registry_entry(field)
    if entry is None:
        return 0, 0
    return (
        int(getattr(load_cfg, entry["min_attr"], 0)),
        int(getattr(load_cfg, entry["max_attr"], 0)),
    )


def ominiwater_field_ok(p, field):
    if not ominiwater_field_enabled(field):
        return None
    if p is None:
        return False
    entry = _ominiwater_registry_entry(field)
    if entry is None:
        return None
    kind = entry["kind"]
    if kind == "exact_int":
        expect = int(getattr(load_cfg, entry.get("expect_attr", ""), -1))
        actual = p.get(entry.get("parse_key"))
        if actual is None:
            return False
        return int(actual) == expect
    if kind == "range_int":
        val = p.get(entry.get("parse_key"))
        if val is None:
            return False
        lo, hi = ominiwater_int_limits(field)
        if lo > hi:
            lo, hi = hi, lo
        v = int(val)
        return lo <= v <= hi
    if kind == "version":
        return ver_triplet_matches(p.get("base_ver"), load_cfg.mcu_ver)
    if kind == "string":
        return config_triplet_matches(
            p.get("base_config"), load_cfg.base_station_config_expected)
    return None


def ominiwater_all_ok(p):
    if p is None:
        return False
    for entry in OMINIWATER_FIELD_REGISTRY:
        ok = ominiwater_field_ok(p, entry["field"])
        if ok is False:
            return False
    return True


def ominiwater_step_notify(step):
    st = int(step)
    if st == 1:
        msg = "进入产测"
    elif st == 3:
        msg = "最终判断结果"
    else:
        msg = "治具步骤：" + str(st)
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=msg, color=wx.BLUE)


def ominiwater_level_notify(level):
    global ominiwater_last_level_notify
    lv = int(level) & 0xFF
    if lv == ominiwater_last_level_notify:
        return
    ominiwater_last_level_notify = lv
    if lv == 0x01:
        msg = "清洁液不在位，请插入"
        color = wx.RED
    elif lv == 0x02:
        msg = "清洁液在位，请取出"
        color = wx.RED
    elif lv == 0x03:
        msg = "清洁液盒通过，请取出"
        color = wx.GREEN
    else:
        msg = "请注意后续操作提示"
        color = wx.RED
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=msg, color=color)


def ominiwater_ui_result_for_field(field, p, finalize):
    entry = _ominiwater_registry_entry(field)
    if entry is None:
        return "monitor", ""
    kind = entry["kind"]
    if kind in ("exact_int", "range_int"):
        val = p.get(entry.get("parse_key")) if p else None
        disp = "" if val is None else str(val)
        if not finalize:
            return "monitor", disp
        ok = ominiwater_field_ok(p, field)
        if ok is None or ok is True:
            return "pass", disp
        return "fail", disp
    if kind == "version":
        return ominiwater_ui_result_for_string("base_ver", p.get("base_ver") if p else None, finalize)
    if kind == "string":
        return ominiwater_ui_result_for_string("base_config", p.get("base_config") if p else None, finalize)
    return "monitor", ""


def ominiwater_string_field_ok(field, actual):
    if field == "base_ver":
        return ver_triplet_matches(actual, load_cfg.mcu_ver)
    if field == "base_config":
        return config_triplet_matches(actual, load_cfg.base_station_config_expected)
    return None


def ominiwater_ui_result_for_string(field, value, finalize):
    disp = value or ""
    if not finalize:
        return "monitor", disp
    ok = ominiwater_string_field_ok(field, value)
    if ok is None or ok is True:
        return "pass", disp
    return "fail", disp


def _ominiwater_refresh_test_ui_impl(p, finalize):
    if p is None:
        return
    for entry in OMINIWATER_FIELD_REGISTRY:
        field = entry["field"]
        if not ominiwater_field_enabled(field):
            continue
        res, val = ominiwater_ui_result_for_field(field, p, finalize)
        MainFrame.main_frame.up_test_ui(name=entry["ui"], result=res, value=val)


def ominiwater_refresh_test_ui_callafter(p, finalize=False):
    wx.CallAfter(_ominiwater_refresh_test_ui_impl, p, finalize)


def ominiwater_add_string_report(name, field, value):
    ok = ominiwater_string_field_ok(field, value)
    if ok is None:
        return
    result = "OK" if ok else "NG"
    if field == "base_ver":
        expect = load_cfg.mcu_ver
    else:
        expect = load_cfg.base_station_config_expected
    mes_run.add_report(
        name=name, result=result, value=value or "",
        val_min=expect, val_max=expect,
    )


def ominiwater_add_reports(p):
    if p is None:
        for entry in OMINIWATER_FIELD_REGISTRY:
            if not ominiwater_field_enabled(entry["field"]):
                continue
            mes_run.add_report(name=entry["mes"], result="NG", value="无数据")
        return
    for entry in OMINIWATER_FIELD_REGISTRY:
        field = entry["field"]
        if not ominiwater_field_enabled(field):
            continue
        kind = entry["kind"]
        if kind == "exact_int":
            val = p.get(entry.get("parse_key"))
            expect = int(getattr(load_cfg, entry.get("expect_attr", ""), -1))
            mes_run.add_report(
                name=entry["mes"],
                result="OK" if ominiwater_field_ok(p, field) else "NG",
                value=str(val) if val is not None else "",
                val_min=expect,
                val_max=expect,
            )
        elif kind == "range_int":
            val = p.get(entry.get("parse_key"))
            lo, hi = ominiwater_int_limits(field)
            mes_run.add_report(
                name=entry["mes"],
                result="OK" if ominiwater_field_ok(p, field) else "NG",
                value=str(val) if val is not None else "",
                val_min=lo,
                val_max=hi,
            )
        elif field == "base_ver":
            ominiwater_add_string_report(entry["mes"], "base_ver", p.get("base_ver"))
        elif field == "base_config":
            ominiwater_add_string_report(entry["mes"], "base_config", p.get("base_config"))


def ominiwater_finalize_88(dev, dat):
    global test_end_time, ominiwater_session_state, ominiwater_last_p, ominiwater_got_step3
    global ominiwater_finalize_done
    if ominiwater_finalize_done:
        print("[OMINI-022-WATER] 重复 0x88，忽略")
        return

    test_end_time = datetime.now()
    print("[OMINI-022-WATER] 测试结束帧 dat=" + str(dat))

    res_byte = dat[0] if len(dat) else 0xFF
    if res_byte == 0x04:
        mes_run.add_report(name="基站通讯", result="NG", value="治具与基站通讯失败")
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="治具与基站通讯失败", color=wx.RED)
        clear_sn_save_list()
        ominiwater_session_state = OMINIWATER_SESS_FINISHED
        ominiwater_finalize_done = True
        return

    if res_byte != 0x03:
        mes_run.add_report(name="结束码", result="NG", value=hex(res_byte))
        res_display_str = "测试结束 NG（结束码 {}）".format(hex(res_byte))
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second=res_display_str, color=wx.RED)
        clear_sn_save_list()
        ominiwater_session_state = OMINIWATER_SESS_FINISHED
        ominiwater_finalize_done = True
        return

    p = ominiwater_last_p
    mes_ok = ominiwater_got_step3 and p is not None and ominiwater_all_ok(p)
    ominiwater_add_reports(p)
    if mes_ok:
        res_display_str = "测试完成 PASS"
        text_color = wx.GREEN
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
    else:
        if not ominiwater_got_step3:
            res_display_str = "测试结束 NG（未到最终判断步骤）"
        elif p is None:
            res_display_str = "测试结束 NG（无结果数据）"
        else:
            res_display_str = "测试结束 NG（测试项未达标）"
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")

    if p is not None:
        ominiwater_refresh_test_ui_callafter(p, finalize=True)
    if mes_ret:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second=res_display_str, color=text_color)
    clear_sn_save_list()
    ominiwater_session_state = OMINIWATER_SESS_FINISHED
    ominiwater_finalize_done = True


def Omini_water_mode(dev, cmd, dat):
    global test_start_time, check_sn_enable
    global ominiwater_session_state, ominiwater_last_step, ominiwater_last_p, ominiwater_got_step3

    if len(dat) <= 0:
        print("[OMINI-022-WATER] len=0 无有效数据")
        return

    if cmd == 0x66:
        if dat[0] == 0x00:
            test_start_time = datetime.now()
            mes_run.clear_report()
            tool.clear_queue(barcode_q)
            check_sn_enable = True
            ominiwater_reset_session()
            ominiwater_session_state = OMINIWATER_SESS_WAIT_SN
            print("[OMINI-022-WATER] 请扫码")
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
    elif cmd == 0x77:
        if ominiwater_session_state != OMINIWATER_SESS_RUNNING:
            return
        p = rv50water_parse_77(dat, min_len=OMINIWATER_77_DATA_LEN)
        if p is None:
            return
        ominiwater_last_p = p
        st = int(p["step"])
        print("[OMINI-022-WATER] 0x77 step=" + str(st) + " p=" + str(p))
        ominiwater_refresh_test_ui_callafter(p, finalize=False)
        if st == 3:
            ominiwater_got_step3 = True
        if st != ominiwater_last_step:
            ominiwater_last_step = st
            if st in (1, 3):
                ominiwater_step_notify(st)
        if st == 2 and ominiwater_field_enabled("cleaner_level"):
            ominiwater_level_notify(p.get("cleaner_liquid_level"))
    elif cmd == 0x88:
        ominiwater_finalize_88(dev, dat)


charge_value = 0
hot_air = 0
ir_code_left = 0
ir_code_lc = 0  # #[RV30-PROTO-77-MOD] 左中红外码
ir_code_right = 0
ir_code_rc = 0  # #[RV30-PROTO-77-MOD] 右中红外码（变量名保留）
clear_tank_install = 0
duty_tank_install = 0
dust_bug_install = 0
clean_base_install = 0
dust_collection_suction = 0
clean_water_pump_current = 0
duty_water_pump_current = 0
cleaner_pump_current = 0
electromagnetic_three_way_current = 0
clean_base_liquid_level = 0
turbidity_data = 0
dev_ver = ""
ver_res = "OK"


# ---------- [WSXQMX-019] RV50 污水箱气密性（device_type=019，帧 dev=0x13）----------
def wsxqmx_reset_session():
    # [WSXQMX-019] 一轮结束后恢复，便于下一轮 0x66
    global wsxqmx_session_state, wsxqmx_last_step, wsxqmx_hold_pressure_kpa, wsxqmx_got_step3
    global wsxqmx_finalize_done
    wsxqmx_session_state = WSXQMX_SESS_IDLE
    wsxqmx_last_step = -1
    wsxqmx_hold_pressure_kpa = None
    wsxqmx_got_step3 = False
    wsxqmx_finalize_done = False


def wsxqmx_bytes_to_int16(hi, lo):
    # [WSXQMX-019] 气压高低字节 → 有符号 int16（单位 10Pa）
    unsigned = ((int(hi) & 0xFF) << 8) | (int(lo) & 0xFF)
    if unsigned >= 0x8000:
        return unsigned - 0x10000
    return unsigned


def wsxqmx_raw_to_kpa(raw_int16):
    # [WSXQMX-019] 10Pa 计数 → kPa
    return float(raw_int16) * 0.01


def wsxqmx_hold_pressure_in_range(kpa):
    # [WSXQMX-019] 保压结束判据：-17～-20 kPa（含端点，下限更负）
    if kpa is None:
        return False
    return (load_cfg.wsxqmx_hold_kpa_min <= kpa <= load_cfg.wsxqmx_hold_kpa_max)


def wsxqmx_step_notify(step, kpa=None):
    # [WSXQMX-019] 仅通知区文案，不调用 up_test_ui
    st = int(step)
    if st == 1:
        msg = "加压中"
        color = wx.BLUE
    elif st == 2:
        msg = "保压中"
        color = wx.BLUE
    elif st == 3:
        if kpa is not None:
            msg = "保压结束 气压：{:.2f} kPa（阈值 {:.1f}～{:.1f}）".format(
                kpa, load_cfg.wsxqmx_hold_kpa_min, load_cfg.wsxqmx_hold_kpa_max)
        else:
            msg = "保压结束"
        color = wx.BLUE
    else:
        msg = "治具步骤：" + str(st)
        color = wx.BLUE
    wx.CallAfter(MainFrame.main_frame.up_notification_ui, second=msg, color=color)


def wsxqmx_parse_77(dat):
    # [WSXQMX-019] 0x77：dat[0]=步骤，dat[1..2]=气压 H/L（仅步骤03有效）
    if len(dat) < 1:
        return None
    step = int(dat[0])
    kpa = None
    raw = None
    if step == 3 and len(dat) >= 3:
        raw = wsxqmx_bytes_to_int16(dat[1], dat[2])
        kpa = wsxqmx_raw_to_kpa(raw)
    return {"step": step, "raw_10pa": raw, "kpa": kpa}


def wsxqmx_finalize_88(dev, dat):
    # [WSXQMX-019] 0x88 dat[0]=03 治具正常结束；04 治具与基站通讯失败
    global test_end_time, wsxqmx_session_state, wsxqmx_hold_pressure_kpa, wsxqmx_got_step3
    global wsxqmx_finalize_done
    if wsxqmx_finalize_done:
        print("[WSXQMX-019] 重复 0x88，忽略")
        return

    test_end_time = datetime.now()
    print("[WSXQMX-019] 测试结束帧 dat=" + str(dat))

    res_byte = dat[0] if len(dat) else 0xFF
    if res_byte == 0x04:
        mes_run.add_report(name="基站通讯", result="NG", value="治具与基站通讯失败")
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second="治具与基站通讯失败", color=wx.RED)
        clear_sn_save_list()
        wsxqmx_session_state = WSXQMX_SESS_FINISHED
        wsxqmx_finalize_done = True
        return

    if res_byte != 0x03:
        mes_run.add_report(name="结束码", result="NG", value=hex(res_byte))
        res_display_str = "测试结束 NG（结束码 {}）".format(hex(res_byte))
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")
        if mes_ret:
            wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                         second=res_display_str, color=text_color)
        clear_sn_save_list()
        wsxqmx_session_state = WSXQMX_SESS_FINISHED
        wsxqmx_finalize_done = True
        return

    kpa = wsxqmx_hold_pressure_kpa
    pressure_ok = wsxqmx_hold_pressure_in_range(kpa)
    mes_ok = wsxqmx_got_step3 and pressure_ok

    if kpa is not None:
        mes_run.add_report(
            name="保压气压",
            result="OK" if pressure_ok else "NG",
            value="{:.2f}".format(kpa),
            val_min=load_cfg.wsxqmx_hold_kpa_min,
            val_max=load_cfg.wsxqmx_hold_kpa_max,
        )
    else:
        mes_run.add_report(name="保压气压", result="NG", value="无步骤03数据")

    if mes_ok:
        if kpa is not None:
            res_display_str = "测试完成 PASS（保压气压 {:.2f} kPa）".format(kpa)
        else:
            res_display_str = "测试完成 PASS"
        text_color = wx.GREEN
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "OK")
    else:
        if not wsxqmx_got_step3:
            res_display_str = "测试结束 NG（未到保压结束步骤）"
        elif kpa is None:
            res_display_str = "测试结束 NG（无保压气压）"
        else:
            res_display_str = "测试结束 NG（保压气压 {:.2f} kPa 超阈值）".format(kpa)
        text_color = wx.RED
        mes_ret = mes_run.send_report(test_start_time, test_end_time, check_sn_str, "NG")

    if mes_ret:
        wx.CallAfter(MainFrame.main_frame.up_notification_ui,
                     second=res_display_str, color=text_color)
    clear_sn_save_list()
    wsxqmx_session_state = WSXQMX_SESS_FINISHED
    wsxqmx_finalize_done = True


def wsxqmx_mode(dev, cmd, dat):
    # [WSXQMX-019] 主入口：0x66 不发 0x67；0x77 无应答；0x88 统一收尾
    global test_start_time, check_sn_enable
    global wsxqmx_session_state, wsxqmx_last_step, wsxqmx_hold_pressure_kpa, wsxqmx_got_step3

    if len(dat) <= 0:
        print("[WSXQMX-019] len=0 无有效数据")
        return

    if cmd == 0x66:
        if dat[0] == 0x00:
            fixture_all_reply_bursts_stop()
            test_start_time = datetime.now()
            mes_run.clear_report()
            tool.clear_queue(barcode_q)
            check_sn_enable = True
            wsxqmx_reset_session()
            wsxqmx_session_state = WSXQMX_SESS_WAIT_SN
            print("[WSXQMX-019] 请扫码")
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")
    elif cmd == 0x77:
        if wsxqmx_session_state != WSXQMX_SESS_RUNNING:
            return
        fixture_gate_burst_cancel_on_first_77()
        p = wsxqmx_parse_77(dat)
        if p is None:
            return
        st = p["step"]
        print("[WSXQMX-019] 0x77 step=" + str(st) + " p=" + str(p))
        if st == 3:
            wsxqmx_got_step3 = True
            if p["kpa"] is not None:
                wsxqmx_hold_pressure_kpa = p["kpa"]
            if st != wsxqmx_last_step or p["kpa"] is not None:
                wsxqmx_step_notify(st, kpa=wsxqmx_hold_pressure_kpa)
            wsxqmx_last_step = st
        elif st != wsxqmx_last_step:
            wsxqmx_last_step = st
            if st in (1, 2):
                wsxqmx_step_notify(st)
    elif cmd == 0x88:
        wsxqmx_finalize_88(dev, dat)
    else:
        print("[WSXQMX-019] 未处理命令 cmd=" + hex(cmd))


# #[RV30-PROTO] RV30 基站成品(device_type=50)：0x66 不发 0x67；门闸 0x57/0x58；0x77 无应答；异常 0x89 0x03；0x88 综合判定 MES
def RV30_finished_product_mode(dev, cmd, dat):
    # #[RV30-PROTO] 调优入口：本函数 + rv30_proto_* + config.yaml rv30_* 键
    global test_start_time
    global test_end_time
    global check_sn_enable
    global ver_res
    global dev_ver
    global charge_value
    global ir_code_left
    global ir_code_lc
    global ir_code_right
    global ir_code_rc
    global dust_bug_install
    global dust_collection_suction
    global rv30_session_state
    global rv30_last_step
    global rv30_max_step
    global rv30_89_mes_done
    global rv30_finalize_done
    global rv30_realtime_ng
    global rv30_last_p  # [up_test_ui_WBH]
    global rv30_last_dust_notify  # [RV30-尘袋步骤3-WBH]
    if len(dat) <= 0:
        print("len=0 无有效数据")
        return

    if cmd == 0x66:
        # #[RV30-PROTO] 开始测试：禁止 ser_send_cmd(0x67)，仅等扫码后 0x57/0x58
        if dat[0] == 0x00:
            fixture_all_reply_bursts_stop()
            test_start_time = datetime.now()
            mes_run.clear_report()
            tool.clear_queue(barcode_q)
            check_sn_enable = True # 置为true，上位机才能返回治具数据


            rv30_last_step = -1
            rv30_max_step = 0
            rv30_89_mes_done = False
            rv30_finalize_done = False
            rv30_realtime_ng = False
            rv30_last_p = None
            rv30_last_dust_notify = -1  # [RV30-尘袋步骤3-WBH]
            rv30_session_state = RV30_SESS_WAIT_SN


            print("RV30 扫描枪扫描二维码")
            wx.CallAfter(MainFrame.main_frame.reset_ui)
            wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="请扫码")


    elif cmd == 0x77:
        # #[RV30-PROTO-77-MOD] 实时数据：数据区 15 字节；不向治具回帧；与 config.yaml rv30_* 比对

        print("RV30 实时数据 len=" + str(len(dat)) + " dat=" + str(dat))
        if len(dat) != 15:
            print("[RV30-PROTO-77-MOD] 期望数据区 15 字节，实际:", len(dat))
        if rv30_session_state != RV30_SESS_RUNNING:  # 状态机放在开头，根据状态决定是否进入流程
            return

        fixture_gate_burst_cancel_on_first_77()

        p = rv30_proto_parse_77_apply_globals(dat)  # 读取数据帧，并且将结果返回到全局变量，以及组合为一个键值对
        wx.CallAfter(MainFrame.main_frame.up_ver_ui, dev_ver)
        if p is not None:
            rv30_last_p = p  # [up_test_ui_WBH]
            rv30_proto_refresh_test_ui_callafter(p)  # ui_test的更新逻辑

            # 更新测试步骤，以及主窗口的ui
            st = p["step"]
            if int(st) > rv30_max_step:
                rv30_max_step = int(st)
            if st != rv30_last_step:
                # #[RV30-PROTO] 步骤变化时刷新提示（步骤表仅作参考，可改文案/条件）
                rv30_last_step = st
                wx.CallAfter(MainFrame.main_frame.up_notification_ui, second="治具步骤：" + str(st), color=wx.BLUE)


            # [RV30-测试项分步报错-WBH] 仅当前 step 已开放项参与实时 NG
            if not rv30_proto_yaml_realtime_ok(p): # 除了步骤三，其他步骤捕捉的值与配置的值进行比较，有错误就进行报错
                rv30_proto_realtime_fail(dev, "yaml阈值:" + str(p)) # 上位机向治具发送报错，并更新上位机ui显示
                return

    elif cmd == 0x88:
        # #[RV30-PROTO] 结束帧：不向治具发 0x89 应答；综合判定见 rv30_proto_finalize_88
        print("RV30 测试结束帧 dat[0]=" + str(dat[0] if dat else None))
        rv30_proto_finalize_88(dev, dat)
    else:
        print("RV30 未处理命令 cmd=" + hex(cmd))
