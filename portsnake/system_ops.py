import ctypes
import ipaddress
import re
import subprocess
from typing import Dict, List

from .logger import log
from .models import VMEndpoint


def sanitize_text(text: str) -> str:
    return (text or "").replace("\x00", "")


def run_cmd(command: str) -> str:
    command = sanitize_text(command)
    log(f"执行命令: {command}")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    stdout = sanitize_text(result.stdout)
    stderr = sanitize_text(result.stderr)
    log(f"命令返回码: {result.returncode}")
    if stdout.strip():
        log(f"标准输出:\n{stdout.strip()}")
    if stderr.strip():
        log(f"错误输出:\n{stderr.strip()}")
    if result.returncode != 0:
        raise RuntimeError(stderr.strip() or f"command failed: {command}")
    return stdout


def is_valid_ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False


def is_admin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def list_host_ipv4() -> List[str]:
    output = run_cmd(
        "Get-NetIPAddress -AddressFamily IPv4 "
        "| Where-Object {$_.IPAddress -ne '127.0.0.1' -and $_.PrefixOrigin -ne 'WellKnown'} "
        "| Select-Object -ExpandProperty IPAddress"
    )
    ips = [sanitize_text(line).strip() for line in output.splitlines()]
    uniq = sorted(set(ip for ip in ips if ip and is_valid_ipv4(ip)))
    if "0.0.0.0" not in uniq:
        uniq.insert(0, "0.0.0.0")
    return uniq


def list_wsl_endpoints() -> List[VMEndpoint]:
    log("开始扫描 WSL2 地址")
    output = run_cmd("wsl -l -q")
    distros = [sanitize_text(line).strip() for line in output.splitlines() if sanitize_text(line).strip()]
    endpoints: List[VMEndpoint] = []

    for distro in distros:
        log(f"查询 WSL2 发行版地址: {distro}")
        proc = subprocess.run(
            [
                "wsl.exe",
                "-d",
                distro,
                "--",
                "sh",
                "-lc",
                "hostname -I 2>/dev/null || ip -o -4 addr show scope global | awk '{print $4}'",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        out = sanitize_text(proc.stdout)
        err = sanitize_text(proc.stderr)
        log(f"wsl.exe 返回码({distro}): {proc.returncode}")
        if out.strip():
            log(f"wsl.exe 标准输出({distro}):\n{out.strip()}")
        if err.strip():
            log(f"wsl.exe 错误输出({distro}):\n{err.strip()}")
        if proc.returncode != 0:
            continue

        for token in re.split(r"\s+", out.strip()) if out.strip() else []:
            ip = token.split("/")[0].strip()
            if is_valid_ipv4(ip):
                endpoints.append(VMEndpoint(kind="WSL2", name=distro, ip=ip))
    return endpoints


def parse_hyperv_ip(report: str) -> str:
    for raw in report.splitlines():
        ip = sanitize_text(raw).split("/")[0].strip()
        if is_valid_ipv4(ip) and not ip.startswith("127."):
            return ip
    return ""


def list_hyperv_endpoints() -> List[VMEndpoint]:
    log("开始扫描 Hyper-V 地址")
    output = run_cmd("Get-VM | Select-Object -ExpandProperty Name")
    names = [sanitize_text(line).strip() for line in output.splitlines() if sanitize_text(line).strip()]
    endpoints: List[VMEndpoint] = []
    for name in names:
        script = (
            "$ErrorActionPreference='SilentlyContinue'; "
            f"$r = Invoke-Command -VMName '{name}' -ScriptBlock "
            "{hostname -I 2>$null}; if ($r) {$r}"
        )
        try:
            report = run_cmd(script)
        except RuntimeError:
            continue
        ip = parse_hyperv_ip(report)
        if ip:
            endpoints.append(VMEndpoint(kind="Hyper-V", name=name, ip=ip))
    return endpoints


def list_vm_endpoints() -> List[VMEndpoint]:
    all_items: List[VMEndpoint] = []
    try:
        all_items.extend(list_wsl_endpoints())
    except RuntimeError as exc:
        log(f"扫描 WSL2 失败: {exc}")
    try:
        all_items.extend(list_hyperv_endpoints())
    except RuntimeError as exc:
        log(f"扫描 Hyper-V 失败: {exc}")
    unique: Dict[str, VMEndpoint] = {}
    for ep in all_items:
        unique[ep.key] = ep
    items = sorted(unique.values(), key=lambda x: (x.kind, x.name, x.ip))
    log(f"虚拟机地址扫描完成，共 {len(items)} 条")
    return items


def create_portproxy_rule(listen_ip: str, listen_port: int, connect_ip: str, connect_port: int) -> None:
    run_cmd(
        f"netsh interface portproxy add v4tov4 "
        f"listenaddress={listen_ip} listenport={listen_port} "
        f"connectaddress={connect_ip} connectport={connect_port}"
    )


def delete_portproxy_rule(listen_ip: str, listen_port: int) -> None:
    try:
        run_cmd(
            f"netsh interface portproxy delete v4tov4 "
            f"listenaddress={listen_ip} listenport={listen_port}"
        )
    except RuntimeError as exc:
        log(f"删除旧规则时忽略错误: {exc}")

