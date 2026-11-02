"""Build the release archive: Bladesmith.exe + tools/ (retoc, UAssetGUI, mappings) + licenses.

usage: python packaging/build_release.py VERSION
The tool binaries come from your bladesmith.toml (retoc built with patches/retoc-partitioned-ucas.patch);
the mappings from UAssetGUI's mappings folder. Needs PyInstaller and the GitHub CLI (for license texts).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bladesmith import config  # noqa: E402

BUILD = ROOT / "build"
LICENSES = {  # third-party files shipped in tools/
    "retoc.txt": "trumank/retoc",
    "UAssetGUI.txt": "atenfyr/UAssetGUI",
    "PBZ-usmap.txt": "KintaroModding/phantombladezero_pbzusmap",
}
README = """Bladesmith {version}
Weapon transmog builder for Phantom Blade Zero
https://github.com/ayokiru/pbz-bladesmith

Start Bladesmith.exe. It finds the game through Steam; if it can't, it asks for the game folder.
The first start reads the weapons from the game and takes a few minutes. Later starts take seconds.

Requirements: Windows 10 or 11, the .NET 8 Desktop Runtime (x64), which UAssetGUI needs.
Bladesmith shows a download button if it is missing.

Close the game before you press Build & install: the game locks the files in its ~mods folder.
Built paks go to ProjectPBZ\\Content\\Paks\\~mods. Remove them from the Installed list in the program,
or delete the three zzz_*_P files there by hand.

Bladesmith keeps its cache in %LOCALAPPDATA%\\Bladesmith. Delete that folder to start fresh.

tools\\ holds retoc (with a patch for the game's split containers), UAssetGUI and the game's mappings
(USMAP File (Proper) by Kintaro). Their licenses are in licenses\\.
"""


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def main(version: str) -> Path:
    cfg = config.load()
    mappings = Path(os.environ["LOCALAPPDATA"]) / "UAssetGUI" / "Mappings" / f"{cfg.mappings}.usmap"
    for f in (cfg.retoc, cfg.uassetgui, mappings):
        if not f.exists():
            raise SystemExit(f"missing: {f}")

    shutil.rmtree(BUILD, ignore_errors=True)
    data = [f"{ROOT / 'bladesmith' / d}{os.pathsep}bladesmith/{d}" for d in ("web", "presets", "data")]
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", "Bladesmith",
           "--icon", str(ROOT / "packaging" / "bladesmith.ico"),
           "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD)]
    for d in data:
        cmd += ["--add-data", d]
    subprocess.run(cmd + [str(ROOT / "packaging" / "launcher.py")], check=True, cwd=ROOT)

    app = BUILD / "dist" / "Bladesmith"
    tools = app / "tools"
    (tools / "Data" / "Mappings").mkdir(parents=True)  # UAssetGUI portable mode: mappings next to the exe
    shutil.copy2(cfg.retoc, tools / "retoc.exe")
    shutil.copy2(cfg.uassetgui, tools / "UAssetGUI.exe")
    shutil.copy2(mappings, tools / "Data" / "Mappings" / "PBZ.usmap")
    lic = app / "licenses"
    lic.mkdir()
    shutil.copy2(ROOT / "LICENSE", lic / "Bladesmith.txt")
    for name, repo in LICENSES.items():
        (lic / name).write_text(run("gh", "api", f"repos/{repo}/license", "--jq", ".content | @base64d"), encoding="utf-8")
    (app / "README.txt").write_text(README.format(version=version), encoding="utf-8")

    archive = BUILD / f"Bladesmith-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                zi = zipfile.ZipInfo(f"Bladesmith/{f.relative_to(app).as_posix()}", (2026, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = 0o644 << 16
                z.writestr(zi, f.read_bytes())
    print(f"{archive} ({archive.stat().st_size // 1024 // 1024} MB)")
    return archive


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dev")
