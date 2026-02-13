# Plano de Integracao

## Fase 1 - Base do Hub

- Criar configuracao por instancia (id, tipo, credenciais, filtros, intervalo).
- Criar runtime manager para iniciar/parar instancias em threads.
- Criar status unificado por instancia.

## Fase 2 - Adapter financeiroAPP

- Reaproveitar o fluxo atual como adapter de instancia.
- Isolar credenciais/tokens por instancia para evitar conflito.
- Expor comandos: executar agora, parar, reprocessar.

## Fase 3 - Adapter anaBot

- Portar parser e fluxo de boletos do anaBot para adapter.
- Garantir compatibilidade com labels Gmail e planilhas.
- Normalizar historico e auditoria no mesmo formato do hub.

## Fase 4 - Painel Web Multi-instancia

- Cards por instancia com status, erros e ultima execucao.
- Filtros de historico por instancia.
- Permissoes por perfil (dev, admin, user).

## Fase 5 - Deploy Servidor

- Executavel/servico para subir o hub automaticamente.
- Pastas de runtime no AppData.
- Estrategia de update segura sem derrubar dados locais.

