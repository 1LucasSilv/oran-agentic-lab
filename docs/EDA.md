# Auditoria da planilha OAI-KPM

A revisão inspecionada contém **1.138 registros de KPM de um único UE** e **840 registros de tráfego iperf3**. O tempo relativo do tráfego está documentado nos cabeçalhos. Para os KPMs, o significado temporal de `Latency` permanece em aberto. Essa distinção determina quais eixos podem ser usados nos gráficos e em comparações futuras.

## Proveniência e reprodução

| Campo | Valor |
|---|---|
| Fonte | [CTTCADAPTRU/OAI-KPM-dataset na revisão auditada](https://github.com/CTTCADAPTRU/OAI-KPM-dataset/tree/328ab90c9faabbba6a036255ac503683c227fa34) |
| Revisão | `328ab90c9faabbba6a036255ac503683c227fa34` |
| Acesso | 26 de novembro de 2026 |
| Licença do dataset | [CC0-1.0](https://github.com/CTTCADAPTRU/OAI-KPM-dataset/blob/328ab90c9faabbba6a036255ac503683c227fa34/LICENSE) |
| Arquivo | `20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks(2).xlsx` |
| SHA-256 | `d570d8c0567b7ec85fd5e3ca865d1cc109dc741583b01d3ee4f1ff964892d30c` |

Os autores descrevem cerca de 10.080 amostras ao longo de cinco semanas. As contagens abaixo correspondem às células do arquivo identificado pelo hash. O procedimento de reprodução está no [README do laboratório](../README.md). [Descrição dos autores](https://github.com/CTTCADAPTRU/OAI-KPM-dataset/blob/328ab90c9faabbba6a036255ac503683c227fa34/README.md)

## Estrutura e qualidade

| Aba | Linhas de dados | Colunas | Células ausentes na tabela | Linhas duplicadas |
|---|---:|---:|---:|---:|
| KPM Metrics | 1.138 | 11 | 1.137 | 0 |
| iperf3 traffic | 840 | 5 | 0 | 0 |
| KPM vs iperf3 | 0 | 0 | — | — |

A coluna K de `KPM Metrics` tem cabeçalho vazio e um único valor, 50.400, na célula K1139. Ela responde por todos os ausentes. O significado desse valor é desconhecido. A terceira aba contém dois gráficos do Excel. Um usa `Register` e `DRB.UEThpUl` da primeira aba, e o outro usa `Total time (sec)` e `Iperf bw (kbps)` da segunda.

## KPMs e unidades

| Coluna | Tipo inferido | Mínimo | Mediana | Máximo | Unidade ou interpretação |
|---|---|---:|---:|---:|---|
| Register | int64 | 1 | 569,5 | 1.138 | Índice com incremento 1 |
| UE.Id | int64 | 1 | 1 | 1 | Identificador do UE |
| Latency | int64 | 1742549397862580 | 1742549966362100 | 1742550534861330 | Unidade e semântica temporal em aberto |
| RRU.PrbTotDl | int64 | 15 | 130 | 225 | Uso de PRBs DL, escala sem confirmação |
| RRU.PrbTotUl | int64 | 950 | 6.167,5 | 15.995 | Uso de PRBs UL, escala sem confirmação |
| DRB.PdcpSduVolumeDL | int64 | 0 | 7 | 8 | Volume DL, unidade sem confirmação |
| DRB.PdcpSduVolumeUL | int64 | 1 | 1.061 | 4.865 | Volume UL, unidade sem confirmação |
| DRB.RlcSduDelayDl | float64 | 0,17 | 8,92 | 9,99 | Atraso DL, unidade sem confirmação |
| DRB.UEThpDl | float64 | 0 | 0 | 1.341,5 | Throughput DL, unidade sem confirmação |
| DRB.UEThpUl | float64 | 1,54 | 1.075,24 | 4.901,2 | Throughput UL, unidade sem confirmação |
| Unnamed: 10 | float64 | 50.400 | 50.400 | 50.400 | Nome atribuído pelo leitor à coluna K |

As métricas com nome têm 1.138 valores presentes. O throughput DL tem mediana zero e o UL varia ao longo dos registros. Os PRBs ultrapassam 100 em ambas as direções. O arquivo não fornece denominador para convertê-los em porcentagem. Diagnósticos de falha exigiriam evidência adicional.

## Tempo, tráfego e alinhamento

**KPM.** As 1.137 diferenças consecutivas de `Latency` são positivas. O mínimo é 999.310, a mediana é 1.000.000 e o máximo é 1.000.800 em escala bruta. Isso seria compatível com um intervalo próximo de um segundo **se** os valores fossem marcas em microssegundos. A planilha não identifica unidade, época ou fuso, e o README chama o campo de latência. A análise mantém os valores brutos e usa o índice `Register` no eixo horizontal do gráfico de KPMs.

**Tráfego.** `Iteration`, `Total time (sec)` e `Time (sec)` são inteiros. Há cinco iterações de 168 registros. O tempo total começa em 0 e termina em 50.340 s, com 839 intervalos de 60 s. O tempo dentro da iteração vai de 0 a 10.020 s e volta a zero quatro vezes. `Bandwidth (kbps)` e `Iperf bw (kbps)` são decimais com unidades explícitas. Seus intervalos observados são, respectivamente, 3,888–5.089,627 kbps e 11,583247–5.085,045472 kbps (extremos arredondados). O gráfico de tráfego usa o tempo total.

**Alinhamento.** Falta um marco verificável que relacione o zero de `Total time (sec)` a um registro KPM. A terceira aba usa eixos independentes, e as tabelas têm contagens e passos distintos. Qualquer junção temporal ou correlação ponto a ponto exigiria confirmar a natureza de `Latency`, sua unidade e a origem comum dos relógios.
