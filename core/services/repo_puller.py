"""
[L-Service] WFCD 数据仓库拉取模块（新版本）

使用 Git 稀疏检出，只拉取需要的文件。
从 scripts/pull_warframe_items.py 迁移而来。

支持 3 个上游仓库:
  - WFCD/warframe-items      → 遗物/物品数据
  - WFCD/warframe-drop-data   → 掉落数据
  - calamity-inc/warframe-public-export-plus → 翻译数据
"""

import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Callable


# ============================================================
# 路径常量（相对于项目根目录）
# ============================================================
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_EXTERNAL_DIR = _PROJECT_ROOT / "external"

# ── warframe-items ──
REPO_DIR = _EXTERNAL_DIR / "warframe-items_sparse"
OUTPUT_DIR = _EXTERNAL_DIR / "warframe-items_sparse" / "data" / "json"
FILES_TO_PULL = [
    "data/json/Relics.json",
    "data/json/i18n.json",
    "data/json/All.json",
]

# ── warframe-drop-data ──
DROP_REPO_URL = "https://github.com/WFCD/warframe-drop-data.git"
DROP_REPO_DIR = _EXTERNAL_DIR / "warframe-drop-data_sparse"
DROP_OUTPUT_DIR = _EXTERNAL_DIR / "warframe-drop-data_sparse" / "data"
DROP_FILES_TO_PULL = ["data/all.json"]

# ── warframe-public-export-plus (翻译) ──
I18N_REPO_URL = "https://github.com/calamity-inc/warframe-public-export-plus.git"
I18N_REPO_BRANCH = "senpai"
I18N_REPO_DIR = _EXTERNAL_DIR / "warframe-i18n_sparse"
I18N_OUTPUT_DIR = _EXTERNAL_DIR / "warframe-i18n_sparse"
I18N_FILES_TO_PULL = ["dict.en.json", "dict.zh.json"]


