#!/usr/bin/env python3
"""Share an Unreal Engine plugin with one project through a Windows junction."""

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path


SKIPPED_SEARCH_DIRS = {"Binaries", "DerivedDataCache", "Intermediate", "Saved"}


class ShareError(RuntimeError):
    pass


def resolve_directory(value, label):
    path = Path(value).expanduser()
    try:
        return path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ShareError("{}不存在：{}".format(label, path)) from exc
    except OSError as exc:
        raise ShareError("无法访问{}：{} ({})".format(label, path, exc)) from exc


def validate_plugin_directory(value):
    plugin_dir = resolve_directory(value, "Plugin 目录")
    if not plugin_dir.is_dir():
        raise ShareError("Plugin 路径不是目录：{}".format(plugin_dir))

    descriptors = sorted(plugin_dir.glob("*.uplugin"))
    if len(descriptors) != 1:
        detail = "未找到 .uplugin" if not descriptors else "找到多个 .uplugin"
        raise ShareError("Plugin 目录根部{}：{}".format(detail, plugin_dir))
    return plugin_dir


def find_uproject(project_input):
    path = Path(project_input).expanduser()
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ShareError("项目路径不存在：{}".format(path)) from exc
    except OSError as exc:
        raise ShareError("无法访问项目路径：{} ({})".format(path, exc)) from exc

    if path.is_file():
        if path.suffix.casefold() != ".uproject":
            raise ShareError("输入文件不是 .uproject：{}".format(path))
        return path
    if not path.is_dir():
        raise ShareError("项目路径不是目录：{}".format(path))

    direct = sorted(path.glob("*.uproject"))
    if len(direct) == 1:
        return direct[0]
    if len(direct) > 1:
        raise ShareError(
            "目录中存在多个 .uproject，请直接传入目标文件：{}".format(
                ", ".join(str(item) for item in direct)
            )
        )

    candidates = []
    for item in path.rglob("*.uproject"):
        relative_parts = item.relative_to(path).parts[:-1]
        if not any(part in SKIPPED_SEARCH_DIRS for part in relative_parts):
            candidates.append(item)
    candidates.sort()
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ShareError("未找到 .uproject：{}".format(path))
    raise ShareError(
        "递归找到多个 .uproject，请直接传入目标文件：{}".format(
            ", ".join(str(item) for item in candidates)
        )
    )


def same_directory(first, second):
    try:
        return os.path.samefile(str(first), str(second))
    except OSError:
        return False


def is_junction(path):
    checker = getattr(os.path, "isjunction", None)
    if checker is not None:
        return checker(str(path))
    try:
        return os.lstat(str(path)).st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    except (AttributeError, OSError):
        return False


def create_junction(plugin_dir, uproject):
    if os.name != "nt":
        raise ShareError("此脚本仅支持 Windows")

    plugins_dir = uproject.parent / "Plugins"
    link_dir = plugins_dir / plugin_dir.name
    if os.path.lexists(str(link_dir)):
        if is_junction(link_dir) and same_directory(link_dir, plugin_dir):
            return link_dir, False
        raise ShareError("链接目录已存在且指向其他内容：{}".format(link_dir))

    try:
        plugins_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ShareError("无法创建项目 Plugins 目录：{} ({})".format(plugins_dir, exc)) from exc

    command = [
        os.environ.get("ComSpec", "cmd.exe"),
        "/d",
        "/c",
        "mklink",
        "/J",
        str(link_dir),
        str(plugin_dir),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise ShareError("无法执行 mklink：{}".format(exc)) from exc
    if completed.returncode:
        raise ShareError("mklink /J 失败，退出码 {}".format(completed.returncode))
    if not same_directory(link_dir, plugin_dir):
        raise ShareError("mklink 返回成功，但 Junction 校验失败：{}".format(link_dir))
    return link_dir, True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_dir", help="要共享的 Unreal Plugin 原始目录")
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="包含 .uproject 的目录，也可直接传 .uproject（默认当前目录）",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        plugin_dir = validate_plugin_directory(args.plugin_dir)
        uproject = find_uproject(args.project)
        link_dir, created = create_junction(plugin_dir, uproject)
        print("[原始目录] {}".format(plugin_dir))
        print("[链接目录] {}".format(link_dir))
        print("[完成] {}".format("已创建 Junction" if created else "Junction 已存在"))
        return 0
    except ShareError as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
