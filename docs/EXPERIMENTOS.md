# Avaliação experimental da Etapa 7

## Pergunta e condições

O protocolo mede concordância com expectativas operacionais fixadas em casos sintéticos. As expectativas representam conformidade com o protocolo do simulador. Rótulos independentes de falhas reais e evidência de superioridade da política Python exigiriam outra validação. A referência A permite observar o que a política determinística entrega. O contraste B/C investiga o efeito de fornecer contexto documental e B/D o de permitir consulta MCP. C/E e D/E ajudam a examinar a combinação. O estudo também registra o custo de cada configuração e as consequências das propostas no simulador.

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
```

**Gere o plano final após o commit definitivo do código.** A identidade inclui a revisão Git e os hashes das fontes, portanto até um commit com as mesmas fontes altera a revisão esperada. Preserve planos anteriores e use uma pasta nova, por exemplo `oran-experiment planejar --fase final --saida results/etapa7/final-revisao-definitiva`.

O plano controlado final prevê 90 sessões em seis casos e três sementes, com 18 sessões Python, 72 decisões finais de LLM e até 36 seleções MCP. O teto é **108 chamadas de chat**. O ciclo completo é um desenho separado. Com as mesmas seis séries e três sementes, o teto de chat é 648. Planeje e autorize cada desenho antes de executar. Após autorização da bateria controlada, use `oran-experiment executar --fase final --autorizar-final --saida results/etapa7/final-revisao-definitiva` com os mesmos parâmetros.

A execução final e sua retomada exigem pré-verificação de recursos. B–E verificam a versão do serviço local Ollama e o digest do gerador. C e E também verificam a tag e o digest do modelo de embeddings e a integridade e compatibilidade do índice RAG com o modelo e o plano. A dispensa os recursos Ollama. A verificação consulta metadados e arquivos locais, sem inferência. Cada tentativa fica em `pre-verificacoes/`, identificada como `pre_execucao` ou `pre_retomada`. Indisponibilidade nessa verificação bloqueia novas sessões e não entra nas contagens experimentais. Problemas após o início ficam registrados nos eventos e resultados da sessão.

Use `--retomar` com os mesmos argumentos e a pasta original. O executor preserva resultados concluídos, trava a pasta contra gravadores simultâneos e reserva cada chamada em disco antes do envio. Se um processo cair depois da reserva, a tentativa continua ocupando a cota. A sessão fica interrompida na retomada e nenhuma de suas chamadas é reenviada. Sessões ainda pendentes podem continuar. Se o teto restante for menor que a reserva máxima da próxima sessão, a execução para antes de iniciá-la. Use uma nova pasta quando alterar limite, seleção, recursos ou código. A CLI expõe as funções do módulo `experiment`, e os eventos persistidos podem ser consultados por programa independentemente do terminal.

## Medidas e revisão humana

`relatorios/decisoes.csv` inclui todas as oportunidades planejadas e distingue original, aceitação/recusa, decisão final, mudança, ausência de proposta, falhas e fallback. A concordância compara ação e parâmetros com a pré-especificação. A medida sobre oportunidades avaliadas inclui ausência como não concordante, e a medida condicional tem denominador próprio para propostas legíveis. Sessões pendentes/interrompidas ficam explícitas. A decisão final Python aparece como resultado operacional, inclusive em fallback. A coluna de mudança atribuída ao modelo exige execução com origem Ollama.

Uma consulta MCP válida é marcada como útil nesta contagem quando acrescenta janela anterior ou pelo menos um registro anterior com medição. Leituras válidas que repetem informação-base são contadas como redundantes por esse critério. É uma medida estrutural de informação nova. A utilidade para a decisão pode exigir leitura humana. As tabelas distinguem fragmentos recuperados, apresentados e citados. A contagem de decisões RAG com citação exige IDs apresentados, conferidos e uma decisão final de origem Ollama.

As tabelas CSV/JSON mostram denominadores, médias, medianas, desvio-padrão e extremos. O resumo agrega primeiro por caso, com peso igual por caso, e reporta dispersão entre casos. Os contrastes pareiam por caso, janela e semente e mostram diferenças por caso. Repetições da mesma janela são repetições técnicas. As tabelas descrevem o cenário sem testes de significância ou métricas de classificação de falhas reais.

Os tempos de consultas MCP somam leituras instrumentadas, inclusive recusas com duração registrada. A descoberta do catálogo, a seleção feita pelo chat e a execução da ação ficam fora dessa soma. Os tokens de embeddings vêm de `prompt_eval_count` da recuperação, quando informado. Célula vazia ou `null` indica falta de medida. Zero indica medida de valor zero. Há gráficos separados de concordância original, concordância final, recusas do modelo, fallbacks e custos. A taxa de recusas usa propostas submetidas ao validador. A taxa de fallback usa decisões avaliadas do agente.

O CSV `avaliacao-cega.csv` usa um ID opaco e apresenta evidências, estado autorizado imediatamente anterior à decisão e ações disponíveis com seus parâmetros. A configuração e o resultado operacional ficam na trilha local. O estilo, as menções a ferramentas e ao texto normativo podem sugerir a origem. Envie ao avaliador uma cópia do CSV, sem a chave local. Para a leitura documental, forneça separadamente o pacote `avaliacao-referencias.json` com os trechos pertinentes. Cada critério vai de 0 a 2:

| Critério | 0 | 1 | 2 |
| --- | --- | --- | --- |
| Fidelidade às evidências KPM | Inventa ou contradiz a janela | Usa parte dos sinais ou omite detalhe decisivo | Usa corretamente os sinais, a referência e a cobertura pertinentes |
| Coerência operacional | Ação incompatível com o estado | Ação plausível com justificativa incompleta | Ação proporcional às evidências e ao estado autorizado |
| Correção técnica | Afirmação técnica incorreta | Explicação plausível com imprecisão | Conceitos e interpretação tecnicamente corretos |
| Reconhecimento das limitações | Conclusão indevida sobre falha, causa ou unidade | Reconhece parte da incerteza | Delimita de forma adequada inferência, dados e simulador |
| Pertinência das referências | Trechos sem relação | Relação parcial | Trechos diretamente pertinentes à questão |
| Suporte das referências | A citação contradiz ou não sustenta a afirmação | Sustenta apenas parte | Sustenta a afirmação atribuída |

Pontuações começam vazias. Os dois itens documentais são independentes dos quatro critérios principais e só se aplicam quando há trechos para conferir. Identifique um único avaliador por lote, por exemplo `oran-experiment importar-avaliacoes --saida results/etapa7/meu-piloto --avaliacoes caminho/avaliado.csv --avaliador rev-01`. A coluna `avaliador` do CSV também aceita o identificador. Cada importação efetiva preserva um lote próprio.

Os arquivos `avaliacoes_consolidadas.csv` e `avaliacoes_consolidadas.json` são locais. Eles mostram totais e recortes por avaliador, configuração e critério. Cada entrada usa a pontuação efetiva mais recente para o mesmo avaliador, resposta e critério, com células vazias preservando notas anteriores. O denominador esperado é o número de respostas elegíveis na configuração multiplicado pelo número de avaliadores ou lotes históricos sem identificação no recorte. A média usa apenas notas registradas. Lotes antigos sem identificação permanecem explícitos, sem atribuir uma identidade a eles.

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

A referência Python sobre o Excel oficial escolheu `nenhuma_acao` nas duas janelas conforme a pré-especificação. Esta execução está em `results/etapa7/excel-python/`. A exploração A–E ficou planejada separadamente. O plano em `results/etapa7/final-planejado/` permanece como registro histórico. A bateria final exige um plano da revisão definitiva e autorização.

## Bateria controlada final

O plano definitivo está em `results/etapa7/final-revisao-definitiva/plano.json`. Foi gerado no commit `b14eccc6b02af39c27f3b60da5aa4cfc055421c7` com SHA-256 de identidade `78205810072de392475bb07445ea843bdfcc4996c67b049cb376bffbdac30498`. A pré-verificação confirmou Ollama 0.40.18, Qwen 2.5 1.5B e EmbeddingGemma pelos respectivos digests e verificou a integridade e a compatibilidade do índice. Os hashes completos dos modelos, do índice e das fontes constam do plano, do manifesto ou do registro de pré-verificação.

O desenho salvo contém as 90 sessões de decisão controlada, com os seis cenários, as cinco configurações e as sementes 42, 43 e 44. O teto de 108 chamadas abrange 72 decisões e até 36 seleções MCP. Temperatura 0, contexto de 8.192, limite de geração de 512, Top-2 e cosseno mínimo de 0,35 foram conferidos antes da execução.

### Execução observada

Em 27 de novembro de 2026, a execução `18d6d4744fcb45e2bf39ca50dacee10d` concluiu **90 de 90 sessões**, com zero pendentes, interrompidas ou com falha de sessão. No Windows 11 AMD64, com Python 3.13.0, Intel Core i5-1235U e 16 GiB de RAM, passaram cerca de **34 min 24 s** até o último evento de janela. Houve 108 chamadas únicas, todas com retorno HTTP 200. Uma decisão do modo E, no cenário de dados ausentes com semente 43, atingiu 512 tokens e não produziu proposta utilizável. O fallback tratou essa falha de resposta.

| Configuração | Chat | Originais concordantes | Aceitas / recusadas pelo validador entre propostas do modelo | Finais concordantes | Fallbacks | Mudanças executadas pelo modelo / fallback / referência |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0 | — | — | 18/18 | — | 0 / 0 / 6 |
| B | 18 | 3/18 | 3 / 15 | 18/18 | 15 | 3 / 3 / 0 |
| C | 18 | 0/18 | 0 / 18 | 18/18 | 18 | 0 / 6 / 0 |
| D | 36 | 6/18 | 6 / 12 | 18/18 | 12 | 6 / 0 / 0 |
| E | 36 | 6/18 | 6 / 11 | 18/18 | 12 | 6 / 0 / 0 |

Das 72 oportunidades de decisão do modelo, 15 propostas originais concordaram com o protocolo. Houve 56 recusas de `ampliar_janela_analise` por evento inexistente e uma resposta incompleta. Os 57 fallbacks produziram decisões concordantes, com 9 mudanças. Ao todo, o simulador executou 30 registros de alerta e confirmou 60 decisões finais aceitas sem alteração. Os registros feitos pela referência e pelo fallback são atribuídos ao Python.

| Cenário | B original | C original | D original | E original | Finais A–E, somadas | Fallbacks B–E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Operação estável | 0/3 | 0/3 | 0/3 | 0/3 | 15/15 | 12 |
| Queda isolada de throughput UL | 0/3 | 0/3 | 0/3 | 0/3 | 15/15 | 12 |
| Queda persistente de throughput UL | 3/3 | 0/3 | 3/3 | 3/3 | 15/15 | 3 |
| Queda simultânea de throughput e PRB UL | 0/3 | 0/3 | 3/3 | 3/3 | 15/15 | 6 |
| Recuperação | 0/3 | 0/3 | 0/3 | 0/3 | 15/15 | 12 |
| Dados ausentes | 0/3 | 0/3 | 0/3 | 0/3 | 15/15 | 12 |

As 30 combinações cenário–configuração tiveram ação e parâmetros finais idênticos nas três sementes. A mesma comparação das propostas originais deu **6/6** trincas idênticas em B, **5/6** em C, **3/6** em D e **4/5** trincas comparáveis em E. A trinca de dados ausentes em E tem uma proposta ausente. As três sementes são repetições técnicas da mesma janela.

### Investigações e custos

D e E selecionaram `consultar_historico` 18 vezes cada. As 36 leituras foram válidas e acrescentaram dados pelo critério estrutural do protocolo. Houve zero inválidas e zero redundantes. C e E recuperaram e apresentaram 36 trechos cada. Foram conferidas 27 ocorrências de IDs citados em C e 25 em E. Seis decisões do modelo terminaram com citação conferida, todas em E. A pertinência técnica e o suporte das citações ainda dependem de avaliação humana.

| Configuração | Chat acumulado / mediana por sessão (s) | Tokens de chat entrada / saída | Tokens de entrada em cache | Tempo de leitura MCP (s) | Recuperação RAG (s) | Tokens de embeddings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B | 406,40 / 24,57 | 19.329 / 2.455 | 11.582 | — | — | — |
| C | 515,52 / 27,38 | 28.944 / 2.464 | 18.489 | — | 4,741 | 819 |
| D | 512,89 / 25,52 | 28.281 / 3.107 | 17.804 | 0,324 | — | — |
| E | 597,90 / 32,00 | 37.896 / 3.379 | 27.618 | 0,398 | 8,290 | 819 |

A mediana agrega o tempo de chat da sessão, incluindo a seleção em D e E. Os tempos são observações deste host e desta execução, com cache variável. A referência A dispensa chat. Os CSV/JSON em `results/etapa7/final-revisao-definitiva/relatorios/` incluem descritivas, pares, recortes por configuração e cenário e a comparação por semente. A auditoria verificou estados iniciais, expectativas, unicidade dos registros de chat, os gráficos e as 89 respostas exportadas para revisão cega. Nenhuma nota humana foi importada.

Os resultados medem conformidade com o protocolo de seis cenários sintéticos. Eles descrevem comportamento operacional e custos neste desenho. A avaliação de qualidade das justificativas e referências permanece pendente. A Fase I conserva a separação entre decisões simuladas e efeitos de rede.

## Experimentos configuráveis na interface

Em `oran-ui`, abra **Experimentos** e escolha fontes, tratamentos A–E, parâmetros comuns, sementes, repetições e orçamento. A prévia roda detector e replay sem inferência. Com a configuração congelada e confirmação explícita, o worker registra revisão, hashes, digests, condições por tratamento e ordem determinística embaralhada com semente 42. O teto soma uma chamada final por oportunidade B–E e até uma adicional de seleção nos tratamentos D e E. A reserva é persistida antes de enviar cada chamada.

Na decisão controlada, o mesmo prefixo causal e o mesmo estado inicial preparado pela política determinística são usados em cada tratamento da fonte. A preparação fica em um evento separado. No ciclo completo, cada sessão tem um simulador independente e suas decisões evoluem o estado usado nas próximas janelas. A janela-alvo é comum a todas as fontes selecionadas no modo controlado. As condições comuns são fixadas inclusive em planos marcados como exploração. A finalidade identifica o uso de um desenho ad hoc.

As saídas ficam em `results/ui/experimentos/<id>/` com sessões, eventos brutos, propostas, validações, fallbacks e relatório compatível com a estrutura da Etapa 7. Os resultados parciais ficam acessíveis por sessão. Para agregar localmente uma pasta parcial, use `oran-experiment agregar --saida results/ui/experimentos/<id>` depois de o worker encerrar. Uma nova submissão recebe outra identidade. Interrupções preservam as reservas e os eventos já gravados, sem reenvio automático.

Nos cenários personalizados, as expectativas de registrar alerta ou de nenhuma ação referem-se ao ID de janela do replay escolhido e só entram nas métricas quando declaradas. Elas descrevem conformidade com o protocolo operacional. A concordância de uma decisão final por fallback é separada da concordância da proposta original. Use o protocolo controlado anterior para reproduzir a bateria publicada em `results/etapa7/`.

É possível associar mais de um gerador à mesma arquitetura. O plano atribui um identificador a cada combinação e registra os parâmetros de cada sessão. Após a pré-verificação, o manifesto inclui tag, digest, arquitetura de tratamento, arquitetura e número de parâmetros do modelo quando informados pelo Ollama. Fontes, sementes, oportunidades, opções de inferência e recursos MCP/RAG aplicáveis são comuns entre tratamentos. O teto de chat é calculado por combinação antes do início.

O relatório configurável pareia por **caso, janela, semente e repetição**. Assim, duas repetições da mesma semente geram dois pares quando ambas as medidas existem. São repetições técnicas da mesma janela. Os relatórios históricos da Etapa 7 conservam seu esquema e os pares definidos no protocolo publicado.

O comando de interrupção da interface é cooperativo. Depois de gravar a janela em curso, o worker deixa as demais oportunidades pendentes e agrega os registros presentes. Os arquivos de reserva e de retorno permanecem no diretório da sessão.
