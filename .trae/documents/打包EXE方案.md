# WARFRAME-RELIC 打包 EXE 方案

> 状态:**P1 ✅ P2 ✅ P3 ✅(用户实测功能正常)· P4(干净机器)待验证**
> 日期:2026-09-22 · 最新产物:`dist/WARFRAME-RELIC_win64_20260922.zip`(176 MB)
> 关联:旧打包产物已按用户要求清理(见 §2)· 执行记录见 §9

---

## 1. 背景与目标

| 项 | 内容 |
|---|---|
| 目标 | 打包为 EXE,在**没有 Python 环境**的电脑上运行全部功能 |
| 已知痛点 | 上次打包后「启动字符画修改后无法保存」 |
| 现状 | 旧 spec / build.py / build/ / dist/ 已清理完毕 |

---

## 2. 旧打包产物清理(已完成)

| 已删除 | 说明 |
|---|---|
| `WARFRAME-RELIC.spec` | 旧 spec,hiddenimports 含已删除模块(theme_config/hotkeys_page/relics_page 等),datas 含已不存在的 `icon/` 目录 |
| `build.py` | 旧构建脚本(逻辑要点已吸收进本方案 §5) |
| `build/` | PyInstaller 中间产物 |
| `dist/` | 旧发行版(含 启动.bat / WARFRAME-RELIC.7z) |

**旧打包的两个错误**(新方案修正):
1. `yolov5nu.pt` 被打进包里,但 core/ 中**零引用**(纯浪费体积);
2. hiddenimports 硬编码全部模块清单 → 每次加新文件都要手动维护,漏了就运行时报错。

---

## 3. 根因分析:字符画为什么保存不了

### 3.1 直接原因

