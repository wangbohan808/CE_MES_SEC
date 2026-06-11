# Omini 基站全功能治具 — 实现规格（020）

> **用途**：供后续 AI 或工程师实现/维护 `device_type=020` Omini 基站全功能工位。  
> **状态**：**已实现**（代码锚点 `# #[OMINI-020-PROTO]`）。  
> **设计原则**：协议帧与 **RV50 全功能（017）** 相同（0x77 数据区 38 字节）；配置独立 **`omini_*` 前缀**；未配置项不参与比较、不显示 UI、不上报 MES。  
> **对照范例**：`test_tool/test.py` 中 `# #[RV50-017-PROTO]`、`# #[OMINIAIR-021-PROTO]`（动态注册表模式）。

---

## 1. 工位标识

| 项 | 值 |
|----|-----|
| `device_type` | `"020"`（`int(load_cfg.dev)==20`） |
| 串口帧 `dev` 字节 | **`0x14`（20）** — 与 `device_type` 数值一致 |
| 窗口标题键 | `heading_line_dict["020"]` → `"Omini全功能测试"` |
| MES 工序站码 | **`HNOMINIGGNCS`**（**待定**，`mes/celink_mes.py` 中标注） |
| 搜索标记 | `# #[OMINI-020-PROTO]`、`omini_`、`Omini_finished_product_mode` |

---

## 2. 协议（与 017 相同）

### 2.1 0x77 数据区（38 字节）

| 下标 | 字段 | 说明 |
|------|------|------|
| 0 | step | 治具步骤 1~7（step4 为模块交互） |
| 1~2 | charge | 充电电流 u16 BE |
| 3~5 | ir_l / ir_r / ir_n | 回充码 |
| 6~9 | clear_tank / duty_tank / dust / clean_base | 步骤四模块状态 0~3 |
| 10~12 | dev_ver | MCU 版本 `NNN.NNN.NNN` |
| 13~15 | base_config | 基站配置码（字符串展示/可选比对） |
| 16~17 | suction_10pa | 集尘吸力 10Pa 计数 |
| 18~37 | 泵/液位/浊度/热风 ADC | 同 017 |

### 2.2 命令字

| 命令 | 行为 |
|------|------|
| `0x66 [0x00]` | 清报告、请扫码 |
| `0x57` / `0x58` | 扫码门闸通过/失败 |
| `0x77` | 实时数据；**仅 RUNNING 态处理** |
| `0x88` | 结束帧：`03` 正常结束再综合判 PASS/NG；`04` 基站通讯失败 |
| `0x89 [0x03]` | 实时阈值 NG / 扫码门闸失败（不上报 MES） |

### 2.3 终判条件

1. 收到 `0x88` 且首字节 `0x03`
2. 本轮 **max_step ≥ 7** 且最后一帧 step ≥ 7
3. 无实时 NG（`omini_realtime_ng == False`）
4. `omini_proto_yaml_finalize_ok(p)`：所有 **enabled** 非步骤四项 `field_ok` 均不为 `False`
5. `omini_step4_flow_complete()`：enabled 步骤四模块均 `== 3`（无 enabled 模块则恒 True）
6. **不**硬编码 `ver_res == "OK"`，版本由 `omini_field_ok(p, "dev_ver")` 处理

---

## 3. 动态配置语义

### 3.1 enabled（参与比较 / 显示 UI）条件

| 判据类型 | config 键 | enabled 条件 |
|----------|-----------|--------------|
| 区间 | `omini_{field}_min/max` | **min 与 max 不全为 0** |
| 集尘 kPa | `omini_suction_kpa_min/max` | 同上（内部转 10Pa） |
| 充电 | `omini_charge_min/max` | 同上 |
| 红外/步骤四期望 | `omini_ir_*` / `omini_*_expected` | **值非 0** |
| MCU 版本 | 公共 `mcu_version` | 非空字符串 |
| 基站配置码 | `base_station_config_expected`（公共） | 非空字符串 |
| 热风 start/end | — | 仅当 `hot_diff` enabled 时 **监视显示**（不参与 NG） |

