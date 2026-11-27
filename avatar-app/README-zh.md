# AlphaAvatar App

[English](README.md)

此目录为 AlphaAvatar 客户端应用预留。
目前只包含这份 README；这里没有交付可安装的 App、移动端运行时或配置界面。

## 📦 包结构

```text
avatar-app/
└── README.md            # Current scope and package boundary.
```

## 边界

服务器命令、配置加载和应用生命周期属于 [Avatar Host](../avatar-host/README.md)。
安装或运行 Host 不需要 App。
未来的 App 集成应使用相同的应用配置和生命周期契约，而不是引入第二套后端启动实现。
