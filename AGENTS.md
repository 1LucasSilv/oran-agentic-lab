# AGENTS.md — Instruções para o Codex

## Leia antes de começar

Este repositório implementa o laboratório **`oran-agentic-lab`**, um protótipo educacional e de pesquisa em **análise e resposta simulada baseada em KPMs de redes 5G Open RAN**.

**Fonte de verdade técnica:** [`docs/PLANO_LABORATORIO.md`](docs/PLANO_LABORATORIO.md). Leia o plano antes de propor mudanças amplas. Se o arquivo estiver ausente, informe a ausência; não invente decisões anteriores.

## Escopo e prioridades

- **Dataset principal:** <https://github.com/CTTCADAPTRU/OAI-KPM-dataset> (arquivo `.xlsx` com KPMs coletados por xApp).
- **Pipeline:** leitura → replay → detecção → decisão → validação → **ação simulada** → verificação.
- **MVP:** pipeline completo com **um agente** Ollama, antes de MCP, RAG ou múltiplos agentes.
- **Evolução planejada:** ferramentas MCP para consulta e ação local; RAG 3GPP para comparação com o mesmo modelo geral; fine-tuning apenas se existir checkpoint real verificado.
- **Não construir:** xApp, rApp, RIC, 5G Core, gNB ou controle de rede real.

## Como executar uma tarefa

1. Inspecione os arquivos atuais e identifique a **etapa autorizada** no plano.
2. Implemente os **módulos completos necessários** para essa etapa; não exija que o usuário programe linha por linha.
3. Prefira soluções diretas, legíveis e pequenas. Evite estruturas, serviços ou dependências que não tragam benefício imediato.
4. Preserve as alterações já existentes. Não refatore etapas não relacionadas sem justificativa.
5. Adicione testes e execute os testes relevantes quando possível. Informe explicitamente o que foi ou não executado.
6. Atualize README e documentação pertinente quando a interface ou os comandos mudarem.
7. Finalize com: **arquivos alterados, comandos para executar, testes/resultados, explicação dos pontos principais, limitações e sugestão de commit**.
8. Não inicie uma **nova etapa grande** sem solicitação. Dentro de uma etapa autorizada, conclua o trabalho de ponta a ponta.

## Dados e validade científica

- Antes de assumir nomes de abas, colunas, tipos, frequência temporal e unidades, **inspecione o `.xlsx` real**. O README é referência inicial, não substituto do arquivo.
- Não assumir que `RRU.PrbTotDl`/`RRU.PrbTotUl` são percentuais ou que aumento de latência isolado significa falha.
- Não inventar rótulos de anomalias; diferenciar **alerta por heurística** de falha comprovada.
- Não interpretar replay histórico como coleta em tempo real.
- Não afirmar que uma **ação simulada** alterou o desempenho da rede 5G que produziu os dados.
- Separar dados, configurações, código e resultados. Preservar o dataset original.
- Se houver teste comparativo, usar os mesmos casos e parâmetros registráveis; não apresentar RAG como fine-tuning.

## IA, ferramentas e ações

- Os modelos **propõem decisões**; código Python determinístico **valida** e **executa**.
- Qualquer ferramenta de escrita deve atuar **somente no estado do simulador**; nenhuma credencial ou acesso a infraestrutura real.
- Validar parâmetros de ações e permitir a decisão de não agir (`nenhuma_acao`). Aplicar limites, histórico, tratamento de erro e recusa segura.
- O MCP fornece acesso padronizado a ferramentas; **não** é o mecanismo de coleta original dos KPMs da RAN.
- Não executar comandos copiados de notebooks de terceiros para SSH, tunelamento ou acesso remoto. Não reproduzir segredos eventualmente presentes em arquivos.
- Modelos Ollama devem ser **configuráveis**; não pressupor disponibilidade de GPU ou memória para 7B.

## Estilo de código

- Python claro, compatível com `venv`, caminhos relativos/configuráveis e funções com responsabilidades pequenas.
- Usar `pandas`/`openpyxl` para Excel quando necessário, `pytest` nos testes e JSON estruturado para decisões.
- Preferir testes com pequenas **fixtures sintéticas claramente identificadas**, sem depender do arquivo real para todo teste automatizado.
- Não instalar LlamaIndex, FAISS, OpenTelemetry, frameworks multiagentes ou stacks 5G antes de uma etapa que os exija.
- Documentar os parâmetros de detecção e inferência, versões dos modelos e hipóteses do simulador.

## Git, arquivos e segurança

- Nunca realizar `git commit`, `git push`, reset destrutivo, exclusão em massa ou sobrescrita ampla sem autorização explícita.
- Não versionar `.env`, segredos, dados de origem em `data/raw/`, artefatos pesados ou saídas temporárias por padrão.
- Preservar `AGENTS.md` e `docs/PLANO_LABORATORIO.md` atualizados quando decisões arquiteturais forem efetivamente alteradas.
- Se estiver faltando o dataset, preparar leitura configurável e testes com amostra sintética, **sem fingir que os KPMs reais foram inspecionados**.

## Formato de resposta ao concluir

- **Entregue:** módulos/arquivos criados ou alterados.
- **Executar:** comandos mínimos para instalar e rodar.
- **Validar:** testes realizados e resultados observados; impedimentos, se houver.
- **Entender:** principais funções e escolhas técnicas, de forma didática e breve.
- **Próximo passo:** etapa sugerida e mensagem de commit (sem executá-lo automaticamente).
