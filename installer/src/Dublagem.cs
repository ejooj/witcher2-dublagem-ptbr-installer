// Dublagem PT-BR de The Witcher 2 - instalador para Windows (formato de pacote 2: patches de cutscene).
// Lê dados\manifest.json ao lado do .exe (ver installer\build_pack.py). As cutscenes NÃO vêm no pacote: cada uma é o
// original do jogador + um patch (.w2mp) com a nossa faixa em português; o resultado é conferido por SHA-256, e a
// desinstalação desfaz o patch e confere o original de novo. Mesmo formato e mesmas regras do instalador Linux
// (installer\linux\dublagem_linux.py) e do protótipo tools\w2patch.py.
// Compatível com instalações antigas (1.x): usa dublagem_ptbr_backup\versao.txt, idioma_anterior.txt, files\ e, se uma
// cutscene estiver com uma dublagem antiga, o original guardado em dublagem_ptbr_backup\movies.
// Linha de comando (testes): --instalar | --desinstalar  [--jogo <pasta>] [--sem-perguntar] [--log <arquivo>]
//   --demo [--demo-escolher <pasta>] [--log <arquivo>]: a janela normal aperta Instalar (ou Desinstalar, com --desinstalar) sozinha (testes gravados)
//                            [--registro <chave em HKCU>]   (o padrão é Software\CD Projekt Red\The Witcher 2)
// Saída: 0 = pronto, 1 = erro, 2 = cancelado.
// Compilado com o csc.exe do .NET Framework 4.8 (C# 5): sem interpolação de strings nem operadores ?. ou ??=.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

namespace Dublagem
{
    // ---------------------------------------------------------------- patches de cutscene (formato W2MP v1)
    class Op { public int Kind; public int First, Count; public int LitOffset, LitLength; }

    class MoviePatch
    {
        public long OrigSize, DubSize; public byte[] OrigSha, DubSha; public List<Op> Apply, Undo; public byte[] Buf;

        public static MoviePatch Read(byte[] m)
        {
            if (m.Length < 86 || m[0] != (byte)'W' || m[1] != (byte)'2' || m[2] != (byte)'M' || m[3] != (byte)'P' || BitConverter.ToUInt16(m, 4) != 1)
                throw new Exception("patch inválido (não é W2MP v1)");
            var p = new MoviePatch(); p.Buf = m; int i = 6;
            p.OrigSize = BitConverter.ToInt64(m, i); p.OrigSha = Sub(m, i + 8, 32); i += 40;
            p.DubSize = BitConverter.ToInt64(m, i); p.DubSha = Sub(m, i + 8, 32); i += 40;
            p.Apply = Recipe(m, ref i); p.Undo = Recipe(m, ref i);
            if (i != m.Length) throw new Exception("patch com bytes sobrando");
            return p;
        }

        static List<Op> Recipe(byte[] m, ref int i)
        {
            int n = (int)BitConverter.ToUInt32(m, i); i += 4; var ops = new List<Op>(n);
            for (int k = 0; k < n; k++)
            {
                var op = new Op(); op.Kind = m[i]; i += 1;
                if (op.Kind == 0) { op.First = (int)BitConverter.ToUInt32(m, i); op.Count = (int)BitConverter.ToUInt32(m, i + 4); i += 8; }
                else { op.LitLength = (int)BitConverter.ToUInt32(m, i); i += 4; op.LitOffset = i; i += op.LitLength; }
                ops.Add(op);
            }
            return ops;
        }

        static byte[] Sub(byte[] a, int o, int n) { var r = new byte[n]; Buffer.BlockCopy(a, o, r, 0, n); return r; }

        // offsets of the chunks of a USM file: 4-byte signature, u32 big-endian size, body
        public static List<long> Chunks(byte[] d)
        {
            var o = new List<long>(); long i = 0;
            while (i + 8 <= d.Length)
            {
                long size = ((long)d[i + 4] << 24) | ((long)d[i + 5] << 16) | ((long)d[i + 6] << 8) | d[i + 7];
                if (size == 0 || i + 8 + size > d.Length) break;
                o.Add(i); i += 8 + size;
            }
            if (i != d.Length) throw new Exception("arquivo de cutscene corrompido (para em " + i + " de " + d.Length + " bytes)");
            o.Add(i);  // end
            return o;
        }

