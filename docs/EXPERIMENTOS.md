# Avaliação experimental da Etapa 7

## Pergunta e condições

O protocolo mede concordância com expectativas operacionais fixadas em casos sintéticos. A referência A permite observar o que a política determinística entrega. O contraste B/C investiga o efeito de fornecer contexto documental e B/D o de permitir consulta MCP. C/E e D/E ajudam a examinar a combinação. O estudo também registra o custo de cada configuração e as consequências das propostas no simulador.

| Código | Configuração |
| --- | --- |
| A | Política determinística Python |
| B | Qwen 2.5 1.5B |
| C | Mesmo Qwen com RAG |
| D | Mesmo Qwen com MCP |
| E | Mesmo Qwen com MCP e RAG |

B–E recebem o mesmo prompt-base experimental, formato de resposta com `acao`, `parametros`, `justificativa` e `referencias`, e o mesmo limite de 300 caracteres para justificativa. O parser aplica o limite e separa as referências antes de entregar a proposta de três campos ao simulador. As referências podem ficar vazias. A lista aceita apenas IDs de trechos presentes. Todos os chats passam pela mesma verificação de orçamento estimada em bytes UTF-8, com reserva de 256 para a formatação e reserva para a geração.

O Qwen usa temperatura 0, sementes 42/43/44, contexto 8.192 e geração 512. RAG usa EmbeddingGemma, Top-2 e cosseno mínimo 0,35. D/E podem gastar uma chamada adicional para escolher uma consulta MCP, com limite de uma por janela. Há uma oportunidade reservada para a decisão final em cada janela avaliada. Uma consulta inválida é registrada e a decisão final ainda é tentada com a evidência disponível. RAG e MCP mudam o conteúdo adicional, o esquema restringe os IDs a partir desse conteúdo, e D/E usam o canal MCP para submeter a ação ao mesmo validador. Essas diferenças fazem parte do tratamento. O modo `oran-loop` anterior mantém suas interfaces.

Cada combinação inicia seu próprio agente e simulador. Uma permutação com semente 20261127 é rotacionada entre casos, alvos e repetições. Ollama usa o mesmo processo e pode reaproveitar cache ou manter modelos residentes. O manifesto registra hardware, versões e digests. A execução registra residência inicial/final, carga quando o sistema a oferece, e tokens de cache quando o Ollama os informa. O protocolo deixa o cache naturalmente variável.

## Casos congelados

Cada valor nas séries abaixo dura uma janela de três registros, com avanço três, UE 1 e Register contínuo. O detector mantém três janelas de referência, queda mínima de 30%, persistência de duas janelas, cobertura mínima de 80% e tolerância de 10% de queda em PRB. PRB usa a escala bruta. O manifesto grava séries, configurações, expectativas por janela e estado inicial de cada entrada, com SHA-256.

| Caso final | Throughput UL por janela | PRB UL por janela | Janela-alvo e expectativa fixa |
| --- | --- | --- | --- |
| Operação estável | 95, 100, 105, 98, 101, 99 | 80, 82, 81, 82, 80, 81 | 5. Normal, nenhuma ação. |
| Queda isolada | 114, 120, 126, 60, 116, 120 | 90, 90, 90, 90, 90, 90 | 4. Insuficiente para confirmar persistência, nenhuma ação. |
| Queda persistente UL | 190, 200, 210, 112, 106, 103 | 150, 146, 148, 147, 149, 148 | 5. Suspeita heurística, registrar `alerta-5`. |
| Queda UL e PRB | 140, 150, 160, 82, 79, 76 | 120, 123, 117, 60, 57, 55 | 5. Suspeita pela regra de throughput, registrar `alerta-5`. A causa permanece aberta. |
| Recuperação | 105, 110, 115, 58, 55, 108 | 75, 74, 76, 77, 75, 74 | 6. Normal, nenhuma ação. O alerta anterior permanece no histórico inicial controlado. |
| Dados ausentes | 125, 130, 135, 129, ausente, 131 | 102, 100, 98, 100, 98, 101 | 5. Evidência insuficiente, nenhuma ação. |

O piloto usa `piloto-episodio` e `piloto-sem-evidencia`, com séries distintas e uma repetição. O caso antigo da Etapa 3–6 fica nos testes e na demonstração do laboratório. Expectativas da bateria final são entradas do protocolo e ficam fixas antes da inferência final.

