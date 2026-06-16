# Omini 工位测试项跳过配置规范

> **用途**：供工程师与后续 AI 维护 Omini 三个工位（020/021/022）时，通过 `config.yaml` 取消某项测试的参考说明。
> **状态**：与现网代码一致（锚点：`# #[OMINI-020-PROTO]`、`# #[OMINIAIR-021-PROTO]`、`# #[OMINIWATER-022-PROTO]`）。
> **加载入口**：`test_tool/test.py` → `load_config()`（**启动时读取，修改后须重启程序**）。

---

## 1. 核心机制

Omini 三个工位均通过以下函数决定某项是否**参与测试**：

| 工位 | device_type | 启用判定函数 | 动态 UI 构建 |
|------|-------------|--------------|--------------|
| Omini 全功能 | 020 | `omini_field_enabled()` | `omini_build_item_result()` |
| Omini 过气 | 021 | `ominiair_field_enabled()` | `ominiair_build_item_result()` |
| Omini 过水 | 022 | `ominiwater_field_enabled()` | `ominiwater_build_item_result()` |

**未启用（disabled）的项行为一致：**

1. **不显示** UI 测试格（启动时按 enabled 项动态生成）
2. **不参与** 终判 PASS/NG（`field_ok` 返回 `None`，不算 NG）
3. **不上报** MES（`add_reports` 中 `continue` 跳过）
4. 实时判据（020 的 `0x89`）**仅对 enabled 项**生效

**设计原则**：跳过 ≠ 失败；`field_ok → None` 表示「不参与比较，视为通过」。

---

## 2. 配置方式：注释 vs 哨兵值

在 `config.yaml` 中取消测试有两种等价写法：

| 写法 | 效果 |
|------|------|
| `#` 注释掉配置键 | YAML 不加载该键，`load_config()` 使用 `LoadCfg` 默认值 |
| 显式写哨兵值 | 与注释等价的可读写法，便于日后恢复 |

**注释与哨兵值等价**，任选其一即可。修改后**必须重启** `python main.py`。

---

## 3. 哨兵值规则（按字段类型）

### 3.1 020 全功能（`omini_*`）

| 类型 | 配置键模式 | 跳过条件（enabled=False） | 注释后默认值 |
|------|-----------|---------------------------|--------------|
| 区间类 | `omini_{name}_min` / `_max` | **min 与 max 同时为 0** | 0 |
| 期望值类 | `omini_{name}_expected`、`omini_ir_*` | 值为 **0** | 0 |
| 集尘 kPa | `omini_suction_kpa_min` / `_max` | min 与 max 同时为 0 | 0 |

> **注意**：区间类必须 **min/max 成对** 注释或置 0；只处理一行可能导致仍 enabled。

### 3.2 021 过气（`ominiair_*`）

| 类型 | 配置键 | 跳过条件 | 注释后默认值 |
|------|--------|----------|--------------|
| 气压区间 | `ominiair_{clear\|mop\|duty}_kpa_min/max` | min 与 max 同时为 0 | 0.0 |

### 3.3 022 过水（`ominiwater_*`）

| 类型 | 配置键 | 跳过条件 | 注释后默认值 |
|------|--------|----------|--------------|
| 水量/液位 | `ominiwater_*_expected` | 值为 **-1** | -1 |
| 温度 ADC | `ominiwater_*_temp_min/max` | min 与 max 同时为 0 | 0 |

---

## 4. 公共配置项

位于 `config.yaml` 顶部公共区，三工位共用。

### 4.1 基站/MCU 版本 — `mcu_version`

| 操作 | 效果 |
|------|------|
| `#` 注释或设为 `""` | `load_cfg.mcu_ver` 为空 → 版本项 disabled |
| 020 | 跳过 `dev_ver` / 「MCU版本」 |
| 021/022 | 跳过 `base_ver` / 「基站版本」 |

**结论**：`mcu_version` 可以 `#` 注释，完全适用核心机制。

### 4.2 基站配置码 — `base_station_config_expected`

| 工位 | `#` 注释跳过比对 | 说明 |
|------|------------------|------|
| **020** | ✅ 可以 | 不参与比对、UI（需 enabled）、MES、终判 |
| **022** | ✅ 可以 | 同上 |
| **021** | ❌ 不可简单注释 | 扫码通过后需 `0x57` 下发配置码；注释后 `rv50air_build_57_payload()` 返回 `None`，提示「基站配置码未配置或格式错误」，**测试无法启动** |

**021 特殊 UI 行为**（即使不配期望值）：

- `show_base_station_config_ui: 1` 时，仍可能显示配置码**回读格**（monitor，不着色、不 NG）
- 终判/MES 仍会因 expected 为空而跳过（`config_triplet_matches` → `None`）

**`FF.FF.FF` 陷阱**：

- `config.yaml` 注释写「不配或 FF.FF.FF 则跳过比对」
- **代码未对 FF.FF.FF 做特殊处理**；保留该值会 **enabled 并参与比对**
- 要跳过须：`#` 注释、设为 `""`，或删除该键

### 4.3 仅隐藏 UI — `show_base_station_config_ui`

| 值 | 作用 |
|----|------|
| `0` | 隐藏「基站配置码」测试格（020/022 在 `build_item_result` 中过滤） |
| `1` | 显示（默认） |

**不能**代替注释来禁用判据/MES；021 还有独立回读 UI 逻辑。

---

## 5. 各工位可跳过项清单

### 5.1 020 全功能（§020，`OMINI_FIELD_REGISTRY`）

