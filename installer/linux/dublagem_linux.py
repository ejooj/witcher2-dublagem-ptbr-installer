#!/usr/bin/env python3
"""Dublagem PT-BR de The Witcher 2 - instalador para Linux / Steam Deck (o jogo de Windows rodando pelo Proton).
Mesmo pacote, mesmas regras e mesmos arquivos de estado do instalador de Windows (installer/src/Dublagem.cs):
  - dados/manifest.json (formato 2), dados/br0.w2speech, dados/files/..., dados/movies/<cutscene>.w2mp
  - cada cutscene é o original do jogador + um patch com a nossa faixa em português; o resultado é conferido por SHA-256,
    e a desinstalação desfaz o patch e confere o original de novo
  - <jogo>/dublagem_ptbr_backup: versao.txt, idioma_anterior.txt, files/, pacote/ (o que a desinstalação precisa)
O idioma do jogo (Language = texto, Speech = voz) fica no registro do Windows do Proton: o arquivo user.reg do prefixo
do jogo (<biblioteca>/steamapps/compatdata/20920/pfx/user.reg). O prefixo só existe depois de abrir o jogo uma vez
pelo Proton.
Só a biblioteca padrão do Python 3. Uso:
  python3 dublagem_linux.py instalar|desinstalar [--jogo <pasta>] [--prefixo <pasta pfx>] [--sim]
Saída: 0 = pronto, 1 = erro, 2 = cancelado."""
import hashlib, json, os, re, shutil, struct, subprocess, sys, time

APPID = "20920"; KEY = r"Software\\CD Projekt Red\\The Witcher 2"   # as written in user.reg (backslashes doubled)
HERE = os.path.dirname(os.path.abspath(__file__)); PACK = os.path.dirname(HERE)


class UserError(Exception): pass


# ------------------------------------------------------------------ patches de cutscene (formato W2MP v1)
def chunks(d):
    out, i = [], 0
    while i + 8 <= len(d):
        size = struct.unpack_from(">I", d, i + 4)[0]
        if size == 0 or i + 8 + size > len(d): break
        out.append(i); i += 8 + size
    if i != len(d): raise UserError(f"arquivo de cutscene corrompido (para em {i} de {len(d)} bytes)")
    out.append(i); return out


def read_patch(m):
    if m[:4] != b"W2MP" or struct.unpack_from("<H", m, 4)[0] != 1: raise UserError("patch inválido (não é W2MP v1)")
    i = 6; osz = struct.unpack_from("<Q", m, i)[0]; osha = m[i + 8:i + 40]; i += 40; dsz = struct.unpack_from("<Q", m, i)[0]; dsha = m[i + 8:i + 40]; i += 40
    rec = []
    for _ in range(2):
        n = struct.unpack_from("<I", m, i)[0]; i += 4; ops = []
        for _ in range(n):
            k = m[i]; i += 1
            if k == 0: a, c = struct.unpack_from("<II", m, i); i += 8; ops.append((0, a, c))
            else: L = struct.unpack_from("<I", m, i)[0]; i += 4; ops.append((1, i, L)); i += L
        rec.append(ops)
    if i != len(m): raise UserError("patch com bytes sobrando")
    return {"osz": osz, "osha": osha, "dsz": dsz, "dsha": dsha, "apply": rec[0], "undo": rec[1], "buf": m}


def build(src, ops, buf):
    c = chunks(src); out = bytearray()
    for op in ops:
        if op[0] == 0: out += src[c[op[1]]:c[op[1] + op[2]]]
        else: out += buf[op[1]:op[1] + op[2]]
    return bytes(out)


# ------------------------------------------------------------------ ajudantes
def sha_bytes(b): return hashlib.sha256(b).digest()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()


def ci(base, rel):
    """the path under base whose parts match rel ignoring case (Linux is case-sensitive; the game came from Windows)"""
    p = base
    for part in rel.replace("\\", "/").split("/"):
        exact = os.path.join(p, part)
        if os.path.exists(exact): p = exact; continue
        try: hit = next((x for x in os.listdir(p) if x.lower() == part.lower()), None)
        except FileNotFoundError: hit = None
        p = os.path.join(p, hit if hit else part)
    return p


def is_game(p): return bool(p) and os.path.isfile(ci(p, "CookedPC/en0.w2speech"))


def write_atomic(dst, data):
    tmp = dst + ".dublagem_tmp"
    with open(tmp, "wb") as f: f.write(data)
    os.replace(tmp, dst)


