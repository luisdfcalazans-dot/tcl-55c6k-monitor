# Rodada do executor no PC: atualiza o repositório, coleta as fontes "pc", testa cupons no carrinho
# e publica o estado. Chamado pela tarefa agendada (a cada 30 min). Log em logs\pc.log.
#
# Prazos somados ficam abaixo dos 30 min entre rodadas (coleta 9 + cupons 18 + git) e do limite de 29 min
# da tarefa. Cada script Python também tem cão de guarda próprio (monitor/saida.py).
$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
New-Item -ItemType Directory -Force "$raiz\logs" | Out-Null
$log = "$raiz\logs\pc.log"
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

function Registrar([string]$texto) { $texto | Out-File -Append -Encoding utf8 $log }

# Roda um script Python com prazo máximo; se estourar, mata a árvore do processo e o Chrome do monitor.
function RodarPython([string[]]$argumentos, [int]$limiteSegundos, [string]$rotulo) {
    $saida = "$raiz\logs\_tmp_$rotulo.txt"
    $p = Start-Process -FilePath $py -ArgumentList $argumentos -WindowStyle Hidden -PassThru `
         -RedirectStandardOutput $saida -RedirectStandardError "$saida.err" -WorkingDirectory $raiz
    $null = $p.Handle   # sem isso o PowerShell 5.1 às vezes perde o processo e WaitForExit não funciona
    if (-not $p.WaitForExit($limiteSegundos * 1000)) {
        Registrar "[run_pc] $rotulo passou de $limiteSegundos s; encerrando a árvore do processo."
        cmd /c "taskkill /T /F /PID $($p.Id) 2>&1" | Out-File -Append -Encoding utf8 $log
        Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
            Where-Object { $_.CommandLine -like "*$raiz\.pw-profile*" } |
            ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -Confirm:$false } catch {} }
    }
    foreach ($f in @($saida, "$saida.err")) {
        if (Test-Path $f) { Get-Content $f -Encoding utf8 | Out-File -Append -Encoding utf8 $log; Remove-Item $f -Force }
    }
}

Registrar "==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===="
# git escreve mensagens normais no stderr; via cmd /c o PowerShell 5.1 não as transforma em "erros"
cmd /c "git pull --rebase --autostash 2>&1" | Out-File -Append -Encoding utf8 $log

RodarPython @("run.py", "--mode", "pc") 540 "coleta"

# teste de cupons no carrinho (cada loja só entra depois do login com --login)
if (Test-Path "$raiz\.pw-profile-carrinho") {
    RodarPython @("testar_cupons.py") 1080 "cupons"
}

cmd /c "git add docs/data 2>&1" | Out-File -Append -Encoding utf8 $log
cmd /c "git diff --cached --quiet -- docs/data"
if ($LASTEXITCODE -ne 0) {
    # "-- docs/data" limita o commit aos dados: nada mais que esteja preparado no git entra junto
    cmd /c "git commit -m `"coleta pc $(Get-Date -Format 'yyyy-MM-dd HH:mm')`" -- docs/data 2>&1" | Out-File -Append -Encoding utf8 $log
    foreach ($i in 1..4) {
        cmd /c "git pull --rebase --autostash 2>&1" | Out-File -Append -Encoding utf8 $log
        cmd /c "git push 2>&1" | Out-File -Append -Encoding utf8 $log
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds (5 * $i)
    }
}
Registrar "==== fim $(Get-Date -Format 'HH:mm:ss') ===="
# mantém o log com no máximo ~2000 linhas
$linhas = Get-Content $log
if ($linhas.Count -gt 2000) { $linhas[-2000..-1] | Set-Content -Encoding utf8 $log }
[Environment]::Exit(0)
