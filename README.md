# oran-agentic-lab

Laboratório educacional e de pesquisa sobre análise de KPMs históricos de uma rede 5G Open RAN experimental. O objetivo é verificar quais padrões merecem investigação por uma regra de referência, avaliar as propostas de um modelo local e medir o custo de introduzir o agente no ciclo de decisão. A planilha veio de uma coleta por xApp. O replay usa registros históricos, e as ações têm efeito apenas no simulador. A condição suspeita é um alerta heurístico, sem rótulo de falha comprovada.

## Fases da pesquisa

- **Fase I — IA Agêntica aplicada à análise e decisão em redes 5G O-RAN.** Prioritária e independente, abrange as Etapas 0 a 8, incluindo 5.1 e 7.1. Avalia conformidade operacional, capacidade investigativa, fundamentação técnica, segurança e custo computacional de agentes com MCP e RAG, com ações no simulador.
- **Fase II — Controle e otimização de redes 5G O-RAN.** Expansão futura opcional, sujeita a autorização específica. As Etapas 9 a 14 abrangem rede experimental, coleta e congestionamento controlado, integração O-RAN, controle em malha fechada, experimentos de desempenho e consolidação ampliada. OpenAirInterface, RFSim, 5G Core e FlexRIC são candidatos sujeitos a avaliação de viabilidade. [Plano técnico](docs/PLANO_LABORATORIO.md)

## Arquitetura

```mermaid
flowchart TD
    Excel["Planilha oficial XLSX"] --> Leitura["Leitura, validação e auditoria EDA"]
    Leitura --> Replay["Replay de janelas por Register"]
    Sintetico["Cenário sintético"] --> Replay
    Replay --> Detector["Detector heurístico"]
    Detector --> Python["Política Python"]
    Detector --> Ollama["Agente Ollama local"]
    Ollama <--> MCP["Ferramentas MCP locais (opcionais)"]
    Normas["Índice 3GPP local (opcional)"] --> Ollama
    Python --> Validador["Validador determinístico"]
    Ollama --> Validador
    MCP --> Validador
    Validador --> Simulador["Ação no simulador"]
    Simulador --> Verificacao["Verificação e auditoria JSON/Markdown"]
```

A EDA registra abas, tipos, lacunas e gráficos. O detector usa uma referência histórica de throughput UL e contextualiza a queda pelo PRB UL na escala original. O simulador registra alertas, prioriza eventos, amplia janelas de análise, intensifica a inspeção ou aceita `nenhuma_acao`. A política Python serve de referência e de fallback para propostas Ollama inválidas. O cliente MCP oferece uma demonstração por stdio e o agente usa ferramentas MCP em memória quando habilitadas.

## Requisitos e compatibilidade

| Uso | Requisitos |
| --- | --- |
| Instalação e modo Python | CPython 3.11 ou superior com `venv` e `pip`. Use a série 3.13 para reproduzir a referência da CI. O `pip` instala pandas, openpyxl e matplotlib nas versões fixadas. Git serve para obter uma cópia do repositório. |
| Suíte de testes | Extra `test` (pytest). Inclua `mcp` e `rag` para a cobertura completa. As planilhas e PDFs da suíte são sintéticos. |
| EDA ou replay oficial | Planilha da revisão auditada e SHA-256 válido. O cenário sintético funciona sem esse download. |
| Agente local | Ollama, serviço HTTP em loopback e uma tag local instalada. Os exemplos usam `qwen2.5:1.5b`. |
| Ferramentas MCP | Extra `mcp` (SDK Python oficial). A demonstração por stdio funciona sem Ollama. |
| RAG 3GPP | Extra `rag` (PyPDF), duas especificações oficiais e Ollama com a tag local de embeddings. Funciona com ou sem MCP. |

Como ponto de partida, use uma CPU de 64 bits com quatro núcleos e 8 GiB de RAM para o modo Python e os testes. Para Ollama com a tag de 1,5 bilhão de parâmetros, prefira 16 GiB de RAM. GPU é opcional. O consumo depende do modelo, da quantização e do contexto.