| 测试项 | 配置键（注释或哨兵） |
|--------|---------------------|
| MCU 版本 | 公共 `# mcu_version` |
| 基站配置码 | 公共 `# base_station_config_expected`（020 可注释） |
| 充电电流 | `omini_charge_min/max` → 0 |
| 左/右/近卫回充码 | `omini_ir_l/r/n` → 0 |
| 清水箱/污水箱/尘袋/清洁底座 | `omini_clear_tank_expected` 等 → 0 |
| 集尘吸力 | `omini_suction_kpa_min/max` → 0 |
| 清水泵/真空泵/液位/电磁三通/清洁泵/浊度/热风差值 | 对应 `omini_*_min/max` → 0 |
| 热风开始/结束 | 注释 `omini_hot_diff_min/max`（跟随 `hot_diff`） |

步骤四：`expected=0` 的模块不进入 `omini_step4_enabled_modules()`，工人不会被提示操作该模块。

### 5.2 021 过气（§021，`OMINIAIR_FIELD_REGISTRY`）

| 测试项 | 配置键 |
|--------|--------|
| 清水/拖布/污水通路气压 | `ominiair_*_kpa_min/max` → 0 |
| 基站版本 | `# mcu_version` |
| 基站配置码 | **不可注释**（见 §4.2）；须保留有效 `XX.XX.XX` 以启动测试 |

### 5.3 022 过水（§022，`OMINIWATER_FIELD_REGISTRY`）

| 测试项 | 配置键 |
|--------|--------|
| 清水/污水/左拖/右拖水量 | `ominiwater_*_volume_expected` → -1 |
| 清洁剂液位 | `ominiwater_cleaner_level_expected` → -1 |
| 左/右拖布温度、基站热水温度 | `ominiwater_*_temp_min/max` → 0 |
| 基站版本 | `# mcu_version` |
| 基站配置码 | `# base_station_config_expected`（022 可注释） |

---

## 6. 不能通过 `#` 跳过的内容

以下不在 `field_enabled` 体系内，无法通过注释专项配置取消：

| 类别 | 说明 |
|------|------|
| 治具通讯失败 | 0x88 结束码 `0x04` |
| 结束码异常 | 0x88 非 `0x03` |
| 扫码/MES 门闸 | SN 校验、过站失败 |
| 021 配置下发 | `0x57` 流程依赖有效 `base_station_config_expected` |
| 020 步骤四 LED 人工确认 | 与 enabled 模块相关，但治具物理步骤仍可能执行 |

---

## 7. 代码锚点（维护时搜索）

```
# #[OMINI-020-PROTO]
omini_field_enabled          test_tool/test.py
omini_build_item_result
omini_field_ok               → None = 跳过
omini_proto_add_reports
omini_proto_yaml_all_items_ok

# #[OMINIAIR-021-PROTO]
ominiair_field_enabled
ominiair_build_item_result
rv50_omini_air_on_scan_pass  → 021 配置码门闸
rv50air_build_57_payload

# #[OMINIWATER-022-PROTO]
ominiwater_field_enabled
ominiwater_build_item_result
ominiwater_field_ok

公共：
load_config()                → 读取 config.yaml
config_triplet_matches       → 配置码比对；期望空 → None
ver_triplet_matches          → 版本比对；期望空 → None
base_station_config_ui_enabled
```

**UI 入口**：`ui/MainFrame.py` — `dev==20/21/22` 时分别调用 `omini_build_item_result()` 等。

**相关规格**：

- `OMINI_FULL_020_IMPLEMENTATION_SPEC.md` / `OMINI_FULL_FUNCTION_AI_IMPLEMENTATION_SPEC.md`
- `OMINI_AIR_021_IMPLEMENTATION_SPEC.md`
- `OMINIWATER_022_IMPLEMENTATION_SPEC.md`

---

## 8. 操作检查清单

修改 `config.yaml` 后，按下列步骤验证：

- [ ] 确认 `device_type` 为 `020` / `021` / `022` 之一
- [ ] 区间类 min/max 已**成对**注释或置哨兵值
- [ ] 021 未注释 `base_station_config_expected`（须为有效 `XX.XX.XX`）
- [ ] 未误留 `FF.FF.FF` 当作「跳过」（仍会比对）
- [ ] 保存后**重启程序**
- [ ] 启动后 UI 测试格：被跳过项不出现（021 配置码回读格除外）
- [ ] 跑一轮：被跳过项不上报 MES、不影响 PASS/NG

---

## 9. 一句话结论

> **除基站配置码在 021 工位不可简单 `#` 注释外，Omini 三工位其余所有走 `field_enabled` 的测试项（含 `mcu_version`）均可通过 `#` 注释或等价哨兵值实现：不显示 UI、不参与终判、不上报 MES、判据返回 None 且不算 NG。**

---

## 10. 配置示例

### 022 跳过左拖布水量与基站版本

```yaml
device_type: "022"

# mcu_version: "005.001.030"   # 跳过版本比对

ominiwater_clear_volume_expected: 3
ominiwater_duty_volume_expected: 3
# ominiwater_left_mop_volume_expected: 3   # 跳过左拖布水量
ominiwater_right_mop_volume_expected: 3
```

### 020 跳过浊度与清水泵

```yaml
# omini_clean_pump_min: 50
# omini_clean_pump_max: 350
# omini_turbidity_min: 5000
# omini_turbidity_max: 15000
```

### 021 跳过拖布通路气压（配置码须保留）

```yaml
ominiair_clear_kpa_min: 20
ominiair_clear_kpa_max: 80
# ominiair_mop_kpa_min: 20      # 跳过拖布通路
# ominiair_mop_kpa_max: 230
ominiair_duty_kpa_min: -30
ominiair_duty_kpa_max: -18

base_station_config_expected: "00.00.17"   # 021 必须保留有效值
```

---

*文档版本：2026-06-16 · 对应仓库 CE_MES_SEC Omini 020/021/022 实现*
