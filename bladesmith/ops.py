"""Edits applied to weapon assets: blade mesh, scabbard, trails, meshes inside attached effects."""
from __future__ import annotations

import copy
import uuid

import fnmatch

from .asset import Asset, prop, prop_value
from .catalog import Weapon
from .game import Game

TRANSFORM = ("RelativeLocation", "RelativeRotation", "RelativeScale3D")


class RecipeError(ValueError):
    pass


def set_blade_mesh(bp: Asset, mesh_package: str) -> list[str]:
    """Point the blueprint's 'Weapon Mesh' at another skeletal mesh and drop its per-mesh transform
    (offsets/scales tuned for the old mesh push the new blade out of its scabbard)."""
    wm = bp.export("Weapon Mesh")
    idx = prop_value(wm["Data"], "SkeletalMesh")
    if not (isinstance(idx, int) and idx < 0):
        raise RecipeError("blueprint has no SkeletalMesh import on 'Weapon Mesh'")
    bp.repoint_import(idx, mesh_package, mesh_package.rsplit("/", 1)[1])
    dropped = [p["Name"] for p in wm["Data"] if p["Name"] in TRANSFORM]
    wm["Data"] = [p for p in wm["Data"] if p["Name"] not in TRANSFORM]
    return dropped


def set_blade_material(bp: Asset, mi_package: str) -> None:
    """Give the blueprint's 'Weapon Mesh' its own material for slot 0 (OverrideMaterials), so only this weapon
    changes color; the mesh and every other weapon using it keep the original material."""
    wm = bp.export("Weapon Mesh")
    idx = bp.add_object_import(mi_package, mi_package.rsplit("/", 1)[1], "MaterialInstanceConstant", "/Script/Engine")
    bp.ensure_name("OverrideMaterials")
    item = {"$type": "UAssetAPI.PropertyTypes.Objects.ObjectPropertyData, UAssetAPI", "Name": "0", "ArrayIndex": 0,
            "PropertyGuid": None, "IsZero": False, "PropertyTagFlags": "None", "PropertyTypeName": None,
            "PropertyTagExtensions": "NoExtension", "Value": idx}
    override = {**item, "$type": "UAssetAPI.PropertyTypes.Objects.ArrayPropertyData, UAssetAPI",
                "ArrayType": "ObjectProperty", "Name": "OverrideMaterials", "Value": [item]}
    wm["Data"] = [p for p in wm["Data"] if p["Name"] != "OverrideMaterials"] + [override]


def _import(a: Asset, obj: str, outer: int, cls: str, cls_pkg: str) -> int:
    for i, x in enumerate(a.imports):
        if (x["ObjectName"], x["OuterIndex"], x["ClassName"], x["ClassPackage"]) == (obj, outer, cls, cls_pkg):
            return -(i + 1)
    for n in (obj, cls, cls_pkg):
        a.ensure_name(n)
    a.imports.append({"$type": "UAssetAPI.Import, UAssetAPI", "ObjectName": obj, "OuterIndex": outer,
                      "ClassPackage": cls_pkg, "ClassName": cls, "PackageName": None, "bImportOptional": False})
    return -len(a.imports)


