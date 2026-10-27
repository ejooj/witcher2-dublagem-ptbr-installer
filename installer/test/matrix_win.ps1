# Full Windows test matrix for the installer (the user, 2026-10-26: "Test it thorougly pls. this is going live to ppl").
# Runs the real Instalar dublagem.exe in its command-line mode (--sem-perguntar) against a proven-vanilla game copy, with
# a test registry key, one scenario at a time; every scenario ends with the copy back to vanilla (checked).
# usage: powershell -File matrix_win.ps1 -Pack <package> -Game <vanilla copy> -Out <folder>
param([string]$Pack, [string]$Game, [string]$Out)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Out | Out-Null
$Reg = "Software\DublagemTeste\W2"; $RegPS = "HKCU:\$Reg"; $Exe = "$Pack\Instalar dublagem.exe"
$m = Get-Content -Raw -Encoding UTF8 "$Pack\dados\manifest.json" | ConvertFrom-Json
$OrigDir = "D:\Witcher2Dub\orig\movies"; $V153 = "D:\Witcher2Dub\work\movies14_v153"
$rep = New-Object System.Collections.Generic.List[string]; $fails = 0; $cur = ""
function Check($ok, $what) { $script:rep.Add(("  {0}  {1}" -f ($(if ($ok) { "OK   " } else { "FALHA" }), $what))); if (-not $ok) { $script:fails++ } }
function Sha($p) { if (Test-Path -LiteralPath $p) { (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLower() } else { "ausente" } }
function MoviePath($n) { "$Game\CookedPC\movies\$n" }
function Count($key) { $c = 0; foreach ($x in $m.movies) { if ((Sha (MoviePath $x.name)) -eq $x.$key) { $c++ } }; $c }
$OrigFiles = "D:\Witcher2Dub\orig\files"; $origSmall = @{}; foreach ($f in $m.files) { $origSmall[$f.path] = $(if ($f.original_sha256) { $f.original_sha256 } else { "ausente" }) }
function Snapshot { $h = @{}; foreach ($x in $m.movies) { $h[$x.name] = Sha (MoviePath $x.name) }; $h["speech"] = Sha "$Game\CookedPC\br0.w2speech"; foreach ($f in $m.files) { $h[$f.path] = Sha ("$Game\CookedPC\" + ($f.path -replace '/', '\')) }; $h }
function Same($a, $b) { foreach ($k in $a.Keys) { if ($a[$k] -ne $b[$k]) { return $false } }; return $true }
function Run($args2, $exe = $Exe) {
    $log = "$Out\last.log"; if (Test-Path $log) { Remove-Item $log }
    $p = Start-Process -FilePath $exe -ArgumentList ($args2 + @("--sem-perguntar", "--registro", "`"$Reg`"", "--log", "`"$log`"")) -Wait -PassThru
    $t = if (Test-Path $log) { Get-Content -Raw -Encoding UTF8 $log } else { "" }
    Add-Content -Encoding UTF8 "$Out\logs.txt" "===== $cur : $($args2 -join ' ') -> exit $($p.ExitCode)`n$t"
    return @{ Code = $p.ExitCode; Text = $t }
}
function Install { Run @("--instalar", "--jogo", "`"$Game`"") }
function Uninstall { Run @("--desinstalar", "--jogo", "`"$Game`"") }
function Lang { $p = Get-ItemProperty $RegPS -ErrorAction SilentlyContinue; "$($p.Language)/$($p.Speech)" }
function Vanilla {
    # back to vanilla by copying the originals (independent of the installer under test)
    foreach ($x in $m.movies) { if ((Sha (MoviePath $x.name)) -ne $x.orig_sha256) { Copy-Item "$OrigDir\$($x.name)" (MoviePath $x.name) -Force } }
    if (Test-Path "$Game\CookedPC\br0.w2speech") { Remove-Item "$Game\CookedPC\br0.w2speech" }
    Get-ChildItem "$Game\CookedPC\movies" -Filter "*.dublagem_tmp" -ErrorAction SilentlyContinue | Remove-Item -Force
    if (Test-Path "$Game\dublagem_ptbr_backup") { Remove-Item -Recurse -Force "$Game\dublagem_ptbr_backup" }
    foreach ($f in $m.files) { $d = "$Game\CookedPC\" + ($f.path -replace '/', '\'); if ($f.original_sha256) { Copy-Item ("$OrigFiles\" + ($f.path -replace '/', '\')) $d -Force } elseif (Test-Path $d) { Remove-Item $d } }
    New-Item -Force $RegPS | Out-Null; Set-ItemProperty $RegPS Language "EN"; Set-ItemProperty $RegPS Speech "EN"
}
function IsVanilla { (-not ($m.files | ? { (Sha ("$Game\CookedPC\" + ($_.path -replace '/', '\'))) -ne $origSmall[$_.path] })) -and (Count "orig_sha256") -eq $m.movies.Count -and -not (Test-Path "$Game\CookedPC\br0.w2speech") -and -not (Test-Path "$Game\dublagem_ptbr_backup") }
function Scenario($name) { $script:cur = $name; $script:rep.Add(""); $script:rep.Add($name); Vanilla; if (-not (IsVanilla)) { Check $false "começou do jogo original" } }
$small = ($m.movies | Sort-Object orig_bytes | Select-Object -First 1).name
$big = ($m.movies | Sort-Object orig_bytes -Descending | Select-Object -First 1).name

$rep.Add("Matriz de testes do instalador (Windows) - $(Get-Date -Format 'yyyy-MM-dd HH:mm') - pacote $($m.version)")

Scenario "W1 instalação nova e desinstalação"
$r = Install; Check ($r.Code -eq 0) "instalar terminou sem erro"
Check ((Count "dub_sha256") -eq $m.movies.Count) "43 cutscenes exatamente as dubladas"
Check ((Sha "$Game\CookedPC\br0.w2speech") -eq $m.speech.sha256) "br0.w2speech confere"
foreach ($f in $m.files) { Check ((Sha ("$Game\CookedPC\" + ($f.path -replace '/', '\'))) -eq $f.sha256) "arquivo $($f.path)" }
Check ((Lang) -eq "BR/BR") "idioma BR/BR"
Check (Test-Path "$Game\dublagem_ptbr_backup\pacote\Desinstalar dublagem.exe") "cópia para desinstalar guardada"
$r = Uninstall; Check ($r.Code -eq 0) "desinstalar terminou sem erro"
Check ((Count "orig_sha256") -eq $m.movies.Count) "43 cutscenes exatamente as originais"
foreach ($f in $m.files) { Check ((Sha ("$Game\CookedPC\" + ($f.path -replace '/', '\'))) -eq $origSmall[$f.path]) "arquivo $($f.path) como era" }
Check (-not (Test-Path "$Game\CookedPC\br0.w2speech")) "br0.w2speech removido"
Check ((Lang) -eq "EN/EN") "idioma de volta EN/EN"
Check (-not (Test-Path "$Game\dublagem_ptbr_backup")) "nenhum rastro (dublagem_ptbr_backup removida)"

Scenario "W2 instalar duas vezes"
$r = Install; $r2 = Install; Check ($r2.Code -eq 0) "segunda instalação sem erro"
Check ($r2.Text -match "já dublada") "segunda instalação reconhece as cutscenes já dubladas"
Check ((Count "dub_sha256") -eq $m.movies.Count) "continua tudo dublado"
$r = Uninstall; Check ((Count "orig_sha256") -eq $m.movies.Count -and -not (Test-Path "$Game\dublagem_ptbr_backup")) "desinstalar volta ao original sem rastro"

Scenario "W3 atualizar por cima da dublagem 1.5.3 (instalador antigo)"
New-Item -ItemType Directory -Force "$Game\dublagem_ptbr_backup\movies" | Out-Null
foreach ($x in $m.movies) { if (Test-Path "$V153\$($x.name)") { Copy-Item (MoviePath $x.name) "$Game\dublagem_ptbr_backup\movies\$($x.name)"; Copy-Item "$V153\$($x.name)" (MoviePath $x.name) -Force } }
Set-Content -Encoding UTF8 "$Game\dublagem_ptbr_backup\versao.txt" "1.5.3-experimental"; Set-ItemProperty $RegPS Language "BR"; Set-ItemProperty $RegPS Speech "BR"; Set-Content -Encoding UTF8 "$Game\dublagem_ptbr_backup\idioma_anterior.txt" "EN|EN"
$old = 0; foreach ($x in $m.movies) { if ((Sha (MoviePath $x.name)) -ne $x.orig_sha256 -and (Sha (MoviePath $x.name)) -ne $x.dub_sha256) { $old++ } }; Check ($old -gt 0) "simulação: $old cutscenes com a dublagem antiga"
$r = Install; Check ($r.Code -eq 0) "atualização sem erro"
Check ((Count "dub_sha256") -eq $m.movies.Count) "todas as cutscenes na versão nova"
Check ($r.Text -match "1.5.3-experimental -> agora") "informa a versão anterior"
$r = Uninstall; Check ((Count "orig_sha256") -eq $m.movies.Count) "desinstalar devolve os originais"
Check ((Lang) -eq "EN/EN") "idioma volta ao de antes da dublagem antiga (EN)"

Scenario "W4 uma cutscene grande alterada por outro mod"
$b = [IO.File]::ReadAllBytes((MoviePath $big)); $b[$b.Length - 1] = $b[$b.Length - 1] -bxor 1; [IO.File]::WriteAllBytes((MoviePath $big), $b); $mod = Sha (MoviePath $big)
$r = Install; Check ($r.Code -ne 0) "instalação avisa (código de erro)"
Check ($r.Text -match [regex]::Escape($big)) "o aviso cita $big"
Check ((Sha (MoviePath $big)) -eq $mod) "$big ficou como estava (nada estragado)"
Check ((Count "dub_sha256") -eq ($m.movies.Count - 1)) "as outras 42 foram dubladas"
$r = Uninstall; Check ((Count "orig_sha256") -eq ($m.movies.Count - 1)) "desinstalar devolve as 42 originais"
Check ((Sha (MoviePath $big)) -eq $mod) "$big continua como o outro mod deixou"

Scenario "W5 a cutscene de conferência alterada (versão diferente do jogo)"
$b = [IO.File]::ReadAllBytes((MoviePath $small)); $b[100] = $b[100] -bxor 1; [IO.File]::WriteAllBytes((MoviePath $small), $b); $before = Snapshot
$r = Install; Check ($r.Code -ne 0) "recusa"
Check ($r.Text -match "não é a versão esperada") "explica que a cópia do jogo não é a esperada"
Check (Same $before (Snapshot)) "nada foi alterado"
Check (-not (Test-Path "$Game\CookedPC\br0.w2speech")) "br0.w2speech não foi copiado"

Scenario "W6 jogo aberto"
$fake = "$Out\witcher2.exe"; Copy-Item "$env:windir\System32\ping.exe" $fake -Force; $gp = Start-Process $fake -ArgumentList "-n 120 127.0.0.1" -WindowStyle Hidden -PassThru; Start-Sleep 1
$before = Snapshot; $r = Install; Check ($r.Code -ne 0) "recusa"; Check ($r.Text -match "jogo está aberto") "avisa que o jogo está aberto"; Check (Same $before (Snapshot)) "nada foi alterado"
Stop-Process -Id $gp.Id -Force; Start-Sleep 1; Remove-Item $fake -Force

Scenario "W7 sem permissão de escrita"
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls "$Game\CookedPC\movies" /deny "${me}:(AD,WD)" | Out-Null  # only: no new files in the folder (a broad W deny also blocks reading)
$before = Snapshot; try { $r = Install } finally { & icacls "$Game\CookedPC\movies" /remove:d "$me" | Out-Null }; Check ($r.Code -ne 0) "recusa"; Check ($r.Text -match "administrador") "diz para executar como administrador"
& icacls "$Game\CookedPC\movies" /remove:d "$me" | Out-Null
Check (Same $before (Snapshot)) "nada foi alterado"

Scenario "W8 instalação interrompida no meio e repetida"
$log = "$Out\last.log"; $p = Start-Process -FilePath $Exe -ArgumentList @("--instalar", "--jogo", "`"$Game`"", "--sem-perguntar", "--registro", "`"$Reg`"", "--log", "`"$log`"") -PassThru
$t0 = Get-Date; while (((Get-Date) - $t0).TotalSeconds -lt 9 -and -not $p.HasExited) { Start-Sleep -Milliseconds 250 }
$wasRunning = -not $p.HasExited; Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; Start-Sleep 1
Check $wasRunning "a instalação foi mesmo interrompida no meio ($(Count 'dub_sha256') de 43 já dubladas)"
$partial = 0; foreach ($x in $m.movies) { $h = Sha (MoviePath $x.name); if ($h -ne $x.orig_sha256 -and $h -ne $x.dub_sha256) { $partial++ } }
Check ($partial -eq 0) "nenhuma cutscene ficou pela metade (cada uma é a original ou a dublada)"
$r = Install; Check ($r.Code -eq 0) "repetir a instalação termina sem erro"; Check ((Count "dub_sha256") -eq $m.movies.Count) "tudo dublado"
Check (-not (Get-ChildItem "$Game\CookedPC" -Recurse -Filter "*.dublagem_tmp")) "nenhum arquivo temporário sobrando"
$r = Uninstall; Check ((Count "orig_sha256") -eq $m.movies.Count) "desinstalar devolve os originais"

Scenario "W9 pasta errada"
$r = Run @("--instalar", "--jogo", "`"D:\Witcher2Dub\work`""); Check ($r.Code -ne 0) "recusa"; Check ($r.Text -match "Pasta do jogo não encontrada") "explica"; Check (IsVanilla) "o jogo não foi tocado"

Scenario "W10 pacote sem o arquivo de vozes"
$bad = "$Out\pacote_incompleto"; if (Test-Path $bad) { Remove-Item -Recurse -Force $bad }
New-Item -ItemType Directory -Force "$bad\dados" | Out-Null; Copy-Item $Exe $bad; Copy-Item "$Pack\dados\manifest.json" "$bad\dados"; Copy-Item -Recurse "$Pack\dados\movies" "$bad\dados\movies"; Copy-Item -Recurse "$Pack\dados\files" "$bad\dados\files"
$before = Snapshot; $r = Run @("--instalar", "--jogo", "`"$Game`"") "$bad\Instalar dublagem.exe"
Check (Same $before (Snapshot)) "nada foi alterado"
Check ($r.Code -ne 0) "recusa"; Check ($r.Text -match "incompleto") "diz que o pacote está incompleto"
Remove-Item -Recurse -Force $bad

Scenario "W11 desinstalar sem ter instalado"
$before = Snapshot; $r = Uninstall; Check ($r.Code -eq 0) "termina sem erro"; Check (Same $before (Snapshot)) "nada de jogo mudou"

Scenario "W12 outro mod muda uma cutscene depois de instalar"
$r = Install; $b = [IO.File]::ReadAllBytes((MoviePath $big)); $b[$b.Length - 1] = $b[$b.Length - 1] -bxor 1; [IO.File]::WriteAllBytes((MoviePath $big), $b); $mod = Sha (MoviePath $big)
$r = Uninstall; Check ($r.Code -ne 0) "desinstalar avisa"; Check ($r.Text -match [regex]::Escape($big)) "cita $big"
Check ((Sha (MoviePath $big)) -eq $mod) "$big ficou como o outro mod deixou"; Check ((Count "orig_sha256") -eq ($m.movies.Count - 1)) "as outras 42 voltaram ao original"

Scenario "W13 a pasta dublagem_ptbr_backup apagada pelo jogador com a dublagem instalada"
$r = Install; Remove-Item -Recurse -Force "$Game\dublagem_ptbr_backup"
$r = Run @("--desinstalar", "--jogo", "`"$Game`"") "$Pack\Instalar dublagem.exe"
Check ($r.Code -ne 0 -and $r.Text -match "Verificar integridade") "desinstalar avisa e indica Verificar integridade"
foreach ($f in ($m.files | ? { $_.original_sha256 })) { Check (Test-Path ("$Game\CookedPC\" + ($f.path -replace '/', '\'))) "$($f.path) NÃO foi apagado (o jogo precisa dele)" }
Check ((Count "orig_sha256") -eq $m.movies.Count) "as 43 cutscenes voltaram ao original mesmo sem a pasta de backup"

Scenario "W14 jogador com o texto oficial em português da Steam (texto BR antes da dublagem)"
Set-ItemProperty $RegPS Language "BR"; Set-ItemProperty $RegPS Speech "EN"
$r = Install; Check ((Lang) -eq "BR/BR") "instalado: BR/BR"
$r = Uninstall; Check ((Lang) -eq "BR/EN") "desinstalado: texto continua BR (o da Steam), voz volta a EN: $(Lang)"

Scenario "W15 desinstalar pela cópia guardada na pasta do jogo (Aplicativos > Desinstalar)"
$r = Install; $kept = "$Game\dublagem_ptbr_backup\pacote\Desinstalar dublagem.exe"; Check (Test-Path $kept) "cópia guardada existe"
$psBefore = @(Get-Process powershell -ErrorAction SilentlyContinue | % Id)
$r = Run @("--desinstalar") $kept
Start-Sleep -Milliseconds 1500
$psNew = @(Get-Process powershell -ErrorAction SilentlyContinue | ? { $psBefore -notcontains $_.Id })
Check ($r.Code -eq 0) "desinstalar pela cópia terminou sem erro"
Check ((Count "orig_sha256") -eq $m.movies.Count) "43 cutscenes voltaram ao original"
Check (-not (Test-Path "$Game\CookedPC\br0.w2speech")) "br0.w2speech removido"
Check ($r.Text -match "Sobrou a pasta") "avisa qual pasta sobrou para apagar"
Check ($psNew.Count -eq 0) "nenhum processo escondido iniciado (PowerShell)"
$leftFiles = @(Get-ChildItem -Recurse -File "$Game\dublagem_ptbr_backup" | % { $_.FullName.Substring("$Game\dublagem_ptbr_backup\".Length) } | ? { $_ -notlike "pacote\*" })
Check ($leftFiles.Count -eq 0) "só a pasta pacote sobrou: $($leftFiles -join ', ')"

Vanilla; Remove-Item -Recurse -Force ("HKCU:\Software\DublagemTeste") -ErrorAction SilentlyContinue
$rep.Add(""); $rep.Add($(if ($fails -eq 0) { "RESULTADO: todos os cenários OK" } else { "RESULTADO: $fails falha(s)" }))
$rep.Add("jogo de teste de volta ao original: $(IsVanilla)")
$rep | Set-Content -Encoding UTF8 "$Out\relatorio_windows.txt"
