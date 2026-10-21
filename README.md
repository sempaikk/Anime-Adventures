# Anime Adventures

Bot de perguntas sobre o jogo no Discord, com respostas no chat, reconhecimento de imagens do jogo e três alternativas por botão. Use **`/adventures`**, escolha as opções no painel e toque em **Começar**. Todos podem jogar, e só o primeiro acerto recebe um ponto. O conteúdo ativo cobre o lançamento de julho de 2022, antes da Update 1; os painéis não repetem a data a cada rodada.

- **2.199 perguntas em 14 categorias:** unidades, raridades, evoluções, mundos, chefes, atos, comida e XP, traits, summon, economia, modos, missões, loja e códigos, upgrades. Inclui fatos históricos, comparações e cenários calculados a partir deles; não são 2.199 descobertas históricas independentes.
- **Só assuntos do jogo:** as adivinhas de biografia do anime foram removidas. Reconhecimento visual usa a unidade no Anime Adventures e exige imagem disponível.
- **Três alternativas:** uma escolha por pessoa em cada rodada; o primeiro clique correto processado ganha um ponto. Cliques concorrentes não duplicam crédito. A ordem muda a cada rodada e permanece estável durante pausa/retomada; perguntas com botões não aceitam atalhos pelo chat.
- **44 unidades base e quatro relações de evolução documentadas.** Nomes do anime e nomes antigos/atuais cadastrados são aceitos nas perguntas de identidade. Chefes também aceitam nomes equivalentes verificados, como Zarbo/Zarbon e Freezo/Frieza. Perguntas sobre uma evolução ou transformação exigem a forma pedida.
- **Interface Components V2:** os dois banners fornecidos pelo usuário, identidade roxa/dourada e cartões separados para pergunta, relógio e resultado. Dez ícones coloridos da wiki, com transparência, aparecem nos títulos, botões e menus: mochila, Summon, unidades, evolução, traits, placar e outros sistemas. Sem emojis Unicode na interface nem imagens geradas por IA. Ajuda e placar são consultas privadas.
- **Duração configurável:** 10, 20 ou 30 perguntas, ou partida contínua; a seleção inicial é de 10 perguntas. A primeira rodada sem participação encerra qualquer formato. O painel mostra o avanço e o resultado final reconhece empates.
- **Tempo configurável:** 30, 45 (padrão) ou 60 segundos por pergunta; intervalo de 8 segundos. Edições do relógio a cada 10 segundos; uma edição lenta não aumenta o prazo.
- **Assuntos configuráveis:** quatro grupos e as 14 categorias individuais. A escolha filtra o banco Release antes de embaralhar, sem introduzir outros updates.
- **Mais opções:** dificuldade fácil/média/difícil e formato misto/alternativas/texto/imagens. A classificação considera o esforço da pergunta, sem depender da raridade do personagem. Combinações sem perguntas desabilitam Começar e explicam como ajustar.
- **Desempenho privado:** participação, primeiros acertos e resumo por assunto, com respostas e fontes das últimas 50 rodadas. O percentual inclui velocidade; não mede sozinho conhecimento. Respostas digitadas não são guardadas no histórico.
- **Avisos de perguntas:** formulário após a resposta, até cinco envios por pessoa em 24h e um por pergunta. A moderação revisa a fila do próprio servidor; um aviso não altera perguntas ou pontos automaticamente.
- **Anfitrião:** transferência por seleção de membro. Se ele sair do servidor, a saída é confirmada antes de permitir que um participante ou moderador assuma. Consultas não sobrescrevem transferências mais recentes. Não exige novo intent privilegiado.
- **Variedade:** o sorteio alterna categorias e famílias de perguntas enquanto houver opções disponíveis, para o volume de comparações de raridade não dominar o início da partida. Nenhuma pergunta se repete até o esgotamento do banco escolhido.
- **Pausa imediata:** congela o relógio da pergunta ou do intervalo; retomar preserva exatamente o tempo restante. Respostas enviadas em pausa não contam, inclusive se chegarem depois da retomada. Só o anfitrião escolhe opções/inicia; anfitrião e moderadores com Administrador, Gerenciar Servidor ou Gerenciar Canais controlam pausa/fim.
- **Proteção contra abuso:** no chat, até três respostas diferentes por pessoa/rodada; repetir a mesma resposta normalizada não gasta outra tentativa. Mensagens vazias, maiores que 160 caracteres ou de webhooks não contam. Pausar não devolve tentativas. Abrir partida tem intervalo de 3 segundos por jogador, e consultas repetidas de ajuda/pontos são reconhecidas sem refazer a consulta. Pausas de 10 minutos encerram a sessão e liberam o canal. Atualizações idênticas de painel não geram edições repetidas.
- **Antifarm global:** a mesma pergunta soma no total de cada jogador uma vez a cada 24 horas, entre canais e partidas. O placar da partida continua recebendo um ponto por primeiro acerto. A resposta aceita é gravada antes da confirmação visual; o crédito é único e transacional.
- **Quedas de conexão:** o relógio pausa durante uma desconexão do Gateway e retoma após reconectar, sem aceitar o lote antigo de respostas. Pausas manuais continuam pausadas. O limite de dez minutos também vale nesses casos.
- **Retomada após reinício:** partidas salvas nas últimas 24h oferecem um painel de recuperação com placar e opções. Anfitrião/moderação confirma a retomada; uma rodada interrompida sem acerto é anulada. Recibos reconciliam um ponto gravado antes da última cópia da partida, sem crédito duplicado. Uma alteração incompatível do banco de perguntas invalida a partida antiga e preserva os pontos.
- **Capacidade:** até três partidas abertas por servidor, 50 no processo e 200 participantes por partida. Vagas são reservadas antes de operações de rede. Remover threads/canais ou retirar o bot de um servidor libera suas partidas.
- **Falhas e reinício:** erros de comando e de botões recebem explicação privada, quando o Discord permite responder. SIGTERM inicia encerramento organizado; a tentativa de avisar os painéis tem prazo de três segundos.
- **Encerrar e jogar novamente**, sem comandos adicionais. Encerrar uma pergunta ativa aguarda seu desfecho; em pausa, encerra imediatamente. Apagar o painel libera o canal; um acerto já registrado continua pontuando.
- Um resultado por pergunta, explicação, link da fonte e placar da sessão. Qualquer tentativa válida de um jogador conta como participação; sem participação, a sessão termina.
- Sem aproximação de nomes: maiúsculas, acentos, pontuação e separadores são normalizados. Mensagens anteriores à pergunta, de bots, de webhooks, editadas ou recebidas após o prazo não contam.
- Pontos acumulados em SQLite, com crédito único por pergunta e importação única do `scores.json` antigo, caso o arquivo ainda esteja disponível.

