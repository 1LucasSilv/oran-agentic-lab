# Plano de desenvolvimento — Laboratório de IA Agêntica para Redes 5G Open RAN

**Identificador do projeto:** `oran-agentic-lab`  
**Estado:** Etapas 0 a 6 aprovadas, incluindo 5.1. Bateria controlada da Etapa 7 executada e consolidada. Avaliação humana pendente. [Status e evidências](STATUS_PROJETO.md)\
**Abordagem:** protótipo pequeno, incremental, funcional e reproduzível  
**Ambiente de trabalho:** Python, VS Code + Codex e GitHub. Windows e Linux têm evidências locais nas revisões registradas. A matriz com Windows, Linux e macOS usa Python 3.13.

## 1. Visão geral

### Fase I — IA Agêntica aplicada à análise e decisão em redes 5G O-RAN

A Fase I compreende as Etapas 0 a 8, incluindo 5.1 e 7.1. Seu objetivo é avaliar conformidade operacional, capacidade investigativa, fundamentação técnica, segurança e custo computacional de agentes com MCP e RAG sobre dados históricos de redes 5G. As ações ficam restritas ao simulador. Esta fase é prioritária e será concluída independentemente da Fase II.

Desenvolver e avaliar um **protótipo de análise e resposta assistida por SLM/LLM** usando métricas KPM históricas de uma rede 5G experimental. O sistema deverá ler os dados, detectar situações potencialmente anormais, investigar o contexto, **propor uma ação**, executá-la no **simulador de software** após validação e verificar os efeitos que podem ser observados nesse simulador.

**Ciclo:** `Observar → Detectar → Investigar → Decidir → Validar → Agir → Verificar`.

### O que está fora do escopo da Fase I

- Construir xApps, rApps, Near-RT RIC ou ambiente 5G real.
- Enviar comandos para O-DU/O-CU/gNB/UE reais.
- Demonstrar ganho real de throughput/latência produzido por uma ação aplicada sobre o dataset histórico.
- Treinar ou ajustar um LLM no início do projeto.
- Criar sistema multiagente complexo antes de validar um único agente.

### Fase II — Controle e otimização de redes 5G O-RAN

Possibilidade de expansão futura, opcional e sujeita a autorização específica. OpenAirInterface, RFSim, 5G Core e FlexRIC são tecnologias candidatas para uma futura avaliação de viabilidade.

| Etapa | Proposta futura |
| --- | --- |
| 9 | Implantação de rede 5G experimental |
| 10 | Coleta contínua de KPMs e geração controlada de congestionamento |
| 11 | Integração de mecanismos de controle O-RAN |
| 12 | Controle em malha fechada com IA Agêntica |
| 13 | Experimentos de desempenho e mitigação de congestionamento |
| 14 | Consolidação científica da pesquisa ampliada |

## 2. Questões que orientam o laboratório

1. KPMs históricos permitem identificar e explicar **condições que merecem investigação** utilizando regras simples e modelos de linguagem?
2. Um LLM pode **selecionar ferramentas e recomendar ações apropriadas** em cenários definidos, respeitando as restrições do simulador?
3. **RAG com trechos 3GPP** melhora a qualidade técnica das explicações e decisões em relação ao **mesmo modelo geral sem RAG**?
4. Qual o custo de introduzir o agente (latência, recursos e falhas de decisão) em comparação com uma referência determinística?

Não chamar eventos de “falhas comprovadas” sem rótulos ou evidências verificáveis; critérios heurísticos devem ser declarados como tais.

## 3. Fontes de dados e documentação

### 3.1 Dataset principal — KPM de xApp

