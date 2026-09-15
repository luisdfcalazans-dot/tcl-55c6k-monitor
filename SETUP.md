# Configuração passo a passo — Monitor TCL 55C6K

Tempo total: 20 a 30 minutos. Você só precisa de: Telegram no celular, uma conta no GitHub (gratuita) e este PC.

Já está pronto neste PC: Python 3.12, GitHub CLI (`gh`), Google Chrome, o projeto commitado em `C:\Users\luisd\OneDrive\Área de Trabalho\promos`.

---

## 0. Onde digitar os comandos

1. Abra um terminal **novo**: tecla Windows + X → **Terminal** (ou procure "PowerShell" no menu Iniciar).
2. Entre na pasta do projeto. Esta é sempre a primeira linha:
   ```powershell
   cd "C:\Users\luisd\OneDrive\Área de Trabalho\promos"
   ```
3. Confira as ferramentas:
   ```powershell
   python --version
   gh --version
   ```
   Esperado: `Python 3.12.10` e `gh version 2.x`.
   Se `python` abrir a Microsoft Store em vez de responder: Configurações → Aplicativos → Configurações avançadas de aplicativos → **Aliases de execução de aplicativo** → desligue `python.exe` e `python3.exe`, feche e abra o terminal de novo.

---

## 1. Criar o bot do Telegram (no celular ou no PC)

1. No Telegram, procure **@BotFather** e abra a conversa.
2. Envie `/newbot`.
3. Ele pede um **nome**: responda `Monitor TCL 55C6K`.
4. Ele pede um **username**, que precisa terminar em `bot` e ser único: por exemplo `luis_tcl55c6k_bot`. Se disser que já existe, tente outro.
5. Ele responde com o **token**, algo como `8123456789:AAF3x...` (uma linha longa). Copie e guarde. Esse token é a senha do bot: não compartilhe.
6. Procure **@userinfobot**, envie `/start`. Ele responde com `Id: 123456789`. Esse número é o seu **chat id**. Guarde.
7. Volte à lista de conversas, abra o seu bot novo (procure pelo username) e envie qualquer mensagem, por exemplo `oi`. Sem isso o bot não consegue falar com você.

---

## 2. Colocar o token no PC e testar

1. No terminal (dentro da pasta do projeto):
   ```powershell
   copy .env.example .env
   notepad .env
   ```
2. No Bloco de Notas, troque as duas primeiras linhas pelos seus valores:
   ```
   TELEGRAM_BOT_TOKEN=8123456789:AAF3x...
   TELEGRAM_CHAT_ID=123456789
   ```
   Deixe o resto como está. Salve (Ctrl+S) e feche.
3. Teste o envio. Este comando faz uma coleta completa e manda o resumo diário no Telegram:
   ```powershell
   python run.py --mode cloud --resumo
   ```
   Em cerca de um minuto deve chegar uma mensagem "☀️ Resumo diário — TCL 55C6K" no seu Telegram.

   Se não chegar, olhe o final da saída do comando:
   - `falha 401` → token errado (copie de novo do BotFather).
   - `falha 400 ... chat not found` → chat id errado ou você não mandou o "oi" para o bot (passo 1.7).
   - `(sem TELEGRAM_BOT_TOKEN/CHAT_ID)` → o arquivo `.env` não foi salvo na pasta certa.

---

## 3. Entrar no GitHub pelo terminal

1. Se ainda não tem conta, crie em <https://github.com/signup> (gratuita). Anote o nome de usuário.
2. No terminal:
   ```powershell
   gh auth login
   ```
   Responda com as setas e Enter:
   - **Where do you use GitHub?** → `GitHub.com`
   - **What is your preferred protocol?** → `HTTPS`
   - **Authenticate Git with your GitHub credentials?** → `Yes` (importante: é isso que permite a tarefa do PC fazer `git push` sozinha)
   - **How would you like to authenticate?** → `Login with a web browser`
   - Ele mostra um código de 8 caracteres (tipo `AB12-CD34`). Copie, aperte Enter, o navegador abre; cole o código e clique em **Authorize**.
3. Confira:
   ```powershell
   gh auth status
   ```
   Esperado: `Logged in to github.com account SEU_USUARIO`.

---

## 4. Criar o repositório e enviar o projeto

```powershell
gh repo create tcl-55c6k-monitor --public --source . --remote origin --push
```
Isso cria o repositório público `SEU_USUARIO/tcl-55c6k-monitor` e envia tudo. Para ver no navegador:
```powershell
gh repo view --web
```
Você deve ver os arquivos (`monitor/`, `docs/`, `run.py`…) e a aba **Actions**.

---

## 5. Guardar o token e o chat id no GitHub (Secrets)

Os segredos ficam criptografados no GitHub; o código nunca os mostra.
```powershell
gh secret set TELEGRAM_BOT_TOKEN
```
Ele pede `? Paste your secret:`. Cole o token (não aparece na tela) e aperte Enter.
```powershell
gh secret set TELEGRAM_CHAT_ID
```
Cole o chat id e Enter. Confira:
```powershell
gh secret list
```
Esperado: as duas linhas `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.

---

## 6. Liberar o robô para salvar dados e ligar o painel (GitHub Pages)

Dois comandos:
```powershell
gh api -X PUT repos/{owner}/{repo}/actions/permissions/workflow -f default_workflow_permissions=write -F can_approve_pull_request_reviews=false
```
```powershell
gh api -X POST repos/{owner}/{repo}/pages -f "source[branch]=main" -f "source[path]=/docs"
```
(Digite `{owner}/{repo}` literalmente assim; o `gh` substitui pelo seu usuário e repositório.)

Se preferir fazer pelo site, é o mesmo que: **Settings → Actions → General → Workflow permissions → "Read and write permissions" → Save** e **Settings → Pages → Source "Deploy from a branch" → Branch `main`, pasta `/docs` → Save**.

O painel fica em **`https://SEU_USUARIO.github.io/tcl-55c6k-monitor/`** e demora de 1 a 3 minutos para aparecer da primeira vez. Salve esse endereço no celular; ele abre de qualquer computador.

