# Zips a built package for release: one top folder, Unix run permission on the Linux scripts, LF endings checked,
# then re-reads the zip and compares every file with the package. Writes <zip>.sha256 next to it.
# usage: python -I make_zip.py <package dir> <zip path> <top folder name inside the zip> [--skip <path prefix>]...
#   e.g. Windows-only: --skip linux/ --skip instalar-linux.sh --skip desinstalar-linux.sh ; Linux-only: --skip "Instalar dublagem.exe"
import hashlib, os, sys, zipfile

pack, out, top = sys.argv[1], sys.argv[2], sys.argv[3]
skip = [sys.argv[i + 1] for i in range(4, len(sys.argv) - 1) if sys.argv[i] == "--skip"]
EXEC = (".sh", ".py")

def sha(data): return hashlib.sha256(data).hexdigest()

files = []
for root, _, names in os.walk(pack):
    for n in sorted(names):
        p = os.path.join(root, n); files.append((p, os.path.relpath(p, pack).replace("\\", "/")))
files = [f for f in files if not any(f[1].startswith(s) for s in skip)]
files.sort(key=lambda x: x[1])

for p, rel in files:
    if rel.endswith(EXEC) and b"\r\n" in open(p, "rb").read(): sys.exit(f"CRLF line endings in {rel}: fix before zipping")

tmp = out + ".tmp"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
    for p, rel in files:
        zi = zipfile.ZipInfo.from_file(p, top + "/" + rel)
        zi.create_system = 3  # unix, so unzip on Linux honours the permission bits
        zi.external_attr = ((0o100755 if rel.endswith(EXEC) else 0o100644) << 16)
        # audio and patches are already compressed: storing them is as small and much faster to open
        zi.compress_type = zipfile.ZIP_STORED if rel.startswith(("dados/movies/", "dados/br0")) else zipfile.ZIP_DEFLATED
        with open(p, "rb") as src, z.open(zi, "w", force_zip64=True) as dst:
            while True:
                b = src.read(1 << 20)
                if not b: break
                dst.write(b)
        print("  +", rel, flush=True)

# verify: every file in the zip matches the package byte for byte
bad = 0
with zipfile.ZipFile(tmp) as z:
    if z.testzip() is not None: sys.exit("zip CRC check failed")
    names = set(z.namelist())
    for p, rel in files:
        h1 = hashlib.sha256(); h2 = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""): h1.update(b)
        with z.open(top + "/" + rel) as f:
            for b in iter(lambda: f.read(1 << 20), b""): h2.update(b)
        if h1.digest() != h2.digest(): print("MISMATCH", rel); bad += 1
    if len(names) != len(files): print("file count differs", len(names), len(files)); bad += 1
if bad: os.remove(tmp); sys.exit(f"{bad} problem(s): zip not written")
if os.path.exists(out): os.remove(out)
os.replace(tmp, out)
h = hashlib.sha256()
with open(out, "rb") as f:
    for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
open(out + ".sha256", "w", newline="\n").write(f"{h.hexdigest()}  {os.path.basename(out)}\n")
print(f"OK {out}  {os.path.getsize(out) / 1e9:.2f} GB  {len(files)} files  sha256 {h.hexdigest()}")