def add_effect_component(bp: Asset, system: str, var: str, socket: str) -> None:
    """Give a weapon blueprint a Niagara component that plays `system` at `socket` of its 'Weapon Mesh', as one
    more construction script node (the same layout as SnakeDual's phantom sword component)."""
    ex = bp.j["Exports"]
    scs_i = next(k for k, e in enumerate(ex) if str(e["ObjectName"]).startswith("SimpleConstructionScript")) + 1
    node0 = next(e for e in ex if str(e["ObjectName"]).startswith("SCS_Node_") and e["OuterIndex"] == scs_i)
    template = next(e for e in ex if str(e["ObjectName"]).endswith("_GEN_VARIABLE") and e["OuterIndex"] == 1
                    and e["$type"].endswith("NormalExport, UAssetAPI"))
    if any(e["ObjectName"] == f"{var}_GEN_VARIABLE" for e in ex):
        raise RecipeError(f"blueprint already has a component '{var}'")
    script_pkg = _import(bp, "/Script/Niagara", 0, "Package", "/Script/CoreUObject")
    comp_cls = _import(bp, "NiagaraComponent", script_pkg, "Class", "/Script/CoreUObject")
    comp_def = _import(bp, "Default__NiagaraComponent", script_pkg, "NiagaraComponent", "/Script/Niagara")
    sys_pkg = _import(bp, system, 0, "Package", "/Script/CoreUObject")
    sys_obj = _import(bp, system.rsplit("/", 1)[1], sys_pkg, "NiagaraSystem", "/Script/Niagara")
    obj_prop = {"$type": "UAssetAPI.PropertyTypes.Objects.ObjectPropertyData, UAssetAPI", "ArrayIndex": 0,
                "PropertyGuid": None, "IsZero": False, "PropertyTagFlags": "None", "PropertyTypeName": None,
                "PropertyTagExtensions": "NoExtension"}
    name_prop = {**obj_prop, "$type": "UAssetAPI.PropertyTypes.Objects.NamePropertyData, UAssetAPI"}
    bool_prop = {**obj_prop, "$type": "UAssetAPI.PropertyTypes.Objects.BoolPropertyData, UAssetAPI"}

    comp = copy.deepcopy(template)
    comp.update(ObjectName=f"{var}_GEN_VARIABLE", ClassIndex=comp_cls, TemplateIndex=comp_def,
                SerializationBeforeSerializationDependencies=[1], CreateBeforeSerializationDependencies=[sys_obj],
                SerializationBeforeCreateDependencies=[comp_cls, comp_def], CreateBeforeCreateDependencies=[1],
                Data=[{**obj_prop, "Name": "Asset", "Value": sys_obj}])
    ex.append(comp)
    comp_i = len(ex)

    node = copy.deepcopy(node0)
    nodes = [e for e in ex if str(e["ObjectName"]).startswith("SCS_Node_")]
    node_name = f"SCS_Node_{1 + max(int(str(e['ObjectName']).rsplit('_', 1)[1]) for e in nodes)}"
    guid = prop(node0["Data"], "VariableGUID")
    guid = copy.deepcopy(guid)
    guid["Value"][0]["Value"] = "{" + str(uuid.uuid4()).upper() + "}"
    node.update(ObjectName=node_name, CreateBeforeSerializationDependencies=[comp_i],
                Data=[{**obj_prop, "Name": "ComponentClass", "Value": comp_cls},
                      {**obj_prop, "Name": "ComponentTemplate", "Value": comp_i},
                      {**name_prop, "Name": "AttachToName", "Value": socket},
                      {**name_prop, "Name": "ParentComponentOrVariableName", "Value": "Weapon Mesh"},
                      {**bool_prop, "Name": "bIsParentComponentNative", "Value": True},
                      guid,
                      {**name_prop, "Name": "InternalVariableName", "Value": var}])
    ex.append(node)
    node_i = len(ex)

    scs = ex[scs_i - 1]
    scs["CreateBeforeSerializationDependencies"] = scs["CreateBeforeSerializationDependencies"] + [node_i]
    for arr in ("RootNodes", "AllNodes"):
        items = prop(scs["Data"], arr)["Value"]
        item = copy.deepcopy(items[0])
        item["Name"], item["Value"] = str(len(items)), node_i
        items.append(item)
    for n in (f"{var}_GEN_VARIABLE", var, node_name, "Asset", "AttachToName", socket, "Weapon Mesh",
              "ObjectProperty", "NameProperty", "BoolProperty"):
        bp.ensure_name(n)


def set_scabbard(data_asset: Asset, slot: int, mesh_package: str, socket: str) -> None:
    dd = prop(data_asset.main_data(), "Display Data")["Value"]
    entry = dd[slot]["Value"]
    idx = data_asset.add_object_import(mesh_package, mesh_package.rsplit("/", 1)[1], "SkeletalMesh", "/Script/Engine")
    sm = prop(entry, "ScabbardMesh")
    sm["Value"] = idx
    sm["IsZero"] = False
    ss = prop(entry, "ScabbardSocket")
    if ss.get("Value") != socket:
        data_asset.ensure_name(socket)
        ss["Value"] = socket


