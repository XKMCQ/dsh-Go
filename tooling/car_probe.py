#!/usr/bin/env python3
"""车机体检：这台车机能不能装 dsh-go 的 x64 包，装上之后哪几项会挡路。

只读，不改设备上的任何东西。判断依据是 `adb shell getprop`、`wm size`、
`wm density`、`ime list` 这些公开查询，和 docs/car-x86_64.md 的清单一一对应。

    python3 tooling/car_probe.py                 # 连着的那台设备
    python3 tooling/car_probe.py --serial ABC    # 指定设备（adb devices 里那串）
    python3 tooling/car_probe.py --props p.txt   # 离线：把 getprop 输出存成文件再看

离线文件就是 `adb shell getprop` 的原文，可另加三行覆盖（没有就问 adb 拿不到）：

    wm.size=1280x480
    wm.density=160
    ime.list=com.sohu.inputmethod.sogou/.SogouIME

退出码：0 可以装，1 装不上（ABI 或 API 不符），2 能装但有风险（看 warn 行）。
"""

import argparse
from pathlib import Path
import re
import subprocess
import sys
import unicodedata

# app/android/app/build.gradle.kts: minSdk 26, targetSdk 28 (Termux's choice, so
# the API 29+ exec restriction on app-private files does not apply to the rootfs).
MIN_SDK = 26
TARGET_SDK = 28

# app/lib/ui/shell/adaptive/adaptive_layout.dart, with carMode on: a head unit's
# window is wide and short and nothing folds up from below, so only the width
# decides which columns fit.
MEDIUM_MIN = 600.0
EXPANDED_MIN = 840.0
COMPACT_HEIGHT = 480.0

OK, WARN, FAIL = "ok", "warn", "fail"


class Probe:
    def __init__(self):
        self.lines = []
        self.worst = OK

    def add(self, level, title, detail=""):
        order = {OK: 0, WARN: 1, FAIL: 2}
        if order[level] > order[self.worst]:
            self.worst = level
        self.lines.append((level, title, detail))

    def report(self, props):
        marks = {OK: "  ok  ", WARN: " warn ", FAIL: " fail "}
        width = max((display_width(title) for _, title, _ in self.lines), default=0)
        for level, title, detail in self.lines:
            print(f"[{marks[level]}] {title}{' ' * (width - display_width(title))}  {detail}".rstrip())
        print()
        if self.worst == FAIL:
            print(f"结论：装不上。设备 {props.get('ro.product.model', '?')}，"
                  "见上面 fail 行。")
        elif self.worst == WARN:
            print(f"结论：能装，但有风险。设备 {props.get('ro.product.model', '?')}，"
                  "见上面 warn 行。")
        else:
            print(f"结论：可以装。设备 {props.get('ro.product.model', '?')}，"
                  "按 docs/car-x86_64.md 装包并做首次启动检查。")
        return {OK: 0, FAIL: 1}.get(self.worst, 2)


def adb(serial, *args):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise SystemExit(f"adb {' '.join(args)} 失败：{out.stderr.strip() or out.stdout.strip()}")
    return out.stdout


def read_device(serial):
    props = {}
    for line in adb(serial, "shell", "getprop").splitlines():
        match = re.match(r"\[(.+?)\]: \[(.*)\]", line.strip())
        if match:
            props[match.group(1)] = match.group(2)
    props["wm.size"] = adb(serial, "shell", "wm", "size").strip()
    props["wm.density"] = adb(serial, "shell", "wm", "density").strip()
    for key, args in (
        ("ime.list", ("shell", "ime", "list", "-s")),
        ("storage", ("shell", "df", "-k", "/data")),
        ("selinux", ("shell", "getenforce")),
        ("gms", ("shell", "pm", "list", "packages", "com.google.android.gms")),
    ):
        try:
            props[key] = adb(serial, *args).strip()
        except SystemExit:
            props[key] = ""
    return props