---

## 7. Primeira coleta na nuvem

```powershell
gh workflow run "monitor 55C6K"
```
Acompanhe (espere uns 20 segundos e rode):
```powershell
gh run list --limit 3
```
Esperado: uma linha `completed  success  monitor 55C6K`. Se aparecer `failure`, rode `gh run view --log-failed` e me mande o texto.

A partir daqui o GitHub roda sozinho **a cada 15 minutos**, sem o PC ligado. Cada execução faz um commit "coleta cloud …" no repositório e atualiza o painel. O primeiro disparo automático pode atrasar alguns minutos.

Você não vai receber mensagem nesta primeira rodada se nada mudou: o estado inicial já foi registrado hoje. As mensagens chegam quando houver preço novo, queda, cupom aplicável ou postagem nova.

---

## 8. Ligar o executor do PC (Amazon, Casas Bahia, Mercado Livre, AliExpress)

Essas lojas bloqueiam servidores; por isso são lidas aqui, com o Chrome, a cada 30 minutos, enquanto o PC estiver ligado e você logado.

1. Teste manual primeiro (abre o Chrome fora da tela por cerca de 1 minuto):
   ```powershell
   python run.py --mode pc --no-notify
   ```
   Esperado no final: `pc: 4 preços de loja …`.
2. Agende:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1
   ```
   Esperado: `Tarefa 'Monitor TCL 55C6K' registrada: a cada 30 min`.
3. Depois de meia hora, confira o registro:
   ```powershell
   notepad logs\pc.log
   ```
   Deve ter linhas `[ok] amazon`, `[ok] casasbahia`… e no fim um `git push` sem erro.

Para ver ou pausar a tarefa: menu Iniciar → **Agendador de Tarefas** → Biblioteca → "Monitor TCL 55C6K".

---

## 9. (Opcional) Grupo ENVOLTOTECH e bot AquiSuaPromoBot

Esses dois não têm página pública; o monitor lê com a **sua conta** do Telegram, só no PC.

1. Abra <https://my.telegram.org/apps>, entre com seu telefone (código chega no Telegram).
2. Em **Create new application** preencha: App title `monitor`, Short name `monitor`, Platform `Desktop`. Clique em Create.
3. Copie **api_id** (número) e **api_hash** (letras e números).
4. No terminal:
   ```powershell
   python scripts\telegram_login.py
   ```
   Cole api_id, api_hash, depois o telefone no formato `+5511999999999`, depois o código que o Telegram enviar (e a senha de duas etapas, se você tiver).
5. O script mostra seus grupos e imprime quatro linhas `TELEGRAM_API_ID=…`, `TELEGRAM_API_HASH=…`, `TELEGRAM_SESSION=…`, `TELEGRAM_CHATS_USUARIO=…`. Abra `notepad .env`, apague o `#` das quatro linhas correspondentes e cole os valores. Em `TELEGRAM_CHATS_USUARIO` deixe `@ENVOLTOTECH,@AquiSuaPromoBot` (pode acrescentar outros da lista que o script mostrou, separados por vírgula).
6. Teste:
   ```powershell
   python run.py --mode pc --no-notify --so telegram.usuario
   ```

Atenção: a linha `TELEGRAM_SESSION` dá acesso total à sua conta. Ela fica só no `.env` deste PC, que nunca vai para o GitHub.

---

## 10. Ajustes do dia a dia

| Quero… | Comando |
|---|---|
| Mudar o alvo de preço (ex.: R$ 2.800 no Pix) | `gh variable set ALVO_PIX --body 2800` e a mesma linha no `.env` do PC |
| Mudar o alvo parcelado | `gh variable set ALVO_PARCELADO --body 2900` |
| Acompanhar mais canais públicos do Telegram | `gh variable set TELEGRAM_CANAIS_EXTRA --body "canal1,canal2"` |
| Pausar a nuvem | `gh workflow disable "monitor 55C6K"` (retomar: `enable`) |
| Pausar o PC | `Disable-ScheduledTask -TaskName "Monitor TCL 55C6K"` (retomar: `Enable-ScheduledTask …`) |
| Forçar uma coleta agora | `gh workflow run "monitor 55C6K"` ou `python run.py --mode all` |
| Receber o resumo de preços agora | `gh workflow run "monitor 55C6K" -f resumo=true` |
| Ver o histórico em planilha | abra `docs\data\historico_cloud.csv` e `historico_pc.csv` no Excel |

---

## 11. Se algo der errado

- **Mensagem "⚠️ Fonte X falhou 3 vezes"**: o site mudou ou bloqueou. Me mande a mensagem que eu ajusto o coletor. As outras fontes continuam.
- **`index.lock` ou "unable to write" no `logs\pc.log`**: o OneDrive travou um arquivo do git. Feche o OneDrive por um minuto ou mova a pasta para fora dele (ex.: `C:\promos`) e rode o `setup_task.ps1` de novo.
- **`gh: command not found` / `python` abre a Store**: abra um terminal novo; veja o passo 0.
- **Muitas mensagens de uma vez**: o limite é 15 por rodada; ajuste com `gh variable set MAX_ALERTAS_POR_EXECUCAO --body 5`.
- **Quero parar tudo**: `gh workflow disable "monitor 55C6K"` e `Unregister-ScheduledTask -TaskName "Monitor TCL 55C6K"`.