        public byte[] Build(byte[] src, List<Op> ops)
        {
            var c = Chunks(src); long total = 0;
            foreach (var op in ops) total += op.Kind == 0 ? c[op.First + op.Count] - c[op.First] : op.LitLength;
            var outb = new byte[total]; long w = 0;
            foreach (var op in ops)
            {
                if (op.Kind == 0) { long a = c[op.First], b = c[op.First + op.Count]; Buffer.BlockCopy(src, (int)a, outb, (int)w, (int)(b - a)); w += b - a; }
                else { Buffer.BlockCopy(Buf, op.LitOffset, outb, (int)w, op.LitLength); w += op.LitLength; }
            }
            return outb;
        }
    }

    // ---------------------------------------------------------------- instalação / desinstalação
    class Core
    {
        public string Pack, Game, RegPath = @"Software\CD Projekt Red\The Witcher 2"; public Dictionary<string, object> Man;
        public Action<string> Log = delegate { }; public Action<double, string> Progress = delegate { };
        public string Leftover;  // after uninstall: the folder this program could not delete because it runs from it
        long done, total;
        const string UninstKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\DublagemPTBR_Witcher2";

        public Core(string pack)
        {
            Pack = pack;
            Man = (Dictionary<string, object>)new JavaScriptSerializer { MaxJsonLength = int.MaxValue }.DeserializeObject(File.ReadAllText(Path.Combine(pack, "dados", "manifest.json"), Encoding.UTF8));
        }

        public string Version { get { return (string)Man["version"]; } }
        IEnumerable<Dictionary<string, object>> List(string k) { object v; if (!Man.TryGetValue(k, out v) || v == null) return new Dictionary<string, object>[0]; return ((object[])v).Cast<Dictionary<string, object>>(); }
        Dictionary<string, object> Obj(string k) { return (Dictionary<string, object>)Man[k]; }
        static long L(Dictionary<string, object> d, string k) { return Convert.ToInt64(d[k]); }
        static string S(Dictionary<string, object> d, string k) { return (string)d[k]; }

        string Bk { get { return Path.Combine(Game, "dublagem_ptbr_backup"); } }
        string Cooked(string rel) { return Path.Combine(Game, "CookedPC", rel.Replace('/', '\\')); }
        string Dados(string rel) { return Path.Combine(Pack, "dados", rel.Replace('/', '\\')); }

        public static bool IsGame(string p) { return !string.IsNullOrEmpty(p) && File.Exists(Path.Combine(p, "CookedPC", "en0.w2speech")); }

        public static string FindGame(string pack)
        {
            try { var up = Path.GetDirectoryName(pack); if (IsGame(up)) return up; var up2 = Path.GetDirectoryName(up); if (IsGame(up2)) return up2; } catch { }
            var libs = new List<string>();
            try
            {
                using (var k = Registry.CurrentUser.OpenSubKey(@"Software\Valve\Steam"))
                {
                    var steam = k == null ? null : k.GetValue("SteamPath") as string;
                    if (steam != null)
                    {
                        libs.Add(steam.Replace('/', '\\'));
                        var vdf = Path.Combine(steam, "steamapps", "libraryfolders.vdf");
                        if (File.Exists(vdf)) foreach (Match mt in Regex.Matches(File.ReadAllText(vdf), "\"path\"\\s+\"([^\"]+)\"")) libs.Add(mt.Groups[1].Value.Replace("\\\\", "\\"));
                    }
                }
            }
            catch { }
            foreach (var l in libs) { var p = Path.Combine(l, "steamapps", "common", "the witcher 2"); if (IsGame(p)) return p; }
            foreach (var key in new[] { @"SOFTWARE\WOW6432Node\GOG.com\Games\1207658930", @"SOFTWARE\GOG.com\Games\1207658930" })
                try { using (var k = Registry.LocalMachine.OpenSubKey(key)) { var p = k == null ? null : k.GetValue("path") as string; if (IsGame(p)) return p; } } catch { }
            return null;
        }

        static string Hex(byte[] h) { var sb = new StringBuilder(); foreach (var b in h) sb.Append(b.ToString("x2")); return sb.ToString(); }
        static byte[] Sha(byte[] d) { using (var s = SHA256.Create()) return s.ComputeHash(d); }
        static string ShaFile(string p) { using (var s = SHA256.Create()) using (var f = File.OpenRead(p)) return Hex(s.ComputeHash(f)); }
        static bool Eq(byte[] a, byte[] b) { if (a.Length != b.Length) return false; for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false; return true; }

        void Step(long n, string what) { done += n; Progress(total > 0 ? Math.Min(1.0, (double)done / total) : 0, what); }

