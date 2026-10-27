#!/usr/bin/env python3
"""Full Linux test matrix for the installer (the user, 2026-10-26: "Test it thorougly pls. this is going live to ppl").
Runs in WSL (Ubuntu). A fake Steam lives in a throwaway HOME: libraryfolders.vdf -> a library whose
steamapps/common/the witcher 2 is a link to a vanilla game copy, and steamapps/compatdata/20920/pfx/user.reg is a
Proton prefix registry. The real installer (linux/dublagem_linux.py from the package) runs as a player would run it
(--sim answers the Y/n question). Every scenario starts from vanilla (restored from the original movies) and is checked.
usage: python3 matrix_linux.py <package dir> <vanilla game copy> <original movies dir> <out dir>"""
import hashlib, json, os, shutil, signal, subprocess, sys, time

PACK, GAME, ORIG, OUT = sys.argv[1:5]
os.makedirs(OUT, exist_ok=True)
MAN = json.load(open(os.path.join(PACK, "dados", "manifest.json"), encoding="utf-8"))
SCRIPT = os.path.join(PACK, "linux", "dublagem_linux.py")
HOME = "/tmp/w2test_home"; LIB = "/tmp/w2test_lib"; PFX = os.path.join(LIB, "steamapps", "compatdata", "20920", "pfx")
B2 = "\\\\"  # two backslashes, as Wine writes key names
REG0 = ("WINE REGISTRY Version 2\n;; All keys relative to " + B2 + "User" + B2 + "S-1-5-21-0-0-0-1000\n\n#arch=win64\n\n"
        "[Control Panel" + B2 + "Desktop] 1700000000\n#time=1d0000000000000\n\"FontSmoothing\"=\"2\"\n\n"
        "[Software" + B2 + "CD Projekt Red" + B2 + "The Witcher 2] 1700000000\n#time=1da0000000000\n\"Language\"=\"EN\"\n\"Speech\"=\"EN\"\n\n"
        "[Software" + B2 + "Wine] 1700000000\n\"Version\"=\"win10\"\n")
rep, fails, logs = [], [0], open(os.path.join(OUT, "logs_linux.txt"), "w", encoding="utf-8")


def check(ok, what):
    rep.append(f"  {'OK   ' if ok else 'FALHA'}  {what}")
    if not ok: fails[0] += 1


def sha(p):
    if not os.path.exists(p): return "ausente"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()


def mv(n, game=None): return os.path.join(game or GAME, "CookedPC", "movies", n)
def count(key, game=None): return sum(1 for m in MAN["movies"] if sha(mv(m["name"], game)) == m[key])
def small_path(f, game=None): return os.path.join(game or GAME, "CookedPC", *f["path"].split("/"))
ORIG_FILES = "/mnt/d/Witcher2Dub/orig/files"
ORIG_SMALL = {f["path"]: f.get("original_sha256", "ausente") for f in MAN.get("files", [])}


def snapshot(game=None):
    h = {m["name"]: sha(mv(m["name"], game)) for m in MAN["movies"]}
    h["speech"] = sha(os.path.join(game or GAME, "CookedPC", "br0.w2speech")); h.update({f["path"]: sha(small_path(f, game)) for f in MAN.get("files", [])}); return h


def reg():
    t = open(os.path.join(PFX, "user.reg"), encoding="utf-8").read(); key = "[Software" + B2 + "CD Projekt Red" + B2 + "The Witcher 2]"
    if key not in t: return "-/-", t
    sec = t.split(key, 1)[1].split("\n[", 1)[0]
    val = lambda n: (sec.split(f'"{n}"="', 1)[1].split('"', 1)[0]) if f'"{n}"="' in sec else "-"
    return f"{val('Language')}/{val('Speech')}", t


