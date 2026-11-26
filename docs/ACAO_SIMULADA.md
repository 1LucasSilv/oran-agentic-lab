# Etapa 3 — Loop de ação simulada

`loop.py` chama `detect` com os parâmetros da Etapa 2. Para cada janela, `propose` gera uma proposta. `Simulator.apply` valida a proposta, prepara a alteração em uma cópia, verifica o efeito e registra o resultado no histórico. A lógica de detecção e seus valores padrão são os da [Etapa 2](REPLAY_DETECCAO.md).

A política Python propõe `registrar_alerta` ao abrir um episódio suspeito. Para janelas normais, evidência insuficiente e continuidade de episódios, propõe `nenhuma_acao` com uma justificativa. As outras ações podem ser submetidas explicitamente pelo mesmo método `apply`.

## Interface e limites

A proposta é um objeto JSON com `acao`, `parametros` e uma `justificativa` textual. Quem chama `apply` informa `origin` e, quando aplicável, `window_id`. Para registrar um alerta, o ID da janela é obrigatório. Por exemplo, a política pode enviar esta proposta com `window_id=5`.

```json
{
  "acao": "registrar_alerta",
  "parametros": {"evento_id": "alerta-5"},
  "justificativa": "Queda persistente de throughput UL na regra experimental."
}
```

| Ação | Parâmetros | Condição e efeito simulado |
|---|---|---|
| `registrar_alerta` | `evento_id` | A janela deve ser a abertura do episódio identificado pelo detector, com evidências de cobertura, referência, queda e persistência. Cria o evento com prioridade normal e vincula o alerta à janela. Uma segunda proposta para o mesmo episódio é recusada. |
| `priorizar_evento` | `evento_id`, `prioridade` | Exige evento existente e um dos níveis `baixa`, `normal` ou `alta`. Altera a prioridade de investigação. |
| `ampliar_janela_analise` | `evento_id`, `tamanho_registros` | O tamanho é o total desejado, incluindo a janela de origem. Consulta apenas os registros contíguos anteriores que faltam, no mesmo segmento. Registra os IDs, a quantidade e o resumo de throughput e PRB UL das linhas adicionais. |
| `ativar_monitoramento_intensificado` | `evento_id`, `avanco_registros` | Exige evento existente e avanço inteiro entre o mínimo configurado e o avanço atual. Um avanço menor configura inspeções futuras mais próximas entre si. |
| `nenhuma_acao` | Objeto vazio | Registra a justificativa com estado operacional igual antes e depois. |

`Limits` configura o máximo de registros por ampliação acumulada de cada evento (120), o orçamento de consultas adicionais por sessão (240) e o avanço mínimo de inspeção (1 registro). A janela de origem vem do detector e seu tamanho pode ser maior que o limite de ampliação. O orçamento mede leituras adicionais por evento, de modo que uma mesma linha consultada em eventos diferentes consome orçamento em cada consulta. A ampliação recusa pedidos sem histórico contíguo suficiente. O tamanho, a prioridade e o avanço são metas absolutas. Repetir a meta já em vigor é aceito sem nova execução ou consumo de orçamento.

## Estado, verificação e auditoria

Em cada execução, o estado começa com os mapas de alertas e eventos vazios. A seção `analise` contabiliza registros adicionais consultados, e `inspecao` guarda o avanço em número de registros. Cada evento contém a prioridade, a janela de origem e seu contexto de análise. O arquivo final guarda a versão do formato, a proveniência, os parâmetros do replay e do detector, os limites do simulador e as detecções completas em `deteccoes`. O campo `janela_id` vincula o alerta às evidências sem replicá-las em todo instantâneo.

O histórico registra o evento quando identificável, a janela, a origem da proposta, seus parâmetros, as justificativas, os dois estados, as seções alteradas e o resultado da verificação. Validação `aceita` é autorização para prosseguir. Execução `executada` indica mudança aprovada pela verificação. `nao_executada` cobre recusas e decisões cuja meta já está atendida, inclusive `nenhuma_acao`. Uma exceção ou uma mudança divergente gera execução `falha`, verificação `reprovada` e descarte da cópia. Uma proposta recusada tem verificação `nao_aplicavel`.

O simulador reutiliza os registros históricos carregados em memória, e cada execução começa com uma sessão nova. A ampliação altera o contexto consultado. A intensificação altera a configuração local de inspeção e vale para passagens futuras, mantendo como evidência as janelas já avaliadas. As unidades físicas e a duração das janelas seguem as limitações da EDA. Uma transição aprovada demonstra um efeito sobre o estado do simulador. Diagnóstico, qualidade do detector e impacto sobre a rede exigem evidências independentes.

## Execuções de referência

Use os comandos do [README](../README.md). O Excel oficial e o cenário sintético escrevem em diretórios distintos.

- **Excel oficial.** 1.138 registros, 38 janelas, 38 decisões `nenhuma_acao`, zero alertas e estado operacional final igual ao inicial. O resultado conserva o SHA-256 da [planilha auditada](EDA.md).
- **Cenário sintético.** Em uma série de 16 registros, o throughput UL muda de 100 para 50 por seis registros e depois volta a 100. O PRB UL fica em 1.000 na escala bruta. O detector abre `alerta-5` nos registros 9 e 10. Foram executadas quatro ações e recusadas duas. O alerta duplicado e a tentativa de expansão para 121 registros preservaram o estado operacional.

| Campo do cenário sintético | Antes | Depois |
|---|---|---|
| Alertas | 0 | 1 |
| Prioridade de `alerta-5` | Normal, após abertura | Alta |
| Contexto do evento | Registros 9–10 | Registros 6–10 |
| Registros adicionais consultados | 0 | 3, IDs 6–8 |
| Avanço de inspeção | 2 registros | 1 registro |
