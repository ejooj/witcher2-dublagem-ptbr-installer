"""Movie patches for the distributable installer (the user, 2026-10-26: "first we must test our patcher tool... make sure
we're patching stuff appropriately"). A patch turns the player's ORIGINAL movie into our dubbed one and back, without
shipping CD Projekt's video: only our chunks travel.

A USM file is a run of chunks (4-byte signature, u32 big-endian size, body). Our dubbed movie is the original's chunks in
the same order, plus inserted channel-14 audio chunks, with two small tables rewritten (CRID index, video seek table).
So a patch is two recipes over chunks:
  apply  dubbed  = [COPY original chunks a..b | LITERAL bytes]...
  undo   original = [COPY dubbed chunks a..b | LITERAL bytes]...   (keeps the original tables verbatim: exact undo)
plus the size and SHA-256 of both files. Apply refuses anything but the expected original; undo refuses anything but
the expected dubbed file; both verify the result before reporting success.

File format (little-endian): b"W2MP" u16 version=1 | orig: u64 size, 32-byte sha256 | dub: u64 size, 32-byte sha256 |
recipe apply | recipe undo. Recipe: u32 op count, then ops: u8 0 = COPY (u32 first chunk, u32 count), u8 1 = LITERAL
(u32 length, bytes).
usage: python -I w2patch.py make  <orig.usm> <dubbed.usm> <out.w2mp>
       python -I w2patch.py apply <orig.usm> <patch.w2mp> <out.usm>
       python -I w2patch.py undo  <dubbed.usm> <patch.w2mp> <out.usm>
       python -I w2patch.py test  <orig dir> <dubbed dir> <patch dir>   (make + apply + undo for every movie, byte-exact)"""
import hashlib, os, struct, sys

MAGIC, VER = b"W2MP", 1


def chunks(data):
    out, i = [], 0
    while i + 8 <= len(data):
        size = struct.unpack(">I", data[i + 4:i + 8])[0]
        if size == 0 or i + 8 + size > len(data): break
        out.append((i, i + 8 + size)); i += 8 + size
    if i != len(data): raise ValueError(f"not a clean chunk stream: stops at {i} of {len(data)} bytes")
    return out


def recipe(src, dst):
    """Ops building dst from src's chunks: dst chunks equal to the next src chunk are copied, a dst chunk that is not in
    src is a literal; a src chunk with no match in dst is skipped (replaced by the literal before it)."""
    cs, cd = chunks(src), chunks(dst); ops = []; p = 0
    for a, b in cd:
        c = dst[a:b]
        # undo direction: our inserted audio chunks in src have no place in dst; step over them
        while p < len(cs) and not is_new_audio(c) and is_new_audio(src[cs[p][0]:cs[p][1]]): p += 1
        if p < len(cs) and src[cs[p][0]:cs[p][1]] == c:
            if ops and ops[-1][0] == 0 and ops[-1][1] + ops[-1][2] == p: ops[-1] = (0, ops[-1][1], ops[-1][2] + 1)
            else: ops.append((0, p, 1))
            p += 1
        else:
            # a changed table replaces the src chunk at p (same signature); anything else is an insertion
            if p < len(cs) and src[cs[p][0]:cs[p][0] + 4] == c[:4] and c[:4] in (b"CRID", b"@SFV", b"@SFA") and not is_new_audio(c): p += 1
            ops.append((1, c))
    if p != len(cs): raise ValueError(f"recipe left {len(cs) - p} source chunks unused")
    return ops


def is_new_audio(c): return c[:4] == b"@SFA" and c[12] == 14


def build(src, ops):
    cs = chunks(src); out = bytearray()
    for op in ops:
        if op[0] == 0: out += src[cs[op[1]][0]:cs[op[1] + op[2] - 1][1]]
        else: out += op[1]
    return bytes(out)


def pack_recipe(ops):
    b = bytearray(struct.pack("<I", len(ops)))
    for op in ops: b += struct.pack("<BII", 0, op[1], op[2]) if op[0] == 0 else struct.pack("<BI", 1, len(op[1])) + op[1]
    return b


def unpack_recipe(m, i):
    n = struct.unpack_from("<I", m, i)[0]; i += 4; ops = []
    for _ in range(n):
        k = m[i]; i += 1
        if k == 0: a, c = struct.unpack_from("<II", m, i); i += 8; ops.append((0, a, c))
        else: L = struct.unpack_from("<I", m, i)[0]; i += 4; ops.append((1, bytes(m[i:i + L]))); i += L
    return ops, i


