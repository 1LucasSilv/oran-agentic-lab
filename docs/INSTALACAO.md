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

## Limpeza e desinstalação

### Antes de apagar

Pare os testes, o replay e o loop do laboratório. Abra um terminal na raiz da cópia que pretende limpar e confira o caminho e o estado do Git. Os comandos Git abaixo funcionam no PowerShell e no Bash/Zsh.

```sh
git rev-parse --show-toplevel
git status --short --ignored --untracked-files=normal
git log --oneline --branches --not --remotes
git stash list
```

Copie para fora do repositório os resultados que deseja preservar, incluindo JSON, relatórios, gráficos, parâmetros, versões, revisão e SHA-256 do dataset. Inclua planilhas próprias e saídas gravadas em outros caminhos com `--saida`. Para conservar alterações sem commit, arquivos não rastreados, branches locais e stashes de um clone comum, copie a pasta do projeto incluindo a pasta oculta `.git`. Exclua o ambiente e caches da seleção do backup se estiver copiando somente o que precisa manter. Se houver `.env` ou outros arquivos com credenciais, guarde-os apenas em um backup privado. Abra a cópia e confirme que os arquivos esperados estão acessíveis antes de excluir a origem. [Documentação de git status](https://git-scm.com/docs/git-status)

**A exclusão pelo terminal pode ser definitiva.** Confira o caminho completo de cada alvo. Se houver link simbólico ou junção, identifique o destino antes de prosseguir. Para pastas inteiras, prefira a Lixeira do Explorador no Windows, a Lixeira do Finder no macOS ou a lixeira do gerenciador de arquivos no Linux, quando disponível. Em pastas sincronizadas, excluir a cópia local pode propagar a exclusão.

### Limpar caches e temporários do projeto

Na raiz, revise `.pytest_cache/` e as pastas `__pycache__/` sob `src/oran_lab/`, `tests/` e `scripts/`. Remova `build/` ou `dist/` somente se contiverem artefatos descartáveis. Se usou o exemplo com `--basetemp`, revise também `results/pytest-temporario/`. Execute a inspeção e a remoção em separado. Os exemplos abaixo atingem apenas `.pytest_cache/`. Preserve caches compartilhados, como o cache global do pip e o diretório temporário do sistema.

**Windows (PowerShell)**

```powershell
Get-Item -LiteralPath '.\.pytest_cache' -Force | Format-List FullName, LinkType, Target
Remove-Item -LiteralPath '.\.pytest_cache' -Recurse -Confirm
```

**Linux e macOS (Bash/Zsh)**

```bash
pwd -P
ls -ld ./.pytest_cache
rm -ri -- ./.pytest_cache
```

Rode a última linha de cada exemplo apenas se a inspeção mostrar a pasta esperada dentro da cópia do laboratório.

### Remover o ambiente virtual do laboratório

Se o ambiente estiver ativo, execute `deactivate`, depois feche terminais, notebooks e processos que o utilizem. Envie somente `.venv/` da raiz do laboratório para a lixeira pelo gerenciador de arquivos. No Windows e no macOS, habilite a exibição de itens ocultos se a pasta não aparecer. No Linux sem lixeira, é possível remover a pasta confirmando os alvos com `rm -ri -- ./.venv`, depois de conferir `pwd -P` e `ls -ld ./.venv`.

A remoção apaga a instalação editável e as dependências daquele ambiente. Mantenha o Python base, Git, VS Code e outros ambientes e ferramentas compartilhados. [Documentação oficial do venv](https://docs.python.org/3/library/venv.html)

### Remover datasets e resultados

Revise os três caminhos separadamente antes de enviar os arquivos selecionados para a lixeira.

| Caminho relativo à raiz | Conteúdo a revisar |
| --- | --- |
| `data/raw/` | Planilha oficial verificada e planilhas próprias ou recebidas de terceiros. Guarde os arquivos que não podem ser baixados novamente. |
| `data/processed/` | Dados derivados. Preserve os arquivos ou as entradas e configurações necessárias para reproduzi-los. |
| `results/` | Resultados, relatórios e gráficos. Preserve o histórico científico e confira os caminhos personalizados de saída antes de descartá-los. |

### Remover somente modelos do Ollama (opcional)

Os modelos pertencem ao serviço Ollama e podem ser usados por outros projetos. Com o serviço local correto em execução, liste as tags e remova apenas a tag que decidiu descartar. O exemplo funciona nos três sistemas. Se criou uma variante local, preserve o `Modelfile` e os insumos necessários para reconstruí-la antes de removê-la. [Referência da CLI Ollama](https://docs.ollama.com/cli)

```sh
ollama list
ollama rm qwen2.5:1.5b
ollama list
```

Confira a primeira listagem antes de executar `ollama rm`. Se configurou `OLLAMA_MODELS`, confirme que o serviço aponta para o armazenamento pretendido. Os locais padrão documentados são `%USERPROFILE%\.ollama\models` no Windows, `~/.ollama/models` no macOS e `/usr/share/ollama/.ollama/models` no Linux com serviço padrão. Use a CLI para remover tags individuais e preserve o restante do armazenamento. [Locais dos modelos](https://docs.ollama.com/faq#where-are-models-stored)

### Desinstalar o Ollama (opcional)

Se outras aplicações usam o serviço, mantenha o Ollama instalado. Antes de desinstalar, preserve modelos, configurações e logs de interesse. Os procedimentos a seguir dependem de como o Ollama foi instalado.

- **Windows.** Encerre o Ollama pelo ícone da bandeja. Para a instalação feita com `OllamaSetup.exe`, vá a **Configurações → Aplicativos → Aplicativos instalados → Ollama → Desinstalar**. Em uma instalação por ZIP, pare a instância que você iniciou e remova apenas a pasta onde extraiu o ZIP e a entrada específica que adicionou ao PATH, se houver. Verifique o diretório personalizado de `OLLAMA_MODELS` e os arquivos de `%LOCALAPPDATA%\Ollama` separadamente. [Ollama para Windows](https://docs.ollama.com/windows#uninstall) · [Suporte Microsoft](https://support.microsoft.com/en-us/windows/apps/uninstall-or-remove-apps-and-programs-in-windows)
- **Linux.** Para uma instalação gerenciada por pacote, use o gerenciador que a instalou. Para uma instalação manual ou com o instalador oficial, confira `command -v ollama`. Se usa systemd, confira `systemctl show -p FragmentPath -p ExecStart ollama.service` e, se for o serviço que deseja remover, execute `sudo systemctl disable --now ollama.service`. Se iniciou `ollama serve` manualmente, encerre-o no terminal em que foi iniciado. Remova a unidade local confirmada e o executável instalado, depois rode `sudo systemctl daemon-reload` se removeu a unidade. Para bibliotecas, remova apenas a subpasta `ollama` confirmada, como `/usr/lib/ollama` ou `/usr/local/lib/ollama`. A conta do serviço e `/usr/share/ollama` são uma decisão separada, pois essa pasta pode conter modelos. Preserve diretórios de sistema e verifique o caminho real de qualquer unidade ou binário antes da remoção. [Ollama para Linux](https://docs.ollama.com/linux#uninstall)
- **macOS.** Encerre o Ollama e mova `/Applications/Ollama.app` para a Lixeira no Finder, ou use a pasta em que colocou o aplicativo. Confira `ls -l /usr/local/bin/ollama`. Se for o link para a instalação removida, exclua somente esse link com `rm -i -- /usr/local/bin/ollama`, usando a permissão apropriada. Revise separadamente os arquivos de suporte do aplicativo em `~/Library/Application Support/Ollama` e os dados em `~/.ollama`. Para instalação por gerenciador de pacotes, use o mesmo gerenciador na remoção. [Ollama para macOS](https://docs.ollama.com/macos#uninstall) · [Suporte Apple](https://support.apple.com/102610)

### Excluir o repositório local

Após conferir o backup, feche a pasta no editor e saia dela nos terminais. No diretório pai, compare o caminho completo da pasta `oran-agentic-lab` com o que `git rev-parse --show-toplevel` informou. Mova apenas essa pasta para a lixeira, incluindo a pasta oculta `.git`. Confira a cópia de segurança antes de esvaziar a lixeira. Se o volume não oferecer lixeira, arquive primeiro o projeto em outro local e valide o arquivo antes de qualquer exclusão definitiva. A operação se aplica à cópia local.
