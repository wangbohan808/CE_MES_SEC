# Omini 基站过水治具 — 实现规格（022）

> **用途**：供后续 AI 或工程师实现/维护 `device_type=022` Omini 基站过水工位。  
> **状态**：**已实现**（代码锚点 `# #[OMINIWATER-022-PROTO]`）。  
> **设计原则**：协议帧与 **RV50 过水（016）** 相同（0x77 数据区 22 字节）；配置独立 **`ominiwater_*` 前缀**；未配置项不参与比较、不显示 UI、不上报 MES。  
> **对照范例**：`test_tool/test.py` 中 `# #[RV50-016-WATER-PROTO]`、`# #[OMINIAIR-021-PROTO]`。

---

## 1. 工位标识

| 项 | 值 |
|----|-----|
| `device_type` | `"022"`（`int(load_cfg.dev)==22`） |
| 串口帧 `dev` 字节 | **`0x16`（22）** — 与 `device_type` 数值一致 |
| 窗口标题键 | `heading_line_dict["022"]` → `"Omini过水测试"` |
| MES 工序站码 | **`HNOMINIGSCS`**（**待定**，`mes/celink_mes.py` 中标注） |
| 搜索标记 | `# #[OMINIWATER-022-PROTO]`、`ominiwater_`、`Omini_water_mode` |

---

## 2. 协议（与 016 相同）

### 2.1 0x77 数据区（22 字节）

| 偏移 | 含义 |
|------|------|
| `dat[0]` | step（1=进入产测，2=测试中，3=结果上传） |
| `dat[1..2]` | 清水通路水量 u16 BE |
| `dat[3..4]` | 污水通路水量 u16 BE |
| `dat[5..6]` | 左拖布水量 u16 BE |
| `dat[7..8]` | 右拖布水量 u16 BE |
| `dat[9..10]` | 左拖布温度 ADC u16 BE |
| `dat[11..12]` | 右拖布温度 ADC u16 BE |
| `dat[13]` | 清洁剂液位单字节 |
| `dat[14..15]` | 基站热水温度 ADC u16 BE |
| `dat[16..18]` | 基站版本 `NNN.NNN.NNN` |
| `dat[19..21]` | 基站配置码 `NNN.NNN.NNN` |

解析复用 `rv50water_parse_77`（布局一致）。

### 2.2 命令字

| 命令 | 行为 |
|------|------|
| `0x66 [0x00]` | 清报告、请扫码 |
| `0x57` / `0x58` | 扫码门闸通过/失败（通用 `barcode_check_process`） |
| `0x77` | 实时数据；**仅 RUNNING 态处理** |
| `0x88` | 结束帧：`03` 正常结束再综合判 PASS/NG；`04` 基站通讯失败 |

**022 不发 `0x89`**（与 016 一致）。

### 2.3 终判条件

与 016/021 对齐：

1. 收到 `0x88` 且首字节 `0x03`  
2. 本轮 **到过 step=3**（`ominiwater_got_step3 == True`）  
3. 锁存最后一帧 `0x77` 解析结果 `ominiwater_last_p` 非空  
4. `ominiwater_all_ok(p)`：所有 **enabled** 项 `ominiwater_field_ok` 均不为 `False`

---

## 3. 动态配置语义

### 3.1 enabled（参与比较）条件

| 判据类型 | config 键 | enabled 条件 |
|----------|-----------|--------------|
| 精确匹配（清水通路水量） | `ominiwater_clear_volume_expected` | **值 ≥ 0**（默认 `-1` 表示未配置） |
| 精确匹配（污水通路水量） | `ominiwater_duty_volume_expected` | 同上 |
| 精确匹配（左拖布水量） | `ominiwater_left_mop_volume_expected` | 同上 |
| 精确匹配（右拖布水量） | `ominiwater_right_mop_volume_expected` | 同上 |
| 精确匹配（清洁剂液位） | `ominiwater_cleaner_level_expected` | **值 ≥ 0**（默认 `-1`） |
| 区间（三路温度 ADC） | `ominiwater_{left\|right}_mop_temp_min/max`、`ominiwater_base_hot_temp_min/max` | **min 与 max 不同时为 0** |
| 基站版本 | 公共 `mcu_version` | 非空字符串 |
| 基站配置码 | `ominiwater_base_config_expected` | 非空字符串 |