def make(orig, dub):
    ap, un = recipe(orig, dub), recipe(dub, orig)
    assert build(orig, ap) == dub and build(dub, un) == orig, "recipes do not rebuild the files"
    return (MAGIC + struct.pack("<H", VER) + struct.pack("<Q", len(orig)) + hashlib.sha256(orig).digest() + struct.pack("<Q", len(dub)) + hashlib.sha256(dub).digest()
            + pack_recipe(ap) + pack_recipe(un))


def read_patch(m):
    if m[:4] != MAGIC or struct.unpack_from("<H", m, 4)[0] != VER: raise ValueError("not a W2MP v1 patch")
    i = 6; osz = struct.unpack_from("<Q", m, i)[0]; osha = m[i + 8:i + 40]; i += 40; dsz = struct.unpack_from("<Q", m, i)[0]; dsha = m[i + 8:i + 40]; i += 40
    ap, i = unpack_recipe(m, i); un, i = unpack_recipe(m, i)
    if i != len(m): raise ValueError("trailing bytes in patch")
    return osz, osha, dsz, dsha, ap, un


def apply(orig, m):
    osz, osha, dsz, dsha, ap, _ = read_patch(m)
    if len(orig) == dsz and hashlib.sha256(orig).digest() == dsha: return orig, "already dubbed"
    if len(orig) != osz or hashlib.sha256(orig).digest() != osha: raise ValueError("this is not the original movie the patch expects")
    out = build(orig, ap)
    if len(out) != dsz or hashlib.sha256(out).digest() != dsha: raise ValueError("result does not match the expected dubbed movie")
    return out, "patched"


def undo(dub, m):
    osz, osha, dsz, dsha, _, un = read_patch(m)
    if len(dub) == osz and hashlib.sha256(dub).digest() == osha: return dub, "already original"
    if len(dub) != dsz or hashlib.sha256(dub).digest() != dsha: raise ValueError("this is not the dubbed movie the patch expects")
    out = build(dub, un)
    if len(out) != osz or hashlib.sha256(out).digest() != osha: raise ValueError("result does not match the original movie")
    return out, "restored"


def rd(p): return open(p, "rb").read()


def main():
    a = sys.argv[1:]
    if a[0] == "make": open(a[3], "wb").write(make(rd(a[1]), rd(a[2])))
    elif a[0] in ("apply", "undo"):
        out, what = (apply if a[0] == "apply" else undo)(rd(a[1]), rd(a[2])); open(a[3], "wb").write(out); print(what)
    elif a[0] == "test":
        od, dd, pd = a[1:4]; os.makedirs(pd, exist_ok=True); tot_p = tot_m = 0; bad = 0
        for n in sorted(f for f in os.listdir(od) if f.lower().endswith(".usm")):
            o, d = rd(os.path.join(od, n)), rd(os.path.join(dd, n)) if os.path.exists(os.path.join(dd, n)) else None
            if d is None: print(f"{n}: no dubbed movie"); continue
            try:
                m = make(o, d); open(os.path.join(pd, n[:-4] + ".w2mp"), "wb").write(m)
                r1, w1 = apply(o, m); r2, w2 = undo(d, m)
                ok = (r1 == d and r2 == o and w1 == "patched" and w2 == "restored")
                # refusals: the patch must reject an already-dubbed file politely and a foreign file outright
                r3, w3 = apply(d, m); ok &= (w3 == "already dubbed" and r3 == d)
                try: apply(o[:-1] + bytes([o[-1] ^ 1]), m); ok = False
                except ValueError: pass
                tot_p += len(m); tot_m += len(o); bad += not ok
                print(f"{n}: {'OK' if ok else 'FAIL'}  patch {len(m) / 1e6:6.1f} MB  movie {len(o) / 1e6:7.1f} MB", flush=True)
            except Exception as e: bad += 1; print(f"{n}: FAIL {e}", flush=True)
        print(f"{'ALL OK' if not bad else f'{bad} FAILED'}: patches {tot_p / 1e6:.0f} MB for {tot_m / 1e9:.2f} GB of movies")


if __name__ == "__main__":
    main()