        void CopyWithProgress(string src, string dst, string what)
        {
            var tmp = dst + ".dublagem_tmp";
            using (var i = File.OpenRead(src)) using (var o = File.Create(tmp))
            {
                var buf = new byte[1 << 22]; int n;
                while ((n = i.Read(buf, 0, buf.Length)) > 0) { o.Write(buf, 0, n); Step(n, what); }
            }
            if (File.Exists(dst)) File.Delete(dst);
            File.Move(tmp, dst);
        }

        static void WriteAtomic(string dst, byte[] data) { var tmp = dst + ".dublagem_tmp"; File.WriteAllBytes(tmp, data); if (File.Exists(dst)) File.Delete(dst); File.Move(tmp, dst); }

        public void CheckGameClosed() { if (Process.GetProcessesByName("witcher2").Length > 0) throw new UserError("O jogo está aberto. Feche o The Witcher 2 e tente de novo."); }

        // ---- checks before anything changes (the user, 2026-10-26)
        void PreCheck()
        {
            // write permission: a game under Program Files needs "Executar como administrador"
            var probe = Path.Combine(Game, "CookedPC", "movies", ".dublagem_teste_escrita");
            try { Directory.CreateDirectory(Path.GetDirectoryName(probe)); File.WriteAllText(probe, "ok"); File.Delete(probe); }
            catch (Exception) { throw new UserError("Sem permissão para alterar a pasta do jogo:\n" + Game + "\n\nFeche esta janela, clique com o botão direito no instalador e escolha \"Executar como administrador\"."); }
            // the expected copy of the game: one small movie must be the original, our dub, or have the original in an older backup
            var m = List("movies").OrderBy(x => L(x, "orig_bytes")).FirstOrDefault(); if (m == null) return;
            var dst = Cooked("movies/" + S(m, "name")); var old = Path.Combine(Bk, "movies", S(m, "name"));
            Func<string, bool> known = f => File.Exists(f) && (ShaFile(f) == S(m, "orig_sha256") || ShaFile(f) == S(m, "dub_sha256"));
            if (!known(dst) && !(File.Exists(old) && ShaFile(old) == S(m, "orig_sha256")))
                throw new UserError("Esta cópia do jogo não é a versão esperada (a cutscene " + S(m, "name") + " é diferente da original da Steam).\n\nNada foi alterado. Se você tem outros mods de cutscene, remova-os; se não, use Steam > The Witcher 2 > Propriedades > Arquivos instalados > Verificar integridade, e tente de novo.");
        }

