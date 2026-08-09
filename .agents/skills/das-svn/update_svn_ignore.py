#!/usr/bin/env python3
"""Update svn:ignore from svnIgnore.txt in an SVN working directory."""

import argparse
import subprocess
import sys
from pathlib import Path


IGNORE_FILE_NAME = "svnIgnore.txt"


class SvnIgnoreError(RuntimeError):
    pass


def resolve_work_dir(value):
    path = Path(value).expanduser()
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise SvnIgnoreError("工作目录不存在：{}".format(path)) from exc
    except OSError as exc:
        raise SvnIgnoreError("无法访问工作目录：{} ({})".format(path, exc)) from exc
    if not path.is_dir():
        raise SvnIgnoreError("工作目录路径不是目录：{}".format(path))
    return path


def ensure_ignore_file(work_dir):
    ignore_file = work_dir / IGNORE_FILE_NAME
    if ignore_file.exists():
        if not ignore_file.is_file():
            raise SvnIgnoreError("忽略配置路径不是文件：{}".format(ignore_file))
        return ignore_file, False
    try:
        ignore_file.touch(exist_ok=False)
    except OSError as exc:
        raise SvnIgnoreError("无法创建忽略配置：{} ({})".format(ignore_file, exc)) from exc
    return ignore_file, True


def update_svn_ignore(work_dir):
    command = [
        "svn",
        "propset",
        "svn:ignore",
        "-F",
        IGNORE_FILE_NAME,
        ".",
    ]
    try:
        return subprocess.run(command, cwd=str(work_dir), check=False).returncode
    except FileNotFoundError as exc:
        raise SvnIgnoreError("找不到 svn 命令，请先安装 SVN 并将其加入 PATH") from exc
    except OSError as exc:
        raise SvnIgnoreError("无法执行 svn propset：{}".format(exc)) from exc


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "work_dir",
        nargs="?",
        default=".",
        help="需要更新 svn:ignore 的 SVN 工作目录（默认当前目录）",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        work_dir = resolve_work_dir(args.work_dir)
        ignore_file, created = ensure_ignore_file(work_dir)
        print("[工作目录] {}".format(work_dir))
        print("[忽略配置] {}{}".format(ignore_file, "（已创建）" if created else ""))
        return_code = update_svn_ignore(work_dir)
        if return_code:
            print("[错误] svn propset 失败，退出码 {}".format(return_code), file=sys.stderr)
            return return_code
        print("[完成] 已更新 svn:ignore")
        return 0
    except SvnIgnoreError as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
