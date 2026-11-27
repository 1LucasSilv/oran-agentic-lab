# Recuperação documental 3GPP

O modo `--rag` recupera contexto técnico para o mesmo agente Ollama do laboratório. Use-o com ou sem `--mcp`. O detector continua usando dados históricos e critérios experimentais. O simulador recebe a proposta de três campos que já valida.

## Preparar os recursos locais

Na raiz do projeto, ative o ambiente virtual conforme o [README](../README.md). Os comandos abaixo são comuns ao PowerShell e ao Bash/Zsh. O extra `rag` instala PyPDF na versão fixada. Com o serviço Ollama ativo, baixe o modelo de embeddings se ele ainda estiver ausente e se o download puder ser realizado.

```sh
python -m pip install -e ".[test,mcp,rag]"
ollama list
ollama pull embeddinggemma
```

O modelo gerador padrão é `qwen2.5:1.5b`. `embeddinggemma` tem cerca de 622 MB na tag padrão. O sistema usa HTTP em loopback, sem serviço remoto, e consulta os digests das tags instaladas. Para outro modelo de embeddings local, use `--modelo-embeddings` nos comandos de indexação, busca, verificação e loop. Consulte também o [guia de instalação e limpeza](INSTALACAO.md). [API de embeddings do Ollama](https://docs.ollama.com/api/embed) · [Ficha de embeddinggemma](https://ollama.com/library/embeddinggemma)

## Obter as especificações

O [manifesto](../src/oran_lab/rag_manifest.json) registra títulos, versões, release, procedência, páginas, cláusulas selecionadas e SHA-256. O corpus inicial usa somente a Release 18 destas duas publicações oficiais:

- **3GPP TS 28.552 V18.7.0.** Mede desempenho 5G. A seleção inclui throughput UL do UE e uso/disponibilidade de PRB UL. [PDF oficial](https://www.etsi.org/deliver/etsi_ts/128500_128599/128552/18.07.00_60/ts_128552v180700p.pdf)
- **3GPP TS 38.300 V18.4.0.** Descreve NR e NG-RAN. A seleção inclui divisão funcional e informações de carga. [PDF oficial](https://www.etsi.org/deliver/etsi_ts/138300_138399/138300/18.04.00_60/ts_138300v180400p.pdf)

Obtenha as cópias previstas no manifesto com `oran-rag obter`. Para importar PDFs que já baixou pelos links oficiais, preserve os nomes de arquivo e passe a pasta de origem com `oran-rag obter --importar "caminho/para/pdfs"`. Também é possível colocá-los manualmente em `data/rag/documentos/`. O verificador confere os hashes, e a extração confere a capa e o total de páginas. Uma cópia divergente exige revisão manual. Guarde PDFs, índices e resultados com trechos apenas localmente e fora do Git. Consulte as condições da ETSI antes de reproduzir ou compartilhar conteúdo desses documentos. [Uso em pesquisa](https://www.etsi.org/expertise/research-innovation-support/) · [Termos da ETSI](https://www.etsi.org/terms/) · [Licenças de reprodução](https://www.etsi.org/resources/intellectual-property-rights/)

## Construir, consultar e atualizar o índice

```sh
oran-rag obter
oran-rag indexar
oran-rag verificar
oran-rag buscar --consulta "3GPP measurement definitions: DRB.UEThpUl and uplink physical resource block use"
```

A indexação trabalha com seis cláusulas selecionadas no manifesto. O PyPDF extrai texto das páginas físicas correspondentes. A extração descarta cabeçalhos recorrentes, entradas de sumário identificáveis e linhas vazias ou sem conteúdo textual. Cada fragmento pertence a uma cláusula e registra as páginas físicas do PDF, contadas a partir de 1. A formatação de fórmulas, tabelas e figuras pode se perder na extração. Para examiná-las, consulte a página original.

Cada fragmento tem até **1.000 caracteres, cerca de 256 tokens por estimativa**, com sobreposição de aproximadamente 120 caracteres em limites de palavras. A entrada do modelo de embeddings inclui o título da cláusula e o texto, ou a consulta técnica precedida de um marcador de busca. As chamadas usam `/api/embed` com `truncate: false`. O índice JSON guarda vetores normalizados, metadados, versão do extrator e checksum. Um índice incompatível com o manifesto, o formato, a versão do PyPDF ou a tag/digest do modelo exige reconstrução com `oran-rag indexar`. A substituição do índice ocorre após validação e gravação da nova cópia. A busca usa similaridade de cosseno, por padrão **Top-2** de cláusulas distintas e score mínimo **0,35**. Esse limiar é experimental. Use `--top-k` e `--score-minimo` para a busca avulsa, ou `--top-k-rag` e `--score-minimo-rag` no loop.

O diagnóstico `oran-rag verificar` mostra PyPDF, hashes dos documentos, modelo/digest e integridade do índice. Uma ausência aparece no JSON e gera código de saída 1. `--documentos`, `--indice` e `--api` permitem apontar para outros caminhos e portas locais. No loop, o caminho correspondente é `--indice-rag`. Os PDFs são necessários para reconstruir o índice. A busca usa a cópia indexada e os metadados registrados. Para remover o índice, mova apenas `data/rag/indice.json` para a lixeira após conferir o caminho. Os documentos podem ser preservados para reconstrução.

## Rodar o cenário sintético

```sh
oran-loop --sintetico --modo python
oran-loop --sintetico --modo ollama --contexto 8192 --geracao 512 --max-chamadas 2 --saida results/etapa6/ollama-sem-rag
oran-loop --sintetico --modo ollama --contexto 8192 --geracao 512 --max-chamadas 2 --rag
oran-loop --sintetico --modo ollama --contexto 8192 --geracao 512 --max-chamadas 2 --mcp --consultas-mcp 1 --rag
```

O modo Ollama com MCP sem RAG continua disponível com `--mcp`. A consulta do RAG é construída a partir dos nomes e conceitos das métricas disponíveis na janela autorizada. Trechos completos que cabem no orçamento entram no contexto final, depois das consultas MCP, se habilitadas. O cálculo usa bytes UTF-8 como estimativa conservadora dos tokens de texto no Qwen, reserva 256 para a formatação do chat e preserva o espaço da resposta (`--geracao`). Modelos ou templates diferentes podem exigir outra estimativa. Evidências, restrições e resultados MCP permanecem intactos. Se a configuração não comportar a entrada operacional, a decisão segue pela política Python. Com `--rag`, os padrões são 8.192 de contexto e 512 de geração. A demonstração fixa esses dois valores nos dois modos.

As referências curtas `R1`, `R2` mapeiam para os trechos efetivamente enviados. O agente responde em JSON com um campo de referências auditado à parte. O campo omitido ou um ID repetido ou fora dos trechos enviados invalida a proposta. Uma lista vazia é válida e indica uma decisão sem citação. O simulador ainda verifica as ações e os parâmetros. Uma citação que passa nessa checagem só comprova que o trecho estava disponível na entrada. É preciso leitura técnica para avaliar o vínculo entre a citação e a afirmação. O texto documental não determina ações, escala do dataset nem limiares do detector.

O JSON em `results/etapa6/` registra a resposta bruta, o contexto efetivo, os scores, as páginas, as referências e as validações da ação, além de tempos e tokens reportados pelo Ollama. O custo de indexação é separado da recuperação e do chat. Resultados sem trechos utilizáveis seguem o fluxo de decisão seguro e aparecem com sua limitação registrada. Citações inventadas e falhas restantes acionam a política Python. Decisões de fallback e respostas sem citações válidas ficam fora da contagem de decisões com fundamentação documental validada.

### Remover o modelo de embeddings

Confira pelo `ollama list` se a tag é a escolhida e se outros projetos a utilizam. Se decidiu removê-la, rode `ollama rm embeddinggemma` ou informe a tag exata instalada. O índice fica indisponível para recuperação até restaurar o mesmo modelo/digest ou reconstruí-lo com outro modelo local.

## Validação observada

No Windows 11 AMD64, com Python 3.13.0, PyPDF 6.10.2 e Ollama 0.40.18, a preparação dos dois PDFs oficiais gerou 15 fragmentos e vetores de dimensão 768. A extração e as chamadas de indexação levaram cerca de 0,48 s e 6,50 s, respectivamente. Os dois lotes de embeddings reportaram 3.036 tokens de entrada. A consulta técnica avulsa recuperou as cláusulas 5.1.1.3.3 (PDF p. 52, cosseno 0,694) e 5.1.1.2.8 (PDF p. 41, cosseno 0,613) da TS 28.552 V18.7.0 em 0,23 s. Uma consulta sobre reporte de carga recuperou as cláusulas 15.5.1.2 (PDF p. 141–142, cosseno 0,633) e 4.2 (PDF p. 26, cosseno 0,443) da TS 38.300 V18.4.0.

O par sintético usou `qwen2.5:1.5b` Q4_K_M (digest `65ec06548149…`), temperatura 0, semente 42, contexto 8.192, geração máxima de 512 tokens e duas chamadas. O índice usou `embeddinggemma:latest` (digest `85462619ee72…`). Os digests completos, parâmetros, prompts e respostas estão nos artefatos locais.

| Modo | Chamadas de chat | Tokens de entrada / saída informados | Tempo total de chat | Resultado |
| --- | ---: | ---: | ---: | --- |
| Ollama sem RAG | 2 | 1.922 / 213 | 15,94 s | Sem fallback. O modelo registrou o alerta. |
| Ollama com RAG | 2 | 3.262 / 293 | 47,30 s | Uma decisão do modelo com duas citações verificadas, aceita sem efeito adicional. O fallback registrou o alerta após uma proposta recusada. |
| Ollama com MCP e RAG | 2 | 2.115 / 167 | 39,40 s | Uma chamada selecionou a consulta MCP. A outra produziu uma ação recusada. O fallback registrou o alerta. |

A recuperação totalizou 0,37 s no modo RAG e 0,20 s no modo combinado. Os tempos são observações locais e variam com CPU, carga e residência dos modelos. A execução inicial com limite de 256 tokens atingiu o teto de geração nos dois chats RAG e acionou o fallback. A nova execução usou uma orientação mais curta para a justificativa e 512 tokens nos dois lados do par. Os arquivos ficam em `results/etapa6/windows/`, com a segunda rodada em `validacao-512/`. A demonstração verifica o funcionamento em um cenário. A avaliação comparativa depende da Etapa 7.