## Rodar

Use Python 3.12. Instale `python -m pip install -r requirements.txt`. Configure `DISCORD_TOKEN` no ambiente; para uso local, copie `.env.example` para `.env` e preencha o valor apenas nesse arquivo ignorado pelo Git. Execute `python bot.py`.

No Discord Developer Portal, habilite **Message Content Intent**. O bot precisa de **Ver canal**, **Enviar mensagens** e **Inserir links**; em threads, também **Enviar mensagens em threads**. A instalação precisa dos escopos `bot` e `applications.commands`. O único comando é `/adventures`.

## Testar sem conectar o bot de produção

```bash
python -m unittest discover -s tests -v
```

Os testes não usam token, não sincronizam comandos e não enviam mensagens reais. Cobrem 40 cliques corretos simultâneos, tentativa única, limite de respostas do chat, spam de consultas/abertura, pausa abandonada, alternativas válidas, cálculos do banco, rodadas fixas/contínuas, janela global de 24h, migração de schema, retenção sem apagar totais, cancelamento após acerto, variedade do sorteio, pausa/retomada, respostas atrasadas, prazo, falhas do Discord, fontes, imagens, migração e pontuação transacional. Todas as perguntas são verificadas contra os limites nativos dos cartões e a ausência de emojis Unicode.

As decisões visuais e as referências oficiais estão em [`docs/interface.md`](docs/interface.md). O painel inicial expira após dois minutos sem iniciar. Botões antigos de ajuda, pontos e revanche têm tratamento após reinícios; controles de uma sessão encerrada nunca controlam outra.

## Railway

O `Procfile` inicia o worker com `python bot.py`. `.python-version` fixa a série Python 3.12, e as dependências estão fixadas nas versões verificadas. O serviço precisa executar uma única réplica: os bloqueios de sessão são locais ao processo.

**Persistência:** monte um volume no serviço. O bot usa `DATA_DIR`, depois `RAILWAY_VOLUME_MOUNT_PATH`, depois a pasta do projeto, nessa ordem. Nesse diretório ficam `scores.sqlite3` e os registros de crédito. A configuração confirmada pelo usuário é volume de 500 MB montado em `/data` e `DATA_DIR=/data`. O arquivo legado é procurado primeiro ali e depois ao lado de `bot.py`; não é modificado durante a importação. Um arquivo legado danificado impede o início para evitar apagar pontos silenciosamente.

Os registros novos de disputa/antifarm têm retenção de 30 dias, com limpeza em lotes de até mil registros; os totais dos jogadores não são apagados. Páginas livres do SQLite são reutilizadas. Registros legados sem identidade de conteúdo são preservados. Recibos Discord expirados são rejeitados para não recreditar um evento removido.

O início verifica a integridade do SQLite sem apagar bancos danificados. Uma tarefa em segundo plano confere o armazenamento a cada hora e mantém **uma cópia local diária**, em `backups/scores-latest.sqlite3`. Ela usa a API de backup do SQLite em outra thread, valida o resultado e só então substitui a cópia anterior. Exige espaço para o temporário e mais 16 MiB livres; falha preserva o banco e a cópia anterior e gera aviso nos logs. Banco, cópia e temporário ocupam o volume; código e imagens ficam fora dele.

