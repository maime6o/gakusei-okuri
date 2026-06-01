from __future__ import annotations
import json
import pathlib
from typing import List, Optional
from engine.models import CatalogCard, CardInstance, CardKind

_CATALOG_PATH = pathlib.Path(__file__).parent.parent / "data" / "catalog.json"
_catalog: Optional[dict] = None


def _load() -> dict:
    global _catalog
    if _catalog is None:
        _catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    return _catalog


def all_members() -> List[CatalogCard]:
    return [CatalogCard(**c) for c in _load()["members"]]


def all_supports() -> List[CatalogCard]:
    return [CatalogCard(**c) for c in _load()["supports"]]


def all_antis() -> List[CatalogCard]:
    return [CatalogCard(**c) for c in _load()["antis"]]


def all_incidents() -> List[CatalogCard]:
    return [CatalogCard(**c) for c in _load()["incidents"]]


def catalog_id_for(card: CatalogCard) -> str:
    if card.kind == CardKind.MEMBER:
        return f"member_{card.id}"
    return f"{card.kind.value}_{card.name}"


def instance_from_catalog(card: CatalogCard) -> CardInstance:
    return CardInstance(
        catalog_id=catalog_id_for(card),
        kind=card.kind,
        name=card.name,
        part=card.part,
        gender=card.gender,
        draw=card.draw,
        music=card.music,
        human=card.human,
        ability=card.ability,
        phase=card.phase,
        effect=card.effect,
        severity=card.severity,
        description=card.description,
    )