def copy_atomic(src, dst, step):
    tmp = dst + ".dublagem_tmp"
    with open(src, "rb") as i, open(tmp, "wb") as o:
        for b in iter(lambda: i.read(1 << 22), b""): o.write(b); step(len(b))
    os.replace(tmp, dst)


class Bar:
    def __init__(self, total): self.total, self.done, self.last = max(1, total), 0, 0
    def step(self, n, what=""):
        self.done += n; now = time.time()
        if now - self.last > 0.2 or self.done >= self.total:
            self.last = now; p = min(1.0, self.done / self.total); w = 30
            sys.stdout.write(f"\r  [{'#' * int(p * w):<{w}}] {p * 100:5.1f}%  {what[:40]:<40}"); sys.stdout.flush()
    def end(self): sys.stdout.write("\n"); sys.stdout.flush()


# ------------------------------------------------------------------ achar o jogo e o prefixo do Proton
def steam_libraries():
    home = os.path.expanduser("~"); roots = [os.path.join(home, x) for x in (".steam/steam", ".steam/root", ".local/share/Steam", ".var/app/com.valvesoftware.Steam/.local/share/Steam",
                                                                           ".var/app/com.valvesoftware.Steam/.steam/steam")]
    libs = []
    for r in roots:
        if not os.path.isdir(r): continue
        libs.append(r)
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            try: libs += [m.replace("\\\\", "\\") for m in re.findall(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="ignore").read())]
            except OSError: pass
    seen, out = set(), []
    for l in libs:
        k = os.path.realpath(l)
        if k not in seen and os.path.isdir(k): seen.add(k); out.append(k)
    return out


def find_game():
    up = os.path.dirname(PACK)
    if is_game(up): return up, None
    for lib in steam_libraries():
        g = ci(os.path.join(lib, "steamapps", "common"), "the witcher 2")
        if is_game(g): return g, lib
    return None, None


def find_prefix(game, lib):
    libs = ([lib] if lib else []) + steam_libraries()
    # the library holding the game: <lib>/steamapps/common/<game>
    p = os.path.realpath(game)
    if os.path.basename(os.path.dirname(p)).lower() == "common": libs.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(p))))
    for l in libs:
        pfx = os.path.join(l, "steamapps", "compatdata", APPID, "pfx")
        if os.path.isfile(os.path.join(pfx, "user.reg")): return pfx
    return None


def game_running():
    try: return subprocess.run(["pgrep", "-fi", "witcher2.exe"], capture_output=True).returncode == 0
    except FileNotFoundError: return False


# ------------------------------------------------------------------ idioma no user.reg do prefixo (formato do Wine)
def reg_read(path):
    lines = open(path, encoding="utf-8", errors="surrogateescape").read().split("\n")
    head = "[" + KEY.lower() + "]"
    for i, l in enumerate(lines):
        if l.lower().startswith(head):
            j = i + 1; vals = {}
            while j < len(lines) and not lines[j].startswith("["):
                m = re.match(r'"([^"]+)"="(.*)"$', lines[j])
                if m: vals[m.group(1).lower()] = (j, m.group(2))
                j += 1
            return lines, i, j, vals
    return lines, None, None, {}


def reg_set(path, values):
    """sets string values in the game's key of a Wine user.reg; returns the previous values"""
    bak = path + ".dublagem_bak"
    if not os.path.exists(bak): shutil.copy2(path, bak)
    lines, i, j, vals = reg_read(path); prev = {k: vals.get(k.lower(), (None, None))[1] for k in values}
    if i is None:
        while lines and lines[-1] == "": lines.pop()
        ft = int((time.time() + 11644473600) * 10 ** 7)
        lines += ["", f"[{KEY}] {int(time.time())}", f"#time={ft:x}"] + [f'"{k}"="{v}"' for k, v in values.items()] + [""]
    else:
        add = []
        for k, v in values.items():
            if k.lower() in vals: lines[vals[k.lower()][0]] = f'"{k}"="{v}"'
            else: add.append(f'"{k}"="{v}"')
        end = j
        while end > i + 1 and lines[end - 1] == "": end -= 1
        lines[end:end] = add
    tmp = path + ".dublagem_tmp"
    open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="\n").write("\n".join(lines))
    os.replace(tmp, path)
    return prev


