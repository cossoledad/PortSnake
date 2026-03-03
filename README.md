# PortSnake

基于 `Flet + Nuitka` 的 Windows 桌面工具，用于把 WSL2 / Hyper-V 虚拟机内服务端口映射到主机 IP:Port。

## 功能

1. 获取当前主机 IPv4 地址（含 `0.0.0.0`）。
2. 获取当前 WSL2 发行版 IP。
3. 尝试获取当前 Hyper-V 虚拟机 IP（通过 PowerShell Direct）。
4. 创建或覆盖端口映射（`netsh interface portproxy`）。
5. 可选自动创建防火墙入站规则。
6. 查看并删除已有端口映射规则。

## 环境要求

- Windows 10/11
- 以管理员权限运行（端口代理和防火墙规则需要管理员权限）
- Python 3.13+
- 已安装依赖：`flet`、`nuitka`

## 开发运行

```powershell
python app.py
```

## 打包

```powershell
.\build_nuitka.ps1
```

可选（减少 onefile 警告并提升压缩效果）：

```powershell
python -m pip install zstandard
```

成功后生成：

`dist\PortSnake.exe`

## 使用步骤

1. 点击 `刷新地址`。
2. 在 `虚拟机 IP` 里选择 WSL2/Hyper-V 目标地址。
3. 选择 `主机监听 IP`（如 `0.0.0.0`）。
4. 填写主机监听端口、虚拟机端口。
5. 点击 `创建/覆盖映射`。
6. 在 VSCode 或局域网中访问 `主机IP:主机端口`。

## 常见问题

- 看不到 WSL2 地址：
  - 先确认 `wsl -l -q` 能列出发行版。
- 看不到 Hyper-V 地址：
  - 需要来宾系统支持 PowerShell Direct，且宿主有权限。
- 端口映射后无法访问：
  - 检查目标服务是否监听在虚拟机对应端口。
  - 检查 Windows 防火墙规则。
