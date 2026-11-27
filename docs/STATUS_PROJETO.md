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
| 5.1 | Implementada e validada localmente no Windows. Primeira execução da matriz no GitHub pendente. |
| 6 | RAG 3GPP. Aguarda autorização. |

## Implementação e decisões

- O mesmo núcleo determinístico valida propostas e verifica efeitos no estado do simulador. O agente único usa Ollama em loopback. As consultas MCP do agente são em memória. O cliente de demonstração usa um subprocesso Python por stdio com UTF-8 explícito.
- A origem, o nome, a revisão e o SHA-256 do dataset oficial são definidos em um módulo comum. O downloader verifica antes de substituir o destino. O diagnóstico consulta versões, recursos e disponibilidade local sem instalar componentes ou baixar recursos.
- A CI usa Python 3.13 em runners hospedados pelo GitHub para Ubuntu, Windows e macOS. A suíte padrão usa fixtures sintéticas, cobre MCP em memória e deixa as integrações com Ollama real e MCP stdio para execuções opcionais.
- Cada execução de validação tem saída própria. Os experimentos Linux das etapas anteriores contêm os resultados de referência. [EDA](EDA.md) · [Replay](REPLAY_DETECCAO.md) · [Simulador](ACAO_SIMULADA.md) · [Ollama](AGENTE_OLLAMA.md) · [MCP](MCP.md)

## Evidência de validação

| Ambiente | Resultado |
| --- | --- |
| Linux, Etapas 0 a 5 | 116 testes aprovados, conforme registro informado pelo pesquisador. A revisão da Etapa 5.1 ainda precisa ser validada no Linux. |
| Windows 11 AMD64, build 26300, Etapa 5.1 | Python 3.13.0, pandas 3.0.6, openpyxl 3.1.5, matplotlib 3.11.2, pytest 9.2.0 e MCP SDK 2.3.0. A suíte padrão teve 116 aprovados e 2 opcionais ignorados. Com Ollama real e MCP stdio habilitados e `-X utf8=0`, os 118 testes passaram. `pip check` reportou dependências consistentes. |
| macOS e runners GitHub, Etapa 5.1 | Validação pendente. A configuração do workflow está no repositório local. |

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

## Limitações e pendências

- Registrar os resultados por sistema quando o workflow executar no GitHub. Diferenciar problemas de runner, rede e instalação de falhas observadas nos testes.
- O detector sinaliza padrões heurísticos. A planilha carece de rótulos de falha e de denominador para interpretar PRB como percentual. A semântica temporal de `Latency` segue indeterminada.
- Os efeitos verificados pertencem ao simulador. Tempos de inferência dependem de runtime, modelo, cache e hardware. Os casos atuais servem como evidência de funcionamento. Uma conclusão comparativa exige o protocolo controlado do plano.
- A Etapa 6 é o próximo marco do [plano técnico](PLANO_LABORATORIO.md) e depende de autorização.