        // ---- instalar
        public void Install()
        {
            CheckGameClosed(); PreCheck();
            var speech = Obj("speech"); var movies = List("movies").ToList(); var files = List("files").ToList();
            if (!File.Exists(Dados(S(speech, "src")))) throw new UserError("O pacote está incompleto (falta dados\\" + S(speech, "src") + "). Baixe o pacote de novo.");
            long maxMovie = movies.Count == 0 ? 0 : movies.Max(m => Math.Max(L(m, "orig_bytes"), L(m, "dub_bytes")));
            long patches = movies.Sum(m => new FileInfo(Dados(S(m, "patch"))).Length);
            long need = L(speech, "bytes") + 2 * maxMovie + patches + (64L << 20);
            var free = new DriveInfo(Path.GetPathRoot(Game)).AvailableFreeSpace;
            if (free < need) throw new UserError(string.Format("Espaço insuficiente no disco {0}: precisa de {1:N1} GB livres, tem {2:N1} GB.", Path.GetPathRoot(Game), need / 1e9, free / 1e9));
            done = 0; total = L(speech, "bytes") + movies.Sum(m => L(m, "dub_bytes")) + patches;
            Directory.CreateDirectory(Bk);

            Log("Vozes dos diálogos (br0.w2speech)...");
            var spDst = Cooked(S(speech, "path"));
            if (File.Exists(spDst) && new FileInfo(spDst).Length == L(speech, "bytes") && ShaFile(spDst) == S(speech, "sha256")) Step(L(speech, "bytes"), "vozes dos diálogos (já instaladas)");
            else CopyWithProgress(Dados(S(speech, "src")), spDst, "vozes dos diálogos");

            foreach (var f in files)
            {
                var dst = Cooked(S(f, "path")); var bk = Path.Combine(Bk, "files", S(f, "path").Replace('/', '\\'));
                if (File.Exists(dst) && !File.Exists(bk) && ShaFile(dst) != S(f, "sha256")) { Directory.CreateDirectory(Path.GetDirectoryName(bk)); File.Copy(dst, bk); }
                Directory.CreateDirectory(Path.GetDirectoryName(dst)); File.Copy(Dados(S(f, "src")), dst, true);
                Log("  arquivo: " + S(f, "path"));
            }

            var problems = new List<string>(); int idx = 0;
            foreach (var m in movies)
            {
                idx++; var name = S(m, "name"); var dst = Cooked("movies/" + name); var what = string.Format("cutscene {0} de {1}: {2}", idx, movies.Count, name);
                Progress((double)done / total, what);
                var patch = MoviePatch.Read(File.ReadAllBytes(Dados(S(m, "patch"))));
                byte[] cur = File.Exists(dst) ? File.ReadAllBytes(dst) : null; byte[] h = cur == null ? null : Sha(cur);
                if (h != null && cur.LongLength == patch.DubSize && Eq(h, patch.DubSha)) { Log("  " + name + ": já dublada"); }
                else
                {
                    if (h == null || cur.LongLength != patch.OrigSize || !Eq(h, patch.OrigSha))
                    {
                        // a dub from an older version (or no file): the old installer kept the original here
                        var old = Path.Combine(Bk, "movies", name);
                        if (File.Exists(old)) { var o = File.ReadAllBytes(old); if (o.LongLength == patch.OrigSize && Eq(Sha(o), patch.OrigSha)) { cur = o; h = patch.OrigSha; } }
                    }
                    if (cur == null || cur.LongLength != patch.OrigSize || !Eq(h, patch.OrigSha)) { problems.Add(name); Log("  " + name + ": NÃO é a cutscene original do jogo; deixada como está"); }
                    else
                    {
                        var res = patch.Build(cur, patch.Apply);
                        if (res.LongLength != patch.DubSize || !Eq(Sha(res), patch.DubSha)) throw new Exception("o patch de " + name + " não deu o resultado esperado; nada desta cutscene foi alterado");
                        WriteAtomic(dst, res); Log("  " + name + ": dublada");
                    }
                }
                Step(L(m, "dub_bytes"), what);
            }

            // a copy of what uninstalling needs (this .exe, the manifest and the movie patches) inside the game folder
            var keep = Path.Combine(Bk, "pacote"); Directory.CreateDirectory(Path.Combine(keep, "dados", "movies"));
            var me = Application.ExecutablePath; var meDst = Path.Combine(keep, "Desinstalar dublagem.exe");
            if (!string.Equals(Path.GetFullPath(me), Path.GetFullPath(meDst), StringComparison.OrdinalIgnoreCase)) File.Copy(me, meDst, true);
            File.Copy(Path.Combine(Pack, "dados", "manifest.json"), Path.Combine(keep, "dados", "manifest.json"), true);
            foreach (var m in movies)
            {
                var src = Dados(S(m, "patch")); var d2 = Path.Combine(keep, "dados", S(m, "patch").Replace('/', '\\'));
                if (!string.Equals(Path.GetFullPath(src), Path.GetFullPath(d2), StringComparison.OrdinalIgnoreCase)) File.Copy(src, d2, true);
                Step(new FileInfo(src).Length, "guardando os dados para desinstalar");
            }

            Log("Conferindo os arquivos instalados...");
            var bad = new List<string>();
            if (ShaFile(spDst) != S(speech, "sha256")) bad.Add("br0.w2speech");
            foreach (var f in files) if (ShaFile(Cooked(S(f, "path"))) != S(f, "sha256")) bad.Add(S(f, "path"));
            if (bad.Count > 0) throw new UserError("Arquivos com problema depois da cópia: " + string.Join(", ", bad) + ". Rode o instalador de novo.");

            var vt = Path.Combine(Bk, "versao.txt"); var antes = File.Exists(vt) ? File.ReadAllText(vt).Trim() : null;
            File.WriteAllText(vt, Version, new UTF8Encoding(false));
            SetLanguage();
            Register(meDst);
            if (antes != null && antes != Version) Log("Versão anterior: " + antes + " -> agora: " + Version);
            if (!File.Exists(Cooked("br0.w2strings"))) Log("Aviso: o texto em português (CookedPC\\br0.w2strings) não está instalado. No Steam: The Witcher 2 > Propriedades > Idioma > Português (Brasil).");
            if (problems.Count > 0)
                throw new UserError(problems.Count + " cutscene(s) não eram as originais do jogo e ficaram sem dublagem: " + string.Join(", ", problems) +
                    ".\nNo Steam: The Witcher 2 > Propriedades > Arquivos instalados > Verificar integridade, e depois instale de novo. O resto da dublagem já está instalado.");
            Progress(1, "pronto");
        }

