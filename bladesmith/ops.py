"""Edits applied to weapon assets: blade mesh, scabbard, trails, meshes inside attached effects."""
from __future__ import annotations

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


def add_equip_tag(data_asset: Asset, tag: str) -> bool:
    """Add a gameplay tag to the weapon's 'Weapon Equip Tags'. False if it is already there."""
    tags = prop(data_asset.main_data(), "Weapon Equip Tags")["Value"][0]["Value"]
    if tag in tags:
        return False
    data_asset.ensure_name(tag)
    tags.append(tag)
    return True


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
