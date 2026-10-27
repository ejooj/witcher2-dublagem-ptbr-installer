"""Builds the distributable package (format 2: movie PATCHES instead of whole movies; Windows + Linux installers).
The user, 2026-10-26: "Ok, so we need a installer that works fine on linux and windows" / "build with linux in mind".

From a full release folder (release\\Witcher2_Dublagem_PTBR_v<ver>, the one the old installer ships) and the original
movies (orig\\movies), it writes release\\Witcher2_Dublagem_PTBR_v<ver>-pacote\\:
  Instalar dublagem.exe        Windows installer (installer\\src\\Dublagem.cs, compiled with the csc.exe of .NET 4.8)
  instalar-linux.sh            Linux / Steam Deck (Proton) launcher -> linux\\dublagem_linux.py
  desinstalar-linux.sh
  LEIA-ME.txt
  dados\\manifest.json          format 2 (below)
  dados\\br0.w2speech           our speech file (entirely ours)
  dados\\files\\<path>           the small loose files
  dados\\movies\\<movie>.w2mp    one patch per movie (tools\\w2patch.py format: our channel-14 audio + 2 small tables)
  linux\\dublagem_linux.py
manifest format 2:
  {"format": 2, "version", "speech": {path, src, bytes, sha256}, "files": [{path, src, bytes, sha256}],
   "movies": [{name, patch, orig_bytes, orig_sha256, dub_bytes, dub_sha256}], "steam_appid": 20920, "gog_id": "1207658930"}
Every patch is re-checked (apply + undo byte-exact) while building.
usage: python -I build_pack.py <version>       e.g. 1.5.4-experimental"""
import hashlib, json, os, shutil, struct, subprocess, sys
H = os.path.dirname(os.path.abspath(__file__)); W = os.path.dirname(H)
sys.path.insert(0, os.path.join(W, "tools")); import w2patch
CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()


def main():
    ver = sys.argv[1]; REL = os.path.join(W, "release", "Witcher2_Dublagem_PTBR_v" + ver); OUT = REL + "-pacote"; ORIG = os.path.join(W, "orig", "movies")
    old = json.load(open(os.path.join(REL, "manifest.json"), encoding="utf-8"))
    if os.path.exists(OUT): shutil.rmtree(OUT)
    D = os.path.join(OUT, "dados"); os.makedirs(os.path.join(D, "movies")); os.makedirs(os.path.join(OUT, "linux"))
    man = {"format": 2, "version": ver, "game": "The Witcher 2: Assassins of Kings", "steam_appid": 20920, "gog_id": "1207658930"}
    sp = os.path.join(REL, "CookedPC", "br0.w2speech"); shutil.copy2(sp, os.path.join(D, "br0.w2speech"))
    man["speech"] = {"path": "br0.w2speech", "src": "br0.w2speech", "bytes": os.path.getsize(sp), "sha256": sha(sp)}
    man["files"] = []
    for f in old.get("files", []):
        src = os.path.join(REL, "CookedPC", *f["path"].split("/")); dst = os.path.join(D, "files", *f["path"].split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(src, dst)
        e = {"path": f["path"], "src": "files/" + f["path"], "bytes": os.path.getsize(src), "sha256": sha(src)}
        o = os.path.join(W, "orig", "files", *f["path"].split("/"))  # the game's own file (when it has one), for uninstall safety
        if os.path.exists(o): e["original_sha256"] = sha(o)
        man["files"].append(e)
    man["movies"] = []
    for m in old["movies"]:
        n = m["name"]; o = open(os.path.join(ORIG, n), "rb").read(); d = open(os.path.join(REL, "CookedPC", "movies", n), "rb").read()
        p = w2patch.make(o, d)
        r1, w1 = w2patch.apply(o, p); r2, w2 = w2patch.undo(d, p)
        assert r1 == d and r2 == o and w1 == "patched" and w2 == "restored", n
        open(os.path.join(D, "movies", n[:-4] + ".w2mp"), "wb").write(p)
        man["movies"].append({"name": n, "patch": "movies/" + n[:-4] + ".w2mp", "orig_bytes": len(o), "orig_sha256": hashlib.sha256(o).hexdigest(),
                              "dub_bytes": len(d), "dub_sha256": hashlib.sha256(d).hexdigest()})
        print(n, "patch ok", flush=True)
    json.dump(man, open(os.path.join(D, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # Windows installer
    exe = os.path.join(OUT, "Instalar dublagem.exe")
    r = subprocess.run([CSC, "/nologo", "/codepage:65001", "/target:winexe", "/optimize+", "/out:" + exe, "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/r:System.Web.Extensions.dll",
                        "/win32manifest:" + os.path.join(H, "src", "app.manifest"), os.path.join(H, "src", "Dublagem.cs")], capture_output=True, text=True)
    if r.returncode: print(r.stdout, r.stderr); raise SystemExit("C# build failed")
    # Linux installer
    shutil.copy2(os.path.join(H, "linux", "dublagem_linux.py"), os.path.join(OUT, "linux", "dublagem_linux.py"))
    for name in ("instalar-linux.sh", "desinstalar-linux.sh"):
        open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n").write(open(os.path.join(H, "linux", name), encoding="utf-8").read())
    shutil.copy2(os.path.join(H, "LEIA-ME.txt"), os.path.join(OUT, "LEIA-ME.txt"))
    size = sum(os.path.getsize(os.path.join(a, f)) for a, _, fs in os.walk(OUT) for f in fs)
    print(f"package: {OUT} ({size / 1e9:.2f} GB, {len(man['movies'])} movie patches)")


if __name__ == "__main__":
    main()