        // ---- desinstalar
        public void Uninstall()
        {
            CheckGameClosed();
            var movies = List("movies").ToList(); done = 0; total = movies.Sum(m => L(m, "orig_bytes")); var left = new List<string>(); int idx = 0;
            foreach (var m in movies)
            {
                idx++; var name = S(m, "name"); var dst = Cooked("movies/" + name); var what = string.Format("cutscene {0} de {1}: {2}", idx, movies.Count, name);
                Progress((double)done / Math.Max(1, total), what);
                if (File.Exists(dst))
                {
                    var cur = File.ReadAllBytes(dst); var h = Sha(cur); var pp = Dados(S(m, "patch"));
                    var patch = File.Exists(pp) ? MoviePatch.Read(File.ReadAllBytes(pp)) : null;
                    if (patch != null && cur.LongLength == patch.OrigSize && Eq(h, patch.OrigSha)) Log("  " + name + ": já original");
                    else if (patch != null && cur.LongLength == patch.DubSize && Eq(h, patch.DubSha))
                    {
                        var res = patch.Build(cur, patch.Undo);
                        if (res.LongLength != patch.OrigSize || !Eq(Sha(res), patch.OrigSha)) throw new Exception("desfazer " + name + " não deu o original; nada desta cutscene foi alterado");
                        WriteAtomic(dst, res); Log("  " + name + ": original de volta");
                    }
                    else
                    {
                        var old = Path.Combine(Bk, "movies", name);
                        if (File.Exists(old)) { File.Copy(old, dst, true); Log("  " + name + ": original de volta (cópia antiga)"); }
                        else { left.Add(name); Log("  " + name + ": não reconhecida; deixada como está"); }
                    }
                }
                Step(L(m, "orig_bytes"), what);
            }
            var noBackup = new List<string>();
            foreach (var f in List("files"))
            {
                var dst = Cooked(S(f, "path")); var bk = Path.Combine(Bk, "files", S(f, "path").Replace('/', '\\'));
                if (File.Exists(bk)) { File.Copy(bk, dst, true); File.Delete(bk); }
                else if (File.Exists(dst))
                {
                    // this file replaces one of the game's own: without the backup it cannot be put back, so it is NOT deleted
                    // (the game needs it); Steam's "Verificar integridade" restores the original (2026-10-26 test W13)
                    if (f.ContainsKey("original_sha256")) { if (ShaFile(dst) != S(f, "original_sha256")) noBackup.Add(S(f, "path")); }
                    else File.Delete(dst);
                }
            }
            var sp = Cooked(S(Obj("speech"), "path")); if (File.Exists(sp)) File.Delete(sp);
            var vt = Path.Combine(Bk, "versao.txt"); if (File.Exists(vt)) File.Delete(vt);
            RestoreLanguage();
            try { Registry.CurrentUser.DeleteSubKeyTree(UninstKey, false); } catch { }
            // leave no trace: the kept copy and empty folders. When this program runs from the kept copy (Apps > Desinstalar),
            // Windows does not let it delete its own folder; it says so and the player deletes it (no hidden helper process:
            // that pattern looks like malware to antivirus and to Nexus Mods' review, 2026-10-26)
            var keep = Path.Combine(Bk, "pacote"); Leftover = null;
            bool fromKeep = Application.ExecutablePath.StartsWith(keep + "\\", StringComparison.OrdinalIgnoreCase);
            if (Directory.Exists(keep) && !fromKeep) try { Directory.Delete(keep, true); } catch { }
            RemoveEmptyDirs(Path.Combine(Bk, "files")); RemoveEmptyDirs(Bk);
            if (Directory.Exists(Bk)) Leftover = Bk;
            Progress(1, "pronto");
            if (noBackup.Count > 0) throw new UserError("Dublagem removida, mas a cópia de segurança de " + string.Join(", ", noBackup) + " sumiu (a pasta dublagem_ptbr_backup foi apagada?), então esse arquivo ficou como estava. Para o original do jogo: Steam > The Witcher 2 > Propriedades > Arquivos instalados > Verificar integridade." + (left.Count > 0 ? " Também ficaram sem reconhecer: " + string.Join(", ", left) + "." : ""));
            if (left.Count > 0) throw new UserError("Dublagem removida, mas " + left.Count + " cutscene(s) não foram reconhecidas e ficaram como estavam: " + string.Join(", ", left) + ". Use Verificar integridade no Steam.");
        }

