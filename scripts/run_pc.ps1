# Rodada do executor no PC: atualiza o repositório, coleta as fontes "pc" e publica o estado.
# Chamado pela tarefa agendada (a cada 30 min). Log em logs\pc.log.
$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
New-Item -ItemType Directory -Force "$raiz\logs" | Out-Null
$log = "$raiz\logs\pc.log"
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

"==== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" | Out-File -Append -Encoding utf8 $log
# git escreve mensagens normais no stderr; via cmd /c o PowerShell 5.1 não as transforma em "erros"
cmd /c "git pull --rebase --autostash 2>&1" | Out-File -Append -Encoding utf8 $log
cmd /c "`"$py`" run.py --mode pc 2>&1" | Out-File -Append -Encoding utf8 $log
# teste de cupons no carrinho (só faz algo se o login foi feito com --login)
if (Test-Path "$raiz\.pw-profile-carrinho\magalu") {
    cmd /c "`"$py`" testar_cupons.py --loja magalu 2>&1" | Out-File -Append -Encoding utf8 $log
}

cmd /c "git add docs/data 2>&1" | Out-File -Append -Encoding utf8 $log
cmd /c "git diff --cached --quiet"
if ($LASTEXITCODE -ne 0) {
    cmd /c "git commit -m `"coleta pc $(Get-Date -Format 'yyyy-MM-dd HH:mm')`" 2>&1" | Out-File -Append -Encoding utf8 $log
    foreach ($i in 1..4) {
        cmd /c "git pull --rebase --autostash 2>&1" | Out-File -Append -Encoding utf8 $log
        cmd /c "git push 2>&1" | Out-File -Append -Encoding utf8 $log
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds (5 * $i)
    }
}
# mantém o log com no máximo ~2000 linhas
$linhas = Get-Content $log
if ($linhas.Count -gt 2000) { $linhas[-2000..-1] | Set-Content -Encoding utf8 $log }
