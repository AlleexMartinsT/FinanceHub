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
