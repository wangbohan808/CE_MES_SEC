# Omini 基站过气治具 — 实现规格（021）

> **用途**：供后续 AI 或工程师实现/维护 `device_type=021` Omini 基站过气工位，并可作为 **022 过水** 等 Omini 子工位的裁剪模板。  
> **状态**：**已实现**（代码锚点 `# #[OMINIAIR-021-PROTO]`）。  
> **设计原则**：协议帧与 **RV50 过气（015）** 相同（0x77 数据区 13 字节）；配置独立 **`ominiair_*` 前缀**；未配置项不参与比较、不显示 UI、不上报 MES。  
> **对照范例**：`test_tool/test.py` 中 `# #[RV50-015-AIR-PROTO]`、`doc/ce_mes_iteration/OMINI_FULL_FUNCTION_AI_IMPLEMENTATION_SPEC.md` §6.2。

---

## 1. 工位标识

| 项 | 值 |
|----|-----|
| `device_type` | `"021"`（`int(load_cfg.dev)==21`） |
| 串口帧 `dev` 字节 | **`0x15`（21）** — 与 `device_type` 数值一致 |
| 窗口标题键 | `heading_line_dict["021"]` → `"Omini过气测试"` |
| MES 工序站码 | **`HNOMINIQMXCS`**（**待定**，`mes/celink_mes.py` 中标注） |
| 搜索标记 | `# #[OMINIAIR-021-PROTO]`、`ominiair_`、`Omini_air_mode` |

---

## 2. 协议（与 015 相同）

### 2.1 0x77 数据区（13 字节）

| 偏移 | 含义 |
|------|------|
| `dat[0]` | step（1=进入产测，2=测试中，3=结果上传） |
| `dat[1..2]` | 清水通路气压 u16 BE，10Pa 计数 |
| `dat[3..4]` | 拖布通路气压 u16 BE |
| `dat[5..6]` | 污水通路气压 **有符号** int16 |
| `dat[7..9]` | 基站版本 `NNN.NNN.NNN` |
| `dat[10..12]` | 基站配置码 `NNN.NNN.NNN` |

气压显示/比较：raw × 0.01 → kPa（含端点）。

### 2.2 命令字

| 命令 | 行为 |
|------|------|
| `0x66 [0x00]` | 清报告、请扫码 |
| `0x57` / `0x58` | 扫码门闸通过/失败（通用 `barcode_check_process`） |
| `0x77` | 实时数据；**仅 RUNNING 态处理** |
| `0x88` | 结束帧：`03` 正常结束再综合判 PASS/NG；`04` 基站通讯失败 |

**021 不发 `0x89`**（与 015 一致）。

### 2.3 终判条件

与 015 对齐：

1. 收到 `0x88` 且首字节 `0x03`  
2. 本轮 **到过 step=3**（`ominiair_got_step3 == True`）  
3. 锁存最后一帧 `0x77` 解析结果 `ominiair_last_p` 非空  
4. `ominiair_all_ok(p)`：所有 **enabled** 项 `ominiair_field_ok` 均不为 `False`

---

## 3. 动态配置语义

### 3.1 enabled（参与比较）条件

| 判据类型 | config 键 | enabled 条件 |
|----------|-----------|--------------|
| 区间（三路气压） | `ominiair_{clear\|mop\|duty}_kpa_min/max` | **min 与 max 不同时为 0** |
| 基站版本 | 公共 `mcu_version` | 非空字符串 |
| 基站配置码 | `ominiair_base_config_expected` | 非空字符串 |

### 3.2 `ominiair_field_ok` 返回值

| 返回值 | 含义 | 终判 |
|--------|------|------|
| `True` | 在阈值内 / 字符串相等 | 通过 |
| `False` | 超阈值 / 不等 | **NG** |
| `None` | 未 enabled | **跳过（不算 NG）** |

汇总：**仅 `ok is False` 导致 NG**。

### 3.3 UI

- 启动时 `ominiair_build_item_result()` 按 enabled 项 **动态生成** 测试格（未配置项不创建）。  
- 过程帧（step 1~2）：enabled 项显示 **monitor**（实时 kPa/字符串）。  
- 终判：`pass` / `fail` 着色。

### 3.4 MES

- `ominiair_add_reports()` **仅上报 enabled 项**。  
- `p is None` 时仅对 enabled 项报 NG。

---

## 4. config.yaml 示例

```yaml
device_type: "021"
project_name: "Omini"

# §021  Omini 基站过气（帧 dev=0x15）
# 某项 min/max 均为 0 → 不参与比较、不显示 UI
ominiair_clear_kpa_min: 20
ominiair_clear_kpa_max: 80
ominiair_duty_kpa_min: -30
ominiair_duty_kpa_max: -18
# 不配 ominiair_mop_kpa_* → 无拖布通路传感器则不测

mcu_version: "002.001.078"
ominiair_base_config_expected: "001.002.003"  # 可选；不配则跳过
```

---

## 5. 代码文件索引

| 文件 | 改动 |
|------|------|
| `test_tool/test.py` | `LoadCfg` `ominiair_*`；`OMINIAIR_*` 会话；`ominiair_field_*`；`Omini_air_mode`；`load_config`；`test_cmd_handle`；`barcode_check_process` |
| `ui/MainFrame.py` | `ominiair_build_item_result()` 动态测试格；`dev==21` 显示测试区 |
| `config.yaml` | §021 索引 + 专项配置 |
| `mes/celink_mes.py` | `"021": "HNOMINIQMXCS"`（待定） |

---

## 6. 字段注册表（复用模板）

```python
OMINIAIR_FIELD_REGISTRY = [
    {"field": "clear",       "kind": "range_kpa", "ui": "clear_water_pressure",  "mes": "清水通路气压",
     "min_attr": "ominiair_clear_kpa_min", "max_attr": "ominiair_clear_kpa_max"},
    {"field": "mop",         "kind": "range_kpa", "ui": "mop_water_pressure",    "mes": "拖布通路气压",
     "min_attr": "ominiair_mop_kpa_min",   "max_attr": "ominiair_mop_kpa_max"},
    {"field": "duty",        "kind": "range_kpa", "ui": "duty_water_pressure",   "mes": "污水通路气压",
     "min_attr": "ominiair_duty_kpa_min",  "max_attr": "ominiair_duty_kpa_max"},
    {"field": "base_ver",    "kind": "version",   "ui": "base_station_ver",        "mes": "基站版本"},
    {"field": "base_config", "kind": "string",    "ui": "base_station_config",     "mes": "基站配置码",
     "expect_attr": "ominiair_base_config_expected"},
]
```

**022 过水** 可仿此结构，改 `OMINIWATER_FIELD_REGISTRY` 与解析长度即可。

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-06-11 | 初版：021 动态裁剪过气工位规格 + 代码实现 |
