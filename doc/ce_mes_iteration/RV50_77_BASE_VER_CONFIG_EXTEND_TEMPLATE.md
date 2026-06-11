# RV50 工位 0x77 扩展：基站版本 + 基站配置码 — 通用修改模板

> **锚点标记**：`# #[RV50-77-VER-CONFIG-EXT]`  
> **首版实现**：`device_type=015` 过气（`RV50AIR_77_DATA_LEN=13`）  
> **用途**：后续 016/017/018 等工位仿照本模板扩展 `0x77` 数据区，**不改变既有流程**。

---

## 1. 扩展原则（所有工位通用）

| 原则 | 说明 |
|------|------|
| 帧尾追加 | 原 `dat[0..N-1]` **下标不变**，在末尾追加 6 字节 |
| 追加内容 | `dat[N..N+2]` 基站版本（3 B）+ `dat[N+3..N+5]` 基站配置码（3 B） |
| 码值格式 | 每 3 字节 → `"NNN.NNN.NNN"`（与 `mcu_version` / 017 `dev_ver` 一致） |
| 版本期望 | 复用公共配置 **`mcu_version`** |
| 配置期望 | 工位专属 **`{prefix}_base_config_expected`**（字符串，格式同 `mcu_version`） |
| 流程不变 | `0x66 → 扫码 → 0x57/0x58 → 0x77… → 0x88`；不发 `0x89` |
| step 语义不变 | step 3 仅置 `got_step3`；**不在 step 3 单独比对** |
| UI 过程态 | 每帧 `0x77`：`monitor`（只显示实测值） |
| 终判时机 | 仅 `0x88` + `dat[0]==0x03` 时 `all_ok()` + UI `pass`/`fail` + MES |
| 空配置跳过 | 期望值为空 → `string_field_ok` 返回 `None`，不参与终判 |

### 1.1 帧长计算

```
新 DATA 长度 = 原长度 + 6
LEN 字段     = 2 + 新 DATA 长度
整帧字节数   = 2(帧头) + 1(LEN) + 1(DEV) + 1(CMD) + 新DATA + 1(CHECKSUM)
```

015 示例：原 7 → 新 13；LEN `0x09` → `0x0F`；整帧 13 → 19 字节。

---

## 2. 0x77 DATA 布局（015 范例）

| 下标 | 字段 | 宽度 | 说明 |
|------|------|------|------|
| 0 | step | 1 B | 不变 |
| 1~6 | 原业务字段 | 6 B | 过气：三路气压 |
| **7~9** | **base_ver** | **3 B** | 基站版本 |
| **10~12** | **base_config** | **3 B** | 基站配置码 |

解析：

```python
base_ver    = ".".join(format(int(dat[i]), "03d") for i in range(7, 10))
base_config = ".".join(format(int(dat[i]), "03d") for i in range(10, 13))
```

---

## 3. 代码修改清单（按文件）

### 3.1 `config.yaml`

1. 工位 § 注释注明新 DATA 长度与末 6 字节含义。  
2. `device_type` 索引行加注 `0x77 数据区 N 字节`。  
3. 新增工位键：`{prefix}_base_config_expected: "001.002.003"`。  
4. **不新增**版本键，继续用公共 `mcu_version`。

### 3.2 `test_tool/test.py`

| 步骤 | 内容 |
|------|------|
| ① 常量 | `{PREFIX}_77_DATA_LEN = 原长 + 6` |
| ② LoadCfg | `+ {prefix}_base_config_expected: str` |
| ③ load_config | 读入 `{prefix}_base_config_expected` |
| ④ 解析辅助 | `{prefix}_fmt_ver_3bytes(dat, start)` |
| ⑤ parse_77 | `len` 校验改为新常量；return 增加 `base_ver`、`base_config` |
| ⑥ string_field_ok | `base_ver`→`mcu_ver`；`base_config`→`{prefix}_base_config_expected`；空期望返回 `None` |
| ⑦ all_ok | 原判据 + 两项 `string_field_ok`；遇 `False` 即失败 |
| ⑧ ui_result_for_string | 过程 `monitor`；终判 `pass`/`fail` |
| ⑨ refresh_test_ui | 气压循环后追加 2 个 `up_test_ui` |
| ⑩ add_reports | 无数据分支 +2 条 NG；正常分支 `add_string_report` ×2 |
| ⑪ finalize_88 | NG 文案改为「测试项未达标」（可选） |