        static void RemoveEmptyDirs(string d)
        {
            if (!Directory.Exists(d)) return;
            foreach (var sub in Directory.GetDirectories(d)) RemoveEmptyDirs(sub);
            try { if (Directory.GetFileSystemEntries(d).Length == 0) Directory.Delete(d); } catch { }
        }

        // ---- idioma do jogo (o mesmo que o Configurador grava: Language = texto, Speech = voz)
        void SetLanguage()
        {
            var txt = Path.Combine(Bk, "idioma_anterior.txt");
            using (var k = Registry.CurrentUser.CreateSubKey(RegPath))
            {
                var t = k.GetValue("Language") as string; var v = k.GetValue("Speech") as string;
                if (!File.Exists(txt)) File.WriteAllText(txt, (t ?? "") + "|" + (v ?? ""), new UTF8Encoding(false));
                k.SetValue("Language", "BR"); k.SetValue("Speech", "BR");
                Log("Idioma do jogo: voz BR, texto BR (era: texto " + (t ?? "-") + ", voz " + (v ?? "-") + ")");
            }
        }

        void RestoreLanguage()
        {
            string t = "EN", v = "EN"; var txt = Path.Combine(Bk, "idioma_anterior.txt");
            if (File.Exists(txt))
            {
                var a = File.ReadAllText(txt).Trim().Split('|');
                // text BR is Steam's official Portuguese (br0.w2strings): kept when that file is there; only the BR voice is ours
                if (a.Length > 0 && a[0] != "" && (a[0] != "BR" || File.Exists(Cooked("br0.w2strings")))) t = a[0];
                if (a.Length > 1 && a[1] != "" && a[1] != "BR") v = a[1];
                File.Delete(txt);
            }
            using (var k = Registry.CurrentUser.OpenSubKey(RegPath, true)) if (k != null) { k.SetValue("Language", t); k.SetValue("Speech", v); }
            Log("Idioma do jogo: voz " + v + ", texto " + t);
        }

        void Register(string exe)
        {
            if (RegPath != @"Software\CD Projekt Red\The Witcher 2") return;  // tests with another key: no entry in Apps
            using (var k = Registry.CurrentUser.CreateSubKey(UninstKey))
            {
                k.SetValue("DisplayName", "Dublagem PT-BR de The Witcher 2"); k.SetValue("DisplayVersion", Version); k.SetValue("Publisher", "Dublagem PT-BR (projeto de fã)");
                k.SetValue("InstallLocation", Game); k.SetValue("DisplayIcon", exe); k.SetValue("UninstallString", "\"" + exe + "\" --desinstalar");
                k.SetValue("NoModify", 1, RegistryValueKind.DWord); k.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                k.SetValue("EstimatedSize", (int)((L(Obj("speech"), "bytes") + (150L << 20)) / 1024), RegistryValueKind.DWord);
            }
        }
    }

    class UserError : Exception { public UserError(string m) : base(m) { } }

    // ---------------------------------------------------------------- janela
    class MainForm : Form
    {
        Core core; TextBox folder, log; Button browse, install, uninstall, close; ProgressBar bar; Label status; bool busy, uninstallMode;
        public string DemoPick, DemoLog; public bool Demo; Action<bool> after;

