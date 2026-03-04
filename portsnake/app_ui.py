from __future__ import annotations

from typing import Dict, List, Optional, Set
from uuid import uuid4

import flet as ft

from .config_store import load_mappings, save_mappings
from .logger import log
from .models import MappingItem, VMEndpoint
from .system_ops import (
    create_portproxy_rule,
    delete_portproxy_rule,
    is_admin,
    is_valid_ipv4,
    list_host_ipv4,
    list_vm_endpoints,
)


class PortSnakeUI:
    def __init__(self, page: ft.Page):
        self.page = page
        self.host_ips: List[str] = []
        self.vm_endpoints: List[VMEndpoint] = []
        self.mappings: List[MappingItem] = load_mappings()
        self.editing_ids: Set[str] = set()
        self.closing = False

        self.status_text = ft.Text("准备就绪", color=ft.Colors.GREEN_700, size=13)
        self.vm_select = ft.Dropdown(label="虚拟机地址", width=460, options=[])
        self.host_ip_select = ft.Dropdown(label="主机 IP", width=170, options=[])
        self.host_port_input = ft.TextField(label="主机端口", width=140, value="8000")
        self.vm_port_input = ft.TextField(label="虚拟机端口", width=140, value="8000")
        self.search_input = ft.TextField(
            label="筛选映射（按名称/IP/端口）",
            width=340,
            dense=True,
            on_change=self._on_filter_change,
        )

        self.mappings_column = ft.Column(spacing=10, expand=True)

    def build(self) -> None:
        self.page.title = "PortSnake - 端口映射"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.window_width = 1280
        self.page.window_height = 860
        self.page.padding = 20
        self.page.bgcolor = "#F5F7FB"
        self.page.scroll = ft.ScrollMode.AUTO
        self.page.window.prevent_close = False

        self.page.on_disconnect = lambda _: self.shutdown_cleanup()
        self.page.on_window_event = self._on_window_event

        header = ft.Container(
            border_radius=16,
            padding=18,
            gradient=ft.LinearGradient(
                begin=ft.Alignment(-1, 0),
                end=ft.Alignment(1, 0),
                colors=["#1D3557", "#457B9D"],
            ),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        spacing=4,
                        controls=[
                            ft.Text("PortSnake", size=30, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                            ft.Text(
                                "WSL2 / Hyper-V 端口映射管理",
                                size=13,
                                color="#E9F1F7",
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.FilledButton(
                                "刷新环境",
                                icon=ft.Icons.REFRESH,
                                style=ft.ButtonStyle(bgcolor="#A8DADC", color="#123"),
                                on_click=self.on_refresh,
                            ),
                            ft.FilledTonalButton(
                                "重建上次启用",
                                icon=ft.Icons.RESTART_ALT,
                                on_click=self.rebuild_last_active,
                            ),
                        ],
                    ),
                ],
            ),
        )

        create_panel = ft.Container(
            bgcolor=ft.Colors.WHITE,
            border_radius=14,
            padding=16,
            shadow=ft.BoxShadow(
                blur_radius=18,
                color="#22000000",
                offset=ft.Offset(0, 4),
            ),
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Text("新增映射", size=20, weight=ft.FontWeight.W_600, color="#1D3557"),
                    self.vm_select,
                    ft.Row(
                        spacing=10,
                        wrap=True,
                        controls=[self.host_ip_select, self.host_port_input, self.vm_port_input],
                    ),
                    ft.FilledButton(
                        "新增并启用",
                        icon=ft.Icons.ADD_LINK,
                        style=ft.ButtonStyle(bgcolor="#2A9D8F", color=ft.Colors.WHITE),
                        on_click=self.on_add_mapping,
                    ),
                    ft.Divider(height=12, color=ft.Colors.BLUE_GREY_50),
                    self.status_text,
                ],
            ),
        )

        list_panel = ft.Container(
            bgcolor=ft.Colors.WHITE,
            border_radius=14,
            padding=16,
            expand=True,
            shadow=ft.BoxShadow(
                blur_radius=18,
                color="#22000000",
                offset=ft.Offset(0, 4),
            ),
            content=ft.Column(
                spacing=10,
                expand=True,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("映射列表", size=20, weight=ft.FontWeight.W_600, color="#1D3557"),
                            self.search_input,
                        ],
                    ),
                    self.mappings_column,
                ],
            ),
        )

        self.page.add(
            ft.Column(
                spacing=14,
                controls=[
                    header,
                    ft.ResponsiveRow(
                        run_spacing=12,
                        controls=[
                            ft.Column(col={"xs": 12, "md": 4}, controls=[create_panel]),
                            ft.Column(col={"xs": 12, "md": 8}, controls=[list_panel]),
                        ],
                    ),
                ],
            )
        )

        try:
            self.refresh_environment()
            self.set_status("初始化完成")
        except Exception as exc:  # noqa: BLE001
            self.render_mapping_list()
            self.set_status(f"初始化失败: {exc}", error=True)

    def set_status(self, text: str, error: bool = False) -> None:
        log(f"状态更新: {'错误' if error else '正常'} - {text}")
        self.status_text.value = text
        self.status_text.color = ft.Colors.RED_700 if error else ft.Colors.GREEN_700
        self.page.update()

    def vm_options(self) -> List[ft.dropdown.Option]:
        return [ft.dropdown.Option(key=ep.key, text=ep.label) for ep in self.vm_endpoints]

    def host_ip_options(self) -> List[ft.dropdown.Option]:
        return [ft.dropdown.Option(key=ip, text=ip) for ip in self.host_ips]

    def parse_vm_key(self, key: str) -> Optional[VMEndpoint]:
        for ep in self.vm_endpoints:
            if ep.key == key:
                return ep
        return None

    def resolve_vm_ip(self, item: MappingItem) -> tuple[str, bool]:
        candidates = [ep.ip for ep in self.vm_endpoints if ep.kind == item.vm_kind and ep.name == item.vm_name]
        if not candidates:
            raise RuntimeError(f"未找到虚拟机: {item.vm_kind}/{item.vm_name}")
        if item.vm_ip in candidates:
            return item.vm_ip, False
        return candidates[0], True

    def apply_mapping(self, item: MappingItem, persist: bool = True) -> None:
        if not is_valid_ipv4(item.host_ip):
            raise RuntimeError("主机 IP 非法")
        if not (1 <= item.host_port <= 65535 and 1 <= item.vm_port <= 65535):
            raise RuntimeError("端口范围必须在 1-65535")

        new_ip, changed = self.resolve_vm_ip(item)
        if changed:
            log(f"虚拟机 IP 变化: {item.vm_ip} -> {new_ip}")
            item.vm_ip = new_ip

        delete_portproxy_rule(item.host_ip, item.host_port)
        create_portproxy_rule(item.host_ip, item.host_port, item.vm_ip, item.vm_port)
        item.active = True
        item.last_active = True
        if persist:
            save_mappings(self.mappings)

    def stop_mapping(self, item: MappingItem, keep_last_active: bool = False, persist: bool = True) -> None:
        delete_portproxy_rule(item.host_ip, item.host_port)
        item.active = False
        if not keep_last_active:
            item.last_active = False
        if persist:
            save_mappings(self.mappings)

    def refresh_environment(self) -> None:
        if not is_admin():
            raise RuntimeError("请以管理员权限运行程序")

        self.host_ips = list_host_ipv4()
        self.vm_endpoints = list_vm_endpoints()
        self.vm_select.options = self.vm_options()
        if self.vm_select.options and not self.vm_select.value:
            self.vm_select.value = self.vm_select.options[0].key
        self.host_ip_select.options = self.host_ip_options()
        if self.host_ip_select.options and (self.host_ip_select.value not in self.host_ips):
            self.host_ip_select.value = "0.0.0.0" if "0.0.0.0" in self.host_ips else self.host_ips[0]
        self.render_mapping_list()

    def find_mapping(self, mapping_id: str) -> Optional[MappingItem]:
        for item in self.mappings:
            if item.id == mapping_id:
                return item
        return None

    def _filtered_mappings(self) -> List[MappingItem]:
        keyword = (self.search_input.value or "").strip().lower()
        if not keyword:
            return self.mappings
        result: List[MappingItem] = []
        for item in self.mappings:
            haystack = f"{item.vm_kind} {item.vm_name} {item.vm_ip} {item.vm_port} {item.host_ip} {item.host_port}".lower()
            if keyword in haystack:
                result.append(item)
        return result

    def render_mapping_list(self) -> None:
        cards: List[ft.Control] = []
        shown = self._filtered_mappings()

        if not shown:
            cards.append(
                ft.Container(
                    border_radius=12,
                    padding=18,
                    bgcolor="#F8FAFD",
                    border=ft.border.all(1, "#E6ECF5"),
                    content=ft.Text("没有匹配的映射记录。", color="#5B6B7A"),
                )
            )

        for item in shown:
            cards.append(self._build_mapping_card(item))

        self.mappings_column.controls = cards
        self.page.update()

    def _build_mapping_card(self, item: MappingItem) -> ft.Control:
        is_editing = item.id in self.editing_ids
        vm_key = f"{item.vm_kind}|{item.vm_name}|{item.vm_ip}"

        vm_dd = ft.Dropdown(label="虚拟机", width=360, disabled=not is_editing)
        if is_editing:
            vm_dd.options = self.vm_options()
            vm_dd.value = vm_key
        else:
            vm_dd.options = [ft.dropdown.Option(key=vm_key, text=f"[{item.vm_kind}] {item.vm_name} ({item.vm_ip})")]
            vm_dd.value = vm_key

        host_ip_dd = ft.Dropdown(
            label="主机 IP",
            options=self.host_ip_options(),
            value=item.host_ip,
            width=160,
            disabled=not is_editing,
        )
        host_port_tf = ft.TextField(label="主机端口", width=120, value=str(item.host_port), disabled=not is_editing)
        vm_port_tf = ft.TextField(label="虚拟机端口", width=120, value=str(item.vm_port), disabled=not is_editing)

        chip = ft.Container(
            bgcolor="#2A9D8F" if item.active else "#64748B",
            border_radius=999,
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            content=ft.Text(
                "运行中" if item.active else "未运行",
                color=ft.Colors.WHITE,
                weight=ft.FontWeight.W_600,
                size=12,
            ),
        )
        tip = ft.Text(
            "上次关闭前已启用，可重建" if item.last_active and not item.active else "",
            size=12,
            color="#B7791F",
        )

        def on_edit(_: ft.ControlEvent, mapping_id: str = item.id) -> None:
            self.editing_ids.add(mapping_id)
            self.render_mapping_list()

        def on_cancel(_: ft.ControlEvent, mapping_id: str = item.id) -> None:
            self.editing_ids.discard(mapping_id)
            self.render_mapping_list()

        def on_save(
            _: ft.ControlEvent,
            mapping_id: str = item.id,
            vm_control: ft.Dropdown = vm_dd,
            host_ip_control: ft.Dropdown = host_ip_dd,
            host_port_control: ft.TextField = host_port_tf,
            vm_port_control: ft.TextField = vm_port_tf,
        ) -> None:
            target = self.find_mapping(mapping_id)
            if not target:
                self.set_status("保存失败：映射不存在", error=True)
                return
            try:
                selected = self.parse_vm_key(vm_control.value or "")
                if not selected:
                    raise RuntimeError("请选择虚拟机地址")
                host_ip = (host_ip_control.value or "").strip()
                if not is_valid_ipv4(host_ip):
                    raise RuntimeError("主机 IP 非法")
                target.vm_kind = selected.kind
                target.vm_name = selected.name
                target.vm_ip = selected.ip
                target.host_ip = host_ip
                target.host_port = int((host_port_control.value or "").strip())
                target.vm_port = int((vm_port_control.value or "").strip())
                if target.active:
                    self.stop_mapping(target, keep_last_active=True, persist=False)
                    self.apply_mapping(target, persist=False)
                save_mappings(self.mappings)
                self.editing_ids.discard(mapping_id)
                self.render_mapping_list()
                self.set_status("映射已保存")
            except Exception as exc:  # noqa: BLE001
                self.set_status(f"保存失败: {exc}", error=True)

        def on_apply(_: ft.ControlEvent, mapping_id: str = item.id) -> None:
            target = self.find_mapping(mapping_id)
            if not target:
                self.set_status("重建失败：映射不存在", error=True)
                return
            try:
                self.apply_mapping(target)
                self.render_mapping_list()
                self.set_status(f"映射已重建: {target.title}")
            except Exception as exc:  # noqa: BLE001
                self.set_status(f"重建失败: {exc}", error=True)

        def on_stop(_: ft.ControlEvent, mapping_id: str = item.id) -> None:
            target = self.find_mapping(mapping_id)
            if not target:
                return
            try:
                self.stop_mapping(target)
                self.render_mapping_list()
                self.set_status(f"映射已关闭: {target.host_ip}:{target.host_port}")
            except Exception as exc:  # noqa: BLE001
                self.set_status(f"关闭失败: {exc}", error=True)

        def on_delete(_: ft.ControlEvent, mapping_id: str = item.id) -> None:
            target = self.find_mapping(mapping_id)
            if not target:
                return
            try:
                if target.active:
                    self.stop_mapping(target, persist=False)
                self.mappings.remove(target)
                save_mappings(self.mappings)
                self.editing_ids.discard(mapping_id)
                self.render_mapping_list()
                self.set_status("映射已删除")
            except Exception as exc:  # noqa: BLE001
                self.set_status(f"删除失败: {exc}", error=True)

        action_buttons = (
            [
                ft.FilledButton("保存", icon=ft.Icons.SAVE_ALT, on_click=on_save),
                ft.OutlinedButton("取消", icon=ft.Icons.CLOSE, on_click=on_cancel),
            ]
            if is_editing
            else [
                ft.OutlinedButton("编辑", icon=ft.Icons.EDIT_OUTLINED, on_click=on_edit),
                ft.FilledTonalButton("重建", icon=ft.Icons.PLAY_ARROW, on_click=on_apply),
                ft.OutlinedButton("关闭", icon=ft.Icons.STOP_CIRCLE_OUTLINED, on_click=on_stop, disabled=not item.active),
                ft.TextButton("删除", icon=ft.Icons.DELETE_OUTLINE, on_click=on_delete),
            ]
        )

        return ft.Container(
            bgcolor="#FCFDFF",
            border_radius=12,
            border=ft.border.all(1, "#E8EEF5"),
            padding=12,
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text(item.title, size=14, weight=ft.FontWeight.W_600),
                            chip,
                        ],
                    ),
                    tip,
                    ft.Row(wrap=True, spacing=8, controls=[vm_dd, host_ip_dd, host_port_tf, vm_port_tf]),
                    ft.Row(wrap=True, spacing=6, controls=action_buttons),
                ],
            ),
        )

    def shutdown_cleanup(self) -> None:
        if self.closing:
            return
        self.closing = True
        try:
            log("开始执行关闭清理：关闭全部活动映射")
            changed = False
            for item in self.mappings:
                if item.active:
                    self.stop_mapping(item, keep_last_active=True, persist=False)
                    changed = True
            if changed:
                save_mappings(self.mappings)
            log("关闭清理完成")
        except Exception as exc:  # noqa: BLE001
            log(f"关闭清理失败: {exc}")
        finally:
            self.closing = False

    def _on_window_event(self, e: ft.WindowEvent) -> None:
        if e.data == "close":
            self.shutdown_cleanup()

    def _on_filter_change(self, _: ft.ControlEvent) -> None:
        self.render_mapping_list()

    def on_refresh(self, _: ft.ControlEvent) -> None:
        try:
            self.refresh_environment()
            self.set_status(f"环境已刷新：虚拟机 {len(self.vm_endpoints)} 条，主机地址 {len(self.host_ips)} 条")
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"刷新失败: {exc}", error=True)

    def on_add_mapping(self, _: ft.ControlEvent) -> None:
        try:
            if not is_admin():
                raise RuntimeError("请以管理员权限运行程序")
            selected = self.parse_vm_key(self.vm_select.value or "")
            if not selected:
                raise RuntimeError("请选择虚拟机地址")
            host_ip = (self.host_ip_select.value or "").strip()
            if not is_valid_ipv4(host_ip):
                raise RuntimeError("主机 IP 非法")
            host_port = int((self.host_port_input.value or "").strip())
            vm_port = int((self.vm_port_input.value or "").strip())
            if not (1 <= host_port <= 65535 and 1 <= vm_port <= 65535):
                raise RuntimeError("端口范围必须在 1-65535")

            conflict = next((m for m in self.mappings if m.host_ip == host_ip and m.host_port == host_port), None)
            if conflict:
                raise RuntimeError("该主机监听地址和端口已存在映射，请先编辑或删除旧映射")

            item = MappingItem(
                id=uuid4().hex,
                vm_kind=selected.kind,
                vm_name=selected.name,
                vm_ip=selected.ip,
                vm_port=vm_port,
                host_ip=host_ip,
                host_port=host_port,
                last_active=False,
                active=False,
            )
            self.apply_mapping(item, persist=False)
            self.mappings.append(item)
            save_mappings(self.mappings)
            self.render_mapping_list()
            self.set_status(f"映射已新增并启用: {item.title}")
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"新增失败: {exc}", error=True)

    def rebuild_last_active(self, _: ft.ControlEvent) -> None:
        try:
            if not is_admin():
                raise RuntimeError("请以管理员权限运行程序")
            count = 0
            for item in self.mappings:
                if item.last_active:
                    self.apply_mapping(item, persist=False)
                    count += 1
            if count:
                save_mappings(self.mappings)
            self.render_mapping_list()
            self.set_status(f"重建完成: {count} 条")
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"批量重建失败: {exc}", error=True)


def main(page: ft.Page) -> None:
    app = PortSnakeUI(page)
    app.build()
