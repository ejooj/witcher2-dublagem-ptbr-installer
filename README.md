# The Witcher 2 – Brazilian Portuguese dub (installer source)

Source code for the installer of the fan-made **Brazilian Portuguese (PT-BR) voice dub** for
*The Witcher 2: Assassins of Kings* (Steam / GOG, Windows and Linux/Steam Deck via Proton).

Mod page: https://www.nexusmods.com/witcher2/mods/1194

The voices were generated with AI text-to-speech. It is not an official dub and is not affiliated with CD PROJEKT RED. This is a
non-commercial fan project.

## What is in the download

| File | What it is |
|---|---|
| `Instalar dublagem.exe` | Windows installer, built from `installer/src/Dublagem.cs` (this repo) |
| `instalar-linux.sh`, `desinstalar-linux.sh`, `linux/dublagem_linux.py` | Linux / Steam Deck installer (plain Python 3, standard library only) |
| `dados/manifest.json` | list of every file the installer writes, with SHA-256 hashes |
| `dados/br0.w2speech` | the Portuguese dialogue voices (a new file, the game's own language slot `br`) |
| `dados/files/...` | 3 dialogue scene files and `ui_video.swf` (so cutscenes can play the Portuguese track) |
| `dados/movies/*.w2mp` | 43 cutscene **patches**: our Portuguese audio track plus two small index tables. No CD Projekt video is shipped; each patch is applied to the player's own copy of the cutscene |
| `LEIA-ME.txt` | instructions (Portuguese) |

## What the Windows installer does

Everything is local; it has **no network access, no admin rights** (`asInvoker` manifest), and starts
**no other processes** (the only exception: after uninstalling from the copy in the game folder, it can
open that folder in Explorer if the player clicks *Yes*).

Install:
1. Finds the game (Steam registry + `libraryfolders.vdf`, then GOG registry) or lets the player pick the folder.
2. Refuses if the game is running, if the folder is not writable, or if the cutscenes are not the
   expected original versions (checked by SHA-256). Nothing is changed in those cases.
3. Copies `br0.w2speech` and the 4 small files into `CookedPC`. If one of those files already exists and
   differs, it is backed up to `<game>\dublagem_ptbr_backup\files` first.
4. For each of the 43 cutscenes in `CookedPC\movies`: reads the original, applies the patch in memory,
   checks the result against the expected SHA-256, writes it to a temp file, then swaps it in.
5. Keeps a copy of itself (as `Desinstalar dublagem.exe`), the manifest and the patches in
   `<game>\dublagem_ptbr_backup\pacote`, so the dub can be uninstalled later.
6. Sets the game's language in `HKCU\Software\CD Projekt Red\The Witcher 2` (`Language`/`Speech` = `BR`,
   the same values the game's own configurator writes), remembering the previous values.
7. Adds an entry to *Apps & features* (`HKCU\...\Uninstall\DublagemPTBR_Witcher2`).

Uninstall reverses every step: un-patches each cutscene back to the exact original (SHA-256 checked),
restores backed-up files, removes `br0.w2speech`, restores the previous language and removes the Apps entry.

The Linux installer (`installer/linux/dublagem_linux.py`) does the same; it writes the language to the
Proton prefix (`steamapps/compatdata/20920/pfx/user.reg`) instead of the Windows registry.

## Building

### The Windows installer (only this is needed to check the .exe)

Windows has the compiler built in (.NET Framework 4.8). From PowerShell, in the repo folder:

```powershell
& "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /codepage:65001 /target:winexe /optimize+ `
  "/out:Instalar dublagem.exe" /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll `
  /win32manifest:installer\src\app.manifest installer\src\Dublagem.cs
```

This old compiler has no deterministic-build option, so the result is not byte-identical to the released
.exe (timestamps and IDs differ), but the code is the same.

To run it, put the `.exe` next to a `dados` folder from the release.

### The whole package

`installer/build_pack.py` builds the release folder from the full dubbed game files and the original
cutscenes (not in this repo: they are game data). It creates every patch with `tools/w2patch.py` and checks
it both ways (original → dubbed → original, byte for byte), then compiles the .exe with the command above.
`installer/make_zip.py` zips the folder and re-checks every file in the zip.

### Patch format (W2MP v1)

`tools/w2patch.py` is the reference implementation (`make`, `apply`, `undo`, `test`). A patch is a recipe of
chunk operations: copy a chunk of the original, or insert a literal chunk (our audio track, channel 14, and
the rewritten CRID/seek tables), with the SHA-256 and size of both the original and the dubbed file.

## Tests

- `installer/test/matrix_win.ps1`: 15 scenarios run against a vanilla copy of the game (fresh install and
  uninstall, reinstall, upgrade from the old 1.5.3 installer, another mod changing a cutscene, wrong game
  version, game running, no write permission, interrupted install, wrong folder, incomplete package,
  uninstall without install, missing backup folder, Steam's official Portuguese text, uninstall from the
  copy in the game folder). Each scenario ends with the game back to the exact original files.
- `installer/test/matrix_linux.py`: the same scenarios for the Linux installer, with a fake Steam library
  and Proton prefix.

The test scripts point to local folders (a vanilla game copy and the original cutscenes); edit the paths at
the top to run them.
