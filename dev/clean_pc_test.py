"""Runs a released Bladesmith zip as a stranger's PC would: unpacked by Explorer (every file marked as
downloaded), under a Cyrillic path with spaces, empty user folders, no Python on PATH, and no UAssetGUI mappings
of our own. Opens the real window and drives it over WebView2's debugging port, like a user clicking through.

usage: python clean_pc_test.py <zip>"""
import base64, json, os, shutil, socket, struct, subprocess, sys, time, urllib.request, zipfile
from pathlib import Path

ZIP = Path(sys.argv[1])
ROOT = Path(os.environ["USERPROFILE"]) / "pbz-modding" / "Чистый ПК тест"
APP = ROOT / "Загрузки" / "Bladesmith"
LOCAL = ROOT / "Пользователь Иван" / "AppData" / "Local"
PORT = 9333
REAL_MAPPINGS = Path(os.environ["LOCALAPPDATA"]) / "UAssetGUI" / "Mappings"
HIDDEN = REAL_MAPPINGS.with_name("Mappings.hidden-by-test")
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail else ""), flush=True)


# --- a tiny CDP client over a raw websocket (stdlib only) -------------------------------------------------
class Cdp:
    def __init__(self, ws_url):
        host, path = ws_url[len("ws://"):].split("/", 1)
        h, p = host.split(":")
        self.s = socket.create_connection((h, int(p)), timeout=600)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self.extra = buf.split(b"\r\n\r\n", 1)[1]
        self.n = 0

    def _recv(self, n):
        while len(self.extra) < n:
            self.extra += self.s.recv(65536)
        out, self.extra = self.extra[:n], self.extra[n:]
        return out

    def _frame(self):
        b1, b2 = self._recv(2)
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._recv(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._recv(8))[0]
        return b1 & 0x0F, self._recv(ln)

    def call(self, method, **params):
        self.n += 1
        data = json.dumps({"id": self.n, "method": method, "params": params}).encode()
        mask = os.urandom(4)
        head = bytes([0x81]) + (bytes([0x80 | len(data)]) if len(data) < 126 else
                               bytes([0x80 | 126]) + struct.pack(">H", len(data)) if len(data) < 65536 else
                               bytes([0x80 | 127]) + struct.pack(">Q", len(data)))
        self.s.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))
        while True:
            op, payload = self._frame()
            if op == 1:
                msg = json.loads(payload)
                if msg.get("id") == self.n:
                    return msg

    def js(self, expr, timeout=600):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True, timeout=timeout * 1000)
        res = r.get("result", {})
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"].get("exception", {}).get("description", res["exceptionDetails"]))
        return res.get("result", {}).get("value")


def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    APP.parent.mkdir(parents=True)
    LOCAL.mkdir(parents=True)
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(APP.parent)
    marked = 0
    for f in APP.rglob("*"):  # what Explorer does when it unpacks a downloaded zip
        if f.is_file():
            with open(str(f) + ":Zone.Identifier", "w") as ads:
                ads.write("[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://www.nexusmods.com/\r\n")
            marked += 1
    check("unpacked under a Cyrillic path, every file marked as downloaded", marked > 100, f"{marked} files")

    env = {k: v for k, v in os.environ.items() if k.upper() not in ("PATH", "PYTHONPATH", "PYTHONHOME", "LOCALAPPDATA", "APPDATA")}
    env["PATH"] = r"C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem;C:\Program Files\dotnet"
    env["LOCALAPPDATA"] = str(LOCAL)
    env["APPDATA"] = str(LOCAL.parent / "Roaming")
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={PORT}"
    exe = APP / "Bladesmith.exe"
    proc = subprocess.Popen([str(exe)], cwd=str(APP.parent), env=env)
    try:
        page = None
        for _ in range(120):
            time.sleep(1)
            if proc.poll() is not None:
                break
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2))
                page = next((p for p in pages if p.get("type") == "page"), None)
                if page:
                    break
            except OSError:
                pass
        check("window opened", page is not None and proc.poll() is None, f"exit code {proc.poll()}" if proc.poll() is not None else "")
        if not page:
            return
        cdp = Cdp(page["webSocketDebuggerUrl"])
        t0 = time.time()
        state = cdp.js("""new Promise(res => { const t0 = Date.now(); (function wait() {
            if (typeof S !== 'undefined' && S.data) return res(S.data.setup ? 'setup: ' + S.data.setup.message : 'ready ' + S.data.weapons.length + ' weapons, ' + S.data.trails.length + ' trails');
            const err = document.getElementById('loading-log'); if (err && /Could not read/.test(err.textContent)) return res('error: ' + err.textContent);
            if (Date.now() - t0 > 900000) return res('timeout: ' + (err && err.textContent)); setTimeout(wait, 500); })(); })""", timeout=960)
        check("first start: reads the game", str(state).startswith("ready"), f"{state} in {time.time() - t0:.0f} s")
        pics = cdp.js("S.data.weapons.filter(w => w.img).length")
        check("weapon pictures", pics and pics > 20, f"{pics} pictures")
        pal = cdp.js("window.pywebview.api.blade_palette('Tang')")
        check("blade color palette", pal and pal.get("ok") and pal["colors"], json.dumps(pal)[:120])
        recipe = {"pak_name": "zzz_CleanPcTest_P", "weapons": [
            {"base": "WoodenSword", "skin": "Tang", "blade_color": {"from": 5, "to": "#3060ff"}},
            {"base": "Iron", "skin": "Tang", "scabbard": True, "trails": {"Normal.A": "NS_JinYe_BloodTrail_101"}, "trail_tint": "gold"},
            {"base": "ZhanMaBlade", "skin": "Long", "scabbard": True, "trail_color": "outlaw-crimson"}]}
        t0 = time.time()
        res = cdp.js(f"window.pywebview.api.build({json.dumps(recipe)}, false)", timeout=900)
        check("build from the window (no install)", res and res.get("ok"), f"{json.dumps(res)[:200]} in {time.time() - t0:.0f} s")
        out = LOCAL / "Bladesmith" / "out" / "zzz_CleanPcTest_P"
        files = sorted(p.name for p in out.glob("*")) if out.is_dir() else []
        check("pak files written", len(files) == 3, ", ".join(files))
        inst = cdp.js("window.pywebview.api.installed()")
        check("installed list", isinstance(inst, list), json.dumps(inst)[:120])
    finally:
        proc.kill()
        proc.wait()
        log = LOCAL / "Bladesmith" / "bladesmith.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        check("no errors in bladesmith.log", "Traceback" not in text, text[-600:] if "Traceback" in text else "")
        leftovers = [str(p) for p in APP.rglob("*") if p.is_file() and os.path.exists(str(p) + ":Zone.Identifier")]
        check("downloaded-file marks cleared by the app", not leftovers, f"{len(leftovers)} still marked")


if __name__ == "__main__":
    REAL_MAPPINGS.rename(HIDDEN)  # this PC's own UAssetGUI mappings: a stranger doesn't have them
    try:
        main()
    finally:
        made = REAL_MAPPINGS.exists()
        if made:  # UAssetGUI creates an empty Mappings folder when it starts and finds none
            leftover = list(REAL_MAPPINGS.iterdir())
            if leftover:
                print("WARNING: UAssetGUI wrote into the stand-in Mappings folder:", leftover)
                REAL_MAPPINGS.rename(REAL_MAPPINGS.with_name("Mappings.from-test"))
            else:
                REAL_MAPPINGS.rmdir()
        HIDDEN.rename(REAL_MAPPINGS)
        print("mappings restored:", sorted(p.name for p in REAL_MAPPINGS.iterdir()))
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)