A fase `exploratorio` verifica o SHA-256 do Excel oficial e usa alvos pré-selecionados na aba `KPM Metrics`. A janela 1 (Register 1–30) está em formação da referência. A janela 4 (Register 91–120) é a primeira normal pelo detector. O protocolo prevê nenhuma ação nas duas. São categorias heurísticas em uma exploração de um único arquivo e UE. A base carece de verdade de referência para falhas reais.

## Modos

- **Decisão controlada.** Cada configuração vê a mesma janela e evidências operacionais, com o mesmo estado inicial. O código corta a série no último Register autorizado antes de chamar o detector. A política Python prepara as janelas anteriores. Seu histórico tem origem `preparacao_python` e fica fora das métricas da decisão avaliada.
- **Ciclo completo.** A sessão começa com estado vazio, percorre as janelas em ordem e preserva o próprio estado entre decisões. O MCP consulta apenas o passado e a janela corrente. As oportunidades são fixadas pelo replay, enquanto o estado pode divergir entre configurações. Em ciclo exploratório, só as janelas previamente selecionadas têm expectativa pontuável.

## Execução e retomada

Na raiz do projeto, ative o ambiente virtual conforme o [README](../README.md). Os comandos funcionam no PowerShell, Bash e Zsh. Para C/E reais, prepare o índice, os modelos e o Ollama conforme o [guia RAG](RAG.md).

```sh
python -m pip install -e ".[test,mcp,rag]"
oran-experiment planejar --fase piloto --saida results/etapa7/meu-piloto
oran-experiment executar --fase piloto --saida results/etapa7/meu-piloto
oran-experiment agregar --saida results/etapa7/meu-piloto
```

Use `--configuracoes A B C D E`, `--casos`, `--repeticoes`, `--limite-chamadas` e `--modo ciclo` para selecionar um desenho. O piloto aceita até 12 chamadas. A fase exploratória aceita `--excel` e pode começar pela referência A, com `--limite-chamadas 0`.

```sh
oran-experiment planejar --fase exploratorio --saida results/etapa7/excel-planejado
oran-experiment executar --fase exploratorio --configuracoes A --limite-chamadas 0 --saida results/etapa7/excel-python
oran-experiment planejar --fase final --saida results/etapa7/final-planejado
```

O plano controlado final prevê 90 sessões em seis casos e três sementes, com 18 sessões Python, 72 decisões finais de LLM e até 36 seleções MCP. O teto é **108 chamadas de chat**. O ciclo completo é um desenho separado. Com as mesmas seis séries e três sementes, o teto de chat é 648. Planeje e autorize cada desenho antes de executar. Após autorização da bateria controlada, use a mesma pasta e os mesmos parâmetros com `oran-experiment executar --fase final --autorizar-final --saida results/etapa7/final-planejado`.

Use `--retomar` com os mesmos argumentos e a pasta original. O executor preserva resultados concluídos, trava a pasta contra gravadores simultâneos e reserva cada chamada em disco antes do envio. Se um processo cair depois da reserva, a tentativa continua ocupando a cota. A sessão fica interrompida na retomada e nenhuma de suas chamadas é reenviada. Sessões ainda pendentes podem continuar. Se o teto restante for menor que a reserva máxima da próxima sessão, a execução para antes de iniciá-la. Use uma nova pasta quando alterar limite, seleção, recursos ou código. A CLI expõe as funções do módulo `experiment`, e os eventos persistidos podem ser consultados por programa independentemente do terminal.

## Medidas e revisão humana

`relatorios/decisoes.csv` inclui todas as oportunidades planejadas e distingue original, aceitação/recusa, decisão final, mudança, ausência de proposta, falhas e fallback. A concordância compara ação e parâmetros com a pré-especificação. A medida sobre oportunidades avaliadas inclui ausência como não concordante, e a medida condicional tem denominador próprio para propostas legíveis. Sessões pendentes/interrompidas ficam explícitas. A decisão final Python aparece como resultado operacional, inclusive em fallback. A coluna de mudança atribuída ao modelo exige execução com origem Ollama.

