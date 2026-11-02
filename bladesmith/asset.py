"""Helpers for editing UAssetGUI JSON safely (imports, name map, exports)."""
from __future__ import annotations

import copy
import json
import re

_NUM = re.compile(r"^(.*)_([1-9][0-9]*)$")


def _imp(obj: str, outer: int, cls: str, cls_pkg: str) -> dict:
    return {"$type": "UAssetAPI.Import, UAssetAPI", "ObjectName": obj, "OuterIndex": outer, "ClassPackage": cls_pkg,
            "ClassName": cls, "PackageName": None, "bImportOptional": False}


class Asset:
    def __init__(self, data: dict):
        self.j = copy.deepcopy(data)

    @property
    def names(self) -> list[str]:
        return self.j["NameMap"]

    @property
    def imports(self) -> list[dict]:
        return self.j["Imports"]

    def dump(self) -> str:
        return json.dumps(self.j, ensure_ascii=False)

    # --- names ------------------------------------------------------------------------------------
    def ensure_name(self, name: str) -> None:
        """Add a name plus its FName base: 'Foo_101' is stored as 'Foo' + number, and UAssetGUI writes
        nothing at all if the base is missing."""
        for n in (name, *([_NUM.match(name).group(1)] if _NUM.match(name) else [])):
            if n not in self.names:
                self.names.append(n)

    def _name_refs(self, name: str) -> int:
        body = {k: v for k, v in self.j.items() if k != "NameMap"}
        return json.dumps(body, ensure_ascii=False).count(json.dumps(name, ensure_ascii=False))

    def rename(self, old: str, new: str, uses: int | None) -> None:
        """Swap a name in place (keeping the map order) if it is used exactly `uses` times, or always when
        uses is None; otherwise just add the new one."""
        if old in self.names and new not in self.names and (uses is None or self._name_refs(old) == uses):
            self.names[self.names.index(old)] = new
        self.ensure_name(new)

    # --- imports ----------------------------------------------------------------------------------
    def imp(self, index: int) -> dict:
        return self.imports[-index - 1]

    def package_of(self, index: int) -> str:
        return self.imp(self.imp(index)["OuterIndex"])["ObjectName"]

    def find_imports(self, cls: str) -> list[int]:
        return [-(i + 1) for i, x in enumerate(self.imports) if x["ClassName"] == cls]

    def add_object_import(self, package: str, obj: str, cls: str, cls_pkg: str) -> int:
        for i in self.find_imports(cls):
            if self.imp(i)["ObjectName"] == obj and self.package_of(i) == package:
                return i
        for n in (package, obj, cls, cls_pkg, "Package", "/Script/CoreUObject"):
            self.ensure_name(n)
        self.imports.append(_imp(package, 0, "Package", "/Script/CoreUObject"))
        self.imports.append(_imp(obj, -len(self.imports), cls, cls_pkg))
        return -len(self.imports)

    def repoint_import(self, index: int, package: str, obj: str) -> None:
        """Point an existing object import (and its package import) at another asset."""
        o, p = self.imp(index), self.imp(self.imp(index)["OuterIndex"])
        if p["ObjectName"] != package:
            self.rename(p["ObjectName"], package, 1)
            p["ObjectName"] = package
        if o["ObjectName"] != obj:
            self.rename(o["ObjectName"], obj, 1)
            o["ObjectName"] = obj

    # --- exports ----------------------------------------------------------------------------------
    def export(self, name: str) -> dict:
        hits = [e for e in self.j["Exports"] if e.get("ObjectName") == name]
        if len(hits) != 1:
            raise KeyError(f"export '{name}': {len(hits)} matches")
        return hits[0]

    def main_data(self) -> list[dict]:
        return self.j["Exports"][0]["Data"]


def prop(data: list[dict], name: str) -> dict:
    hits = [p for p in data if p.get("Name") == name]
    if len(hits) != 1:
        raise KeyError(f"property '{name}': {len(hits)} matches")
    return hits[0]


def prop_value(data: list[dict], name: str, default=None):
    hits = [p for p in data if p.get("Name") == name]
    return hits[0].get("Value") if hits else default
