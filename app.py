import ipaddress
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List

import flet as ft


@dataclass
class VMEndpoint:
    kind: str
    name: str
    ip: str

    @property
    def label(self) -> str:
        return f"[{self.kind}] {self.name} ({self.ip})"


def run_cmd(command: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        raise RuntimeError(err or f"Command failed: {command}")
    return result.stdout


def is_valid_ipv4(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
        return isinstance(ip, ipaddress.IPv4Address)
    except ValueError:
        return False


def list_host_ipv4() -> List[str]:
    output = run_cmd(
        "Get-NetIPAddress -AddressFamily IPv4 "
        "| Where-Object {$_.IPAddress -ne '127.0.0.1' -and $_.PrefixOrigin -ne 'WellKnown'} "
        "| Select-Object -ExpandProperty IPAddress"
    )
    ips = [line.strip() for line in output.splitlines() if line.strip()]
    uniq = sorted(set(ip for ip in ips if is_valid_ipv4(ip)))
    if "0.0.0.0" not in uniq:
        uniq.insert(0, "0.0.0.0")
    return uniq


def list_wsl_endpoints() -> List[VMEndpoint]:
    output = run_cmd("wsl -l -q")
    distros = [d.strip() for d in output.splitlines() if d.strip()]
    endpoints: List[VMEndpoint] = []

    for distro in distros:
        cmd = (
            f"wsl -d \"{distro}\" -- sh -lc "
            "\"hostname -I 2>/dev/null || ip -o -4 addr show scope global | awk '{print \\$4}'\""
        )
        try:
            ip_output = run_cmd(cmd)
        except RuntimeError:
            continue

        tokens = re.split(r"\s+", ip_output.strip()) if ip_output.strip() else []
        for token in tokens:
            ip = token.split("/")[0].strip()
            if is_valid_ipv4(ip):
                endpoints.append(VMEndpoint(kind="WSL2", name=distro, ip=ip))

    unique: Dict[str, VMEndpoint] = {}
    for ep in endpoints:
        unique[f"{ep.kind}:{ep.name}:{ep.ip}"] = ep
    return sorted(unique.values(), key=lambda x: (x.kind, x.name, x.ip))


def parse_hyperv_ip(report: str) -> str:
    for raw in report.splitlines():
        line = raw.strip()
        if not line or line.startswith("127."):
            continue
        candidate = line.split("/")[0].strip()
        if is_valid_ipv4(candidate):
            return candidate
    return ""


def list_hyperv_endpoints() -> List[VMEndpoint]:
    output = run_cmd("Get-VM | Select-Object -ExpandProperty Name")
    names = [line.strip() for line in output.splitlines() if line.strip()]
    endpoints: List[VMEndpoint] = []
    for name in names:
        script = (
            "$ErrorActionPreference='SilentlyContinue'; "
            f"$r = Invoke-Command -VMName '{name}' -ScriptBlock "
            "{hostname -I 2>$null}; "
            "if ($r) {$r}"
        )
        try:
            report = run_cmd(script)
        except RuntimeError:
            continue
        ip = parse_hyperv_ip(report)
        if ip:
            endpoints.append(VMEndpoint(kind="Hyper-V", name=name, ip=ip))
    return sorted(endpoints, key=lambda x: (x.kind, x.name, x.ip))


def list_vm_endpoints() -> List[VMEndpoint]:
    endpoints: List[VMEndpoint] = []
    try:
        endpoints.extend(list_wsl_endpoints())
    except RuntimeError:
        pass
    try:
        endpoints.extend(list_hyperv_endpoints())
    except RuntimeError:
        pass

    unique: Dict[str, VMEndpoint] = {}
    for ep in endpoints:
        unique[f"{ep.kind}:{ep.name}:{ep.ip}"] = ep
    return sorted(unique.values(), key=lambda x: (x.kind, x.name, x.ip))


def list_portproxy_rules() -> List[str]:
    try:
        output = run_cmd("netsh interface portproxy show v4tov4")
    except RuntimeError:
        return []
    lines = [ln.rstrip() for ln in output.splitlines() if ln.strip()]
    return lines


def create_portproxy_rule(listen_ip: str, listen_port: int, connect_ip: str, connect_port: int) -> None:
    run_cmd(
        f"netsh interface portproxy add v4tov4 "
        f"listenaddress={listen_ip} listenport={listen_port} "
        f"connectaddress={connect_ip} connectport={connect_port}"
    )


def delete_portproxy_rule(listen_ip: str, listen_port: int) -> None:
    run_cmd(
        f"netsh interface portproxy delete v4tov4 "
        f"listenaddress={listen_ip} listenport={listen_port}"
    )


def ensure_firewall_rule(name: str, listen_ip: str, listen_port: int) -> None:
    check = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"Get-NetFirewallRule -DisplayName '{name}' | Out-Null",
        ],
        capture_output=True,
        text=True,
    )
    if check.returncode == 0:
        return
    run_cmd(
        "New-NetFirewallRule "
        f"-DisplayName '{name}' -Direction Inbound -Action Allow "
        f"-Protocol TCP -LocalAddress {listen_ip} -LocalPort {listen_port}"
    )


