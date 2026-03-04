from dataclasses import dataclass


@dataclass
class VMEndpoint:
    kind: str
    name: str
    ip: str

    @property
    def key(self) -> str:
        return f"{self.kind}|{self.name}|{self.ip}"

    @property
    def label(self) -> str:
        return f"[{self.kind}] {self.name} ({self.ip})"


@dataclass
class MappingItem:
    id: str
    vm_kind: str
    vm_name: str
    vm_ip: str
    vm_port: int
    host_ip: str
    host_port: int
    last_active: bool = False
    active: bool = False

    @property
    def title(self) -> str:
        return f"{self.host_ip}:{self.host_port} -> {self.vm_kind}/{self.vm_name} {self.vm_ip}:{self.vm_port}"

