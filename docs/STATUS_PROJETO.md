# Status do projeto

Atualizado em 27 de novembro de 2026.

## Fases da pesquisa

- **Fase I — IA Agêntica aplicada à análise e decisão em redes 5G O-RAN.** Prioritária, será concluída de forma independente. Abrange as Etapas 0 a 8, incluindo 5.1 e 7.1, e avalia conformidade operacional, capacidade investigativa, fundamentação técnica, segurança e custo computacional sobre KPMs históricos. As ações ficam restritas ao simulador.
- **Fase II — Controle e otimização de redes 5G O-RAN.** Opcional, com Etapas 9 a 14 propostas e autorização específica pendente. OpenAirInterface, RFSim, 5G Core e FlexRIC são candidatos para avaliação futura de viabilidade. [Etapas propostas](PLANO_LABORATORIO.md)

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
| 7 | Bateria controlada final executada e consolidada. Avaliação humana pendente. |
| 7.1.1 | Aprovada funcionalmente. Matriz GitHub do commit `2c9acaa` aprovada, conforme registro informado pelo pesquisador. |
| 7.1.2 | Gerenciamento de recursos, experimentos e navegação implementados e validados localmente no Windows. |
| 7.1.3 | Central de execução, resultados, avaliação científica e modo apresentação implementados. |

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

Na execução #5, para o commit dos ajustes pré-bateria `b14eccc`, Ubuntu, Windows e macOS tiveram 152 testes aprovados e 2 opcionais ignorados em cada runner. [Execução #5](https://github.com/1LucasSilv/oran-agentic-lab/actions/runs/46047810873)

A CI do commit `3bf9b00`, que introduziu gerenciamento de recursos e experimentos na interface, terminou com sucesso conforme informado pelo pesquisador. A matriz permanece configurada para Ubuntu, Windows e macOS.

A CI do commit `0a15770`, com o refinamento da Etapa 7.1.2, terminou com sucesso conforme informado pelo pesquisador. A matriz da Etapa 7.1.3 aguarda execução.

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

A referência Python no Excel oficial escolheu `nenhuma_acao` nas janelas 1 e 4 conforme o protocolo, com zero chamadas de chat. O plano A–E exploratório ficou em `results/etapa7/excel-planejado/`, e a execução A em `results/etapa7/excel-python/`. O plano histórico em `results/etapa7/final-planejado/` foi preservado. A bateria definitiva usou outro plano, gerado no commit `b14eccc`.

A bateria final agora exige pré-verificação do serviço, dos modelos e do índice conforme a configuração. Os recursos locais foram conferidos sem chamadas de inferência. Os novos gráficos e a consolidação humana foram verificados em uma cópia do piloto, com os resultados originais preservados. O exportador inclui o estado autorizado e as ações disponíveis. O relatório separa critérios principais de documentais e distingue ausências de zero. Nenhuma avaliação humana foi importada.

A suíte padrão local teve 147 testes aprovados e 2 opcionais ignorados. A instalação editável disponibilizou `oran-experiment` e o `pip check` confirmou as dependências. A matriz GitHub conserva as fixtures sintéticas e os três runners.

Após os ajustes pré-bateria, a suíte padrão local teve 152 testes aprovados e 2 opcionais ignorados. O `pip check` passou.