# ------------------------------------------------------------------ instalar / desinstalar
class Core:
    def __init__(self, pack, game, prefix):
        self.pack, self.game, self.prefix = pack, game, prefix
        self.man = json.load(open(os.path.join(pack, "dados", "manifest.json"), encoding="utf-8"))
        self.bk = os.path.join(game, "dublagem_ptbr_backup")

    def dados(self, rel): return os.path.join(self.pack, "dados", *rel.split("/"))
    def cooked(self, rel): return ci(self.game, "CookedPC/" + rel)

    def precheck(self):
        """before anything changes: write permission, and the expected copy of the game (one small movie checked)"""
        probe = os.path.join(self.cooked("movies"), ".dublagem_teste_escrita")
        try:
            os.makedirs(os.path.dirname(probe), exist_ok=True); open(probe, "w").write("ok"); os.remove(probe)
        except OSError: raise UserError(f"Sem permissão para alterar a pasta do jogo: {self.game}\nRode o instalador com um usuário que possa escrever nela.")
        ms = sorted(self.man["movies"], key=lambda m: m["orig_bytes"])
        if not ms: return
        m = ms[0]; d = self.cooked("movies/" + m["name"]); old = os.path.join(self.bk, "movies", m["name"])
        known = os.path.isfile(d) and sha_file(d) in (m["orig_sha256"], m["dub_sha256"])
        if not known and not (os.path.isfile(old) and sha_file(old) == m["orig_sha256"]):
            raise UserError(f"Esta cópia do jogo não é a versão esperada (a cutscene {m['name']} é diferente da original da Steam).\nNada foi alterado. "
                            "Se você tem outros mods de cutscene, remova-os; se não, use Steam > The Witcher 2 > Propriedades > Arquivos instalados > Verificar integridade, e tente de novo.")

    def install(self):
        if game_running(): raise UserError("O jogo está aberto. Feche o The Witcher 2 e tente de novo.")
        if not self.prefix: raise UserError("Não achei o prefixo do Proton deste jogo (compatdata/20920). No Steam: The Witcher 2 > Propriedades > Compatibilidade > marque "
                                            "\"Forçar o uso de uma ferramenta de compatibilidade\" (Proton), abra o jogo uma vez até o menu, feche, e rode este instalador de novo.")
        sp = self.man["speech"]; movies = self.man["movies"]; files = self.man.get("files", [])
        self.precheck()
        if not os.path.isfile(self.dados(sp["src"])): raise UserError(f"O pacote está incompleto (falta dados/{sp['src']}). Baixe o pacote de novo.")
        patches = sum(os.path.getsize(self.dados(m["patch"])) for m in movies)
        need = sp["bytes"] + 2 * max([max(m["orig_bytes"], m["dub_bytes"]) for m in movies] or [0]) + patches + (64 << 20)
        free = shutil.disk_usage(self.game).free
        if free < need: raise UserError(f"Espaço insuficiente: precisa de {need / 1e9:.1f} GB livres, tem {free / 1e9:.1f} GB.")
        os.makedirs(self.bk, exist_ok=True)
        bar = Bar(sp["bytes"] + sum(m["dub_bytes"] for m in movies) + patches)
        dst = self.cooked(sp["path"])
        if os.path.isfile(dst) and os.path.getsize(dst) == sp["bytes"] and sha_file(dst) == sp["sha256"]: bar.step(sp["bytes"], "vozes dos diálogos (já instaladas)")
        else: copy_atomic(self.dados(sp["src"]), dst, lambda n: bar.step(n, "vozes dos diálogos"))
        for f in files:
            d = self.cooked(f["path"]); b = os.path.join(self.bk, "files", *f["path"].split("/"))
            if os.path.isfile(d) and not os.path.exists(b) and sha_file(d) != f["sha256"]: os.makedirs(os.path.dirname(b), exist_ok=True); shutil.copy2(d, b)
            os.makedirs(os.path.dirname(d), exist_ok=True); shutil.copy2(self.dados(f["src"]), d)
        problems = []
        for i, m in enumerate(movies, 1):
            name = m["name"]; d = self.cooked("movies/" + name); what = f"cutscene {i}/{len(movies)}"
            p = read_patch(open(self.dados(m["patch"]), "rb").read())
            cur = open(d, "rb").read() if os.path.isfile(d) else None; h = sha_bytes(cur) if cur is not None else None
            if cur is not None and len(cur) == p["dsz"] and h == p["dsha"]: pass
            else:
                if cur is None or len(cur) != p["osz"] or h != p["osha"]:
                    old = os.path.join(self.bk, "movies", name)  # an older install kept the original here
                    if os.path.isfile(old):
                        o = open(old, "rb").read()
                        if len(o) == p["osz"] and sha_bytes(o) == p["osha"]: cur, h = o, p["osha"]
                if cur is None or len(cur) != p["osz"] or h != p["osha"]: problems.append(name)
                else:
                    res = build(cur, p["apply"], p["buf"])
                    if len(res) != p["dsz"] or sha_bytes(res) != p["dsha"]: raise UserError(f"o patch de {name} não deu o resultado esperado; nada desta cutscene foi alterado")
                    write_atomic(d, res)
            bar.step(m["dub_bytes"], what)
        keep = os.path.join(self.bk, "pacote"); os.makedirs(os.path.join(keep, "dados", "movies"), exist_ok=True); os.makedirs(os.path.join(keep, "linux"), exist_ok=True)
        shutil.copy2(os.path.join(self.pack, "dados", "manifest.json"), os.path.join(keep, "dados", "manifest.json"))
        me = os.path.abspath(__file__); me2 = os.path.join(keep, "linux", "dublagem_linux.py")
        if os.path.realpath(me) != os.path.realpath(me2): shutil.copy2(me, me2)
        for m in movies:
            s = self.dados(m["patch"]); t = os.path.join(keep, "dados", *m["patch"].split("/"))
            if os.path.realpath(s) != os.path.realpath(t): shutil.copy2(s, t)
            bar.step(os.path.getsize(s), "guardando os dados para desinstalar")
        bar.end()
        bad = [] if sha_file(dst) == sp["sha256"] else ["br0.w2speech"]
        bad += [f["path"] for f in files if sha_file(self.cooked(f["path"])) != f["sha256"]]
        if bad: raise UserError("Arquivos com problema depois da cópia: " + ", ".join(bad) + ". Rode o instalador de novo.")
        vt = os.path.join(self.bk, "versao.txt"); before = open(vt, encoding="utf-8").read().strip() if os.path.isfile(vt) else None
        open(vt, "w", encoding="utf-8").write(self.man["version"])
        it = os.path.join(self.bk, "idioma_anterior.txt"); prev = reg_set(os.path.join(self.prefix, "user.reg"), {"Language": "BR", "Speech": "BR"})
        if not os.path.exists(it): open(it, "w", encoding="utf-8").write(f"{prev.get('Language') or ''}|{prev.get('Speech') or ''}")
        print(f"  idioma do jogo: voz BR, texto BR (era: texto {prev.get('Language') or '-'}, voz {prev.get('Speech') or '-'})")
        if before and before != self.man["version"]: print(f"  versão anterior: {before} -> agora: {self.man['version']}")
        if not os.path.isfile(self.cooked("br0.w2strings")): print("  Aviso: o texto em português (CookedPC/br0.w2strings) não está instalado. No Steam: The Witcher 2 > Propriedades > Idioma > Português (Brasil).")
        if problems: raise UserError(f"{len(problems)} cutscene(s) não eram as originais do jogo e ficaram sem dublagem: {', '.join(problems)}.\n"
                                     "No Steam: The Witcher 2 > Propriedades > Arquivos instalados > Verificar integridade, e depois instale de novo. O resto da dublagem já está instalado.")

    def uninstall(self):
        if game_running(): raise UserError("O jogo está aberto. Feche o The Witcher 2 e tente de novo.")
        movies = self.man["movies"]; bar = Bar(sum(m["orig_bytes"] for m in movies)); left = []
        for i, m in enumerate(movies, 1):
            name = m["name"]; d = self.cooked("movies/" + name)
            if os.path.isfile(d):
                cur = open(d, "rb").read(); h = sha_bytes(cur); pp = self.dados(m["patch"]); p = read_patch(open(pp, "rb").read()) if os.path.isfile(pp) else None
                if p and len(cur) == p["osz"] and h == p["osha"]: pass
                elif p and len(cur) == p["dsz"] and h == p["dsha"]:
                    res = build(cur, p["undo"], p["buf"])
                    if len(res) != p["osz"] or sha_bytes(res) != p["osha"]: raise UserError(f"desfazer {name} não deu o original; nada desta cutscene foi alterado")
                    write_atomic(d, res)
                else:
                    old = os.path.join(self.bk, "movies", name)
                    if os.path.isfile(old): shutil.copy2(old, d)
                    else: left.append(name)
            bar.step(m["orig_bytes"], f"cutscene {i}/{len(movies)}")
        bar.end()
        no_backup = []
        for f in self.man.get("files", []):
            d = self.cooked(f["path"]); b = os.path.join(self.bk, "files", *f["path"].split("/"))
            if os.path.isfile(b): shutil.copy2(b, d); os.remove(b)
            elif os.path.isfile(d):
                # replaces one of the game's own files: without the backup it is NOT deleted (the game needs it)
                if f.get("original_sha256"):
                    if sha_file(d) != f["original_sha256"]: no_backup.append(f["path"])
                else: os.remove(d)
        s = self.cooked(self.man["speech"]["path"])
        if os.path.isfile(s): os.remove(s)
        vt = os.path.join(self.bk, "versao.txt")
        if os.path.isfile(vt): os.remove(vt)
        t, v = "EN", "EN"; it = os.path.join(self.bk, "idioma_anterior.txt")
        if os.path.isfile(it):
            a = open(it, encoding="utf-8").read().strip().split("|")
            if a and a[0] and (a[0] != "BR" or os.path.isfile(self.cooked("br0.w2strings"))): t = a[0]  # BR text is Steam's official Portuguese
            if len(a) > 1 and a[1] and a[1] != "BR": v = a[1]
            os.remove(it)
        if self.prefix: reg_set(os.path.join(self.prefix, "user.reg"), {"Language": t, "Speech": v}); print(f"  idioma do jogo: voz {v}, texto {t}")
        keep = os.path.join(self.bk, "pacote")
        if os.path.isdir(keep): shutil.rmtree(keep, ignore_errors=True)  # also when running from it: Linux lets a running script delete itself
        for root, dirs, fs in os.walk(self.bk, topdown=False):  # leave no empty folders behind
            if not os.listdir(root):
                try: os.rmdir(root)
                except OSError: pass
        if no_backup: raise UserError(f"Dublagem removida, mas a cópia de segurança de {', '.join(no_backup)} sumiu (a pasta dublagem_ptbr_backup foi apagada?), então esse arquivo ficou como estava. "
                                      "Para o original do jogo: Steam > The Witcher 2 > Propriedades > Arquivos instalados > Verificar integridade." + (f" Também ficaram sem reconhecer: {', '.join(left)}." if left else ""))
        if left: raise UserError(f"Dublagem removida, mas {len(left)} cutscene(s) não foram reconhecidas e ficaram como estavam: {', '.join(left)}. Use Verificar integridade no Steam.")


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("instalar", "desinstalar"): print(__doc__); return 1
    opt = lambda n: a[a.index(n) + 1] if n in a and a.index(n) + 1 < len(a) else None
    try:
        man = json.load(open(os.path.join(PACK, "dados", "manifest.json"), encoding="utf-8"))
    except Exception as e: print(f"Não consegui ler o pacote (dados/manifest.json): {e}"); return 1
    print(f"Dublagem PT-BR de The Witcher 2 - versão {man['version']}\n")
    game, lib = (opt("--jogo"), None) if opt("--jogo") else find_game()
    if not game and PACK.rstrip("/").endswith("dublagem_ptbr_backup/pacote"): game = os.path.dirname(os.path.dirname(PACK))
    if not is_game(game):
        if "--sim" in a: print("Pasta do jogo não encontrada; passe --jogo <pasta>."); return 1
        game = input("Não achei o jogo. Cole o caminho da pasta do The Witcher 2 (a que contém CookedPC): ").strip().strip("'\"")
        if not is_game(game): print("Essa pasta não tem o jogo (falta CookedPC/en0.w2speech)."); return 1
    prefix = opt("--prefixo") or find_prefix(game, lib)
    print(f"Jogo: {game}\nProton: {prefix or '(prefixo não encontrado)'}\n")
    if "--sim" not in a:
        r = input(("Desinstalar" if a[0] == "desinstalar" else "Instalar") + " a dublagem nesta pasta? [S/n] ").strip().lower()
        if r not in ("", "s", "sim", "y", "yes"): print("Cancelado; nada foi alterado."); return 2
    try:
        c = Core(PACK, game, prefix)
        if a[0] == "instalar": c.install(); print("\nPronto! É só abrir o jogo: ele já está com voz e texto em português (BR).")
        else: c.uninstall(); print("\nDublagem removida.")
        return 0
    except UserError as e: print(f"\n{e}"); return 1


if __name__ == "__main__":
    sys.exit(main())