# a game effect with no emitters: trails set to "none" point here and draw nothing
EMPTY_SYSTEM = "/PBZVFXPack/VFX/BattleFX/ZuoShang_LongTi/NS_ZuoShangLongTi_NoneWater_201"

def set_trails(data_asset: Asset, mapping: dict[str, str], base: Weapon, game: Game) -> list[str]:
    """mapping: tag pattern (fnmatch, part after 'Weapon.Trail.') -> Niagara system name or package path."""
    report, used = [], set()
    tr = prop(data_asset.main_data(), "Trails")["Value"]
    for key, val in tr:
        tag = key["Value"][0]["Value"].removeprefix("Weapon.Trail.")
        pat = next((p for p in mapping if fnmatch.fnmatchcase(tag, p)), None)
        if pat is None:
            continue
        used.add(pat)
        target = mapping[pat]
        part = next(x for x in val["Value"] if x["Name"].startswith("Particle_"))
        none = target.lower() == "none"  # no trail: an empty reference makes the game fall back to a default one
        pkg = game.resolve(EMPTY_SYSTEM if none else target)  # a typo here would ship a pak that points at nothing
        idx = data_asset.add_object_import(pkg, pkg.rsplit("/", 1)[1], "NiagaraSystem", "/Script/Niagara")
        part["Value"] = idx
        part["IsZero"] = False
        if none:
            report.append(f"{tag} -> none")
            continue
        if base.fades and game.has(pkg) and b"UE_StartFade" not in game.raw_bytes(pkg):
            report.append(f"warning: {base.key} fades its trails but {pkg.rsplit('/', 1)[1]} has no UE_StartFade "
                          f"-> it will keep trailing the blade after the attack ({tag})")
        report.append(f"{tag} -> {pkg.rsplit('/', 1)[1]}")
    unused = set(mapping) - used
    if unused:
        raise RecipeError(f"{base.key}: no trail tag matches {sorted(unused)}")
    return report


def copy_effect_with_mesh(raw: dict, old_pkg: str, new_pkg: str, mesh_from: str, mesh_to: str) -> Asset:
    """Relocated copy of a Niagara system (raw, unmapped JSON: lossless) with one static mesh swapped."""
    a = Asset(raw)
    hits = [i for i in a.find_imports("StaticMesh") if a.package_of(i) == mesh_from]
    if len(hits) != 1:
        raise RecipeError(f"{old_pkg.rsplit('/', 1)[1]} does not use {mesh_from}")
    a.repoint_import(hits[0], mesh_to, mesh_to.rsplit("/", 1)[1])
    a.rename(old_pkg, new_pkg, None)  # the package's own name: always replaced
    for x in a.imports:
        if x["ObjectName"] == old_pkg:
            x["ObjectName"] = new_pkg
    if a.j.get("FolderName") == old_pkg:
        a.j["FolderName"] = new_pkg
    return a


def repoint_attached_effect(bp: Asset, old_pkg: str, new_pkg: str) -> None:
    hits = [i for i in bp.find_imports("NiagaraSystem") if bp.package_of(i) == old_pkg]
    if len(hits) != 1:
        raise RecipeError(f"blueprint does not use {old_pkg}")
    bp.repoint_import(hits[0], new_pkg, new_pkg.rsplit("/", 1)[1])


def retarget_trails(data_asset: Asset, remap: dict[str, str], canon, source: str) -> list[str]:
    """Point every trail that uses a system in `remap` (original package -> copy package) at the copy."""
    report = []
    tr = prop(data_asset.main_data(), "Trails")["Value"]
    for key, val in tr:
        part = next(x for x in val["Value"] if x["Name"].startswith("Particle_"))
        idx = part.get("Value")
        if not (isinstance(idx, int) and idx < 0):
            continue
        src = canon(data_asset.package_of(idx))
        if src in remap:
            dst = remap[src]
            part["Value"] = data_asset.add_object_import(dst, dst.rsplit("/", 1)[1], "NiagaraSystem", "/Script/Niagara")
            report.append(f"{key['Value'][0]['Value'].removeprefix('Weapon.Trail.')} -> {dst}")
    if not report:
        raise RecipeError(f"{source}: none of this weapon's trails can be recolored this way")
    return report
