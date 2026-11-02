# Bladesmith

Weapon transmog builder for Phantom Blade Zero. Pick a weapon whose stats and moveset you like, put another weapon's
look on it (blade model, scabbard, attack trails), and Bladesmith builds a pak mod for the `~mods` folder.

It reads the assets from your own game install and writes only the few files it changes, so no game files ship with
it, and after a game patch you rebuild the pak from the updated game.

Status: early, command line only. A simple window app is planned.

## What it can do

- **Skins.** Swap the blade model of any player weapon for another weapon's model, slot by slot for dual weapons.
  The per-model offset/scale of the old blade is removed, so the new one sits right in hand and scabbard.
- **Scabbards.** Use the skin's scabbard (Sanguine, Sanguine Reach and Sanguine Twin have one).
- **Trails.** Replace attack trails per tag (`Normal.A`, `Normal.B.*`, ...) with any Niagara system in the game.
- **Effect meshes.** Copy an effect attached to a blade (for example a ghost blade) with another mesh inside.
- **Checks.** Skins are limited to the same weapon type (one-handed, two-handed, dual), because hitboxes and
  animations stay with the base weapon. Weapons that end their trails with a fade (Outlaw Warblade and eight others)
  get a warning when a trail without fade support is picked, since such a trail keeps following the blade.

Not yet: recoloring effects, display names, previews.

## Requirements

- Windows, Python 3.11+
- [retoc](https://github.com/trumank/retoc) built with [`patches/retoc-partitioned-ucas.patch`](patches/retoc-partitioned-ucas.patch).
  The game splits its container into `ProjectPBZ-Windows_s1..s49.ucas`; upstream retoc only opens the first file.
- [UAssetGUI](https://github.com/atenfyr/UAssetGUI) 1.1.0
- Mappings for the game: [USMAP File (Proper)](https://www.nexusmods.com/phantombladezero/mods/55) on Nexus, saved as
  `%LOCALAPPDATA%\UAssetGUI\Mappings\PBZ.usmap`

## Setup

```
copy bladesmith.example.toml bladesmith.toml
```

Edit `game_dir` and the tool paths in `bladesmith.toml`.

## Usage

```
python -m bladesmith catalog                 # list player weapons, write catalog.json
python -m bladesmith build examples/wild-oriole.json --install
```

`--install` copies the pak into `~mods`. Close the game first, it locks mod files.

### Recipe

```json
{
  "pak_name": "zzz_MySkins_P",
  "fx_folder": "/PBZVFXPack/VFX/Bladesmith",
  "weapons": [
    {"base": "Iron", "skin": "Tang", "scabbard": true,
     "trails": {"Normal.A": "NS_JinYe_BloodTrail_101"}},
    {"base": "LuanYing_Evolution", "skin": "Tang", "slots": [0], "scabbard": true},
    {"base": "SnakeDual", "skin": "Double", "scabbard": true,
     "effect_meshes": [{"slot": 1, "system": "NS_SnakeDual_PhantomSword_001", "mesh": "SM_FX_DoubleBlade_101"}]}
  ]
}
```

- `base`, `skin`: weapon keys from `catalog.json` (the part after `Weapon_Hun_`).
- `slots`: which blades of the base to reskin (default: all).
- `trails`: tag pattern -> effect name or package path. Tags are the part after `Weapon.Trail.`.
- Each pak needs its own `pak_name`. Two paks that edit the same weapon conflict; separate weapons stack fine.

The examples rebuild [Sanguine Skins](https://www.nexusmods.com/phantombladezero/mods/399) asset for asset
(except Outlaw Warblade's recolored trails).

## Credits

- [retoc](https://github.com/trumank/retoc) by trumank and Archengius
- [UAssetGUI / UAssetAPI](https://github.com/atenfyr/UAssetGUI) by atenfyr
- Game mappings: USMAP File (Proper), Nexus mod 55

## License

MIT