Uma consulta MCP válida é marcada como útil nesta contagem quando acrescenta janela anterior ou pelo menos um registro anterior com medição. Leituras válidas que repetem informação-base são contadas como redundantes por esse critério. É uma medida estrutural de informação nova. A utilidade para a decisão pode exigir leitura humana. As tabelas distinguem fragmentos recuperados, apresentados e citados. A contagem de decisões RAG com citação exige IDs apresentados, conferidos e uma decisão final de origem Ollama.

As tabelas CSV/JSON mostram denominadores, médias, medianas, desvio-padrão e extremos. O resumo agrega primeiro por caso, com peso igual por caso, e reporta dispersão entre casos. Os contrastes pareiam por caso, janela e semente e mostram diferenças por caso. Repetições da mesma janela são repetições técnicas. As tabelas descrevem o cenário sem testes de significância ou métricas de classificação de falhas reais.

O CSV `avaliacao-cega.csv` omite configuração e resultado operacional e usa um ID opaco. O estilo, as menções a ferramentas e ao texto normativo podem sugerir a origem. Envie ao avaliador uma cópia do CSV, sem a chave local. Para a leitura documental, forneça separadamente o pacote `avaliacao-referencias.json` com os trechos pertinentes. Cada critério vai de 0 a 2:

| Critério | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Fidelidade às evidências KPM | Inventa ou contradiz a janela | Usa parte dos sinais ou omite detalhe decisivo | Usa corretamente os sinais, a referência e a cobertura pertinentes |
| Coerência operacional | Ação incompatível com o estado | Ação plausível com justificativa incompleta | Ação proporcional às evidências e ao estado autorizado |
| Correção técnica | Afirmação técnica incorreta | Explicação plausível com imprecisão | Conceitos e interpretação tecnicamente corretos |
| Reconhecimento das limitações | Conclusão indevida sobre falha, causa ou unidade | Reconhece parte da incerteza | Delimita de forma adequada inferência, dados e simulador |
| Pertinência das referências | Trechos sem relação | Relação parcial | Trechos diretamente pertinentes à questão |
| Suporte das referências | A citação contradiz ou não sustenta a afirmação | Sustenta apenas parte | Sustenta a afirmação atribuída |

Pontuações começam vazias. Os dois itens documentais são independentes dos quatro critérios principais e só se aplicam quando há trechos para conferir. Importe uma cópia preenchida com `oran-experiment importar-avaliacoes --saida results/etapa7/meu-piloto --avaliacoes caminho/avaliado.csv`. Cada importação efetiva cria um lote próprio.

## Arquivos

Cada pasta de execução tem um `plano.json` imutável, um `manifesto.json` com ID e ambiente, e `execucoes/<id>/` com eventos de preparação, janelas, requisições e respostas originais, validações, efeitos e estado de conclusão. As tabelas e o gráfico ficam em `relatorios/`. Guarde o material localmente, inclusive respostas com trechos de documentos. Os arquivos estão fora do Git.

## Piloto observado no Windows

A execução `results/etapa7/piloto-20261127/` concluiu as dez oportunidades com oito decisões de chat e quatro seleções MCP. Não houve falha de comunicação. Os dois modelos locais e o índice estavam disponíveis. As quatro consultas MCP retornaram evidência histórica adicional conforme o critério estrutural. As quatro decisões com RAG receberam dois trechos cada.

| Configuração | Propostas originais concordantes | Decisões finais concordantes | Fallbacks | Decisões do agente com citação conferida |
| --- | ---: | ---: | ---: | ---: |
| A | — | 2/2 | — | — |
| B | 1/2 | 2/2 | 1 | — |
| C | 0/2 | 2/2 | 2 | 0 |
| D | 1/2 | 2/2 | 1 | — |
| E | 1/2 | 2/2 | 1 | 1 |

As cinco recusas ocorreram quando o modelo propôs ampliar a janela de um evento ainda inexistente. No caso com throughput ausente, todos os agentes fizeram essa proposta. A concordância final reflete sobretudo a ação do fallback nesse caso. Os resultados são descritivos de dois casos piloto. As notas humanas continuam vazias.

A referência Python sobre o Excel oficial escolheu `nenhuma_acao` nas duas janelas conforme a pré-especificação. Esta execução está em `results/etapa7/excel-python/`. A exploração A–E ficou planejada separadamente. O plano final de seis casos está salvo em `results/etapa7/final-planejado/` e aguarda autorização.
