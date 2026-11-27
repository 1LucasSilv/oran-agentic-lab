# Instalação avançada e diagnóstico

Siga o [README](../README.md) para preparar o ambiente e executar os primeiros casos. As opções abaixo usam a raiz do repositório como diretório de trabalho.

## Selecionar o interpretador sem ativar o ambiente

Se a política do PowerShell bloquear `Activate.ps1`, chame o interpretador e os comandos do ambiente diretamente.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test,mcp]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\oran-loop.exe --sintetico --modo python --saida results/minha-execucao/python-sintetico
```

No Bash/Zsh, os equivalentes são `.venv/bin/python` e `.venv/bin/oran-loop`. Se a criação do ambiente falhar com `ensurepip` ausente, instale o pacote `venv` correspondente ao Python pelo gerenciador da distribuição Linux. Recrie o ambiente ao mudar de interpretador ou copiar o projeto entre máquinas.

## Diagnosticar dependências e dados

- `python scripts/check_environment.py` roda mesmo antes da instalação editável. O código de saída 1 indica ausência ou incompatibilidade no núcleo. Extras ausentes, indisponibilidade do Ollama e problemas na planilha aparecem no relatório. Use `python -m pip check` para conflitos transitivos.
- Para uma cópia local, use `python scripts/download_dataset.py --verificar --destino "caminho/planilha.xlsx"` e `python scripts/check_environment.py --dataset "caminho/planilha.xlsx"`. O primeiro encerra com código 1 se o arquivo estiver ausente, inacessível ou com hash divergente.
- Se o arquivo estiver corrompido, rode o downloader com o destino desejado. Ele publica a cópia nova apenas depois de validar o SHA-256 e mantém o arquivo que já estava no destino se o download falhar. Em uma instalação sem rede, transfira a planilha auditada de outra máquina e use `--verificar`.
- Se o pytest receber um erro de permissão no diretório temporário, use `python -m pytest -q --basetemp "results/pytest-temporario"` com um diretório exclusivo e descartável. O pytest limpa esse diretório ao reutilizá-lo.

## Configurar serviço local e modelo

O agente aceita HTTP em loopback. Para outra porta local, passe a mesma URL a `check_environment.py --api` e `oran-loop --api`. Passe também `--modelo` aos dois comandos quando usar uma tag diferente. O diagnóstico consulta versão e inventário local do serviço, e a inferência só ocorre ao rodar o loop. Se a CLI não estiver no PATH, reabra o terminal após a instalação. No Windows, o diagnóstico também procura o executável na pasta de instalação por usuário.

Se o serviço estiver ativo e a inferência falhar, confira no JSON de saída o status HTTP, a saída original, a decisão final e o fallback. Aumente `--timeout` se o carregamento do modelo exceder o limite e registre o novo valor. A escolha de modelo, digest, quantização, parâmetros e hardware deve acompanhar cada medição. [Contrato do agente e opções](AGENTE_OLLAMA.md)

## Auditar outras planilhas

Use `oran-eda outra.xlsx --aba 'Medições' --tempo 'Medições' 'Instante' data --saida results/minha-execucao/outra` para selecionar uma aba e declarar a coluna temporal. Os modos são `data` para datas Excel ou texto ISO 8601, `segundos` para contadores em segundos e `bruto` para diferenças em unidade desconhecida. As opções `--aba` e `--tempo` podem ser repetidas na auditoria. Para replay de uma aba compatível, use `oran-replay outra.xlsx --aba 'Medições' --tamanho 30 --avanco 15`. [Critérios de auditoria](EDA.md) · [Parâmetros do replay](REPLAY_DETECCAO.md)

## UTF-8, caminhos e MCP

- Abra relatórios e JSON gerados com UTF-8. Em Windows PowerShell com exibição incorreta, use `Get-Content -Encoding UTF8`. Em código Python, informe `encoding="utf-8"` ao ler ou gravar arquivos de texto do laboratório.
- Coloque caminhos com espaços entre aspas. Se houver erro com caminhos longos ou arquivos sincronizados e bloqueados, use uma cópia mais próxima da raiz ou um diretório local gravável fora da sincronização. Feche visualizadores que mantenham o arquivo de saída aberto.
- O cliente stdio lança o servidor com o mesmo interpretador e usa UTF-8 nas duas pontas. Desative logs personalizados em stdout do servidor para que o pipe transporte apenas mensagens MCP. Se o sistema bloquear subprocessos ou pipes, execute a validação em um terminal com essas permissões e use o teste em memória para diagnosticar as ferramentas separadamente. [Transportes e auditoria](MCP.md)

Use diretórios de saída distintos por sistema, modo, origem e execução. Mantenha os registros anteriores para comparação e guarde os comandos e versões usados.
