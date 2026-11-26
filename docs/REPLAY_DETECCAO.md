# Etapa 2 — Replay histórico e detector de referência

O leitor de Excel da Etapa 1 entrega a aba de KPMs e o hash do arquivo. `replay.py` valida a sequência e produz janelas com os respectivos registros e linhas do Excel. `detector.py` avalia as janelas por segmento e grava as evidências, situações e alertas em JSON, com um resumo em Markdown.

## Replay

- A ordem das linhas da planilha é a ordem do replay. `Register` deve conter números inteiros positivos estritamente crescentes. Células vazias, texto, duplicatas e recuos nessa coluna geram erro com a linha do Excel.
- Um salto em `Register` inicia um novo segmento. Cada janela contém apenas registros consecutivos disponíveis naquele segmento. Uma aba sem linhas produz zero janelas.
- O tamanho é o máximo de registros por janela. O avanço define a distância em registros entre os inícios dentro do segmento. Um avanço menor que o tamanho cria sobreposição. Um avanço maior cria trechos sem cobertura.
- O replay para quando uma janela alcança o fim do segmento. Se ela for parcial, é emitida por padrão e marcada como incompleta. A opção `--descartar-incompletas` a omite.
- O JSON lista os identificadores `Register` e os limites das linhas Excel de cada janela. A aba usa a primeira linha como cabeçalho, conforme o leitor existente.

## Métricas e regras

O throughput UL (`DRB.UEThpUl`) é a evidência principal. A comparação é relativa à própria série, com os valores na escala da planilha. O uso de recursos na mesma direção (`RRU.PrbTotUl`) oferece contexto adicional. Sua variação é calculada em relação à própria referência, sobre valores brutos. O denominador necessário para estimar ocupação de recursos é desconhecido. A EDA encontrou mediana zero no throughput DL e documentou a ambiguidade de `Latency`. [Auditoria da Etapa 1](EDA.md)

1. **Cobertura.** Para cada métrica, calcula-se a mediana dos valores numéricos, finitos e não negativos. Células vazias e valores inválidos são contados separadamente. A mediana exige a cobertura configurada. A janela deve estar completa e todos os registros devem identificar o UE. A análise espera um único UE por aba.
2. **Referência histórica.** Em cada segmento, a referência é a mediana das medianas das primeiras janelas elegíveis e sem registros compartilhados. A referência fica fixa depois de formada. Uma janela que toca a referência aguarda dados independentes. Para usar PRB como contexto, todas as janelas de referência precisam ter mediana de PRB disponível.
3. **Comparação.** A variação é `(mediana atual − mediana de referência) / mediana de referência`, com denominador positivo. O JSON registra ainda a variação em relação à janela elegível anterior mais recente sem registros compartilhados, quando disponível. Essa comparação ajuda a distinguir uma piora recente de uma queda sustentada em relação à referência.
4. **Detecção e alertas.** Uma janela abaixo do limiar de queda recebe situação `normal`. Ao atingir o limiar, a situação é `evidencia_insuficiente` até completar a persistência. Dentro de uma sequência de quedas, só contam janelas com registros posteriores aos da última janela contada. Reconhecida a persistência, a situação passa a `suspeita`. Quando o PRB UL também se mantém dentro da tolerância de queda ou aumenta, o detector registra essa combinação na regra. A mesma sequência suspeita compartilha um identificador e emite um único alerta na abertura.
5. **Interrupção.** Uma queda menor que o limiar, dados insuficientes para avaliação ou um trecho sem cobertura interrompem a sequência. Uma lacuna em `Register` também reinicia a referência. Janelas parciais, referência em formação ou referência de throughput sem denominador utilizável recebem `evidencia_insuficiente` com o motivo registrado.

### Parâmetros experimentais

| Opção | Padrão | Justificativa |
|---|---:|---|
| `--tamanho` | 30 registros | Resume oscilações individuais por uma mediana e mantém dezenas de janelas no Excel auditado. |
| `--avanco` | Igual ao tamanho | Produz janelas independentes por padrão. |
| `--referencia` | 3 janelas | A mediana reduz a influência de uma janela inicial atípica e mantém a referência curta. |
| `--queda` | 0,30 | Exige uma variação relativa substancial para este experimento. |
| `--persistencia` | 2 janelas | Exige confirmação por um segundo bloco independente e filtra quedas isoladas. |
| `--cobertura` | 0,80 | Exige que a mediana represente pelo menos quatro quintos dos registros. |
| `--tolerancia-prb` | 0,10 | Admite uma pequena redução de PRB ao identificar quedas de throughput com recursos aproximadamente mantidos. |

As frações de queda e cobertura aceitam valores maiores que zero até 1. A tolerância de PRB aceita de 0 a 1. Os valores iniciais são escolhas experimentais. Um regime de tráfego diferente pode exigir outra referência ou outra configuração. Persiste a incerteza sobre a duração das janelas em segundos. Uma queda de throughput pode acompanhar variações de demanda, e a regra de PRB descreve apenas a combinação observada.

## Resultados do Excel oficial

Na execução padrão foram emitidas 38 janelas dos 1.138 registros da aba `KPM Metrics`. As três primeiras formaram a referência e a última ficou incompleta, com 28 registros. Houve 34 janelas abaixo do limiar, quatro com evidência insuficiente e zero alertas. A origem e a revisão do Excel estão documentadas na [EDA](EDA.md). As saídas locais ficam em `results/etapa2/`.

## Cenários sintéticos

Os testes criam seus próprios dados para verificar expectativas previamente definidas, incluindo estabilidade, queda isolada, queda persistente, recuperação, PRB mantido, lacuna em `Register`, baixa cobertura e referência zero. Também comparam duas execuções byte a byte e verificam que o Excel de entrada mantém o conteúdo original. Esses cenários verificam a implementação das regras. Acurácia e F1-score em dados reais exigem verdade de referência independente.
