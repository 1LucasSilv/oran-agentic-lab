# Status do projeto

Atualizado em 27 de novembro de 2026.

## Etapas

| Etapa | Estado e entrega |
| --- | --- |
| 0 | Aprovada. Estrutura Python, instalação editável e testes. |
| 1 | Aprovada. Leitura, auditoria e gráficos da revisão oficial. |
| 2 | Aprovada. Replay por registro e detector heurístico. |
| 3 | Aprovada. Validação, execução e verificação de ações no simulador. |
| 4 | Aprovada. Agente Ollama com propostas estruturadas, auditoria e fallback Python. |
| 5 | Aprovada. Ferramentas MCP locais e integração com o agente. |
| 5.1 | Implementada e validada localmente no Windows. Suíte padrão aprovada nos três runners do GitHub Actions. Documentação de armazenamento e desinstalação disponível. |
| 6 | Aprovada. RAG 3GPP demonstrado localmente no Windows e suíte padrão aprovada na matriz GitHub. |
| 7 | Infraestrutura de avaliação implementada. A bateria final aguarda autorização. |
| 7.1 | Proposta futura de interface web local para acompanhar e gerenciar o laboratório. |

## Implementação e decisões

- O mesmo núcleo determinístico valida propostas e verifica efeitos no estado do simulador. O agente único usa Ollama em loopback. As consultas MCP do agente são em memória. O cliente de demonstração usa um subprocesso Python por stdio com UTF-8 explícito.
- A origem, o nome, a revisão e o SHA-256 do dataset oficial são definidos em um módulo comum. O downloader verifica antes de substituir o destino. O diagnóstico consulta versões, recursos e disponibilidade local sem instalar componentes ou baixar recursos.
- A CI usa Python 3.13 em runners hospedados pelo GitHub para Ubuntu, Windows e macOS. A suíte padrão usa fixtures sintéticas, cobre MCP em memória e deixa as integrações com Ollama real e MCP stdio para execuções opcionais.
- O RAG opcional usa PDFs de duas revisões oficiais, índice cosseno local e embeddings via Ollama. Os trechos entram sob orçamento antes da inferência final. A auditoria das referências é separada da proposta operacional. [Corpus, configuração e resultados](RAG.md)
- Cada execução de validação tem saída própria. Os experimentos Linux das etapas anteriores contêm os resultados de referência. [EDA](EDA.md) · [Replay](REPLAY_DETECCAO.md) · [Simulador](ACAO_SIMULADA.md) · [Ollama](AGENTE_OLLAMA.md) · [MCP](MCP.md)

## Evidência de validação

| Ambiente | Resultado |
| --- | --- |
| Linux, Etapas 0 a 5 | 116 testes aprovados, conforme registro informado pelo pesquisador. |
| Windows 11 AMD64, build 26300, Etapa 5.1 | Python 3.13.0, pandas 3.0.6, openpyxl 3.1.5, matplotlib 3.11.2, pytest 9.2.0 e MCP SDK 2.3.0. A suíte padrão teve 116 aprovados e 2 opcionais ignorados. Com Ollama real e MCP stdio habilitados e `-X utf8=0`, os 118 testes passaram. `pip check` reportou dependências consistentes. |

### GitHub Actions

Em 27 de novembro de 2026, a execução #1 do workflow Testes foi disparada por push na `main` para o commit `7aadfba4ce99ea88633b43e64a6d70e078d3bde1`. A instalação editável e o pytest terminaram com sucesso nos três jobs. [Execução #1](https://github.com/1LucasSilv/oran-agentic-lab/actions/runs/46023193720)

