---
name: das-ue-daspixel
description: 为 Unreal Engine 功能补齐 DasPixel Web C++ 与 JavaScript 接口；用户提到 UE 导出 Web 接口、DasPixel 或更新前端 .js 接口时使用。
user-invocable: false
---

# DasPixel Web 接口

- 单例接口参考 `UWebCamera`、`WebCamera.cpp` 和 `Camera.js`。
- 实例接口参考 `UWebDasCustomLayer`、`WebDasCustomLayer.cpp`、`DasCustomLayer.js` 及其父类 `UWebDasLayerBase`、`DasLayerBase.js`。
- 接口注册参考 `DasPixelStreamingInput.cpp`：包含 Web 类头文件，并在 `UDasPixelStreamingInput::BeginPlay()` 中调用 `registerClass()`。