def run_cmd(cmd: list, cwd: Path = None, capture: bool = False) -> tuple:
    """
    运行 Git 命令
    :param cmd: 命令列表
    :param cwd: 工作目录
    :param capture: 是否捕获输出
    :return: (返回码, 标准输出, 标准错误)
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return -1, "", str(e)


def _rmtree_force(path: Path):
    """强制删除目录（处理 Windows 下的只读文件问题）。"""
    import stat
    def _on_error(func, p, exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(str(path), onerror=_on_error)


# ============================================================
# 通用稀疏检出模板
# ============================================================

def _sparse_checkout(
    repo_url: str,
    repo_dir: Path,
    output_dir: Path,
    files_to_pull: list[str],
    label: str,
    log_callback=None,
    progress_callback=None,
    clone_url: str = None,
    branch: str = None,
) -> bool:
    """通用 Git 稀疏检出流程。

    Args:
        repo_url: 默认仓库 URL
        repo_dir: 本地仓库目录
        output_dir: 输出文件目录
        files_to_pull: 需要检出的文件路径列表
        label: 日志标签（如 "遗物/物品"）
        log_callback: (level, msg)
        progress_callback: (pct) 或 (stage, cur, total)
        clone_url: 自定义克隆 URL（代理镜像）
        branch: 指定分支（None 则用默认）
    Returns:
        是否成功
    """
    total_steps = 5
    current_step = 0

    def _log(level: str, msg: str):
        if log_callback:
            log_callback(level, msg)

    def _progress(stage: str, cur: int = None, total: int = None, pct: int = None):
        nonlocal current_step
        if progress_callback:
            if pct is not None:
                progress_callback(pct)
            elif cur is not None and total is not None:
                progress_callback(stage, cur, total)

    url = clone_url if clone_url else repo_url

    current_step += 1
    _progress("初始化仓库", current_step, total_steps, int((current_step / total_steps) * 100))

    # 清理旧的
    if repo_dir.exists():
        _log('info', f"\n清理旧仓库: {repo_dir}")
        _rmtree_force(repo_dir)

    # 步骤 1: git clone --sparse
    current_step += 1
    _progress("克隆仓库", current_step, total_steps, int((current_step / total_steps) * 100))
    _log('info', f"\n克隆仓库: {url}")
    clone_args = ["git", "clone", "--depth=1", "--filter=blob:none", "--sparse", "--no-checkout"]
    if branch:
        clone_args.append(f"--branch={branch}")
    clone_args.extend([url, str(repo_dir)])

    code, out, err = run_cmd(clone_args, capture=True)
    if code != 0:
        _log('error', f"[X] git clone 失败: {err}")
        _log('info', "回退: 尝试不带 --filter 的克隆...")
        if repo_dir.exists():
            _rmtree_force(repo_dir)
        fallback_args = ["git", "clone", "--depth=1", "--sparse", "--no-checkout"]
        if branch:
            fallback_args.append(f"--branch={branch}")
        fallback_args.extend([url, str(repo_dir)])
        code, out, err = run_cmd(fallback_args, capture=True)
        if code != 0:
            _log('error', f"[X] git clone (回退) 也失败: {err}")
            return False

    # 步骤 2: 配置要检出的文件
    current_step += 1
    _progress("配置稀疏检出", current_step, total_steps, int((current_step / total_steps) * 100))
    _log('info', "配置要检出的文件:")
    for f in files_to_pull:
        _log('info', f"  - {f}")

    code, _, err = run_cmd(
        ["git", "sparse-checkout", "set", "--no-cone"] + files_to_pull,
        cwd=repo_dir
    )
    if code != 0:
        _log('error', f"[X] sparse-checkout 配置失败: {err}")
        return False

    # 步骤 3: 检出文件
    current_step += 1
    _progress("检出文件", current_step, total_steps, int((current_step / total_steps) * 100))
    _log('info', "\n检出文件...")
    code, out, err = run_cmd(["git", "checkout"], cwd=repo_dir, capture=True)
    if code != 0:
        _log('error', f"[X] git checkout 失败: {err}")
        return False

    # 步骤 4: 复制文件到输出目录
    current_step += 1
    _progress("复制文件", current_step, total_steps, int((current_step / total_steps) * 100))
    _log('info', "\n复制文件到目标目录...")
    output_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    for idx, src_path in enumerate(files_to_pull):
        _progress("复制文件", idx + 1, len(files_to_pull), int((idx + 1) / len(files_to_pull) * 100))
        src_file = repo_dir / src_path
        if src_file.exists():
            dest_file = output_dir / Path(src_path).name
            try:
                if src_file.samefile(dest_file):
                    _log('info', f"  [OK] {Path(src_path).name} (已在目标位置)")
                    success_count += 1
                    continue
            except OSError:
                pass
            copied = False
            for attempt in range(5):
                try:
                    shutil.copy2(src_file, dest_file)
                    copied = True
                    break
                except PermissionError:
                    import time as _time
                    if attempt < 4:
                        _log('warn', f"  [!] {Path(src_path).name} 被占用，等待 1 秒后重试 ({attempt + 1}/5)...")
                        _time.sleep(1)
                    else:
                        _log('error', f"  [X] {Path(src_path).name} 复制失败: 文件被锁定")
            if copied:
                _log('info', f"  [OK] {Path(src_path).name}")
                success_count += 1

    # 步骤 5: 完成
    current_step += 1
    _progress("完成", current_step, total_steps, 100)

    _log('info', "\n" + "=" * 80)
    if success_count == len(files_to_pull):
        _log('ok', f"[OK] {label} 全部成功！")
    else:
        _log('warn', f"[!] {label} 完成，部分缺失: {success_count}/{len(files_to_pull)}")
    _log('info', f"  保存位置: {output_dir.absolute()}")
    _log('info', "=" * 80)
    return success_count > 0


# ============================================================
# 公开接口：各仓库的初始化和更新
# ============================================================

def init_items_sparse_checkout(
    log_callback=None, progress_callback=None, clone_url: str = None,
) -> bool:
    """初始化 warframe-items 稀疏检出仓库。"""
    return _sparse_checkout(
        repo_url="https://github.com/WFCD/warframe-items.git",
        repo_dir=REPO_DIR,
        output_dir=OUTPUT_DIR,
        files_to_pull=FILES_TO_PULL,
        label="WFCD/warframe-items 遗物/物品",
        log_callback=log_callback,
        progress_callback=progress_callback,
        clone_url=clone_url,
    )


def update_items_existing(
    log_callback=None, progress_callback=None, clone_url: str = None,
) -> bool:
    """更新已有的 warframe-items 仓库（删除后重建）。"""
    def _log(level, msg):
        if log_callback:
            log_callback(level, msg)
    _log('info', "仓库已存在，删除后重新初始化...")
    if REPO_DIR.exists():
        _rmtree_force(REPO_DIR)
    return init_items_sparse_checkout(
        log_callback=log_callback, progress_callback=progress_callback, clone_url=clone_url,
    )


def init_drop_data_sparse_checkout(
    log_callback=None, progress_callback=None, clone_url: str = None,
) -> bool:
    """初始化 warframe-drop-data 稀疏检出仓库。"""
    return _sparse_checkout(
        repo_url=DROP_REPO_URL,
        repo_dir=DROP_REPO_DIR,
        output_dir=DROP_OUTPUT_DIR,
        files_to_pull=DROP_FILES_TO_PULL,
        label="WFCD/warframe-drop-data 掉落数据",
        log_callback=log_callback,
        progress_callback=progress_callback,
        clone_url=clone_url,
    )


def update_drop_data_existing(
    log_callback=None, progress_callback=None, clone_url: str = None,
) -> bool:
    """更新已有的 drop-data 仓库。"""
    def _log(level, msg):
        if log_callback:
            log_callback(level, msg)
    _log('info', "掉落数据仓库已存在，删除后重新初始化...")
    if DROP_REPO_DIR.exists():
        _rmtree_force(DROP_REPO_DIR)
    return init_drop_data_sparse_checkout(
        log_callback=log_callback, progress_callback=progress_callback, clone_url=clone_url,
    )


def init_i18n_sparse_checkout(
    log_callback=None, progress_callback=None, clone_url: str = None,
) -> bool:
    """初始化 warframe-public-export-plus 翻译数据稀疏检出仓库。"""
    return _sparse_checkout(
        repo_url=I18N_REPO_URL,
        repo_dir=I18N_REPO_DIR,
        output_dir=I18N_OUTPUT_DIR,
        files_to_pull=I18N_FILES_TO_PULL,
        label="calamity-inc/warframe-public-export-plus 翻译数据",
        log_callback=log_callback,
        progress_callback=progress_callback,
        clone_url=clone_url,
        branch=I18N_REPO_BRANCH,
    )


def update_i18n_existing(
    log_callback=None, progress_callback=None, clone_url: str = None,
) -> bool:
    """更新已有的 i18n 仓库。"""
    def _log(level, msg):
        if log_callback:
            log_callback(level, msg)
    _log('info', "翻译数据仓库已存在，删除后重新初始化...")
    if I18N_REPO_DIR.exists():
        _rmtree_force(I18N_REPO_DIR)
    return init_i18n_sparse_checkout(
        log_callback=log_callback, progress_callback=progress_callback, clone_url=clone_url,
    )