- **Origem:** <https://github.com/CTTCADAPTRU/OAI-KPM-dataset>
- **Ambiente descrito:** OpenAirInterface 5G Core/gNB, FlexRIC, KPM xApp, UEs emulados e `iperf3`.
- **Formato disponibilizado:** arquivo `.xlsx`, com dados KPM e tráfego. O README cita exemplos de abas `KPM Metrics` e `iperf3 Traffic`, **a confirmar no arquivo real**.
- **Volume informado no README:** cerca de 10.080 amostras ao longo de cinco semanas; **não tratar como número auditado antes de abrir a planilha**.
- **Métricas documentadas:**
  - `Register`, `UE.Id`, `Latency`;
  - `RRU.PrbTotDl`, `RRU.PrbTotUl`;
  - `DRB.PdcpSduVolumeDL`, `DRB.PdcpSduVolumeUL`;
  - `DRB.RlcSduDelayDl`;
  - `DRB.UEThpDl`, `DRB.UEThpUl`.
- **Licença no repositório:** CC0-1.0; registrar a versão/revisão do repositório para rastreabilidade acadêmica.

**Auditoria obrigatória antes do uso:** listar abas e colunas, unidades, tipos, valores faltantes, duplicatas, timestamps, frequência de amostragem e possibilidades reais de alinhar KPMs e tráfego. Não assumir que PRBs representam percentuais. Medição de latência/throughput não implica diagnóstico automático de congestionamento.

### 3.2 Notebook do Miguel e documentos 3GPP

Referência fornecida: `lab_TSpec.ipynb`. O notebook explora **Qwen 2.5 7B Instruct, Ollama, RAG, LlamaIndex, embeddings e FAISS**. **Não há demonstração de fine-tuning no código**. Ele também contém tentativas de download/indexação que não devem ser consideradas execução bem-sucedida sem validação.

A Etapa 6 usa cláusulas selecionadas da TS 28.552 V18.7.0 e da TS 38.300 V18.4.0. O manifesto fixa revisão e SHA-256. PyPDF e embeddings Ollama geram um índice local, com referências por fragmento, versão, seção e página. As citações são auditadas antes de passar a proposta de ação ao validador. [Corpus, operação e auditoria](RAG.md)

### 3.3 Dataset antigo

`Lower_Layer_Data.db` (NetsLab-5GORAN-IDD) fica **fora do MVP**. Guardar como opção futura para estudos de rádio/segurança; **não misturar os datasets neste primeiro experimento**.

## 4. Arquitetura funcional

```text
OAI-KPM-dataset (.xlsx)
         │
         ▼
[Leitor + validação + armazenamento local]
         │
         ▼
[Reprodutor de janelas por Register]
         │
         ▼
[Detector de referência — regras/estatística]
         │
         ▼
[Política Python ou agente Ollama — propõe ações]
   │                  │
   │                  ├── consulta de histórico via MCP (opcional)
   │                  └── RAG 3GPP opcional (índice local)
   ▼
[Validador determinístico de ações]
         │
         ▼
[Executor de ações no simulador]
         │
         ▼
[Verificador + registros + resultados]
```

**Observação:** a decisão por regras, antes da inclusão do LLM, usa o mesmo validador/executor. **MCP não coleta KPMs diretamente da RAN**: no laboratório, expõe ferramentas locais para o agente consultar dados e ações. A coleta original já foi feita pela xApp do repositório.

## 5. Cenário mínimo de análise e reação

### Problema

Uma janela de medições apresenta **piora de latência e/ou throughput, contextualizada por utilização de recursos e histórico**. O detector indica uma *condição suspeita* de desempenho; não declara falha definitiva sem evidências.

### Primeiras ações permitidas

| Ação do simulador | Mudança verificável | Restrição |
|---|---|---|
| `registrar_alerta` | Evento persistido com causa e evidências | Evitar duplicação excessiva |
| `priorizar_evento` | Prioridade de análise alterada | Permitir apenas níveis pré-definidos |
| `ampliar_janela_analise` | Mais registros históricos são analisados | Tamanho máximo e orçamento limitados |
| `ativar_monitoramento_intensificado` | Alterar frequência de inspeção/reprodução dos registros históricos | Não afirmar nova coleta real |
| `nenhuma_acao` | Registra decisão justificada sem alteração | Aceitar quando evidências insuficientes |

Ação inicial recomendada: **ampliar a janela de análise** após alerta persistente, recuperar contexto e verificar se a decisão ficou mais bem fundamentada e qual foi o custo adicional. Pode-se começar ainda mais simples com `registrar_alerta` e `nenhuma_acao`.