def require_admin() -> None:
    import ctypes

    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise PermissionError("请以管理员权限运行此程序（端口代理和防火墙规则需要管理员权限）。")


def main(page: ft.Page) -> None:
    page.title = "PortSnake - WSL2/Hyper-V 端口映射"
    page.window_width = 1100
    page.window_height = 760
    page.scroll = ft.ScrollMode.AUTO
    page.theme_mode = ft.ThemeMode.LIGHT

    vm_map: Dict[str, VMEndpoint] = {}
    host_ips: List[str] = []

    status = ft.Text(value="准备就绪", color=ft.Colors.BLUE_GREY_700)
    vm_dropdown = ft.Dropdown(label="虚拟机 IP", width=520, options=[])
    host_ip_dropdown = ft.Dropdown(label="主机监听 IP", width=250, options=[])
    vm_port_input = ft.TextField(label="虚拟机端口", width=160, value="8000")
    host_port_input = ft.TextField(label="主机监听端口", width=160, value="8000")
    firewall_checkbox = ft.Checkbox(label="自动创建防火墙入站规则", value=True)
    rule_output = ft.TextField(
        label="当前 portproxy 规则",
        multiline=True,
        min_lines=12,
        max_lines=18,
        read_only=True,
        value="",
    )

    delete_listen_ip = ft.Dropdown(label="删除规则: 监听IP", width=250, options=[])
    delete_listen_port = ft.TextField(label="删除规则: 监听端口", width=180)

    def set_status(message: str, error: bool = False) -> None:
        status.value = message
        status.color = ft.Colors.RED_700 if error else ft.Colors.GREEN_700
        page.update()

    def refresh_rules_view() -> None:
        lines = list_portproxy_rules()
        rule_output.value = "\n".join(lines) if lines else "暂无规则"

    def refresh_all(_: ft.ControlEvent | None = None) -> None:
        nonlocal host_ips, vm_map
        try:
            require_admin()
            host_ips = list_host_ipv4()
            vms = list_vm_endpoints()

            vm_map = {ep.label: ep for ep in vms}
            vm_dropdown.options = [ft.dropdown.Option(key=label, text=label) for label in vm_map.keys()]
            if vm_dropdown.options:
                vm_dropdown.value = vm_dropdown.options[0].key

            host_ip_dropdown.options = [ft.dropdown.Option(key=ip, text=ip) for ip in host_ips]
            if host_ip_dropdown.options:
                wildcard = "0.0.0.0" if "0.0.0.0" in host_ips else host_ips[0]
                host_ip_dropdown.value = wildcard

            delete_listen_ip.options = [ft.dropdown.Option(key=ip, text=ip) for ip in host_ips]
            if delete_listen_ip.options:
                delete_listen_ip.value = delete_listen_ip.options[0].key

            refresh_rules_view()
            set_status(f"已刷新: 发现 {len(vms)} 个虚拟机地址, {len(host_ips)} 个主机地址")
        except Exception as exc:  # noqa: BLE001
            set_status(f"刷新失败: {exc}", error=True)

    def add_mapping(_: ft.ControlEvent) -> None:
        try:
            require_admin()
            vm_key = vm_dropdown.value or ""
            if vm_key not in vm_map:
                raise ValueError("请先选择虚拟机地址")
            target = vm_map[vm_key]

            listen_ip = (host_ip_dropdown.value or "").strip()
            if not is_valid_ipv4(listen_ip):
                raise ValueError("请选择合法主机监听 IP")

            vm_port = int(vm_port_input.value.strip())
            host_port = int(host_port_input.value.strip())
            if not (1 <= vm_port <= 65535 and 1 <= host_port <= 65535):
                raise ValueError("端口范围必须在 1-65535")

            delete_portproxy_rule(listen_ip, host_port)
            create_portproxy_rule(listen_ip, host_port, target.ip, vm_port)

            if firewall_checkbox.value:
                rule_name = f"PortSnake-{listen_ip}-{host_port}"
                ensure_firewall_rule(rule_name, listen_ip, host_port)

            refresh_rules_view()
            set_status(
                f"映射成功: {listen_ip}:{host_port} -> {target.kind}/{target.name} {target.ip}:{vm_port}"
            )
        except Exception as exc:  # noqa: BLE001
            set_status(f"映射失败: {exc}", error=True)

    def remove_mapping(_: ft.ControlEvent) -> None:
        try:
            require_admin()
            listen_ip = (delete_listen_ip.value or "").strip()
            listen_port = int((delete_listen_port.value or "").strip())
            if not is_valid_ipv4(listen_ip):
                raise ValueError("请选择合法监听 IP")
            if not (1 <= listen_port <= 65535):
                raise ValueError("监听端口范围必须在 1-65535")

            delete_portproxy_rule(listen_ip, listen_port)
            refresh_rules_view()
            set_status(f"删除完成: {listen_ip}:{listen_port}")
        except Exception as exc:  # noqa: BLE001
            set_status(f"删除失败: {exc}", error=True)

    page.add(
        ft.Column(
            controls=[
                ft.Text("PortSnake", size=34, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "将 WSL2/Hyper-V 服务端口映射到主机 IP:Port（基于 netsh interface portproxy）",
                    color=ft.Colors.BLUE_GREY_700,
                ),
                ft.Row(
                    controls=[
                        ft.ElevatedButton("刷新地址", icon=ft.Icons.REFRESH, on_click=refresh_all),
                        status,
                    ]
                ),
                ft.Divider(),
                ft.Text("新增映射", size=20, weight=ft.FontWeight.W_600),
                vm_dropdown,
                ft.Row(
                    controls=[host_ip_dropdown, host_port_input, vm_port_input],
                    wrap=True,
                ),
                firewall_checkbox,
                ft.ElevatedButton("创建/覆盖映射", icon=ft.Icons.LINK, on_click=add_mapping),
                ft.Divider(),
                ft.Text("删除映射", size=20, weight=ft.FontWeight.W_600),
                ft.Row(controls=[delete_listen_ip, delete_listen_port], wrap=True),
                ft.ElevatedButton("删除规则", icon=ft.Icons.DELETE_OUTLINE, on_click=remove_mapping),
                ft.Divider(),
                rule_output,
            ],
            spacing=12,
            tight=False,
        )
    )

    refresh_all(None)


if __name__ == "__main__":
    os.environ.setdefault("FLET_APP_HIDDEN", "false")
    ft.app(target=main, view=ft.AppView.FLET_APP)
