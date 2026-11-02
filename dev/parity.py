"""Compare assets produced by bladesmith with a reference stage (e.g. a hand-made, in-game tested build).
usage: python dev/parity.py <bladesmith stage> <reference stage>
Byte-identical files are reported as such; the rest are compared semantically (imports resolved to paths,
name-map order ignored) through UAssetGUI JSON."""
import json, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bladesmith import config, tools  # noqa: E402

def norm(js: dict):
    imps = js["Imports"]
    def res(v):
        if isinstance(v, dict):
            return {k: res(x) for k, x in v.items() if k not in ("SerialSize", "SerialOffset", "ScriptSerializationStartOffset", "ScriptSerializationEndOffset")}
        if isinstance(v, list):
            return [res(x) for x in v]
        return v
    def path(i):
        out = []
        while i < 0:
            out.append(imps[-i - 1]["ObjectName"]); i = imps[-i - 1]["OuterIndex"]
        return "/".join(reversed(out))
    s = json.dumps(js["Exports"])
    exports = res(json.loads(s))
    # replace negative integer import refs in "Value" fields with resolved paths
    def fix(v):
        if isinstance(v, dict):
            return {k: (f"<{path(x)}>" if k in ("Value", "OuterIndex", "ClassIndex", "SuperIndex", "TemplateIndex") and isinstance(x, int) and x < 0 and -x <= len(imps) else fix(x)) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v
    return fix(exports), sorted(path(-(i + 1)) for i in range(len(imps)))

def main(a, b):
    cfg = config.load()
    a, b = Path(a), Path(b)
    tmp = Path(tempfile.mkdtemp())
    bad = 0
    for f in sorted(a.rglob("*.uasset")):
        rel = f.relative_to(a); g = b / rel
        if not g.exists():
            print("NEW      ", rel); continue
        same = f.read_bytes() == g.read_bytes() and f.with_suffix(".uexp").read_bytes() == g.with_suffix(".uexp").read_bytes()
        if same:
            print("IDENTICAL", rel.name); continue
        mapped = "/VFX/" not in str(rel).replace("\\", "/")
        ja, jb = tmp / "a.json", tmp / "b.json"
        tools.to_json(cfg, f, ja, mapped); tools.to_json(cfg, g, jb, mapped)
        na, nb = norm(json.loads(ja.read_text(encoding="utf-8-sig"))), norm(json.loads(jb.read_text(encoding="utf-8-sig")))
        if na == nb:
            print("SAME*    ", rel.name, "(same content, different name/import order)")
        else:
            bad += 1
            print("DIFFERENT", rel.name, "imports differ:" if na[1] != nb[1] else "exports differ",
                  sorted(set(na[1]) ^ set(nb[1]))[:6] if na[1] != nb[1] else "")
    return bad

if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