def read_props_file(path):
    props = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"\[(.+?)\]: \[(.*)\]", line.strip())
        if match:
            props[match.group(1)] = match.group(2)
        elif "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()
    return props


def size_line(text):
    match = re.search(r"(\d+)\s*x\s*(\d+)", text or "")
    return f"{match.group(1)}x{match.group(2)}" if match else ""


def density_line(text):
    match = re.search(r"(\d+)", text or "")
    return match.group(1) if match else ""


def int_of(props, key, default=0):
    try:
        return int(str(props.get(key, "")).strip())
    except ValueError:
        return default


def display_width(text):
    """终端列宽：汉字占两格，对齐才不会被中英混排带歪。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def window_class(width, height, car):
    if height < COMPACT_HEIGHT and not (car and width >= MEDIUM_MIN):
        return "compact"
    if width >= EXPANDED_MIN:
        return "expanded"
    if width >= MEDIUM_MIN:
        return "medium"
    return "compact"


def check_abi(probe, props):
    abilist = props.get("ro.product.cpu.abilist", "") or props.get("ro.product.cpu.abi", "")
    abis = [a.strip() for a in abilist.split(",") if a.strip()]
    supports64 = "x86_64" in abis or props.get("ro.product.cpu.abilist64", "").find("x86_64") >= 0
    props["_x64"] = "1" if supports64 else ""
    if supports64:
        probe.add(OK, "ABI", f"{abilist} —— 可以装 app-x64-release.apk")
    elif "x86" in abis:
        probe.add(FAIL, "ABI",
                  f"{abilist} —— 这是 32 位 Android 系统（CPU 是 x86_64 也一样），"
                  "x64 包装不上；本仓库没有 32 位运行时")
    elif any(a.startswith("arm") for a in abis):
        probe.add(FAIL, "ABI", f"{abilist} —— ARM 车机，请用 arm64 包而不是 x64 包")
    else:
        probe.add(WARN, "ABI", f"{abilist or '读不到'} —— 认不出，按 x86_64 试")


def check_android(probe, props):
    sdk = int_of(props, "ro.build.version.sdk")
    release = props.get("ro.build.version.release", "?")
    if sdk == 0:
        probe.add(WARN, "Android", "读不到 SDK 版本")
        return sdk
    if sdk < MIN_SDK:
        probe.add(FAIL, "Android", f"{release} (API {sdk}) —— 低于 minSdk {MIN_SDK}，装不上")
    elif sdk > TARGET_SDK:
        probe.add(OK, "Android",
                  f"{release} (API {sdk}) —— 高于 targetSdk {TARGET_SDK}："
                  "首次启动若被系统拦下「应用试图运行私有目录文件」，看下一行的提示")
    else:
        probe.add(OK, "Android", f"{release} (API {sdk})")
    return sdk


def check_screen(probe, props, car):
    size = size_line(props.get("wm.size", ""))
    density = int(density_line(props.get("wm.density", "")) or 0) or 160
    match = re.search(r"(\d+)\s*x\s*(\d+)", size)
    if not match:
        probe.add(WARN, "屏幕", f"读不到（wm size: {props.get('wm.size', '') or '空'}）")
        return
    px_w, px_h = int(match.group(1)), int(match.group(2))
    dp_w, dp_h = px_w * 160 / density, px_h * 160 / density
    kind = window_class(dp_w, dp_h, car)
    detail = (f"{px_w}×{px_h} @ {density}dpi = {dp_w:.0f}×{dp_h:.0f}dp，"
              f"{kind} 布局")
    if not car:
        probe.add(WARN, "屏幕", f"{detail}（未带 DSH_CAR=1 时宽而矮的屏会按手机布局显示）")
    elif kind == "compact" and dp_h < COMPACT_HEIGHT:
        probe.add(WARN, "屏幕", f"{detail} —— 宽度不足 {MEDIUM_MIN:.0f}dp，车机规则救不回来")
    else:
        probe.add(OK, "屏幕", detail)


def check_automotive(probe, props):
    traits = props.get("ro.build.characteristics", "")
    feature = props.get("ro.oem.automotive", "") or props.get("ro.hardware.type", "")
    if "automotive" in traits or "automotive" in feature:
        probe.add(OK, "车机特征", f"ro.build.characteristics={traits} —— 是 Android Automotive 类系统")
    else:
        probe.add(OK, "车机特征",
                  f"ro.build.characteristics={traits or '空'} —— 后装车机多半就是这样，"
                  "不影响，用 DSH_CAR=1 的包即可")


def check_input(probe, props):
    imes = [line.strip() for line in props.get("ime.list", "").splitlines() if line.strip()]
    if imes:
        probe.add(OK, "输入法", f"{len(imes)} 个：{imes[0]}")
    else:
        probe.add(WARN, "输入法",
                  "没查到输入法；车内没键盘时打不了字，先装一个（或用 adb 输入）")


def check_storage(probe, props):
    raw = props.get("storage", "")
    match = re.search(r"\s(\d+)\s+\d+\s+(\d+)\s+\d+%", raw)
    if not match:
        probe.add(WARN, "存储", "读不到 /data 可用空间")
        return
    avail_gb = int(match.group(2)) / 1024 / 1024
    detail = f"/data 可用 {avail_gb:.1f} GB"
    if avail_gb < 3:
        probe.add(WARN, "存储", f"{detail} —— 解开的 rootfs 要 2 GB 上下，太紧")
    else:
        probe.add(OK, "存储", detail)


def check_environment(probe, props):
    gms = props.get("gms", "")
    if "com.google.android.gms" in gms:
        probe.add(OK, "Google 服务", "有；本 App 不依赖它，有也不影响")
    else:
        probe.add(OK, "Google 服务", "没有；本 App 不依赖 GMS/Play，正常")
    selinux = (props.get("selinux", "") or props.get("ro.boot.selinux", "")).strip()
    if selinux.lower() == "enforcing":
        probe.add(OK, "SELinux", "enforcing —— Termux 系运行时在 enforcing 下可用，不用关")
    if props.get("_x64"):
        probe.add(WARN, "启动方式",
                  "x86_64 上别开「直接启动」（直跑 glibc 加载器会被部分系统的 seccomp 杀掉），"
                  "默认的 PRoot 启动即可")


def main():
    parser = argparse.ArgumentParser(description="车机 x86_64 体检（只读）")
    parser.add_argument("--serial", default="", help="adb devices 里的设备串")
    parser.add_argument("--props", metavar="FILE", help="离线：getprop 输出的文本文件")
    parser.add_argument("--car", choices=["auto", "on", "off"], default="on",
                        help="按车机规则（DSH_CAR=1）预测布局，默认 on")
    args = parser.parse_args()

    if args.props:
        props = read_props_file(args.props)
    else:
        props = read_device(args.serial)
        if "ro.product.cpu.abilist" not in props and "ro.product.cpu.abi" not in props:
            raise SystemExit("设备没有回答 getprop；确认 USB 调试已打开、adb devices 里能看到它")
    car = args.car != "off"

    probe = Probe()
    check_abi(probe, props)
    sdk = check_android(probe, props)
    check_screen(probe, props, car)
    check_automotive(probe, props)
    check_input(probe, props)
    check_storage(probe, props)
    check_environment(probe, props)
    if sdk > TARGET_SDK:
        probe.add(WARN, "exec 限制",
                  f"API {sdk} > targetSdk {TARGET_SDK}：把 App 的「允许安装未知应用」打开；"
                  "PRoot 在私有目录里执行 ELF，个别 ROM 仍会拦，见 docs/car-x86_64.md §5")
    return probe.report(props)


if __name__ == "__main__":
    sys.exit(main())
