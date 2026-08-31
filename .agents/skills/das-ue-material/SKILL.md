---
name: das-ue-material
description: 创建或修改 Unreal Engine 母材质及其节点逻辑；用户要求制作、调整或生成 UE 材质、材质节点或材质效果时使用。
user-invocable: false
---

# Unreal 母材质

- 只创建或修改 `Material` 母材质资产，不创建任何材质实例。效果需要材质实例时，先完成母材质，再让用户在 Unreal Editor 中手动创建实例。
- 材质的主要计算逻辑尽量收敛到一个 `Custom` 节点，不拆成大量计算节点或多个 `Custom` 节点。材质属性输出、参数与纹理输入，以及引擎必须承担的专用节点可以保留在节点外。
- 将需要调节的数值、颜色、向量和纹理暴露为母材质参数并接入 `Custom` 节点。每个参数都要在母材质中配置可直接使用、能呈现预期效果的默认值，不依赖材质实例补齐。
- 在母材质上配置效果所需的 Material Domain、Blend Mode、Shading Model、Two Sided、Opacity Mask Clip Value 等属性。
- 单个 `Custom` 节点无法实现时，只增加必需的最少节点，并说明限制与原因。
- 完成前确认材质可编译、默认参数有效、未创建材质实例；报告母材质资产路径、`Custom` 节点输入输出和可供用户手动创建实例后调整的参数。