### O que será medido

- Proporção de casos em que o sistema detecta um padrão sob uma **regra/gabarito experimental previamente definido**.
- Conformidade da ação com restrições; ações negadas; justificativa; estado antes/depois.
- Quantidade de registros consultados, tempo de decisão e tempo total do ciclo.
- Consistência da interpretação e qualidade técnica avaliada com **rubrica explícita**.
- **Não medir suposta melhoria da rede real** a partir de ações no replay histórico.

## 6. Cronograma da Fase I e critérios de aceite

| Etapa | Entrega | Critério verificável de conclusão | Commit sugerido |
|---|---|---|---|
| **0. Base** | Estrutura mínima, `venv`, `README`, dependências, testes iniciais | Ambiente instala e `pytest` executa | `chore: inicia estrutura do laboratorio` |
| **1. Dados** | Leitura de `.xlsx`, inspeção de abas/colunas, gráficos e relatório EDA | Excel real carregado ou testes com fixture claramente marcada; unidades/limitações documentadas | `feat: adiciona exploracao de KPIs` |
| **2. Reprodução e detecção** | Replay de janelas, baseline de regras, registro de alertas | O mesmo conjunto produz resultados reproduzíveis; não utiliza rótulos inventados | `feat: adiciona replay e detector de referencia` |
| **3. Loop sem LLM** | Estado do simulador, validação de ações e verificação | Caso controlado altera o simulador; casos inválidos são bloqueados; estado antes/depois registrado | `feat: implementa ciclo de acao simulada` |
| **4. Agente Ollama** | Decisão assistida por modelo, JSON estruturado e fallback | Modelo pode propor ação; saída inválida é bloqueada; execução não depende de resposta insegura | `feat: integra agente ollama ao ciclo` |
| **5. MCP** | Servidor e cliente MCP local, ferramentas de consulta/ação | Testes de chamadas e parâmetros; ações sempre passam pelo validador | `feat: disponibiliza ferramentas mcp` |
| **5.1. Portabilidade e reprodutibilidade** | README autossuficiente, scripts de preparação, diagnóstico e CI | Dataset com revisão e SHA-256, scripts e suíte validados localmente, workflow preparado para Ubuntu, Windows e macOS, evidências por sistema no status | `chore: melhora portabilidade e reprodutibilidade do laboratorio` |
| **6. RAG 3GPP** | Corpus verificado, índice cosseno local e contexto documental opcional com ou sem MCP | Respostas identificam referências apresentadas por versão, seção e página. A falta de contexto e citações inválidas são auditadas. | `feat: adiciona consulta rag a normas 3gpp` |
| **7. Comparação** | Protocolo A–E, decisão controlada e ciclo completo, piloto, auditoria e revisão humana | Casos congelados, orçamento auditável, piloto e plano final documentados | `feat: adiciona avaliacao experimental reproduzivel` |
| **7.1.1. Interface base, configuração e monitoramento** | Streamlit e Plotly em loopback, com worker local e inspeção do agente | Configuração imutável, controles por janela e eventos de execução local verificáveis | `feat: adiciona interface operacional local` |
| **7.1.2. Gerenciamento de recursos e experimentos** | Gerenciar recursos, presets e experimentos pela interface | Novas execuções preservam os protocolos e manifestos existentes | A definir após autorização |
| **7.1.3. Resultados, avaliação científica e modo de apresentação** | Consultar resultados, avaliação e apresentação | Relatórios e avaliações humanas identificados por execução | A definir após autorização |
| **8. Consolidação** | Relatório curto, gráficos, documentação e instruções de reprodução | Terceiro consegue reproduzir o fluxo com dados disponíveis | `docs: consolida resultados do laboratorio` |

### Marco de entrega prioritário (MVP)

**Etapas 0–4**, mantendo somente **um agente**. Ao final, teremos um ciclo verificável **detecção → decisão → validação → ação simulada → verificação**. MCP e RAG são adicionados sem reescrever o núcleo.

## 7. Comparação experimental