### 3.2 `ominiwater_field_ok` 返回值

| 返回值 | 含义 | 终判 |
|--------|------|------|
| `True` | 等于期望值 / 在阈值内 / 字符串相等 | 通过 |
| `False` | 不等 / 超阈值 / 无数据 | **NG** |
| `None` | 未 enabled | **跳过（不算 NG）** |

汇总：**仅 `ok is False` 导致 NG**。

### 3.3 UI

- 启动时 `ominiwater_build_item_result()` 按 enabled 项 **动态生成** 测试格。  
- 过程帧（step 1~2）：enabled 项显示 **monitor**（实时数值/字符串）。  
- 终判：`pass` / `fail` 着色。

### 3.4 清洁剂液位 step=2 通知

仅当 `cleaner_level` 项 **enabled** 时，在 step=2 调用 `ominiwater_level_notify`（插入/取出清洁液操作提示）。

### 3.5 MES

- `ominiwater_add_reports()` **仅上报 enabled 项**。  
- `p is None` 时仅对 enabled 项报 NG。

---

## 4. config.yaml 示例

```yaml
device_type: "022"
project_name: "Omini"

# §022  Omini 基站过水（帧 dev=0x16）
# 水量/液位：不配或 -1 → 不参与比较、不显示 UI
ominiwater_clear_volume_expected: 3
ominiwater_duty_volume_expected: 3
# 不配 left/right_mop_volume_expected → 对应拖布水路不测
ominiwater_left_mop_volume_expected: 3
ominiwater_right_mop_volume_expected: 3
ominiwater_cleaner_level_expected: 3
ominiwater_left_mop_temp_min: 800
ominiwater_left_mop_temp_max: 1800
# 不配 right_mop / base_hot 温度 → 对应传感器不测

mcu_version: "002.001.078"
ominiwater_base_config_expected: "001.002.003"
```

---

## 5. 代码文件索引

| 文件 | 改动 |
|------|------|
| `test_tool/test.py` | `LoadCfg` `ominiwater_*`；`OMINIWATER_*` 会话；`ominiwater_field_*`；`Omini_water_mode`；`load_config`；`test_cmd_handle`；`barcode_check_process` |
| `ui/MainFrame.py` | `ominiwater_build_item_result()` 动态测试格；`dev==22` 显示测试区 |
| `config.yaml` | §022 索引 + 专项配置 |
| `mes/celink_mes.py` | `"022": "HNOMINIGSCS"`（待定） |

---

## 6. 字段注册表

```python
OMINIWATER_FIELD_REGISTRY = [
    {"field": "clear_vol",     "kind": "exact_int", "ui": "clear_water_volume",      "mes": "清水通路过水",
     "parse_key": "clear_water_volume",     "expect_attr": "ominiwater_clear_volume_expected"},
    {"field": "duty_vol",      "kind": "exact_int", "ui": "duty_water_volume",       "mes": "污水通路过水",
     "expect_attr": "ominiwater_duty_volume_expected"},
    {"field": "left_mop_vol",  "kind": "exact_int", "ui": "left_mop_water_volume",   "mes": "左拖布过水",
     "expect_attr": "ominiwater_left_mop_volume_expected"},
    {"field": "right_mop_vol", "kind": "exact_int", "ui": "right_mop_water_volume",  "mes": "右拖布过水",
     "expect_attr": "ominiwater_right_mop_volume_expected"},
    {"field": "left_mop_temp", "kind": "range_int", "ui": "left_mop_temperature",    "mes": "左拖布温度adc", ...},
    {"field": "right_mop_temp","kind": "range_int", "ui": "right_mop_temperature",   "mes": "右拖布温度adc", ...},
    {"field": "cleaner_level", "kind": "exact_int", "ui": "cleaner_liquid_level",    "mes": "清洁剂液位", ...},
    {"field": "base_hot_temp", "kind": "range_int", "ui": "base_hot_water_temp",     "mes": "基站热水温度adc", ...},
    {"field": "base_ver",      "kind": "version",   "ui": "base_station_ver",        "mes": "基站版本"},
    {"field": "base_config",   "kind": "string",    "ui": "base_station_config",     "mes": "基站配置码",
     "expect_attr": "ominiwater_base_config_expected"},
]
```

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-06-11 | 初版：022 动态裁剪过水工位规格 + 代码实现 |