| Runner | CPython | Resultado do pytest |
| --- | --- | --- |
| [ubuntu-latest](https://github.com/1LucasSilv/oran-agentic-lab/actions/runs/46023193720/job/140587797292) | 3.13.18 | 116 aprovados, 2 ignorados |
| [windows-latest](https://github.com/1LucasSilv/oran-agentic-lab/actions/runs/46023193720/job/140587797385) | 3.13.17 | 116 aprovados, 2 ignorados |
| [macos-latest](https://github.com/1LucasSilv/oran-agentic-lab/actions/runs/46023193720/job/140587796756) | 3.13.17 | 116 aprovados, 2 ignorados |

Os dois testes opcionais usam Ollama real e MCP stdio. A matriz cobre a suíte padrão com fixtures sintéticas e MCP em memória.

Na execução #3, para o commit da Etapa 6 `b8cd69b`, Ubuntu, Windows e macOS tiveram 138 testes aprovados e 2 opcionais ignorados em cada runner. [Execução #3](https://github.com/1LucasSilv/oran-agentic-lab/actions/runs/46031000295)

### Execuções locais no Windows

No Windows foram usados Intel Core i5-1235U, 12 CPUs lógicas e 16 GiB de RAM. O Ollama 0.40.18 disponibilizou `qwen2.5:1.5b`, digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`. Os primeiros testes sob sandbox encontraram erros de permissão no diretório temporário do pytest, nos diretórios de preparação e nos pipes. A validação prosseguiu em execuções autorizadas fora do sandbox.

O diagnóstico reconheceu a instalação completa e sinalizou dependências, arquivo e tag ausentes em um teste com o interpretador sem as dependências do ambiente virtual. O download em destino separado passou na verificação de SHA-256. A verificação local preservou o original. Os testes sintéticos do downloader cobrem a recusa de conteúdo incorreto, limpeza temporária e reaproveitamento do arquivo válido.

| Execução Windows | Resultado observado |
| --- | --- |
| EDA e replay oficiais | EDA gerou relatório e gráficos. O replay leu 1.138 registros KPM e emitiu 38 janelas, uma parcial, com zero alertas. |
| Python sintético | Oito janelas, oito propostas aceitas e um alerta registrado. |
| Ollama sintético | Duas chamadas HTTP 200, zero fallbacks e um alerta registrado por proposta do modelo. |
| Demonstração MCP stdio | Cinco ferramentas descobertas. O simulador aceitou o registro e recusou a duplicação. |
| Ollama com MCP em memória | Seis chamadas ao modelo, quatro consultas de histórico concluídas e um fallback que registrou o alerta após a recusa de uma ampliação sobre evento inexistente. |

Os artefatos locais da validação estão em `results/etapa5.1/windows/`. As medições do Windows ficam nesse diretório, separado dos experimentos Linux anteriores.

### Etapa 6 no Windows

Com Python 3.13.0, PyPDF 6.10.2 e Ollama 0.40.18, a revisão oficial de cada PDF passou no SHA-256, na verificação da capa e na contagem de páginas. O índice gerou 15 fragmentos de seis cláusulas com vetores de dimensão 768. O índice e os PDFs estão em `data/rag/`. Os artefatos de execução estão em `results/etapa6/windows/`.

No par sintético com o mesmo Qwen, o modo sem RAG registrou o alerta por proposta do modelo. Com RAG, os dois IDs propostos nas janelas 5 e 6 correspondiam aos trechos de entrada. O validador recusou a ação da primeira janela sobre um evento que ainda não existia. O fallback registrou o alerta. Na janela 6, a proposta com citações passou pelo validador e ficou sem efeito adicional no simulador. Com MCP e RAG, houve uma consulta MCP concluída e a decisão final da janela selecionada foi de fallback. [Resultados e protocolo da demonstração](RAG.md#validação-observada)

A suíte padrão da Etapa 6 teve 138 testes aprovados e 2 opcionais ignorados. Com Ollama real e MCP stdio habilitados e `-X utf8=0`, os 140 testes passaram. A instalação editável com `.[test,mcp,rag]` e o `pip check` também passaram.

### Etapa 7 no Windows

O piloto em `results/etapa7/piloto-20261127/` avaliou dez oportunidades e encerrou com 12 chamadas de chat. Três de oito propostas originais dos agentes concordaram com a expectativa. Houve cinco recusas e cinco fallbacks. As dez decisões finais concordaram com as ações pré-fixadas. Quatro consultas MCP acrescentaram dados históricos segundo o critério estrutural. Um agente concluiu com referência conferida, no modo E. As pontuações humanas seguem vazias. [Protocolo e resultados do piloto](EXPERIMENTOS.md)

A referência Python no Excel oficial escolheu `nenhuma_acao` nas janelas 1 e 4 conforme o protocolo, com zero chamadas de chat. O plano A–E exploratório ficou em `results/etapa7/excel-planejado/`, e a execução A em `results/etapa7/excel-python/`. O plano final controlado está em `results/etapa7/final-planejado/`, com 90 sessões e teto de 108 chamadas. Nenhuma sessão final foi iniciada.

A suíte padrão local teve 147 testes aprovados e 2 opcionais ignorados. A instalação editável disponibilizou `oran-experiment` e o `pip check` confirmou as dependências. A matriz GitHub conserva as fixtures sintéticas e os três runners.

## Limitações e pendências

- As integrações opcionais com Ollama e MCP stdio têm evidência local no Windows para a Etapa 5.1. A execução do GitHub Actions cobre a suíte padrão.
- O detector sinaliza padrões heurísticos. A planilha carece de rótulos de falha e de denominador para interpretar PRB como percentual. A semântica temporal de `Latency` segue indeterminada.
- Os efeitos verificados pertencem ao simulador. Tempos de inferência dependem de runtime, modelo, cache e hardware. Os casos atuais servem como evidência de funcionamento. Uma conclusão comparativa exige o protocolo controlado do plano.
- A CI publicou resultados até a Etapa 6. A revisão da Etapa 7 aguarda execução na matriz.
- A bateria final da Etapa 7 e a futura interface da Etapa 7.1 dependem de autorização. [Plano técnico](PLANO_LABORATORIO.md)