| Configuração | Política | MCP | RAG 3GPP |
| --- | --- | --- | --- |
| A | Python determinística | — | — |
| B | Qwen 2.5 1.5B | — | — |
| C | Mesmo Qwen | — | Sim |
| D | Mesmo Qwen | Sim | — |
| E | Mesmo Qwen | Sim | Sim |

O protocolo avalia propostas originais e decisões finais em modo controlado e em ciclo completo. A fase de piloto usa casos próprios. A fase final controlada usa seis casos fixos, sementes 42/43/44 e teto de 108 chamadas de chat, incluindo uma decisão final e até uma seleção MCP por oportunidade. O Excel oficial entra em análise exploratória separada, com janelas pré-selecionadas e classificação heurística. [Casos, orçamento e rubrica](EXPERIMENTOS.md)

### Cuidados para comparação justa

- Usar **casos fixos** e expectativas de ação definidas antes das inferências; quando houver rótulo, documentar sua origem.
- Evitar vazamento temporal ou alteração das condições entre execuções.
- Registrar modelo e versão, quantização, `temperature`, `seed` quando suportados, hardware, prompt, janelas, documentos e parâmetros.
- Medir: adequação da recomendação, segurança, consistência, latência, consultas realizadas, custo de processamento e justificativa técnica.
- Acurácia/F1-score só com **verdade de referência independente e válida**; avaliação por especialista deve ser explicitada como tal.
- Não assumir que RAG sempre melhora a resposta ou que maior modelo será mais adequado ao hardware.

### Etapa 7.1 — Requisitos da interface web local

- Selecionar dinamicamente os modelos instalados no Ollama e configurar MCP e RAG de forma independente.
- Alterar parâmetros de inferência, replay, detector e simulador entre execuções.
- Gerenciar modelos e índices RAG, importar datasets compatíveis, criar cenários sintéticos personalizados e salvar presets reutilizáveis.
- Monitorar visualmente replay, detector, agente, MCP, RAG, validador e simulador.
- Oferecer modos de apresentação, exploração e avaliação científica.
- Preservar identificadores de execução, manifestos e configurações científicas. Novos experimentos terão suas próprias configurações e manifestos. O protocolo da bateria controlada atual permanece preservado.

A Etapa 7.1.1 cobre configuração operacional, monitoramento e inspeção. Consulte o [guia da interface](INTERFACE.md). As demais entregas pertencem às Etapas 7.1.2 e 7.1.3 e dependem de autorização específica.

## 8. Ferramentas, dependências e recursos

**Essenciais para o modo Python:** Python, `venv`, `pip`, `pandas`, `openpyxl` e `matplotlib`. Use Git para clonar ou obtenha o código em ZIP.

**Por modo:** pytest para testes, Ollama e uma tag local para inferência, MCP Python SDK para ferramentas MCP. A planilha oficial só é necessária para execuções com os dados reais. Bibliotecas de recuperação documental ficam para a etapa correspondente.

A CI instala `.[test,mcp,rag]` e roda a suíte padrão com planilhas e PDFs sintéticos. As integrações reais com Ollama e MCP stdio são opcionais. O workflow usa runners hospedados pelo GitHub com permissão de leitura, sem dependência do runtime operacional.

O modelo para o MVP deve ser **configurável**. Testar um SLM pequeno localmente primeiro; Qwen 2.5 7B é candidato de comparação **somente se o equipamento comportar** ou houver ambiente computacional apropriado.

Não instalar Docker, Core 5G, gNB, FlexRIC, Near-RT RIC, ferramentas de GPU, OpenTelemetry ou stack multiagente sem justificativa concreta para a etapa.

## 9. Organização sugerida do repositório

**Criar de modo progressivo** (não gerar todas as pastas vazias na etapa 0):

