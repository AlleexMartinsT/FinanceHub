# FinanceAnaHub

Projeto novo para integrar os fluxos do `financeiroAPP` e do `anaBot` em um unico servidor web com suporte a multiplas instancias.

## Objetivo

- Manter `financeiroAPP` e `anaBot` intactos como backup.
- Construir uma base nova orientada a instancias.
- Permitir execucao simultanea de diferentes fluxos no mesmo painel.

## Estrutura inicial

- `src/main.py`: bootstrap do hub.
- `src/core/`: motor comum de execucao.
- `src/instances/`: definicoes por instancia.
- `src/adapters/`: adaptadores para importar logica existente.
- `src/web/`: painel web unificado.
- `src/storage/`: persistencia local.
- `docs/integration_plan.md`: plano tecnico de migracao.

## Como executar

```bash
cd C:\Users\vendas\Desktop\FinanceAnaHub
python src/main.py
```

## Instalacao padrao (servidor)

Opcao recomendada (instalacao limpa com verificacao de pre-requisitos):

1. Rode no PowerShell (Administrador):

```bash
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/AlleexMartinsT/FinanceHub/main/scripts/bootstrap_server.ps1' -OutFile 'C:\bootstrap_financehub.ps1'; ^
   powershell -NoProfile -ExecutionPolicy Bypass -File 'C:\bootstrap_financehub.ps1' -RunHub"
```

O bootstrap faz:

- verificacao de `git`, `python` e acesso ao GitHub
- tentativa de instalacao automatica via `winget` quando faltar `git/python`
- clone/update do HUB em `C:\FinanceHub`
- criacao da `.venv`
- start do `run_hub.bat`

Opcao manual:

1. Clone somente o HUB:

```bash
cd C:\
git clone https://github.com/AlleexMartinsT/FinanceHub.git C:\FinanceHub
```

2. Rode `C:\FinanceHub\run_hub.bat`

Por padrao, a instancia `financeiro_principal` tenta usar `C:\FinanceBot`.
Se a pasta nao existir e `auto_clone_missing=true`, o HUB clona automaticamente o repositorio configurado em `repo_url` para `C:\FinanceBot`.

Painel padrao:

- `http://127.0.0.1:8877`

Cada instancia abre em sua propria rota definida no `route_prefix`, por exemplo:

- `http://127.0.0.1:8877/financeiro/`
- `http://127.0.0.1:8877/anabot/`

Arquivo de instancias:

- `C:\Users\vendas\Desktop\FinanceAnaHub\data\instances.json`

Campos por instancia no `instances.json`:

- `instance_id`
- `display_name`
- `instance_type` (`financeiro` ou `anabot`)
- `enabled`
- `backend_url`
- `app_dir`
- `start_args`
- `route_prefix`
- `repo_url`
- `repo_branch`
- `auto_clone_missing`
- `interval_seconds`
- `credentials_key`
- `notes`

## Auto-update do HUB (Git)

O HUB possui updater proprio via Git, com reinicio automatico quando houver novo commit.

Chaves no `instances.json`:

- `auto_update_enabled`: `true`/`false`
- `auto_update_interval_minutes`: intervalo de checagem
- `auto_update_remote`: remoto Git (ex.: `origin`)
- `auto_update_branch`: branch (ex.: `main`)

Importante:

- O HUB deve estar em um clone Git valido (pasta com `.git`).
- O servidor precisa ter `git` instalado e acesso ao repositorio remoto.

## Fase 1 concluida

- Configuracao por instancia em JSON.
- Runtime manager com loop por instancia.
- Controles de `Executar agora` e `Parar`.
- Endpoint/API e painel web basico para status.

## Backups

As pastas abaixo permanecem isoladas e sem alteracoes:

- `C:\Users\vendas\Desktop\financeiroAPP`
- `C:\Users\vendas\Desktop\anaBot`
