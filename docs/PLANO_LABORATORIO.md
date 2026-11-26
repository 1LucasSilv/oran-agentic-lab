# Plano de desenvolvimento — Laboratório de IA Agêntica para Redes 5G Open RAN

**Identificador do projeto:** `oran-agentic-lab`  
**Estado:** Etapas 0 a 4 implementadas\
**Abordagem:** protótipo pequeno, incremental, funcional e reproduzível  
**Ambiente de trabalho:** Linux, Python, VS Code + Codex e GitHub

## 1. Visão geral

Desenvolver e avaliar um **protótipo de análise e resposta assistida por SLM/LLM** usando métricas KPM históricas de uma rede 5G experimental. O sistema deverá ler os dados, detectar situações potencialmente anormais, investigar o contexto, **propor uma ação**, executá-la no **simulador de software** após validação e verificar os efeitos que podem ser observados nesse simulador.

**Ciclo:** `Observar → Detectar → Investigar → Decidir → Validar → Agir → Verificar`.

### O que está fora do escopo

- Construir xApps, rApps, Near-RT RIC ou ambiente 5G real.
- Enviar comandos para O-DU/O-CU/gNB/UE reais.
- Demonstrar ganho real de throughput/latência produzido por uma ação aplicada sobre o dataset histórico.
- Treinar ou ajustar um LLM no início do projeto.
- Criar sistema multiagente complexo antes de validar um único agente.

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

A etapa documental deve usar **poucos documentos 3GPP pertinentes aos KPMs**, registrar título/versão/cláusula/fonte e separar trechos recuperados de interpretações do LLM. Não importar configurações de acesso remoto ou segredos do notebook.

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
   │                  ├── consulta de histórico via MCP (fase posterior)
   │                  └── RAG 3GPP opcional (fase posterior)
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

## 6. Cronograma por etapas e critérios de aceite

| Etapa | Entrega | Critério verificável de conclusão | Commit sugerido |
|---|---|---|---|
| **0. Base** | Estrutura mínima, `venv`, `README`, dependências, testes iniciais | Ambiente instala e `pytest` executa | `chore: inicia estrutura do laboratorio` |
| **1. Dados** | Leitura de `.xlsx`, inspeção de abas/colunas, gráficos e relatório EDA | Excel real carregado ou testes com fixture claramente marcada; unidades/limitações documentadas | `feat: adiciona exploracao de KPIs` |
| **2. Reprodução e detecção** | Replay de janelas, baseline de regras, registro de alertas | O mesmo conjunto produz resultados reproduzíveis; não utiliza rótulos inventados | `feat: adiciona replay e detector de referencia` |
| **3. Loop sem LLM** | Estado do simulador, validação de ações e verificação | Caso controlado altera o simulador; casos inválidos são bloqueados; estado antes/depois registrado | `feat: implementa ciclo de acao simulada` |
| **4. Agente Ollama** | Decisão assistida por modelo, JSON estruturado e fallback | Modelo pode propor ação; saída inválida é bloqueada; execução não depende de resposta insegura | `feat: integra agente ollama ao ciclo` |
| **5. MCP** | Servidor e cliente MCP local, ferramentas de consulta/ação | Testes de chamadas e parâmetros; ações sempre passam pelo validador | `feat: disponibiliza ferramentas mcp` |
| **6. RAG 3GPP** | Índice pequeno, consulta com referência técnica | Respostas exibem fonte e versão recuperadas; ausência de contexto é informada | `feat: adiciona consulta rag a normas 3gpp` |
| **7. Comparação** | Execução padronizada das configurações A/B/C | Mesmos cenários e critérios, com resultados e limitações documentados | `test: compara modelos e configuracoes` |
| **8. Consolidação** | Relatório curto, gráficos, documentação e instruções de reprodução | Terceiro consegue reproduzir o fluxo com dados disponíveis | `docs: consolida resultados do laboratorio` |

### Marco de entrega prioritário (MVP)

**Etapas 0–4**, mantendo somente **um agente**. Ao final, teremos um ciclo verificável **detecção → decisão → validação → ação simulada → verificação**. MCP e RAG são adicionados sem reescrever o núcleo.

## 7. Comparação experimental

Configurações:

- **A — Regras Python:** decisão determinística, sem LLM (referência operacional).
- **B — LLM geral:** modelo escolhido via Ollama, sem acesso documental externo.
- **C — Mesmo LLM + RAG 3GPP:** mesmos casos, prompt-base, limites de ações e parâmetros de inferência; documentos recuperados adicionados com rastreabilidade.
- **D — Fine-tuning (opcional):** somente se houver **checkpoint realmente ajustado**, documentação e compatibilidade. Não confundir com o notebook RAG do Miguel.

### Cuidados para comparação justa

- Usar **casos fixos** e expectativas de ação definidas antes das inferências; quando houver rótulo, documentar sua origem.
- Evitar vazamento temporal ou alteração das condições entre execuções.
- Registrar modelo e versão, quantização, `temperature`, `seed` quando suportados, hardware, prompt, janelas, documentos e parâmetros.
- Medir: adequação da recomendação, segurança, consistência, latência, consultas realizadas, custo de processamento e justificativa técnica.
- Acurácia/F1-score só com **verdade de referência independente e válida**; avaliação por especialista deve ser explicitada como tal.
- Não assumir que RAG sempre melhora a resposta ou que maior modelo será mais adequado ao hardware.

## 8. Ferramentas, dependências e recursos

**Essenciais:** Python, `venv`, `pandas`, `openpyxl` (leitura `.xlsx`), `matplotlib`, `pytest`, Ollama e `git`.

**Conforme necessidade:** Pydantic (saídas estruturadas), MCP Python SDK, bibliotecas de embeddings/índice vetorial e ferramentas para medições de recursos.

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
- Documentar **URL, revisão/commit, nome do Excel, data de acesso, licença e opcionalmente hash** para permitir reproduzir os experimentos.
- Não realizar `git push`, commits, remoções de arquivo ou publicação de dados sem autorização.
- Nunca colocar senha ou token em fonte, prompt, relatório ou commit.

## 11. Modo de trabalho e acompanhamento

O Codex pode implementar **módulos completos por etapa**. O pesquisador participa de decisões, execução, conferência dos resultados e entendimento do funcionamento, **não de cada linha**.

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

As execuções de referência estão documentadas no [relatório de replay e detecção](REPLAY_DETECCAO.md) e no [relatório do ciclo de ação simulada](ACAO_SIMULADA.md). A Etapa 4 integra um agente Ollama à mesma interface de propostas, com validação local, auditoria e fallback Python. A próxima etapa prevista é a interface MCP. [Experimentos com o agente](AGENTE_OLLAMA.md)