        public MainForm(Core c, bool startUninstall)
        {
            core = c; uninstallMode = startUninstall;
            Text = "Dublagem PT-BR de The Witcher 2 - versão " + c.Version; Font = new Font("Segoe UI", 9.5f);
            // laid out by a table that sizes rows to their content, so text never clips at any Windows text scaling (2026-10-26:
            // fixed positions cut the intro's 3rd line and "Procurar..." at 150 % scaling)
            AutoScaleMode = AutoScaleMode.Dpi; FormBorderStyle = FormBorderStyle.Sizable; MaximizeBox = false; StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(560, 440); Size = new Size(700, 540); Padding = new Padding(12);
            var t = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 7 };
            for (int i = 0; i < 7; i++) t.RowStyles.Add(i == 5 ? new RowStyle(SizeType.Percent, 100) : new RowStyle(SizeType.AutoSize));
            var intro = new Label { AutoSize = true, Dock = DockStyle.Fill, Margin = new Padding(3, 0, 3, 10), Text = startUninstall
                ? "Isto remove a dublagem: as cutscenes voltam ao original, as vozes dos diálogos saem e o idioma do jogo volta ao que era."
                : "Isto instala a dublagem em português: vozes dos diálogos e das cutscenes. As cutscenes do seu jogo recebem uma faixa a mais em português; nada do original se perde, e dá para desinstalar." };
            var lf = new Label { AutoSize = true, Text = "Pasta do The Witcher 2 (a que contém CookedPC):" };
            var row = new TableLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, ColumnCount = 2, Margin = new Padding(0) };
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            folder = new TextBox { Dock = DockStyle.Fill, Text = core.Game ?? "" };
            browse = new Button { AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Padding = new Padding(8, 2, 8, 2), Text = "Procurar..." };
            browse.Click += delegate { using (var d = new FolderBrowserDialog { Description = "Escolha a pasta do The Witcher 2 (a que contém a pasta CookedPC)", SelectedPath = folder.Text }) if (d.ShowDialog(this) == DialogResult.OK) folder.Text = d.SelectedPath; };
            row.Controls.Add(folder, 0, 0); row.Controls.Add(browse, 1, 0);
            status = new Label { AutoSize = true, Margin = new Padding(3, 10, 3, 3), Text = " " };
            bar = new ProgressBar { Dock = DockStyle.Fill, Height = 22, Maximum = 1000 };
            log = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, BackColor = SystemColors.Window };
            var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, FlowDirection = FlowDirection.LeftToRight, Margin = new Padding(0, 8, 0, 0) };
            install = new Button { AutoSize = true, Padding = new Padding(16, 4, 16, 4), Text = "Instalar" };
            uninstall = new Button { AutoSize = true, Padding = new Padding(16, 4, 16, 4), Text = "Desinstalar" };
            close = new Button { AutoSize = true, Padding = new Padding(16, 4, 16, 4), Text = "Fechar" };
            install.Click += delegate { Run(false); }; uninstall.Click += delegate { Run(true); }; close.Click += delegate { Close(); };
            buttons.Controls.AddRange(new Control[] { install, uninstall, close });
            t.Controls.Add(intro, 0, 0); t.Controls.Add(lf, 0, 1); t.Controls.Add(row, 0, 2); t.Controls.Add(status, 0, 3); t.Controls.Add(bar, 0, 4); t.Controls.Add(log, 0, 5); t.Controls.Add(buttons, 0, 6);
            Controls.Add(t);
            Resize += delegate { intro.MaximumSize = new Size(t.ClientSize.Width - 8, 0); }; intro.MaximumSize = new Size(Size.Width - 50, 0);
            AcceptButton = startUninstall ? uninstall : install;
            FormClosing += (s, e) => { if (busy) { e.Cancel = true; MessageBox.Show(this, "Espere terminar: interromper agora pode deixar uma cutscene pela metade.", Text); } };
            core.Log = m => BeginInvoke((Action)(() => { log.AppendText(m + Environment.NewLine); }));
            core.Progress = (p, w) => BeginInvoke((Action)(() => { bar.Value = (int)(p * 1000); status.Text = string.Format("{0:0.0}%  {1}", p * 100, w); }));
            if (string.IsNullOrEmpty(core.Game)) log.AppendText("Não achei o jogo sozinho. Clique em Procurar e escolha a pasta do The Witcher 2." + Environment.NewLine);
            else log.AppendText("Jogo encontrado: " + core.Game + Environment.NewLine);
            Shown += delegate { if (Demo) DemoStart(); };
        }

        // --demo: the same window a player sees, pressing its own buttons (for recorded tests)
        void Later(int ms, Action a) { var t = new System.Windows.Forms.Timer { Interval = ms }; t.Tick += delegate { t.Stop(); t.Dispose(); a(); }; t.Start(); }
        void DemoStart()
        {
            Later(2500, () =>
            {
                if (DemoPick != null) { folder.Text = DemoPick; log.AppendText("[demo] pasta escolhida em Procurar: " + DemoPick + Environment.NewLine); }
                Later(2000, () => { after = ok => Later(4000, () => DemoEnd(ok ? 0 : 1)); Run(uninstallMode); });
            });
        }
        void DemoEnd(int code) { if (DemoLog != null) File.WriteAllText(DemoLog, log.Text + Environment.NewLine + "DEMO " + (code == 0 ? "OK" : "FALHOU"), new UTF8Encoding(false)); Program.DemoCode = code; Close(); }

        void Run(bool remove)
        {
            var g = folder.Text.Trim();
            if (Core.IsGame(Path.GetDirectoryName(g)) && !Core.IsGame(g)) g = Path.GetDirectoryName(g);  // picked CookedPC
            if (!Core.IsGame(g)) { MessageBox.Show(this, "Essa pasta não tem o jogo (falta CookedPC\\en0.w2speech):\n\n" + g + "\n\nEscolha a pasta do The Witcher 2.", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning); return; }
            core.Game = g; busy = true; install.Enabled = uninstall.Enabled = browse.Enabled = close.Enabled = false; log.AppendText(Environment.NewLine + (remove ? "Desinstalando..." : "Instalando...") + Environment.NewLine);
            new Thread(() =>
            {
                string msg; bool ok = false;
                try { if (remove) core.Uninstall(); else core.Install(); ok = true; msg = remove ? "Dublagem removida." + LeftoverNote(core) : "Pronto! É só abrir o jogo: ele já está com voz e texto em português (BR)."; }
                catch (UserError e) { msg = e.Message; }
                catch (Exception e) { msg = "Erro: " + e.Message; }
                BeginInvoke((Action)(() =>
                {
                    busy = false; install.Enabled = uninstall.Enabled = browse.Enabled = close.Enabled = true; log.AppendText(Environment.NewLine + msg + Environment.NewLine);
                    if (after != null) { var a = after; after = null; a(ok); return; }
                    if (ok && remove && core.Leftover != null)
                    {
                        if (MessageBox.Show(this, msg + "\n\nAbrir essa pasta agora?", Text, MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes)
                            try { Process.Start("explorer.exe", "/select,\"" + core.Leftover + "\""); } catch { }
                    }
                    else MessageBox.Show(this, msg, Text, MessageBoxButtons.OK, ok ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
                }));
            }) { IsBackground = false }.Start();
        }
        static string LeftoverNote(Core c)
        {
            return c.Leftover == null ? "" : "\n\nSó sobrou a pasta " + c.Leftover + " (este desinstalador está dentro dela, e um programa aberto não pode apagar a própria pasta). Depois de fechar esta janela, pode apagá-la.";
        }
    }

    static class Program
    {
        public static int DemoCode;
        [STAThread]
        static int Main(string[] args)
        {
            var a = new List<string>(args);
            Func<string, string> opt = n => { int i = a.IndexOf(n); return i >= 0 && i + 1 < a.Count ? a[i + 1] : null; };
            bool remove = a.Contains("--desinstalar"), quiet = a.Contains("--sem-perguntar"); var logPath = opt("--log");
            var pack = Path.GetDirectoryName(Application.ExecutablePath);
            Core core;
            try { core = new Core(pack); }
            catch (Exception e) { MessageBox.Show("Não consegui ler o pacote (dados\\manifest.json ao lado do instalador):\n" + e.Message, "Dublagem PT-BR"); return 1; }
            if (opt("--registro") != null) core.RegPath = opt("--registro");
            core.Game = opt("--jogo") ?? Core.FindGame(pack);
            if (remove && opt("--jogo") == null && pack.EndsWith(@"\dublagem_ptbr_backup\pacote", StringComparison.OrdinalIgnoreCase))
                core.Game = Path.GetDirectoryName(Path.GetDirectoryName(pack));  // the copy inside the game folder
            if (quiet)
            {
                var sb = new StringBuilder(); core.Log = m => { lock (sb) sb.AppendLine(m); };
                int code = 0;
                try
                {
                    if (!Core.IsGame(core.Game)) throw new UserError("Pasta do jogo não encontrada; passe --jogo <pasta>.");
                    sb.AppendLine("Jogo: " + core.Game); if (remove) { core.Uninstall(); if (core.Leftover != null) sb.AppendLine("Sobrou a pasta (o programa roda de dentro dela): " + core.Leftover); } else core.Install(); sb.AppendLine("PRONTO");
                }
                catch (UserError e) { sb.AppendLine("AVISO: " + e.Message); code = 1; }
                catch (Exception e) { sb.AppendLine("ERRO: " + e); code = 1; }
                if (logPath != null) File.WriteAllText(logPath, sb.ToString(), new UTF8Encoding(false));
                return code;
            }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            if (opt("--demo-escolher") != null) core.Game = null;  // demo: start as "not found", then pick the folder
            var form = new MainForm(core, remove) { Demo = a.Contains("--demo"), DemoPick = opt("--demo-escolher"), DemoLog = logPath };
            Application.Run(form);
            return form.Demo ? DemoCode : 0;
        }
    }
}
