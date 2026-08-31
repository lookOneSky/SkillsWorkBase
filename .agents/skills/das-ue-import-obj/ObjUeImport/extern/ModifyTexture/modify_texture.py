"""Modify configured Texture2D properties using settings from a JSON file."""

import json
import os
import sys
from pathlib import Path

import unreal


PROPERTY_UPDATE_ORDER = (
    "max_texture_size",
    "virtual_texture_streaming",
)
LOG_PREFIX = "[TexturePropertyBatch]"


def _get_config_path():
    arguments = [argument.strip() for argument in sys.argv if argument.strip()]
    if arguments and arguments[0].casefold().endswith(".py"):
        arguments = arguments[1:]

    script_directory = Path(__file__).resolve().parent
    config_path = (
        Path(arguments[0])
        if arguments
        else Path(__file__).with_suffix(".json")
    )
    config_path = Path(os.path.expandvars(os.path.expanduser(str(config_path))))
    if not config_path.is_absolute():
        config_path = script_directory / config_path
    return config_path.resolve()


def _load_config(config_path):
    try:
        with config_path.open("r", encoding="utf-8-sig") as config_file:
            config = json.load(config_file)
    except (OSError, ValueError) as error:
        raise ValueError("无法读取 JSON 配置 {}：{}".format(config_path, error))

    if not isinstance(config, dict):
        raise ValueError("JSON 根节点必须是对象：{}".format(config_path))

    content_directory = config.get("content_directory", "")
    if not isinstance(content_directory, str):
        raise ValueError("content_directory 必须是字符串。")
    content_directory = content_directory.strip().replace("\\", "/").rstrip("/")
    if not content_directory:
        raise ValueError("JSON 中未配置 content_directory。")
    if not content_directory.startswith("/"):
        raise ValueError(
            "内容目录必须是 Unreal 资产路径，例如 /Game/Textures：{}".format(
                content_directory
            )
        )

    recursive = config.get("recursive", True)
    if not isinstance(recursive, bool):
        raise ValueError("recursive 必须是 true 或 false。")

    texture_properties = config.get("texture_properties")
    if not isinstance(texture_properties, dict) or not texture_properties:
        raise ValueError("texture_properties 必须是包含至少一个属性的对象。")

    unknown_properties = set(texture_properties) - set(PROPERTY_UPDATE_ORDER)
    if unknown_properties:
        raise ValueError(
            "不支持的纹理属性：{}".format(
                ", ".join(sorted(unknown_properties))
            )
        )

    if "virtual_texture_streaming" in texture_properties:
        virtual_texture = texture_properties["virtual_texture_streaming"]
        if not isinstance(virtual_texture, bool):
            raise ValueError("virtual_texture_streaming 必须是 true 或 false。")

    if "max_texture_size" in texture_properties:
        max_texture_size = texture_properties["max_texture_size"]
        if isinstance(max_texture_size, bool) or not isinstance(
            max_texture_size, int
        ):
            raise ValueError("max_texture_size 必须是整数。")
        if max_texture_size < 0:
            raise ValueError("max_texture_size 不能小于 0。")
        if max_texture_size and max_texture_size & (max_texture_size - 1):
            raise ValueError("max_texture_size 必须为 0 或 2 的幂。")

    return content_directory, recursive, texture_properties


def _modify_texture(texture, texture_properties):
    changed_properties = []
    for property_name in PROPERTY_UPDATE_ORDER:
        if property_name not in texture_properties:
            continue

        target_value = texture_properties[property_name]
        if texture.get_editor_property(property_name) == target_value:
            continue

        if not changed_properties:
            texture.modify()
        texture.set_editor_property(property_name, target_value)
        changed_properties.append(property_name)
    return changed_properties


def modify_texture_properties(content_directory, recursive, texture_properties):
    """Update and save Texture2D assets under content_directory."""
    asset_subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
    if not asset_subsystem.does_directory_exist(content_directory):
        raise ValueError("内容目录不存在：{}".format(content_directory))

    asset_paths = asset_subsystem.list_assets(
        content_directory,
        recursive=recursive,
        include_folder=False,
    )
    texture_count = 0
    changed_count = 0
    failed_assets = []

    unreal.log(
        "{} 开始扫描 {}，共发现 {} 个资产。".format(
            LOG_PREFIX, content_directory, len(asset_paths)
        )
    )

    with unreal.ScopedSlowTask(
        len(asset_paths), "正在修改纹理属性..."
    ) as slow_task:
        slow_task.make_dialog(True)

        for asset_path in asset_paths:
            slow_task.enter_progress_frame(1, asset_path)
            if slow_task.should_cancel():
                unreal.log_warning("{} 用户取消了处理。".format(LOG_PREFIX))
                break

            asset = asset_subsystem.load_asset(asset_path)
            if not isinstance(asset, unreal.Texture2D):
                continue

            texture_count += 1
            try:
                changed_properties = _modify_texture(asset, texture_properties)
                if not changed_properties:
                    continue

                if not asset_subsystem.save_loaded_asset(
                    asset, only_if_is_dirty=False
                ):
                    failed_assets.append(asset_path)
                    unreal.log_error("{} 保存失败：{}".format(LOG_PREFIX, asset_path))
                    continue

                changed_count += 1
                unreal.log(
                    "{} 已修改并保存：{}；属性：{}".format(
                        LOG_PREFIX,
                        asset_path,
                        ", ".join(changed_properties),
                    )
                )
            except Exception as error:
                failed_assets.append(asset_path)
                unreal.log_error(
                    "{} 处理失败：{}；{}".format(LOG_PREFIX, asset_path, error)
                )

    unreal.log(
        "{} 完成：扫描 Texture2D {} 个，修改并保存 {} 个，失败 {} 个。".format(
            LOG_PREFIX, texture_count, changed_count, len(failed_assets)
        )
    )
    return changed_count, failed_assets


def main():
    config_path = _get_config_path()
    content_directory, recursive, texture_properties = _load_config(config_path)
    unreal.log("{} 使用配置：{}".format(LOG_PREFIX, config_path))
    _, failed_assets = modify_texture_properties(
        content_directory,
        recursive,
        texture_properties,
    )
    if failed_assets:
        raise RuntimeError(
            "{} 个纹理处理或保存失败，请查看 Output Log。".format(
                len(failed_assets)
            )
        )


if __name__ == "__main__":
    main()
