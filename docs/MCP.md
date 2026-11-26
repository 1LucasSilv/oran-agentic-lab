# Etapa 5 — Ferramentas MCP locais

O extra `mcp` fixa o SDK oficial Python em **2.3.0**. A integração usa `MCPServer` e `Client` da linha estável 2.x. [Publicação no PyPI](https://pypi.org/project/mcp/2.3.0/) · [Transportes do cliente](https://py.sdk.modelcontextprotocol.io/client/transports/)

## Arquitetura

No loop integrado, o hospedeiro vincula o servidor a uma janela e fornece a mesma instância de `Simulator` que produz a auditoria final. O cliente abre conexões MCP em memória para listar e chamar ferramentas. No teste stdio, o cliente inicia o processo do servidor, que possui o único simulador da demonstração. A sessão stdio fixa a janela sintética 5 e usa propostas programadas. O modo Ollama usa JSON estruturado para selecionar uma leitura, chama a ferramenta via MCP e envia o resultado na próxima inferência. O código hospedeiro chama `solicitar_acao` com a proposta final e define a origem e a janela. A ferramenta submete a proposta a `Simulator.apply()`.

| Ferramenta | Argumentos | Resultado |
|---|---|---|
| `consultar_janela` | `janela_id` inteiro positivo | Evidências da janela solicitada até o limite autorizado |
| `consultar_historico` | `limite` inteiro de 1 a 32 | Registros em ordem com Register, throughput UL e PRB UL, terminando na janela atual |
| `consultar_estado` | objeto vazio | Evento corrente, orçamento, inspeção e limites |
| `listar_acoes_permitidas` | objeto vazio | Ações com alvo disponível e seus parâmetros |
| `solicitar_acao` | `acao`, `parametros`, `justificativa` | ID do histórico, validação, execução, origem e verificação |

A autorização exige o episódio da janela corrente para operar sobre eventos existentes, inclusive no modo Ollama direto. O registro de alerta exige a janela de abertura do episódio. O servidor bloqueia janelas futuras e corta o histórico pelo último Register autorizado. Tipos, chaves e parâmetros são verificados antes da consulta ou pelo simulador. A lista de recursos do MCP se limita às cinco ferramentas descritas.

## Limites e fallback

O padrão é duas consultas de leitura por janela, configurável de zero a quatro. Cada requisição MCP tem timeout padrão de cinco segundos. A resposta útil e o contexto final acumulado são limitados a 8 KiB em JSON. O orçamento `--max-chamadas` inclui inferências de seleção e de proposta. Uma chamada fica reservada para a proposta final enquanto o modelo consulta ferramentas. `encerrar` conclui a seleção localmente.

Uma consulta inválida ou uma ação recusada aciona o fallback determinístico. O fallback usa a ferramenta de ação quando disponível. Se o canal de ação falha antes de registrar a proposta, o hospedeiro registra `nenhuma_acao` no simulador. Se a resposta se perde após a operação, o cliente em memória usa a entrada recém-gravada na auditoria local e evita repetir a ação. Em stdio, a demonstração encerra no erro de transporte. Cada passo registra a resposta do modelo, ferramenta, argumentos, resultado, duração e origem final.

## Reprodução

```bash
source .venv/bin/activate
python -m pip install -e '.[test,mcp]'
python -m oran_lab.mcp_client
oran-loop --sintetico --modo ollama --mcp --max-chamadas 6
oran-loop --sintetico --modo ollama --max-chamadas 1 --saida results/etapa5/ollama-sem-mcp/sintetico
pytest -q
ORAN_TEST_MCP_STDIO=1 pytest -q
```

O teste stdio é opcional porque depende de subprocessos com pipes funcionais. Neste ambiente, o sandbox fez a descoberta stdio expirar. A execução com a permissão de ferramenta necessária completou a descoberta e as chamadas.

## Resultados observados

- **Cliente stdio programado.** Descobriu cinco ferramentas. `consultar_historico {"limite":4}` retornou os registros 7 a 10. `solicitar_acao` registrou `alerta-5`, e a repetição recebeu recusa por duplicação. A consulta de estado confirmou o evento no servidor. Evidência em `results/etapa5/stdio.json`.
- **Qwen 2.5 1.5B com MCP.** Em seis chamadas ao modelo, o Qwen selecionou quatro consultas reais de histórico com limite quatro, duas por janela. As quatro retornaram registros. Na janela 5, o modelo pediu ampliação antes de o evento existir. O validador recusou, e o fallback Python registrou o alerta via MCP. Na janela 6, a ampliação para dois registros foi aceita como meta já atendida. O modelo repetiu a mesma consulta e nenhuma das suas propostas alterou o estado. Evidência em `results/etapa5/ollama-mcp/sintetico/`.
- **Qwen sem MCP.** Uma chamada no mesmo cenário registrou o alerta com origem Ollama. Evidência em `results/etapa5/ollama-sem-mcp/sintetico/`. As execuções demonstram o fluxo e a atribuição de resultados. Os orçamentos e os prompts diferem, e o cenário isolado é insuficiente para uma avaliação comparativa.