```text
oran-agentic-lab/
├── AGENTS.md
├── README.md
├── .gitignore
├── pyproject.toml            # ou requirements.txt; escolher um fluxo simples
├── docs/
│   ├── PLANO_LABORATORIO.md
│   ├── DECISOES.md            # criar quando houver decisões importantes
│   └── RESULTADOS.md          # etapa de avaliação
├── data/
│   ├── raw/                  # .xlsx de origem; não versionar por padrão
│   └── processed/            # derivados reprodutíveis
├── src/oran_lab/
│   ├── data.py
│   ├── replay.py
│   ├── detector.py
│   ├── simulator.py
│   ├── agent.py
│   ├── mcp_server.py        # somente na etapa 5
│   ├── rag.py               # somente na etapa 6
│   └── evaluation.py        # quando necessário
├── tests/
└── results/                 # execuções e gráficos gerados
```

O prompt completo para o ChatGPT Project pode ficar **fora do repositório**, em `PROMPT_PROJETO_CHATGPT.md`; o Codex deve seguir `AGENTS.md` e este plano. Evitar importar o notebook inteiro para produção.

## 10. Versionamento e dados

- Git na máquina local; GitHub como repositório remoto.
- `main` estável; branches de funcionalidade **quando forem úteis**, sem burocracia desnecessária.
- Versionar scripts, testes, documentação e **configurações experimentais pequenas**.
- Por padrão ignorar: `data/raw/`, `data/processed/`, `results/`, `.venv/`, caches e `.env`.
- Documentar **URL, revisão/commit, nome do Excel, data de acesso, licença e SHA-256** para permitir reproduzir os experimentos. O downloader verifica o conteúdo antes de publicar o arquivo.
- Não realizar `git push`, commits, remoções de arquivo ou publicação de dados sem autorização.
- Nunca colocar senha ou token em fonte, prompt, relatório ou commit.

## 11. Modo de trabalho e acompanhamento

O Codex pode implementar **módulos completos por etapa**. O pesquisador participa de decisões, execução, conferência dos resultados e entendimento do funcionamento, **não de cada linha**.

Consulte e atualize o [status do projeto](STATUS_PROJETO.md) a cada etapa. Registre as versões e os resultados observados por sistema. A análise da bateria controlada continua com a avaliação humana prevista.

Ao terminar uma etapa, entregar:

1. lista de arquivos criados/alterados;
2. comandos de execução;
3. testes realizados e resultado observado (ou limitação de execução);
4. explicação curta das funções e escolhas técnicas mais importantes;
5. evidência do critério de aceite;
6. pendências, próxima etapa e mensagem sugerida de commit.

**Não avançar automaticamente** para a próxima grande etapa. **Não deixar a etapa autorizada pela metade** quando houver meios de completá-la.

## 12. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Poucos dados ou pouca granularidade | Validar periodicidade real; usar janelas adequadas, sem inventar amostras reais |
| Ausência de rótulos de anomalias | Definir cenários e rubrica de referência; separar anomalias heurísticas de falhas reais |
| Modelo lento ou pesado | Iniciar com SLM menor, prompts curtos, análise por evento e hardware medido |
| Interpretação errada de PRBs e unidades | Conferir especificação da métrica antes de calcular limiares ou percentuais |
| Ação simulada confundida com ação em rede | Exibir explicitamente o estado do simulador; não reivindicar ganho na RAN real |
| Complexidade de MCP/RAG | Garantir MVP sem essas tecnologias; adicionar por interfaces desacopladas |
| Evidência técnica inexistente para decisão | Permitir saída `evidencia_insuficiente` e `nenhuma_acao` |

## 13. Referências de projeto

- [Dataset OAI-KPM (CTTCADAPTRU)](https://github.com/CTTCADAPTRU/OAI-KPM-dataset)
- [Model Context Protocol — documentação](https://modelcontextprotocol.io/)
- [Ollama — documentação](https://docs.ollama.com/)
- Notebook de referência (arquivo local fornecido): `lab_TSpec.ipynb`

As execuções de referência estão documentadas no [relatório de replay e detecção](REPLAY_DETECCAO.md) e no [relatório do ciclo de ação simulada](ACAO_SIMULADA.md). A Etapa 4 integra um agente Ollama à mesma interface de propostas, com validação local, auditoria e fallback Python. A Etapa 5 disponibiliza consultas e ações locais pelo protocolo MCP. [Integração MCP](MCP.md) [Experimentos com o agente](AGENTE_OLLAMA.md)