启动字符画(像素字体)的持久化在 [pixel_font.py L536-543](file:///d:/MyProgram/WARFRAME-RELIC/core/state/pixel_font.py#L536-L543):

```python
def _compute_json_path() -> Path:
    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "data" / "pixel_font.json"
```

打包后 `Path(__file__)` 指向 **exe 解包目录**(`dist\WARFRAME-RELIC\_internal\core\state\`),算出的"项目根"实际是 `_internal\`,于是:

- 写入位置变成 `_internal\data\pixel_font.json` → 程序目录常在 `C:\Program Files` 等受保护位置 → **Permission denied**(`save_pixel_font` 返回「没有写入权限」);
- 即使写在成功,下次更新 exe 覆盖 `_internal` → 用户数据丢失;
- 若改用 onefile 模式则解压到临时目录,程序退出即销毁,**必丢**。

### 3.2 问题面(不止字符画)

全项目 grep 确认 **20+ 处**用 `Path(__file__).parent…` 推导 data/ 目录,同样存在此问题:

| 模块 | 写入目标 | 影响 |
|---|---|---|
| [pixel_font.py](file:///d:/MyProgram/WARFRAME-RELIC/core/state/pixel_font.py#L542) | data/pixel_font.json | 启动字符画(本次 bug) |
| [ui_prefs.py L55](file:///d:/MyProgram/WARFRAME-RELIC/core/services/ui_prefs.py#L55) | data/ui_prefs.json | 窗口透明度/沉浸设置 |
| [trigger_config.py L116](file:///d:/MyProgram/WARFRAME-RELIC/core/trigger_config.py#L116) | data/triggers.json | 辅助触发器配置 |
| [hotkey_config.py L65](file:///d:/MyProgram/WARFRAME-RELIC/core/hotkey_config.py#L65) | data/hotkeys*.json | 快捷键绑定 |
| [toggles_page.py L105](file:///d:/MyProgram/WARFRAME-RELIC/core/pages/toggles_page.py#L105) | data/feature_toggles.json | 功能开关 |
| [cd_assist_service.py L68](file:///d:/MyProgram/WARFRAME-RELIC/core/services/cd_assist_service.py#L68) | data/cd_assist_pos.json | CD 辅助位置 |
| [price_query_state.py L97](file:///d:/MyProgram/WARFRAME-RELIC/core/state/price_query_state.py#L97) | data/wm_items_cache.json | 价格缓存 |
| [localization_service.py L196](file:///d:/MyProgram/WARFRAME-RELIC/core/services/localization_service.py#L196) 等 | data/warframe.db | 数据库(更新写入) |
| [background_service.py L35](file:///d:/MyProgram/WARFRAME-RELIC/core/services/background_service.py#L35) | data/backgrounds/ | 自定义背景图 |
| [cd_debug_log.py L43](file:///d:/MyProgram/WARFRAME-RELIC/core/services/cd_debug_log.py#L43) | data/logs/ | 调试日志 |

**结论:这不是单个 bug,是路径策略缺失,必须统一治理后再打包。**

---

## 4. 新方案总体设计

### 4.1 打包形态:PyInstaller onedir(不用 onefile)

| 对比 | onedir(选它) | onefile |
|---|---|---|
| 启动速度 | 快(直接加载) | 每次解压 200MB+ 到临时目录,慢 |
| 杀软误报 | 较低 | 高 |
| 写入问题 | 可控(本方案治理) | 临时目录退出即毁,无解 |
| 分享方式 | 打成 zip/7z 一个压缩包 | 单文件 |

分享给别人的最终交付物:`WARFRAME-RELIC_win64_日期.zip`,解压即用。
控制台窗口**不显示**(用户决策:`--windowed` 只显示软件窗口);崩溃日志走 `data/logs/console.log`(dev.py frozen 兜底,见 §9)。

### 4.2 路径治理(核心):新建 `core/paths.py`

```
[L-Infrastructure] paths — 运行环境路径解析(纯 Python,无 Qt)

app_root()      → frozen? exe 所在目录 : 项目根      (用户数据根)
resource_dir()  → 打包只读资源目录(_internal/data)   (随包分发,只读)
user_data_dir() → exe 旁 data/;写入失败自动降级 %LOCALAPPDATA%\WARFRAME-RELIC\data
```

**资源二分法**:

| 类别 | 内容 | 打包位置 | 运行时读写 |
|---|---|---|---|
| 只读资源 | tokens yaml、字体、OCR 模型、图标、qt.conf | `_internal/`(PyInstaller datas) | 只读 |
| 初始模板 | 初始 warframe.db / 各 json 默认值 | `_internal/data/` | 只读,首启复制 |
| 用户数据 | 上面 3.2 表中所有会写的东西 | exe 旁 `data/`(降级 %LOCALAPPDATA%) | 读写 |

**首启迁移策略**(同时解决"升级丢配置"):
程序启动时,用户数据文件**不存在才**从只读资源复制初始模板;已存在则直接用 —— 用户修改永远不被覆盖。数据库若需要重建,由现有 db_builder 在 user_data 重建。

### 4.3 写入路径迁移(主要工作量)

把 §3.2 表中 20+ 处 `Path(__file__).parent…` 全部替换为 `core.paths` 调用。
- 纯代码改造,**不打包在开发环境行为完全不变**(paths.py 在非 frozen 态返回与现在相同的路径);
- 每迁一个模块跑一次 144 项回归,分批提交;
- `.bak` 文件(pixel_font.py.bak 等)不迁,顺手删除。

### 4.4 构建脚本:重写 `build.py`(自动收集,免维护)

吸收旧脚本优点(进度条/彩色日志/自检),修正旧缺点:

1. **hiddenimports 自动扫描**:遍历 `core/`(含根目录 .py)与 `data/` 全部模块自动加入 —— 新增文件零维护;
2. **datas 清单显式化**:`assets/`、`data/`、`qt.conf`(`yolov5nu.pt` 剔除);
3. `--collect-all rapidocr_onnxruntime` 保留(OCR 模型);
4. `--noconsole` / `--clean` / `--zip` 命令行选项;
5. UPX **关闭**(降低杀软误报,体积代价可接受);
6. 构建后自检:exe 存在、`_internal` 含 data/yaml/字体/OCR 模型、启动冒烟测试(exe 启动 5 秒后杀进程,看是否闪退);
7. 可选 `--zip` 生成发行压缩包。

---

## 5. 实施分期(每期独立可验证)

| 阶段 | 内容 | 验证方式 | 风险 | 状态 |
|---|---|---|---|---|
| **P1 路径治理** | core/paths.py + 20+ 处写入路径迁移 + 删 .bak | 开发环境全部功能照常 + 144 回归 | 低(行为等价重构) | ✅ |
| **P2 构建脚本** | 新 build.py(自动收集+自检) | 本机打包 + 冒烟 | 低 | ✅ |
| **P3 打包实测** | 本机运行 dist 产物,重点回归「改字符画→重启仍在」 | 手动功能清单 | 中(隐藏依赖可能漏) | ✅(修复 3 个崩溃 + 2 个实测问题后通过) |
| **P4 干净机器** | 无 Python 电脑全功能验证 | §6 清单 | 中 | ⬜ |

每阶段做完停下来给你确认,再进下一阶段。

---

## 6. 干净机器验证清单

- [ ] 双击 exe 正常启动,启动动画(含自定义字符画)正常
- [ ] **改启动字符画 → 保存 → 重启 exe 仍在(本次核心 bug)**
- [ ] 功能开关:切换 + 重启保持
- [ ] 快捷键绑定:修改 + 重启保持;窗口置顶热键
- [ ] 一线战报:加载裂缝、筛选
- [ ] 物品查询:OCR 截图识别(dxcam 摄像头路径)、价格查询(网络)
- [ ] 辅助触发器:增删改 + 重启保持
- [ ] CD 辅助显示:计时 + 位置记忆
- [ ] 护眼遮罩 / 沉浸模式(黑色/主题色切换)
- [ ] 数据总览:数据库状态、操作日志
- [ ] 主题换肤:预设切换、背景图导入、透明度
- [ ] 退出后 data/ 目录出现用户配置文件(路径治理生效的证据)

---

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 杀软误报(PyInstaller 常见) | 关 UPX;文档提示加白名单;必要时后续加代码签名(需证书,暂缓) |
| exe 旁目录不可写(Program Files) | user_data_dir 自动降级 %LOCALAPPDATA%,并写日志说明 |
| dxcam 打包环境异常 | P3 重点实测;dxcam 纯 win32 依赖,onedir 一般无碍 |
| Python 3.14 + PyInstaller 兼容 | 旧构建产物里有 python314.dll,证明上次打包成功,风险低 |
| 隐藏依赖漏(运行时 ModuleNotFoundError) | 构建脚本自动扫描全目录;冒烟测试兜底;崩溃详情见 data/logs/console.log |
| exe 图标 | `icon/` 目录已不存在;需要你提供一个 `.ico`(或先用 PySide6 图标生成) |

---

## 8. 待你决策的点

1. **控制台窗口**:默认保留(看日志方便)→ 同意?还是要 `--noconsole` 纯窗口版?
    打包后的项目不显示CMD窗口，只显示软件的窗口
2. **交付格式**:zip 压缩包(推荐)还是 7z?    
    ZIP包就行
3. **exe 图标**:你能提供一个 `.ico` 文件吗?还是先用默认/由 assets 里的图生成?

4. **数据库定位**:warframe.db 走「首启复制到用户数据 + 后续在用户数据更新」(推荐,支持在线更新不丢)→ 同意?
    同意
5. **P1-P4 分期节奏**:按 §5 每阶段停下来确认,还是 P1+P2 连做后一起确认?
    按 §5 每阶段停下来确认

---

## 9. 执行记录(2026-09-22)

### 9.1 P1 路径治理(✅)

- 新建 `core/paths.py`(四件套),迁移 pixel_font/ui_prefs/trigger/hotkey/toggles/cd_assist/price_cache/background/logs/proxy 配置组 + 数据库组 + matcher/worldstate/fonts/tokens 等只读资源定位
- 顺带修复 matcher 两处指向不存在目录的静默失效 db 路径;AST 三合一扫描(语法/未用/未定义)揪出并修复 4 处清理隐患;144 项回归全过

### 9.2 P2-P3 六次打包迭代(✅)

| # | 结果 | 修复内容 |
|---|---|---|
| 1 | 冒烟假阳性暴露 | windowed 崩溃弹错误对话框撑住进程 → smoke() 加 PIPE + stderr Traceback 检测 |
| 2 | 冒烟 FAIL | `'NoneType' has no 'write'`:windowed 下流为 None → dev.py frozen 兜底换向 console.log |
| 3 | 冒烟 FAIL | `UnicodeEncodeError 'gbk'`:管道/CMD 启动流有效但 GBK → frozen 时 reconfigure UTF-8;另:残留 exe 进程锁 dist → 重启前先杀 |
| 4 | **全绿** | 排除零引用连带库(torch/torchvision/scipy/pandas/matplotlib):dist 1013MB→494MB,ZIP 360MB→**176MB**;smoke 改 taskkill /T 杀进程树(onedir bootloader 孤儿子进程问题) |
| 5 | — | 价格页实测「列表不可用/无预选项」修复(LOADING 放行 + 15s 后台预热 + 本地 DB 降级) |
| 6 | **全绿交付** | 一线战报实测「刷新很慢」修复(磁盘缓存秒显 + 启动 10s 预取);P3 用户实测**功能全部正常** |

### 9.3 遗留事项

- P4 干净机器验证(§6 清单)
- exe 图标(用户未提供 .ico,暂不设)
- `data/logs/console.log` 会持续增长,后续可考虑加轮转上限