### 3.2 `omini_field_ok` 返回值

| 返回值 | 含义 | 终判 |
|--------|------|------|
| `True` | 在阈值内 / 相等 | 通过 |
| `False` | 超阈值 / 不等 | **NG** |
| `None` | 未 enabled | **跳过（不算 NG）** |

汇总：**仅 `ok is False` 导致 NG**。

### 3.3 UI

- 启动时 `omini_build_item_result()` 按 enabled 项 **动态生成** 测试格。
- step=4：enabled 步骤四模块走模块子状态 UI + 工人提示。
- 过程帧：enabled 项 monitor/pass/fail 着色；step≠4 时实时超阈发 `0x89`。

### 3.4 MES

- `omini_proto_add_reports()` **仅上报 enabled 项**。
- 实时 NG：`omini_proto_realtime_fail` → `add_report("Omini实时判据", NG)` + 一次 `send_report NG`。

---

## 4. config.yaml 示例

```yaml
device_type: "020"
project_name: "Omini"

# §020  Omini 基站全功能（帧 dev=0x14）
# 某项 min/max 均为 0 或 expected 为 0 → 不参与比较、不显示 UI
omini_charge_min: 200
omini_charge_max: 3000
omini_ir_l: 0x44
omini_ir_r: 0x42
omini_ir_n: 0x48
omini_clear_tank_expected: 0x03
# 不配 omini_turbidity_* → 无浊度传感器则不测
omini_suction_kpa_min: 17
omini_suction_kpa_max: 30
mcu_version: "002.001.078"
# base_station_config_expected: "001.002.003"  # 公共区，可选
```

---

## 5. 代码文件索引

| 文件 | 改动 |
|------|------|
| `test_tool/test.py` | `LoadCfg` `omini_*`；`OMINI_*` 会话；`OMINI_FIELD_REGISTRY`；`Omini_finished_product_mode`；`load_config`；`test_cmd_handle`；`barcode_check_process` |
| `ui/MainFrame.py` | `omini_build_item_result()` 动态测试格；`dev==20` 显示测试区 |
| `config.yaml` | §020 索引 + 专项配置 |
| `mes/celink_mes.py` | `"020": "HNOMINIGGNCS"`（待定） |

---

## 6. 字段注册表

```python
OMINI_FIELD_REGISTRY = [
    {"field": "dev_ver", "kind": "version", "ui": "mcu_ver", "mes": "MCU版本", "active_from_step": 4},
    {"field": "base_config", "kind": "string", "ui": "base_station_config", "mes": "基站配置码",
     "expect_attr": "base_station_config_expected", "active_from_step": 4},
    {"field": "charge", "kind": "range", "ui": "charge_value", "mes": "充电电流",
     "min_attr": "omini_charge_min", "max_attr": "omini_charge_max", "active_from_step": 1},
    {"field": "ir_l", "kind": "expected", "ui": "ir_code_left", "mes": "左回充码",
     "expect_attr": "omini_ir_l", "active_from_step": 3},
    # ... 完整列表见 test.py OMINI_FIELD_REGISTRY
]
```

步骤四模块字段带 `"step4_module": True`；`omini_step4_enabled_modules()` 仅返回 enabled 的子集。

---

## 7. 相对 RV50 017 的优化

| RV50 017 | Omini 020 |
|----------|-----------|
| UI 固定 20 项 | 注册表 + `omini_build_item_result()` 动态项 |
| 步骤四四模块硬编码 | `omini_step4_enabled_modules()` |
| 终判硬要求 `ver_res==OK` | `omini_field_ok("dev_ver")` |
| MES 全量上报 | 仅 enabled 项 |

---

## 8. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-06-11 | 初版：020 动态裁剪全功能工位规格 + 代码实现 |