**不修改**：`{prefix}_mode()` 主分支、`step_notify`、`barcode_check_process`、`test_rx_data_handle`。

### 3.3 `ui/MainFrame.py`

在 `{prefix}_item_result` 末尾追加：

```python
{"base_station_ver": ["基站版本：", "", "white"]},
{"base_station_config": ["基站配置码：", "", "white"]},
```

UI 键名与 `test.py` 中 `up_test_ui(name=...)` **必须一致**。

---

## 4. 比对与 MES 规则

### 4.1 等值比对（字符串码值）

```python
def xxx_string_field_ok(field, actual):
    if field == "base_ver":
        expect = (load_cfg.mcu_ver or "").strip()
    elif field == "base_config":
        expect = (load_cfg.xxx_base_config_expected or "").strip()
    if not expect:
        return None          # 跳过
    if not actual:
        return False
    return actual == expect
```

### 4.2 MES 上报

```python
mes_run.add_report(
    name="基站版本",  # 或「基站配置码」
    result="OK" if ok else "NG",   # ok is None 时记 OK（跳过）
    value=actual,
    val_min=expect, val_max=expect,
)
```

### 4.3 终判 PASS 条件（在原有条件上叠加）

1. `got_step3 == True`  
2. `last_p` 非空  
3. 原测试项全部达标  
4. `base_ver == mcu_version`（未配置则跳过）  
5. `base_config == xxx_base_config_expected`（未配置则跳过）

---

## 5. 仿照到其他工位时的差异表

| 工位 | 前缀 | 原 DATA 长 | 新 DATA 长 | LEN | 配置键 |
|------|------|-----------|-----------|-----|--------|
| 015 过气 | `rv50air` | 7 | **13** | `0x0F` | `rv50air_base_config_expected` |
| 016 过水 | `rv50water` | 16 | **22** | `0x18` | `rv50water_base_config_expected` |
| 017 全功能 | `rv50` | 38 | **44** | `0x2E` | `rv50_base_config_expected` |
| 018 PCBA | `rv50pcba` | 38 | **44** | `0x2E` | `rv50pcba_base_config_expected` |

> 上表 016/017/018 为按同一规则推算，**实现前需与治具协议 CSV 核对**。

各工位仅替换：**前缀、原 DATA 长度、parse_77 中 ver/config 起始下标（=原长度）**；流程与 UI/MES 模式相同。

---

## 6. 自测检查项

- [ ] 治具发新长度 `0x77`，UI 全部测试项 `monitor` 有值  
- [ ] step 1/2/3 通知文案与改前一致  
- [ ] `0x88 0x03` 全部达标 → PASS  
- [ ] 版本或配置不符 → NG，对应项 `fail`  
- [ ] `mcu_version` 或 `*_base_config_expected` 留空 → 该项跳过  
- [ ] 治具仍发旧长度帧 → 解析失败日志，不崩溃  

---

## 7. 015 已实现文件索引

| 文件 | 标记/符号 |
|------|-----------|
| `config.yaml` §015 | `rv50air_base_config_expected` |
| `test_tool/test.py` | `RV50AIR_77_DATA_LEN`、`rv50air_fmt_ver_3bytes`、`rv50air_string_field_ok` |
| `ui/MainFrame.py` | `rv50air_item_result` +2 行 |

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-06-11 | 初版：015 实现 + 通用模板，替代原 1 字节 `base_config` 方案 B 文档中的 015 部分 |