A bateria final em `results/etapa7/final-revisao-definitiva/` concluiu **90 sessões com 108 chamadas únicas e 108 retornos HTTP 200**. Houve 15 propostas originais concordantes em 72 oportunidades do modelo, 56 recusas, uma resposta incompleta e 57 fallbacks. As 90 decisões finais concordaram com o protocolo. As 30 mudanças verificadas no simulador vieram de 15 decisões do modelo, 9 fallbacks e 6 decisões da referência Python. A consolidação preserva os resultados por configuração, cenário e semente. [Resultados e limitações](EXPERIMENTOS.md#bateria-controlada-final)

### Etapa 7.1.1 no Windows

A interface abriu em 127.0.0.1:8501. O worker Python verificou pausa, avanço e continuação e concluiu oito janelas. O worker com Qwen, MCP e RAG gravou oito janelas e quatro chamadas HTTP 200. A demonstração preservou o resultado completo e registrou um bloqueio concorrente ao publicar o status final. O teste de regressão cobre a tentativa adicional de publicação. A revisão local preservou o manifesto e as 108 reservas da bateria científica. [Interface e evidências](INTERFACE.md#demonstrações-locais)

A revalidação Python publicou a conclusão sob leitura concorrente. A suíte padrão local teve 160 aprovados e dois opcionais ignorados. O `pip check` passou e as quatro páginas foram capturadas.

### Etapa 7.1.2 no Windows

Windows 11 AMD64, Python 3.13.0 e Ollama 0.40.18. A suíte padrão teve **171 testes aprovados e 2 opcionais ignorados** e o `pip check` confirmou as dependências. AppTest navegou pelas nove páginas. Fixtures verificaram a auditoria de CSV e XLSX, a imutabilidade, a identidade de modelos e índices, a trava e a execução controlada A–E com clientes simulados. As nove capturas foram gravadas localmente. A matriz desta revisão ainda aguarda execução.

O experimento Python controlado concluiu uma sessão sem chat. A execução E concluiu oito janelas com quatro chamadas de chat e publicou o estado final durante a consulta concorrente. Houve um fallback que registrou o alerta e uma decisão do modelo aceita sem efeito. O plano da bateria científica preservou o hash lógico `78205810072de392475bb07445ea843bdfcc4996c67b049cb376bffbdac30498` e as 108 reservas. [Demonstrações e IDs](INTERFACE.md#etapa-712-no-windows)

O refinamento acrescentou a barra lateral de 250 px com recolhimento nativo, rascunhos persistentes na sessão, tratamentos com geradores distintos e interrupção cooperativa. No Windows 11 com Python 3.13.0, a suíte padrão teve **175 aprovados e 2 opcionais ignorados** e o `pip check` passou. A verificação usou fixtures e resultados já gravados. A recomputação em memória reproduziu as 144 linhas pareadas do relatório histórico, com 90 oportunidades e 108 reservas. O Chrome verificou foco, hover e recolhimento. As capturas de 1520×1020, 1024×800 e 430×900 estão em `results/ui/capturas/refinamento-7.1.2/`.

### Etapa 7.1.3 no Windows

Windows 11 AMD64 com Python 3.13.0. A suíte padrão teve **179 testes aprovados e dois opcionais ignorados**. O `pip check` passou. AppTest conferiu a renderização e a navegação. Os testes verificaram equivalência de decisões e chamadas com e sem diário, prefixo causal, reservas durante processamento, leitura de registros antigos e importação de avaliações parciais.

O experimento Python `89941cc9baab4a32b45f42f0093307f2` concluiu uma sessão em ciclo completo com oito janelas, 82 eventos e zero chamadas de chat. A execução operacional E `6a0903d843de48b18b700d996a1a3723` foi reproduzida no navegador até a janela 6, com retrocesso confirmado à decisão da janela 5. A interface abriu as 89 respostas anonimizadas da bateria de referência. Notas e importações de teste usaram fixtures. O plano de referência preservou seu hash lógico e as 108 reservas. As capturas ficam em `results/ui/capturas/etapa7.1.3/`.

## Limitações e pendências

- As integrações opcionais com Ollama e MCP stdio têm evidência local no Windows para a Etapa 5.1. A execução do GitHub Actions cobre a suíte padrão.
- O detector sinaliza padrões heurísticos. A planilha carece de rótulos de falha e de denominador para interpretar PRB como percentual. A semântica temporal de `Latency` segue indeterminada.
- Os efeitos verificados pertencem ao simulador. O desenho controlado usa seis cenários sintéticos e repetições técnicas. Tempos de inferência dependem de runtime, modelo, cache e hardware.
- A avaliação humana das 89 respostas exportadas permanece pendente.
- Arquivos antigos só exibem os eventos, métricas e horários que registraram. Comparações entre execuções com protocolos ou recursos distintos são descritivas.
- Diagnóstico e validação pela interface aguardam autorização da Etapa 8. [Plano técnico](PLANO_LABORATORIO.md#etapa-71--requisitos-da-interface-web-local)
