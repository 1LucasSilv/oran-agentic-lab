# Etapa 4 — Agente Ollama

O agente interpreta uma janela de KPMs históricos e propõe uma ação do simulador. O hospedeiro decide quando consultar o modelo, atribui a origem da decisão, vincula a proposta à janela e chama o validador Python. O executor e o verificador são os mesmos da Etapa 3.

## Preparar e executar

Ative o ambiente e instale o laboratório conforme o [README](../README.md). O cliente HTTP usa a biblioteca padrão de Python. Em uma máquina com Ollama instalado, use `ollama list` para verificar o serviço e as tags. Se necessário, inicie o serviço local com `ollama serve`. Para uma instalação nova, consulte as [instruções oficiais do Ollama](https://ollama.com/download). A obtenção do modelo é uma operação separada, com consumo de disco e rede. Para baixar a tag escolhida quando autorizado, use `ollama pull qwen2.5:1.5b`.

```bash
arquivo='data/raw/20250321_11.17.57_KPM_vs_iper3_1000ms_05_weeks(2).xlsx'
oran-loop --modo python --sintetico
oran-loop --modo ollama --sintetico --max-chamadas 2
oran-loop "$arquivo" --modo ollama --selecao todas --max-chamadas 2
pytest -q
ORAN_TEST_OLLAMA=1 pytest -q tests/test_agent.py -k local_ollama_integration
```

A suíte padrão usa um cliente injetável. O último comando envia uma chamada real na primeira janela suspeita do cenário sintético e confere a validação da proposta. Uma recusa operacional seguida de fallback é um resultado válido para esse teste de integração.

| Opção | Padrão | Interpretação |
|---|---|---|
| `--modelo`, `--api` | `qwen2.5:1.5b`, `http://127.0.0.1:11434` | Tag local pequena para uso inclusive com CPU. O endereço aceita HTTP em loopback. |
| `--timeout` | 90 s | Timeout de operação do socket. Cada janela selecionada gera no máximo uma tentativa. |
| `--temperatura`, `--seed` | 0, 42 | Parâmetros enviados ao runtime. A reprodutibilidade da geração depende também da versão, quantização e hardware. |
| `--contexto`, `--geracao` | 4096, 256 | Limites solicitados em tokens. Respostas interrompidas pelo limite de geração acionam fallback. |
| `--max-chamadas` | 4 | Orçamento de inferências de chat na ordem do replay. As consultas de metadados são registradas à parte das inferências. |
| `--falhas-consecutivas` | 2 | Ao atingir o limite, suspende novas inferências pelo restante da execução. |
| `--selecao` | `suspeitas` | Consulta nas janelas suspeitas, incluindo continuação do episódio. `todas` inclui a formação da referência. |
| `--saida` | `results/etapa4/<modo>/<origem>/` | Use um diretório próprio para preservar repetições do experimento. |

## Da janela à decisão

1. `run_loop` executa o mesmo detector e percorre suas saídas na ordem do replay. O catálogo completo fica no código hospedeiro. `build_context` recebe apenas a detecção atual e o estado já confirmado. Envia limites da janela em Register, regra, referência histórica, medianas, cobertura, variações, persistência, o evento do episódio atual quando existente e as opções do simulador. O contexto exclui o nome e o hash do dataset, a contagem total de janelas e os valores brutos de linhas futuras.
2. `AgentSession.decide` aplica a seleção, o orçamento e o limite de falhas. O cliente envia o prompt de sistema versionado e o contexto serializado em `POST /api/chat`, com `stream=false` e JSON Schema em `format`. O corpo possui uma alternativa de esquema por ação. [API de chat](https://docs.ollama.com/api/chat) · [Saídas estruturadas](https://docs.ollama.com/capabilities/structured-outputs)
3. `parse_proposal` exige um objeto com exatamente `acao`, `parametros` e `justificativa` textual preenchida. Cada ação admite apenas seus campos, com tipos estritos, prioridades enumeradas e alvos numéricos inteiros positivos. Campos duplicados, valores não finitos, saída incompleta ou texto fora do JSON invalidam a resposta.
4. `Simulator.apply` recebe o ID da janela do hospedeiro e a origem `ollama`. Verifica evento, evidências, limites e orçamento. Executa sobre uma cópia e confirma apenas a mudança verificada. O modelo tem acesso somente ao contrato de propostas. [Parâmetros e efeitos das cinco ações](ACAO_SIMULADA.md)

Exemplo de forma válida para o contrato, sujeito à existência do evento e aos limites daquela sessão:

```json
{"acao":"priorizar_evento","parametros":{"evento_id":"alerta-5","prioridade":"alta"},"justificativa":"Investigar a queda persistente de throughput UL identificada na janela."}
```

## Fallback e atribuição

Falha de conexão, timeout, HTTP de erro, resposta incompatível, recusa do simulador ou execução com falha acionam a política Python. Uma nova suspeita pode gerar `registrar_alerta`; nas demais situações, a política propõe `nenhuma_acao`. O fallback atravessa o mesmo validador e é identificado como `fallback_python`. Falhas consecutivas incluem recusas operacionais. Uma resposta aceita e verificada zera a contagem.

Janelas fora da seleção ou além do orçamento recebem a política determinística. Janelas elegíveis após a abertura do circuito recebem fallback com o motivo da dispensa. Em todos os casos há uma decisão final por janela. Quando o simulador recusa uma tentativa do modelo também existe uma entrada anterior de auditoria referente à recusa.

## Ler os resultados

Abra `relatorio.md` para os totais e `resultados.json` para inspecionar uma decisão. Em `agente.decisoes`, `contexto` e `resposta_http` identificam a entrada e a resposta original de cada inferência. `proposta_modelo`, `erro`, `fallback`, `origem_decisao_final` e `origem_execucao` distinguem a tentativa e o desfecho. Os IDs `historico_modelo` e `historico_final` apontam para validação, verificação e estados antes/depois em `simulador.historico`. O prompt, seu hash, esquema e configuração são comuns a todas as decisões da execução.

A auditoria mede o tempo da chamada HTTP e o tempo total da decisão em segundos. Preserva as durações do Ollama em nanossegundos e os tokens que ele informa. Digest, quantização, versão do serviço, informações do host e residência final do modelo são consultados quando disponíveis. Metadados ausentes ficam nulos. As medições de desempenho variam com carga, cache e residência do modelo. O cenário, as detecções, limites e regras Python podem ser reproduzidos independentemente desses tempos.

## Limitações

A duração física de cada janela permanece indeterminada. O PRB está em escala bruta e a interpretação temporal de Latency continua em aberto. Uma justificativa pode conter inferências científicas incorretas mesmo com uma proposta estruturalmente válida. O verificador avalia o efeito operacional no simulador. A ação de intensificação configura uma passagem futura, e a passagem corrente conserva as janelas já calculadas. Uma avaliação de benefício dessa ação requer implementar e medir a inspeção subsequente.

Esta demonstração usa um único cenário sintético e um Excel sem rótulos independentes. Para comparações futuras, fixe o mesmo conjunto de janelas, detector, parâmetros, limites e critérios de avaliação antes das inferências.

## Execuções locais observadas

As inferências usaram Ollama 0.40.18, `qwen2.5:1.5b`, quantização `Q4_K_M` e digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`. O host apresentou Intel Core i3-14100, oito CPUs lógicas disponíveis e 6,9 GiB de RAM total. Ao fim de cada execução, a API informou 1.173.136.342 bytes de residência, zero bytes de VRAM e contexto de 4.096 tokens.

Na primeira execução, o prompt `kpm-v1` resultou em quatro propostas recusadas nas duas fontes. O cenário sintético exigiu que o fallback registrasse o alerta. Essa auditoria, com prompt e respostas originais, ficou em `results/etapa4/prompt-v1/ollama/`. A versão `kpm-v2` explicita as ações com alvo disponível e a diferença entre o identificador de episódio do detector e um evento já registrado. A lista é orientação ao modelo. A autorização continua com o validador Python.

| Execução final | Janelas | Chamadas | Propostas do modelo aceitas | Mudanças executadas pelo modelo via simulador | Fallbacks | Alertas finais |
|---|---:|---:|---:|---:|---:|---:|
| A · Python sintético | 8 | 0 | — | — | 0 | 1 |
| B · Ollama sintético | 8 | 2 | 2 | 1 | 0 | 1 |
| C · Ollama oficial | 38 | 2 | 0 | 0 | 38 | 0 |

Em B, a janela 5 gerou o registro de `alerta-5`. Na janela 6, a proposta de ampliação para dois registros foi aceita como meta já atendida. O total consultado permaneceu igual. O texto livre do modelo sugeriu causas sem evidência e mencionou ajuste de persistência. O histórico operacional registra somente o registro do alerta. Em C, o orçamento foi usado nas duas primeiras janelas de formação de referência. O modelo indicou os eventos inexistentes `janela_1` e `janela_2`. Após as duas recusas, o circuito suspendeu as chamadas para as 36 janelas restantes. As 38 decisões finais de fallback foram `nenhuma_acao`.

B consumiu 1.922 tokens de entrada e 241 de saída, com 17,09 s acumulados nas chamadas. C consumiu 1.866 tokens de entrada e 301 de saída em 17,61 s. Esses tempos são observações desta execução. O ajuste do prompt usou os mesmos casos, o que limita qualquer conclusão sobre generalização. A comparação confirmou as mesmas detecções e parâmetros em A e B e reproduziu as 38 detecções do Excel da Etapa 3 em C.
