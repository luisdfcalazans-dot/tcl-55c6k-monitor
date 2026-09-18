# Registra (ou atualiza) a tarefa agendada do Windows que roda o executor do PC a cada 30 minutos.
# Uso: powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1
$raiz = Split-Path -Parent $PSScriptRoot
$script = Join-Path $raiz "scripts\run_pc.ps1"
$nome = "Monitor TCL 55C6K"

$acao = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
# IgnoreNew: nunca interrompe uma rodada em andamento (poderia deixar um cupom aplicado no meio do teste).
# Uma rodada presa é encerrada pelos prazos internos (run_pc.ps1 + monitor/saida.py), e o limite de 29 min
# cobre coleta (até 9 min) + cupons (até 18 min) sem cortar um teste legítimo.
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 29) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $config -Description "Coleta preços da TCL 55C6K nas lojas que exigem navegador (Amazon, Casas Bahia, Mercado Livre, AliExpress, Shopee) e publica no GitHub." | Out-Null
"Tarefa '$nome' registrada: a cada 30 min, rodando $script"
Get-ScheduledTask -TaskName $nome | Select-Object TaskName, State
