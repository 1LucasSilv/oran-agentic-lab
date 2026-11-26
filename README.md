# oran-agentic-lab

Laboratório de análise de KPMs históricos de uma rede experimental Open RAN. Use `oran-eda` para auditar a planilha, `oran-replay` para aplicar o detector de referência e `oran-loop` para percorrer o ciclo de ação simulada. [Auditoria do Excel oficial](docs/EDA.md) · [Replay e detecção](docs/REPLAY_DETECCAO.md) · [Plano técnico](docs/PLANO_LABORATORIO.md)

## Preparar o ambiente

Na raiz do repositório, use Python 3.11 ou superior com suporte a `venv`. A instalação editável disponibiliza o comando e o pacote de testes.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
```

Os testes criam pequenas planilhas sintéticas em diretórios temporários. Podem ser executados antes de baixar os dados.

## Reproduzir a auditoria oficial

Os comandos abaixo baixam o Excel da revisão auditada e verificam seu conteúdo. Se o arquivo já estiver disponível, comece pela verificação do hash.

```bash
arquivo='data/raw/20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks(2).xlsx'
mkdir -p data/raw
curl -fL 'https://raw.githubusercontent.com/CTTCADAPTRU/OAI-KPM-dataset/328ab90c9faabbba6a036255ac503683c227fa34/20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks%282%29.xlsx' -o "$arquivo"
printf '%s  %s\n' d570d8c0567b7ec85fd5e3ca865d1cc109dc741583b01d3ee4f1ff964892d30c "$arquivo" | sha256sum -c -
oran-eda "$arquivo"
```

Abra `results/eda/relatorio.md` para consultar as tabelas e os gráficos PNG. O relatório lista todas as abas, mesmo quando a análise usa uma seleção. Cada gráfico usa uma escala vertical por variável. Dados brutos, ambiente e saídas geradas ficam fora do Git.

## Escolher arquivos, abas e eixos temporais

```bash
oran-eda "$arquivo" --aba 'iperf3 traffic' --saida results/trafego
oran-eda outra_planilha.xlsx --aba 'Medições' --tempo 'Medições' 'Instante' data --saida results/outra
oran-eda --help
```

O leitor usa a primeira linha de cada tabela como cabeçalho. Mantém colunas com valores e cabeçalho vazio (o pandas atribui nomes como `Unnamed: 10`), conta células vazias e preserva texto literal como `NA`. Informa o tipo inferido pelo pandas e o número de valores distintos presentes. Para colunas numéricas, também calcula mínimo, mediana e máximo. Uma duplicata é uma linha igual a outra anterior em todas as colunas.

O hash identifica a revisão oficial que recebeu interpretação específica. Para outros arquivos, o programa reconhece colunas de datas Excel e usa a posição da linha nos gráficos. Use `--tempo ABA COLUNA MODO` para indicar outra coluna ou substituir o modo. Use `data` para datas Excel ou texto ISO 8601, `segundos` para um contador em segundos e `bruto` para inspecionar diferenças numéricas em unidade desconhecida. É possível repetir `--aba` e `--tempo`. No modo `data`, instantes com fuso são convertidos para UTC e valores sem fuso são tratados como UTC para o cálculo.

Os intervalos usam pares adjacentes na ordem da planilha. Uma lacuna interrompe o cálculo naquele par. Repetições e recuos permanecem visíveis. Para comparar execuções de arquivos ou seleções diferentes, escolha um diretório de saída para cada uma.

## Reproduzir janelas e aplicar o detector

Com o ambiente instalado e a planilha em `data/raw/`, execute na raiz do projeto.

```bash
arquivo='data/raw/20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks(2).xlsx'
oran-replay "$arquivo"
oran-replay "$arquivo" --tamanho 30 --avanco 15 --somente-replay
oran-replay --help
```

O primeiro comando grava `resultados.json` e `relatorio.md` em `results/etapa2/`. O segundo grava o inventário das janelas sobrepostas em `results/replay/`. Use `--saida` para guardar outra configuração, `--aba` para escolher o nome exato da aba e `--descartar-incompletas` para omitir as janelas parciais.

Tamanho e avanço são contados em registros de `Register`. Por padrão, o detector compara a mediana do throughput UL com uma referência de três janelas históricas independentes e exige queda de pelo menos 30% em duas janelas independentes de uma mesma sequência. A cobertura mínima é de 80%. O PRB UL ajuda a contextualizar a queda em relação à sua própria referência. [Parâmetros, decisões e resultado da execução oficial](docs/REPLAY_DETECCAO.md)

## Executar o loop de ação simulada

Com o ambiente instalado e a planilha em `data/raw/`, execute da raiz do projeto.

```bash
arquivo='data/raw/20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks(2).xlsx'
oran-loop "$arquivo"
oran-loop --sintetico
```

Cada execução gera `resultados.json` e `relatorio.md` em `results/etapa3/oficial/` ou `results/etapa3/sintetico/`. Escolha outro diretório com `--saida`. Para planilhas locais, `--aba`, `--tamanho` e `--avanco` configuram o replay.

A política propõe o registro de novos episódios suspeitos e justifica quando deixa o estado operacional igual. O cenário sintético exercita as cinco ações, incluindo recusas por duplicação e excesso de tamanho. O JSON conecta o estado e a auditoria às evidências do detector. [Estado, validação e exemplos](docs/ACAO_SIMULADA.md)

## Comparar a política Python e o agente local

Com a instalação editável do laboratório ativa, execute os três experimentos a partir da raiz. O modo Ollama usa o serviço em loopback e o modelo local `qwen2.5:1.5b`. Consulte os modelos instalados com `ollama list`.

```bash
arquivo='data/raw/20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks(2).xlsx'
oran-loop --sintetico --modo python
oran-loop --sintetico --modo ollama --selecao suspeitas --max-chamadas 2
oran-loop "$arquivo" --modo ollama --selecao todas --max-chamadas 2
```

O modo explícito grava os resultados em `results/etapa4/<modo>/<origem>/`. O simulador recebe uma decisão final por janela. No modo Ollama, o JSON também identifica tentativas recusadas, a resposta bruta e a política que assumiu cada fallback. O comando sem `--modo` continua disponível para a demonstração da Etapa 3. [Instalação, configuração, protocolo e resultados do agente](docs/AGENTE_OLLAMA.md)

## Usar ferramentas MCP locais

```bash
python -m pip install -e '.[test,mcp]'
python -m oran_lab.mcp_client
oran-loop --sintetico --modo ollama --mcp --max-chamadas 6
pytest -q
ORAN_TEST_MCP_STDIO=1 pytest -q tests/test_mcp.py
```

O primeiro comando de demonstração usa um subprocesso MCP por stdio. O loop com Ollama usa conexão MCP em memória e aceita `--consultas-mcp` e `--timeout-mcp`. Os artefatos ficam em `results/etapa5/`. [Ferramentas, limites e auditoria](docs/MCP.md)
