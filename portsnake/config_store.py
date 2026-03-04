import json
from dataclasses import asdict
from pathlib import Path
from typing import List

from .logger import log
from .models import MappingItem

CONFIG_PATH = Path("portsnake_config.json")


def load_mappings() -> List[MappingItem]:
    if not CONFIG_PATH.exists():
        return []
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        items: List[MappingItem] = []
        for obj in raw.get("mappings", []):
            items.append(MappingItem(**obj))
        log(f"已加载配置，共 {len(items)} 条映射")
        return items
    except Exception as exc:  # noqa: BLE001
        log(f"读取配置失败: {exc}")
        return []


def save_mappings(mappings: List[MappingItem]) -> None:
    payload = {"mappings": [asdict(item) for item in mappings]}
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"配置已保存: {CONFIG_PATH} ({len(mappings)} 条)")