| Componente | Espaço em disco |
| --- | --- |
| Python base | Cerca de 185 MiB na instalação Windows de referência. Reserve 0,5 GiB se precisar instalar o Python. |
| Ambiente e dependências Python | Cerca de 264 MiB no `.venv` de referência com `[test,mcp]`. Reserve 0,5 GiB para o ambiente e espaço adicional para downloads e temporários do pip. |
| Ollama (opcional) | No Windows, o instalador requer pelo menos 4 GB para os binários. No Linux e no macOS, confira o tamanho do pacote da sua plataforma e reserve espaço para a instalação e a extração. [Requisitos do Ollama no Windows](https://docs.ollama.com/windows#filesystem-requirements) |
| Modelos (opcionais) | `qwen2.5:1.5b` ocupa cerca de 986 MB e `embeddinggemma` cerca de 622 MB. Some espaço para cada tag que pretende usar e para o download. [Qwen](https://ollama.com/library/qwen2.5:1.5b) · [EmbeddingGemma](https://ollama.com/library/embeddinggemma) |
| Dataset e resultados | A planilha oficial ocupa cerca de 152 KiB. As saídas da validação local ocupavam poucos MiB. Para um lote de experimentos, faça uma execução representativa e multiplique o tamanho de sua saída pelo número de execuções que pretende guardar. |

Para começar com Python, reserve 2 GiB livres incluindo temporários e primeiras saídas. Se usar Ollama, some o runtime e os modelos e verifique o espaço livre nos volumes onde cada componente será armazenado.

| Sistema | Evidência |
| --- | --- |
| Windows | Suíte padrão da Etapa 5.1 aprovada no GitHub Actions. Etapa 6 validada localmente em Windows 11 AMD64 com Python 3.13.0. |
| Linux | Suíte padrão da Etapa 5.1 aprovada no runner Ubuntu. Há também evidência local das Etapas 0 a 5. |
| macOS | Suíte padrão da Etapa 5.1 aprovada no runner macOS. |

O histórico e as versões medidas estão no [status do projeto](docs/STATUS_PROJETO.md).

## Instalar o laboratório

Obtenha o repositório com Git e entre na pasta criada. Também é possível extrair o ZIP do GitHub e abrir um terminal na pasta extraída.

```sh
git clone https://github.com/1LucasSilv/oran-agentic-lab.git
cd oran-agentic-lab
```

### **Windows (PowerShell).** 
Instale Python 3.13 da distribuição oficial e certifique-se de que o lançador `py` está disponível. Feche e reabra o terminal após instalar. [Distribuição oficial do Python](https://www.python.org/downloads/)

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test,mcp]"
```

### **Linux e macOS (Bash ou Zsh).** 
Instale Python 3.13 com `pip` e `venv` pelo gerenciador da distribuição ou pelo instalador oficial do macOS. Algumas distribuições Linux empacotam `venv` separadamente. Use `python3.13 --version` para confirmar o interpretador. [Distribuição oficial do Python](https://www.python.org/downloads/)

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test,mcp]"
```

O `pip` resolve e baixa as dependências Python. Para instalar só o núcleo, use `python -m pip install -e .`. Para incluir pytest, use `python -m pip install -e ".[test]"`. 

> **Diagnóstico de Instalação:**
O diagnóstico abaixo informa as versões, os recursos do host e o estado dos componentes opcionais. Execute os próximos comandos na raiz do repositório.

```sh
python scripts/check_environment.py
python -m pip check
python -m pytest -q
oran-loop --sintetico --modo python --saida results/minha-execucao/python-sintetico
```

Para ativação bloqueada no PowerShell ou outras configurações, consulte o [guia de instalação](docs/INSTALACAO.md).

## Baixar a planilha e executar EDA e replay

Use a mesma sequência no PowerShell, Bash ou Zsh. O primeiro comando baixa a revisão fixada abaixo, valida o SHA-256 antes de publicar o arquivo e reutiliza um arquivo local válido. O segundo verifica a cópia local sem acessar a rede. Para download manual, salve o Excel do link de origem com o mesmo nome em `data/raw/` e rode a verificação.

- **Revisão** `328ab90c9faabbba6a036255ac503683c227fa34`. [Baixar a planilha da revisão auditada](https://raw.githubusercontent.com/CTTCADAPTRU/OAI-KPM-dataset/328ab90c9faabbba6a036255ac503683c227fa34/20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks%282%29.xlsx)
- **SHA-256** `d570d8c0567b7ec85fd5e3ca865d1cc109dc741583b01d3ee4f1ff964892d30c`.

```sh
python scripts/download_dataset.py
python scripts/download_dataset.py --verificar
```

**PowerShell**

```powershell
$arquivo = 'data/raw/20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks(2).xlsx'
```

**Bash ou Zsh**

```bash
arquivo='data/raw/20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks(2).xlsx'
```

**Comandos comuns aos três shells**

```sh
oran-eda "$arquivo" --saida results/minha-execucao/eda
oran-replay "$arquivo" --saida results/minha-execucao/detector
oran-loop "$arquivo" --modo python --saida results/minha-execucao/python-oficial
```

Use `oran-replay --help` para escolher aba, tamanho e avanço de janela. O modo `--somente-replay` gera o inventário sem aplicar o detector.

## Executar Ollama e MCP

No **Windows**, execute o instalador oficial do Ollama e reabra o terminal. [Windows](https://docs.ollama.com/windows)

No **macOS**, instale o aplicativo e abra-o para preparar o serviço e a CLI. [macOS](https://docs.ollama.com/macos)

No **Linux**, use o comando abaixo ou instale o pacote manualmente. [Linux](https://docs.ollama.com/linux)

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Se o serviço ainda não estiver ativo, deixe `ollama serve` rodando em um terminal separado.

Em um terminal com o ambiente do projeto, execute o download adicional do modelo e confirme a tag. Para outro modelo local, use a mesma tag em `ollama pull`, `check_environment.py --modelo` e `oran-loop --modelo`.

```sh
ollama pull qwen2.5:1.5b
ollama list
python scripts/check_environment.py --modelo qwen2.5:1.5b
oran-loop --sintetico --modo ollama --max-chamadas 2 --saida results/minha-execucao/ollama
python -m oran_lab.mcp_client --saida results/minha-execucao/stdio.json
oran-loop --sintetico --modo ollama --mcp --max-chamadas 6 --saida results/minha-execucao/ollama-mcp
```

Para usar o agente sobre o Excel, troque `--sintetico` por `"$arquivo"` e escolha outro `--saida`. Inspecione os registros de proposta, validação e fallback para identificar quais decisões vieram do modelo.

## Acrescentar referências 3GPP ao agente

Com o Ollama ativo, use a tag local de embeddings. Baixe-a com `ollama pull embeddinggemma` se ainda estiver ausente. Os comandos funcionam no PowerShell e no Bash/Zsh.

```sh
python -m pip install -e ".[test,mcp,rag]"
oran-rag obter
oran-rag indexar
oran-rag verificar
oran-loop --sintetico --modo ollama --max-chamadas 2 --rag
```

Acrescente `--mcp` para combinar as ferramentas locais com o RAG. Consulte o [guia RAG](docs/RAG.md) para importação manual dos PDFs, busca avulsa, auditoria e limites de uso.

## Validar integrações opcionais

A suíte padrão deixa as integrações com o serviço real do Ollama e com subprocesso MCP stdio desativadas. O teste do Ollama usa a tag e a API padrão e requer ambos disponíveis. O teste stdio requer o extra MCP e permissões para subprocesso e pipes.

**PowerShell**

```powershell
$env:ORAN_TEST_OLLAMA = '1'
python -m pytest -q tests/test_agent.py -k local_ollama_integration
Remove-Item Env:ORAN_TEST_OLLAMA

$env:ORAN_TEST_MCP_STDIO = '1'
python -m pytest -q tests/test_mcp.py
Remove-Item Env:ORAN_TEST_MCP_STDIO
```

**Bash ou Zsh**

```bash
ORAN_TEST_OLLAMA=1 python -m pytest -q tests/test_agent.py -k local_ollama_integration
ORAN_TEST_MCP_STDIO=1 python -m pytest -q tests/test_mcp.py
```

### GitHub Actions

O [workflow Testes](.github/workflows/tests.yml) executa a suíte padrão com Python 3.13 e os extras `test,mcp,rag` em runners hospedados pelo GitHub para Ubuntu, Windows e macOS. Dispara em pushes para `main`, pull requests destinados a `main` e manualmente. A matriz usa fixtures sintéticas para planilhas e PDFs e dispensa Ollama e modelos.

Abra **Actions → Testes**, selecione a execução e abra os logs de cada job. Usuários com acesso de escrita podem abrir **Run workflow**, escolher a branch e rodar a matriz. Erros na preparação do runner, checkout ou acesso a registros de pacotes podem impedir a suíte de iniciar. Se o pytest executar, confira o traceback para localizar o teste e investigar a causa. A execução #1, da Etapa 5.1, teve 116 testes aprovados e 2 ignorados em cada runner. [Execução #1](https://github.com/1LucasSilv/oran-agentic-lab/actions/runs/46023193720) · [Como rodar manualmente](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

## Desinstalar o laboratório

1. Copie resultados científicos, datasets locais e alterações do Git para fora do repositório. Abra a cópia para verificar o backup.
2. Para uma limpeza parcial, remova apenas os caches do projeto ou o ambiente local `.venv`. Se precisar liberar mais espaço, revise separadamente `data/raw/`, `data/processed/` e `results/`.
3. Se instalou Ollama para o laboratório, avalie separadamente a remoção da tag baixada e a desinstalação do aplicativo. Preserve Python, Git, VS Code e outros recursos compartilhados.
4. Para remover a cópia local inteira, feche os processos e mova a pasta `oran-agentic-lab` para a lixeira depois de conferir o backup.

O [procedimento detalhado para Windows, Linux e macOS](docs/INSTALACAO.md#limpeza-e-desinstalação) indica como conferir caminhos, preservar dados e tratar uma instalação compartilhada do Ollama.

## Planejar uma avaliação científica

O comando `oran-experiment` planeja, executa e agrega a matriz Python, Qwen, Qwen com RAG, Qwen com MCP e Qwen com MCP e RAG. A decisão controlada usa a mesma janela e o mesmo estado inicial. O ciclo completo acompanha a evolução de estado de cada configuração.

```sh
oran-experiment planejar --fase piloto --saida results/etapa7/meu-piloto
oran-experiment executar --fase piloto --saida results/etapa7/meu-piloto
oran-experiment agregar --saida results/etapa7/meu-piloto
```

O piloto tem teto de 12 chamadas de chat e casos próprios. O plano final controlado usa seis casos distintos e até 108 chamadas. Gere-o com `oran-experiment planejar --fase final` após o commit definitivo e revise-o antes de autorizar a execução. As saídas incluem auditorias, tabelas, gráficos e modelo para revisão humana em branco. [Protocolo e comandos](docs/EXPERIMENTOS.md)

## Resultados e próximos marcos

### Interface local

```sh
python -m pip install -e ".[ui]"
oran-ui
```

Abra `http://127.0.0.1:8501`. **Laboratório** reúne as execuções operacionais. **Pesquisa** oferece planejamento, Central de execução, Resultados e Avaliação científica. **Recursos** concentra modelos, dados, índices, cenários e presets. Em **Sistema**, o Modo apresentação reproduz registros sem inferência. Use `.[ui,mcp,rag]` para incluir os modos com MCP e RAG. [Instalação, controles e armazenamento](docs/INTERFACE.md)

| Comando | Saída padrão |
| --- | --- |
| `oran-eda` | `results/eda/`, com relatório Markdown e gráficos PNG |
| `oran-replay` | `results/etapa2/` para o detector ou `results/replay/` para `--somente-replay` |
| `oran-loop` sem modo explícito | `results/etapa3/<origem>/` |
| `oran-loop --modo python` ou `--modo ollama` | `results/etapa4/<modo>/<origem>/` |
| `oran-loop --modo ollama --mcp` | `results/etapa5/ollama-mcp/<origem>/` |
| `python -m oran_lab.mcp_client` | `results/etapa5/stdio.json` |
| `oran-loop --modo ollama --rag` | `results/etapa6/ollama-rag/<origem>/` ou `results/etapa6/ollama-mcp-rag/<origem>/` com MCP |
| `oran-experiment` | `results/etapa7/<execucao>/` para planos, eventos brutos, relatórios e avaliações |
| `oran-ui` | `results/ui/<id>/` para execuções operacionais, `results/ui/experimentos/<id>/` para comparações configuráveis e `data/ui/` para fontes e presets locais |

O replay e o loop escrevem `resultados.json` e `relatorio.md`. Use `--saida` para preservar cada execução, com diretórios distintos por sistema e configuração. Dados brutos, ambientes e saídas locais ficam fora do Git.

Na execução oficial de referência no Linux, o detector produziu 38 janelas sobre 1.138 registros KPM e zero alertas. O cenário sintético permitiu verificar ações e recusas do simulador. Os experimentos com Ollama e MCP demonstraram propostas, consultas e fallback. Esses resultados descrevem os casos executados. Novas medições dependem do modelo, do runtime e do hardware. [Replay](docs/REPLAY_DETECCAO.md) · [Simulador](docs/ACAO_SIMULADA.md) · [Agente Ollama](docs/AGENTE_OLLAMA.md) · [MCP](docs/MCP.md)

As Etapas 0 a 6 estão aprovadas, incluindo a preparação reproduzível da Etapa 5.1. A bateria controlada da Etapa 7 concluiu 90 sessões, com avaliação humana pendente. A Etapa 7.1.3 acrescenta acompanhamento experimental, reprodução de registros, comparação de resultados e interface para avaliação humana. [Resultados da Etapa 7](docs/EXPERIMENTOS.md#bateria-controlada-final) · [Plano técnico](docs/PLANO_LABORATORIO.md) · [Status](docs/STATUS_PROJETO.md) · [Auditoria da planilha](docs/EDA.md) · [Instalação avançada](docs/INSTALACAO.md)