def fake_steam(flatpak=False):
    for d in (HOME, LIB):
        if os.path.islink(d) or os.path.isfile(d): os.remove(d)
        elif os.path.isdir(d): shutil.rmtree(d)
    root = os.path.join(HOME, ".var/app/com.valvesoftware.Steam/.local/share/Steam" if flatpak else ".steam/steam")
    os.makedirs(os.path.join(root, "steamapps"), exist_ok=True); os.makedirs(os.path.join(LIB, "steamapps", "common"), exist_ok=True)
    open(os.path.join(root, "steamapps", "libraryfolders.vdf"), "w").write('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % (root, LIB))
    os.symlink(GAME, os.path.join(LIB, "steamapps", "common", "the witcher 2"))
    os.makedirs(PFX, exist_ok=True); open(os.path.join(PFX, "user.reg"), "w", newline="\n").write(REG0)


def run(*args, script=SCRIPT, timeout=1800):
    env = dict(os.environ, HOME=HOME)
    p = subprocess.run([sys.executable, script] + list(args) + ["--sim"], capture_output=True, text=True, env=env, timeout=timeout)
    out = p.stdout + p.stderr; logs.write(f"===== {cur[0]}: {' '.join(args)} -> exit {p.returncode}\n{out}\n"); logs.flush()
    return p.returncode, out


cur = [""]


def vanilla(game=None):
    g = game or GAME
    for m in MAN["movies"]:
        if sha(mv(m["name"], g)) != m["orig_sha256"]: shutil.copyfile(os.path.join(ORIG, m["name"]), mv(m["name"], g))
    for p in (os.path.join(g, "CookedPC", "br0.w2speech"),):
        if os.path.exists(p): os.remove(p)
    for f in os.listdir(os.path.join(g, "CookedPC", "movies")):
        if f.endswith(".dublagem_tmp"): os.remove(os.path.join(g, "CookedPC", "movies", f))
    if os.path.isdir(os.path.join(g, "dublagem_ptbr_backup")): shutil.rmtree(os.path.join(g, "dublagem_ptbr_backup"))
    for f in MAN.get("files", []):
        p = small_path(f, g)
        if f.get("original_sha256"): os.makedirs(os.path.dirname(p), exist_ok=True); shutil.copyfile(os.path.join(ORIG_FILES, *f["path"].split("/")), p)
        elif os.path.exists(p): os.remove(p)
    open(os.path.join(PFX, "user.reg"), "w", newline="\n").write(REG0)


def is_vanilla(game=None):
    g = game or GAME
    return all(sha(small_path(f, g)) == ORIG_SMALL[f["path"]] for f in MAN.get("files", [])) and count("orig_sha256", g) == len(MAN["movies"]) and not os.path.exists(os.path.join(g, "CookedPC", "br0.w2speech")) and not os.path.exists(os.path.join(g, "dublagem_ptbr_backup"))


def scenario(name):
    cur[0] = name; rep.append(""); rep.append(name); vanilla()
    if not is_vanilla(): check(False, "começou do jogo original")


def flip(p, at):
    b = bytearray(open(p, "rb").read()); b[at] ^= 1; open(p, "wb").write(b); return sha(p)


N = len(MAN["movies"]); small = min(MAN["movies"], key=lambda m: m["orig_bytes"])["name"]; big = max(MAN["movies"], key=lambda m: m["orig_bytes"])["name"]
rep.append(f"Matriz de testes do instalador (Linux, WSL {os.uname().release}) - {time.strftime('%Y-%m-%d %H:%M')} - pacote {MAN['version']}")
fake_steam()

scenario("L1 instalação nova achando o jogo e o Proton sozinho, e desinstalação")
c, o = run("instalar"); check(c == 0, "instalar terminou sem erro")
check("the witcher 2" in o and "compatdata/20920/pfx" in o, "achou o jogo e o prefixo do Proton pela biblioteca da Steam")
check(count("dub_sha256") == N, f"{N} cutscenes exatamente as dubladas")
check(sha(os.path.join(GAME, "CookedPC", "br0.w2speech")) == MAN["speech"]["sha256"], "br0.w2speech confere")
for f in MAN.get("files", []): check(sha(small_path(f)) == f["sha256"], f"arquivo {f['path']}")
lang, text = reg(); check(lang == "BR/BR", f"idioma no user.reg do Proton: {lang}")
check("FontSmoothing" in text and '"Version"="win10"' in text, "o resto do user.reg ficou intacto")
c, o = run("desinstalar"); check(c == 0, "desinstalar terminou sem erro")
check(count("orig_sha256") == N, f"{N} cutscenes exatamente as originais")
for f in MAN.get("files", []): check(sha(small_path(f)) == ORIG_SMALL[f["path"]], f"arquivo {f['path']} como era")
check(reg()[0] == "EN/EN", "idioma de volta EN/EN"); check(not os.path.exists(os.path.join(GAME, "dublagem_ptbr_backup")), "nenhum rastro")

scenario("L2 instalar duas vezes")
run("instalar"); c, o = run("instalar"); check(c == 0, "segunda instalação sem erro"); check(count("dub_sha256") == N, "continua tudo dublado")
run("desinstalar"); check(is_vanilla(), "desinstalar volta ao original sem rastro")

scenario("L3 atualizar por cima da dublagem 1.5.3 (instalador antigo)")
v153 = "/mnt/d/Witcher2Dub/work/movies14_v153"; bk = os.path.join(GAME, "dublagem_ptbr_backup", "movies"); os.makedirs(bk)
for m in MAN["movies"]:
    if os.path.exists(os.path.join(v153, m["name"])): shutil.copyfile(mv(m["name"]), os.path.join(bk, m["name"])); shutil.copyfile(os.path.join(v153, m["name"]), mv(m["name"]))
open(os.path.join(GAME, "dublagem_ptbr_backup", "versao.txt"), "w").write("1.5.3-experimental"); open(os.path.join(GAME, "dublagem_ptbr_backup", "idioma_anterior.txt"), "w").write("EN|EN")
old = sum(1 for m in MAN["movies"] if sha(mv(m["name"])) not in (m["orig_sha256"], m["dub_sha256"])); check(old > 0, f"simulação: {old} cutscenes com a dublagem antiga")
c, o = run("instalar"); check(c == 0, "atualização sem erro"); check(count("dub_sha256") == N, "todas na versão nova"); check("1.5.3-experimental -> agora" in o, "informa a versão anterior")
run("desinstalar"); check(count("orig_sha256") == N, "desinstalar devolve os originais"); check(reg()[0] == "EN/EN", "idioma volta a EN")

scenario("L4 uma cutscene grande alterada por outro mod")
mod = flip(mv(big), -1); c, o = run("instalar"); check(c != 0, "instalação avisa"); check(big in o, f"o aviso cita {big}")
check(sha(mv(big)) == mod, f"{big} ficou como estava"); check(count("dub_sha256") == N - 1, "as outras dubladas")
run("desinstalar"); check(count("orig_sha256") == N - 1, "desinstalar devolve as outras originais"); check(sha(mv(big)) == mod, f"{big} continua como o outro mod deixou")

scenario("L5 a cutscene de conferência alterada (versão diferente do jogo)")
flip(mv(small), 100); before = snapshot(); c, o = run("instalar"); check(c != 0, "recusa"); check("não é a versão esperada" in o, "explica"); check(before == snapshot(), "nada foi alterado")

scenario("L6 jogo aberto")
fake = "/tmp/witcher2.exe"; shutil.copyfile("/bin/sleep", fake); os.chmod(fake, 0o755); gp = subprocess.Popen([fake, "120"]); time.sleep(0.5)
before = snapshot(); c, o = run("instalar"); check(c != 0, "recusa"); check("jogo está aberto" in o, "avisa"); check(before == snapshot(), "nada foi alterado")
gp.kill(); gp.wait(); os.remove(fake)

scenario("L7 sem Proton (prefixo ainda não criado)")
shutil.rmtree(os.path.join(LIB, "steamapps", "compatdata")); before = snapshot(); c, o = run("instalar"); check(c != 0, "recusa")
check("Compatibilidade" in o and "Proton" in o, "explica como ativar o Proton e abrir o jogo uma vez"); check(before == snapshot(), "nada foi alterado")
os.makedirs(PFX, exist_ok=True); open(os.path.join(PFX, "user.reg"), "w", newline="\n").write(REG0)

scenario("L8 user.reg sem a chave do jogo (jogo nunca configurado)")
open(os.path.join(PFX, "user.reg"), "w", newline="\n").write(REG0.split("[Software" + B2 + "CD Projekt Red")[0] + "[Software" + B2 + "Wine] 1700000000\n\"Version\"=\"win10\"\n")
c, o = run("instalar"); lang, text = reg(); check(c == 0 and lang == "BR/BR", f"a chave foi criada: {lang}"); check("FontSmoothing" in text and "win10" in text, "o resto ficou intacto")
run("desinstalar"); check(reg()[0] == "EN/EN", "desinstalar deixa EN")

scenario("L9 instalação interrompida no meio e repetida")
env = dict(os.environ, HOME=HOME); p = subprocess.Popen([sys.executable, SCRIPT, "instalar", "--sim"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
t0 = time.time()
while time.time() - t0 < 300 and count("dub_sha256") < 8: time.sleep(0.5)
p.send_signal(signal.SIGKILL); p.wait()
partial = sum(1 for m in MAN["movies"] if sha(mv(m["name"])) not in (m["orig_sha256"], m["dub_sha256"])); check(partial == 0, "nenhuma cutscene pela metade")
c, o = run("instalar"); check(c == 0 and count("dub_sha256") == N, "repetir termina e dubla tudo")
check(not [f for f in os.listdir(os.path.join(GAME, "CookedPC", "movies")) if f.endswith(".dublagem_tmp")], "nenhum arquivo temporário sobrando")
run("desinstalar"); check(count("orig_sha256") == N, "desinstalar devolve os originais")

scenario("L10 pasta errada e pacote incompleto")
c, o = run("instalar", "--jogo", "/tmp"); check(c != 0, "pasta errada: recusa")
bad = "/tmp/w2test_pacote_incompleto"; shutil.rmtree(bad, ignore_errors=True); shutil.copytree(PACK, bad, ignore=shutil.ignore_patterns("br0.w2speech"))
before = snapshot(); c, o = run("instalar", script=os.path.join(bad, "linux", "dublagem_linux.py")); check(c != 0 and "incompleto" in o, "pacote incompleto: recusa e explica"); check(before == snapshot(), "nada foi alterado")
shutil.rmtree(bad)

scenario("L11 desinstalar sem ter instalado")
before = snapshot(); c, o = run("desinstalar"); check(c == 0, "termina sem erro"); check(before == snapshot(), "nada do jogo mudou")

scenario("L12 outro mod muda uma cutscene depois de instalar")
run("instalar"); mod = flip(mv(big), -1); c, o = run("desinstalar"); check(c != 0 and big in o, f"desinstalar avisa e cita {big}")
check(sha(mv(big)) == mod, f"{big} ficou como o outro mod deixou"); check(count("orig_sha256") == N - 1, "as outras voltaram ao original")

scenario("L13 desinstalar só com a cópia guardada na pasta do jogo (sem o pacote)")
run("instalar"); c, o = run("desinstalar", script=os.path.join(GAME, "dublagem_ptbr_backup", "pacote", "linux", "dublagem_linux.py"))
check(c == 0 and count("orig_sha256") == N, "desinstala pela cópia guardada"); check(not os.path.exists(os.path.join(GAME, "dublagem_ptbr_backup")), "e apaga a própria cópia")

scenario("L14 Steam em Flatpak")
fake_steam(flatpak=True); c, o = run("instalar"); check(c == 0 and count("dub_sha256") == N, "achou o jogo pela Steam em Flatpak e instalou"); run("desinstalar"); check(is_vanilla(), "desinstalou")
fake_steam()

cur[0] = "L15"; rep.append(""); rep.append("L15 nomes de pasta com maiúsculas/minúsculas diferentes (Linux diferencia)")
g2 = "/tmp/w2test_case"; shutil.rmtree(g2, ignore_errors=True); os.makedirs(os.path.join(g2, "cookedpc", "MOVIES"))
open(os.path.join(g2, "cookedpc", "EN0.W2SPEECH"), "w").write("x")
for n in (small, "load_a1_a2_r.usm"): shutil.copyfile(os.path.join(ORIG, n), os.path.join(g2, "cookedpc", "MOVIES", n))
c, o = run("instalar", "--jogo", g2, "--prefixo", PFX)
ok = all(sha(os.path.join(g2, "cookedpc", "MOVIES", n)) == next(m["dub_sha256"] for m in MAN["movies"] if m["name"] == n) for n in (small, "load_a1_a2_r.usm"))
check(ok, "achou CookedPC/movies mesmo com outra caixa e dublou as cutscenes presentes")
check(not os.path.exists(os.path.join(g2, "CookedPC")), "não criou uma segunda pasta CookedPC")
c, o = run("desinstalar", "--jogo", g2, "--prefixo", PFX)
ok = all(sha(os.path.join(g2, "cookedpc", "MOVIES", n)) == next(m["orig_sha256"] for m in MAN["movies"] if m["name"] == n) for n in (small, "load_a1_a2_r.usm"))
check(ok, "desinstalou de volta ao original"); shutil.rmtree(g2)

scenario("L17 jogador com o texto oficial em português da Steam (texto BR antes da dublagem)")
open(os.path.join(PFX, "user.reg"), "w", newline="\n").write(REG0.replace('"Language"="EN"', '"Language"="BR"'))
run("instalar"); check(reg()[0] == "BR/BR", "instalado: BR/BR"); run("desinstalar"); check(reg()[0] == "BR/EN", f"desinstalado: texto continua BR, voz volta a EN: {reg()[0]}")

scenario("L16 a pasta dublagem_ptbr_backup apagada pelo jogador com a dublagem instalada")
run("instalar"); shutil.rmtree(os.path.join(GAME, "dublagem_ptbr_backup")); c, o = run("desinstalar")
check(c != 0 and "Verificar integridade" in o, "desinstalar avisa e indica Verificar integridade")
for f in MAN.get("files", []):
    if f.get("original_sha256"): check(os.path.exists(small_path(f)), f"{f['path']} NÃO foi apagado (o jogo precisa dele)")
check(count("orig_sha256") == N, "as cutscenes voltaram ao original mesmo sem a pasta de backup")

vanilla(); rep.append(""); rep.append("RESULTADO: todos os cenários OK" if fails[0] == 0 else f"RESULTADO: {fails[0]} falha(s)")
rep.append(f"jogo de teste de volta ao original: {is_vanilla()}")
open(os.path.join(OUT, "relatorio_linux.txt"), "w", encoding="utf-8").write("\n".join(rep) + "\n"); print("\n".join(rep))
