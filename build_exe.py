# -*- coding: utf-8 -*-
"""
TankBattle 自动打包脚本（PyInstaller 一键生成单文件 exe）
========================================================
功能流程：
  1. 确保 pygame 可用（优先安装 pygame，失败则回退安装 pygame-ce）；
  2. 确保 PyInstaller 可用（缺失则自动安装）；
  3. 调用 PyInstaller 打包 game.py 为单文件、无控制台窗口的 TankBattle.exe；
  4. 清理 build 目录与 *.spec 临时文件；
  5. 校验并打印 exe 的绝对路径。

用法：python build_exe.py
"""

import os
import sys
import glob
import shutil
import subprocess
import importlib.util

# 脚本所在目录（所有操作均以此为工作目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_cmd(cmd):
    """执行子进程命令并实时打印，返回是否成功。"""
    print("  > " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=SCRIPT_DIR)
    return proc.returncode == 0


def pygame_ready():
    """校验 pygame 可导入且主版本 >= 2（游戏用到 border_radius 等 pygame2 特性，
    老旧 pygame 1.9.x 会打包成功但运行即崩）。"""
    try:
        import pygame
        return pygame.version.vernum[0] >= 2
    except Exception:
        return False


def ensure_pygame():
    """步骤一：确保 pygame 可导入且版本>=2。缺失/过旧时先装 pygame，失败回退 pygame-ce。"""
    print("[1/5] 检查 pygame ...")
    if pygame_ready():
        print("      已检测到 pygame（版本 >= 2），跳过安装。")
        return True
    print("      未检测到可用 pygame（缺失或版本 < 2），尝试安装 pygame ...")
    if run_cmd([sys.executable, "-m", "pip", "install", "--upgrade", "pygame"]):
        if pygame_ready():
            print("      pygame 安装成功。")
            return True
    print("      pygame 安装失败（可能缺少对应 wheel），回退安装 pygame-ce ...")
    if run_cmd([sys.executable, "-m", "pip", "install", "--upgrade", "pygame-ce"]):
        if pygame_ready():
            print("      pygame-ce 安装成功（import pygame 写法兼容）。")
            return True
    print("错误：pygame / pygame-ce 均安装失败，无法继续打包。")
    return False


def ensure_pyinstaller():
    """步骤二：确保 PyInstaller 可用，缺失则自动安装。"""
    print("[2/5] 检查 PyInstaller ...")
    if importlib.util.find_spec("PyInstaller") is not None:
        print("      已检测到 PyInstaller，跳过安装。")
        return True
    print("      未检测到 PyInstaller，正在安装 ...")
    if run_cmd([sys.executable, "-m", "pip", "install", "pyinstaller"]):
        if importlib.util.find_spec("PyInstaller") is not None:
            print("      PyInstaller 安装成功。")
            return True
    print("错误：PyInstaller 安装失败，无法继续打包。")
    return False


def build():
    """步骤三：调用 PyInstaller 打包 game.py。

    --onefile   单文件输出
    --windowed  隐藏控制台窗口（等价 --noconsole / -w）
    同时排除与本游戏无关的 panda3d / ursina，减小体积、避免误收集。
    """
    print("[3/5] 开始打包 game.py ...")
    game_path = os.path.join(SCRIPT_DIR, "game.py")
    if not os.path.exists(game_path):
        print("错误：未找到 game.py，请确认其位于脚本同目录。")
        return False
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", "TankBattle",
        "--exclude-module", "panda3d",
        "--exclude-module", "ursina",
        "game.py",
    ]
    return run_cmd(cmd)


def cleanup():
    """步骤四：清理 build 目录与 *.spec 临时文件。"""
    print("[4/5] 清理临时文件 ...")
    shutil.rmtree(os.path.join(SCRIPT_DIR, "build"), ignore_errors=True)
    for spec in glob.glob(os.path.join(SCRIPT_DIR, "*.spec")):
        try:
            os.remove(spec)
            print("      已删除：" + os.path.basename(spec))
        except OSError:
            pass
    print("      清理完成。")


def verify():
    """步骤五：校验 exe 是否生成，打印绝对路径。"""
    print("[5/5] 校验产物 ...")
    exe = os.path.abspath(os.path.join(SCRIPT_DIR, "dist", "TankBattle.exe"))
    if os.path.exists(exe):
        print("打包成功！可执行文件位于：")
        print(exe)
        return True
    print("错误：未找到 " + exe + "，打包失败。")
    return False


def main():
    print("=" * 60)
    print("TankBattle 自动打包（PyInstaller → 单文件 exe）")
    print("=" * 60)
    if not ensure_pygame():
        sys.exit(1)
    if not ensure_pyinstaller():
        sys.exit(1)
    if not build():
        sys.exit(1)
    cleanup()
    if not verify():
        sys.exit(1)


if __name__ == "__main__":
    main()
