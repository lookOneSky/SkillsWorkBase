#!/usr/bin/env python3
"""Execute Python in the Unreal editor that owns the selected .uproject."""

import argparse
import os
import sys
import time
from pathlib import Path

from configure_unreal_mcp import (
    ConfigurationError,
    find_uproject,
    load_json,
    resolve_engine_dir,
)


def normalized_path(value):
    return os.path.normcase(os.path.normpath(os.path.abspath(str(value))))


def select_project_node(nodes, project_dir, project_name):
    expected_root = normalized_path(project_dir)
    exact = [
        node
        for node in nodes
        if node.get("project_root")
        and normalized_path(node["project_root"]) == expected_root
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ConfigurationError("同一项目发现多个 Python 远程节点，请只保留一个编辑器实例")

    by_name = [node for node in nodes if node.get("project_name") == project_name]
    if len(by_name) == 1:
        return by_name[0]
    available = ", ".join(
        "{} ({})".format(node.get("project_name", "?"), node.get("project_root", "?"))
        for node in nodes
    )
    raise ConfigurationError(
        "未发现当前项目的 Python 远程节点；已发现：{}".format(available or "无")
    )


def print_result(result):
    for entry in result.get("output") or []:
        stream = sys.stderr if entry.get("type") == "Error" else sys.stdout
        stream.write(entry.get("output", "") + "\n")
    if result.get("success"):
        return 0
    print("FAILED: {}".format(result.get("result")), file=sys.stderr)
    return 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="包含 .uproject 的目录，也可直接传 .uproject")
    parser.add_argument("script", nargs="?", help="在编辑器内执行的 .py 文件")
    parser.add_argument("-c", dest="code", help="在编辑器内执行的 Python 源码")
    parser.add_argument("--probe", metavar="EXPR", help="打印 unreal API 表达式的公开成员")
    parser.add_argument("--engine-root", help="UE 安装根目录或 Engine 目录")
    parser.add_argument("--timeout", type=float, default=15.0, help="节点发现超时秒数")
    args = parser.parse_args(argv)
    choices = sum(bool(value) for value in (args.script, args.code, args.probe))
    if choices != 1:
        parser.error("必须且只能提供 script、-c 或 --probe 之一")
    return args


def main(argv=None):
    args = parse_args(argv)
    connection = None
    try:
        uproject = find_uproject(args.project)
        project_data = load_json(uproject)
        engine_dir = resolve_engine_dir(project_data, override=args.engine_root)
        remote_module_dir = (
            engine_dir / "Plugins/Experimental/PythonScriptPlugin/Content/Python"
        )
        if not (remote_module_dir / "remote_execution.py").is_file():
            raise ConfigurationError("找不到 remote_execution.py：{}".format(remote_module_dir))
        sys.path.insert(0, str(remote_module_dir))
        import remote_execution

        config = remote_execution.RemoteExecutionConfig()
        config.multicast_group_endpoint = ("239.0.0.1", 6766)
        config.multicast_bind_address = "127.0.0.1"
        connection = remote_execution.RemoteExecution(config)
        connection.start()

        deadline = time.time() + args.timeout
        node = None
        last_error = None
        while time.time() < deadline:
            try:
                node = select_project_node(
                    connection.remote_nodes, uproject.parent, uproject.stem
                )
                break
            except ConfigurationError as exc:
                last_error = exc
                time.sleep(0.25)
        if node is None:
            raise last_error or ConfigurationError(
                "未发现 Unreal Python 远程节点；请确认编辑器已启动且 bRemoteExecution=True"
            )

        connection.open_command_connection(node["node_id"])
        if args.probe:
            command = (
                "import unreal\n"
                "print('{0}:')\n"
                "print('\\n'.join('  ' + name for name in dir({0}) "
                "if not name.startswith('_')))"
            ).format(args.probe)
        elif args.code:
            command = args.code
        else:
            script = Path(args.script).expanduser().resolve()
            if not script.is_file():
                raise ConfigurationError("脚本不存在：{}".format(script))
            command = str(script)

        result = connection.run_command(
            command,
            unattended=True,
            exec_mode=remote_execution.MODE_EXEC_FILE,
            raise_on_failure=False,
        )
        return print_result(result)
    except (ConfigurationError, OSError, RuntimeError) as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.stop()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