A cópia local não protege contra a perda do volume. O roteiro de validação, exportação e recuperação está em [`docs/release-checklist.md`](docs/release-checklist.md). Não há restauração automática de um banco danificado nem troca silenciosa por um banco vazio.

Checkpoints, revisão e avisos ficam no mesmo SQLite e entram no backup. Históricos ficam por até sete dias, com limites de 500 partidas/32 MiB; só as últimas 50 rodadas entram na revisão. Contextos de mensagens têm retenção e limite de 20 mil após limpeza. Avisos ficam por até 30 dias, no máximo cinco mil. Limpeza desses dados não apaga os totais globais.

Sem volume, o disco do container é temporário e os totais podem ser perdidos em um redeploy. Nunca versione o token, o banco nem o arquivo de pontuação.

## Disponibilidade

**Controles → Estado do bot** oferece uma consulta privada. A moderação também vê o último backup e alertas de armazenamento, com aviso em 70% e crítico em 90% de uso do filesystem ou menos de 16 MiB livres. Consultas de presença de anfitrião e backups não bloqueiam a rotina de checkpoints.

O processo escuta em `PORT` (8080 por padrão): **`/health`** indica processo vivo e **`/ready`** retorna 200 somente com Gateway/banco disponíveis e armazenamento fora do estado crítico; caso contrário retorna 503. As respostas são mínimas e não incluem dados de jogadores, caminhos ou credenciais.

O workflow **Bot availability** está preparado para consultar a produção a cada 15 minutos, quando a variável do repositório **`BOT_HEALTH_URL`** contiver a URL HTTPS pública terminada em `/ready`. Sem essa URL, o job não roda. Ativar o domínio/variável depende de o Railway voltar. Notificações de falha seguem as preferências do GitHub; não há envio automático de DMs pelo bot. Veja o procedimento em [`docs/release-checklist.md`](docs/release-checklist.md).

## Conteúdo e próximas etapas

Os fatos estão em [`data/release.json`](data/release.json); [`question_factory.py`](question_factory.py) monta perguntas e cenários de prática com esses dados e os valores das fontes históricas. Há 289 perguntas manuais, 25 reconhecimentos visuais, 44 consultas de raridade e 1.841 perguntas derivadas. A ordem dos botões não conta como uma nova pergunta. O bot não depende de acesso à wiki durante as partidas.

[`data/media.json`](data/media.json) registra origem, forma, processamento, dimensões e hashes de 72 imagens, além das cópias de retratos com nomes neutros. Descrições ALT de miniaturas/galerias exibem apenas `.`. Os visuais atuais da wiki ilustram fatos históricos sem atualizá-los. Reconhecimentos sem retrato ficam fora do sorteio; perguntas de raridade podem continuar sem foto. Molduras que entregariam a raridade ficam ocultas até o resultado. Ícones de moedas, itens, traits e Time Machine ilustram seu contexto; seis imagens reservadas para etapas futuras não aparecem no quiz ativo.

[`data/ui_icons.json`](data/ui_icons.json) liga os dez ícones de interface aos arquivos coloridos da wiki, com transparência e às cópias PNG de até 128px. O Discord os renderiza como imagens de aplicação nos lugares onde aceita apenas o campo técnico `emoji`; são as imagens originais do jogo, não símbolos Unicode. Nomes técnicos são neutros. Não há recoloração: a mochila foi extraída da arte de Unit Storage por remoção determinística de fundo, com o original e seu hash preservados; as demais artes mantêm as cores da wiki. Nenhuma reconstrução ou geração por IA. A manutenção explícita é `python scripts/sync_ui_icons.py`, com `DISCORD_TOKEN` no ambiente. Essa ferramenta registra/reutiliza os ícones na aplicação do bot; não é executada no início nem nos testes e não cria emojis nos servidores. Ícones sem registro deixam o texto dos controles utilizável.

O acervo completo consultado contém 2.387 arquivos. Ele é uma biblioteca de referência, não uma promessa de que cada arquivo aparece no quiz: imagens que entregam respostas, cosméticos posteriores e vídeos sem contexto comprovado não são inseridos para aumentar essa contagem.

Ideias reservadas para depois estão em [`docs/roadmap.md`](docs/roadmap.md): configurações de idioma, histórico de atualizações e conexão entre Discord e site. O bot continua somente em português e com um único comando.

O fechamento desta entrega e as recomendações antes de expandir o projeto estão em [`docs/adventures-readiness.md`](docs/adventures-readiness.md).

A pesquisa, suas limitações e a política para adicionar conteúdo estão em [`docs/release-research.md`](docs/release-research.md). As fontes históricas usadas foram preservadas em `docs/sources/`, com hashes no pacote. [`data/release_pending.json`](data/release_pending.json) registra candidatos, conflitos e conteúdo posterior; **esse arquivo não é carregado pelo quiz**.

Novos updates devem ganhar pacotes próprios. A lista de julho não é um inventário comprovadamente completo do instante do lançamento; os limites históricos estão documentados, e candidatos sem confirmação não foram apresentados como certeza.
