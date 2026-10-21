# Anime Adventures Quiz

Quiz sobre o jogo no Discord, com respostas no chat, reconhecimento de imagens do jogo e três alternativas por botão. Use **`/adventures`**, escolha as opções no painel e toque em **Começar quiz**. Todos podem jogar, e só o primeiro acerto recebe um ponto. O conteúdo ativo cobre o lançamento de julho de 2022, antes da Update 1; os painéis não repetem a data a cada rodada.

- **2.095 perguntas em 14 categorias:** unidades, raridades, evoluções, mundos, chefes, atos, comida e XP, traits, summon, economia, modos, missões, loja e códigos, upgrades. Inclui fatos históricos, comparações e cenários calculados a partir deles; não são 2.095 descobertas históricas independentes.
- **Só assuntos do jogo:** as adivinhas de biografia do anime foram removidas. Reconhecimento visual usa a unidade no Anime Adventures e exige imagem disponível.
- **Três alternativas:** uma escolha por pessoa em cada rodada; o primeiro clique correto processado ganha um ponto. Cliques concorrentes não duplicam crédito. A ordem muda a cada rodada e permanece estável durante pausa/retomada; perguntas com botões não aceitam atalhos pelo chat.
- **44 unidades base e quatro relações de evolução documentadas.** Nomes do anime e nomes antigos/atuais cadastrados são aceitos nas perguntas de identidade. Chefes também aceitam nomes equivalentes verificados, como Zarbo/Zarbon e Freezo/Frieza. Perguntas sobre uma evolução ou transformação exigem a forma pedida.
- **Interface Components V2:** os dois banners fornecidos pelo usuário, identidade roxa/dourada e cartões separados para pergunta, relógio e resultado. Dez ícones transparentes originais da wiki aparecem nos títulos, botões e menus: mochila, Summon, unidades, evolução, traits, placar e outros sistemas. Sem emojis Unicode na interface nem imagens geradas por IA. Ajuda e placar são consultas privadas.
- **Tempo configurável:** 30, 45 (padrão) ou 60 segundos por pergunta; intervalo de 8 segundos. Edições do relógio a cada 10 segundos; uma edição lenta não aumenta o prazo.
- **Assuntos configuráveis:** tudo junto, personagens, mundos e chefes, ou sistemas do jogo. A escolha filtra o banco Release antes de embaralhar, sem introduzir outros updates.
- **Variedade:** o sorteio alterna categorias e famílias de perguntas enquanto houver opções disponíveis, para o volume de comparações de raridade não dominar o início da partida. Nenhuma pergunta se repete até o esgotamento do banco escolhido.
- **Pausa imediata:** congela o relógio da pergunta ou do intervalo; retomar preserva exatamente o tempo restante. Respostas enviadas em pausa não contam, inclusive se chegarem depois da retomada. Só o anfitrião escolhe opções/inicia; anfitrião e moderadores com Administrador, Gerenciar Servidor ou Gerenciar Canais controlam pausa/fim.
- **Proteção contra abuso:** no chat, até três respostas diferentes por pessoa/rodada; repetir a mesma resposta normalizada não gasta outra tentativa. Mensagens vazias, maiores que 160 caracteres ou de webhooks não contam. Pausar não devolve tentativas. Abrir quiz tem intervalo de 3 segundos por jogador, e consultas repetidas de ajuda/pontos são reconhecidas sem refazer a consulta. Pausas de 10 minutos encerram a sessão e liberam o canal. Atualizações idênticas de painel não geram edições repetidas.
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

Os testes não usam token, não sincronizam comandos e não enviam mensagens reais. Cobrem 40 cliques corretos simultâneos, tentativa única, limite de respostas do chat, spam de consultas/abertura, pausa abandonada, alternativas válidas, cálculos do banco, variedade do sorteio, pausa/retomada, respostas atrasadas, prazo, falhas do Discord, fontes, imagens, migração e pontuação transacional. Todas as perguntas são verificadas contra os limites nativos dos cartões e a ausência de emojis Unicode.

As decisões visuais e as referências oficiais estão em [`docs/interface.md`](docs/interface.md). O painel inicial expira após dois minutos sem iniciar. Botões antigos de ajuda, pontos e revanche têm tratamento após reinícios; controles de uma sessão encerrada nunca controlam outra.

## Railway

O `Procfile` inicia o worker com `python bot.py`. `.python-version` fixa a série Python 3.12, e as dependências estão fixadas nas versões verificadas. O serviço precisa executar uma única réplica: os bloqueios de sessão são locais ao processo.

**Persistência:** monte um volume no serviço. O bot usa `DATA_DIR`, depois `RAILWAY_VOLUME_MOUNT_PATH`, depois a pasta do projeto, nessa ordem. Nesse diretório ficam `scores.sqlite3` e os registros de crédito. O arquivo legado é procurado primeiro ali e depois ao lado de `bot.py`; não é modificado durante a importação. Um arquivo legado danificado impede o início para evitar apagar pontos silenciosamente.

Sem volume, o disco do container é temporário e os totais podem ser perdidos em um redeploy, assim como no bot anterior. A sessão em andamento e seu placar não atravessam reinícios. Nunca versione o token, o banco nem o arquivo de pontuação.

## Conteúdo e próximas etapas

Os fatos estão em [`data/release.json`](data/release.json); [`question_factory.py`](question_factory.py) monta perguntas e cenários de prática com esses dados e os valores das fontes históricas. Há 185 perguntas manuais, 25 reconhecimentos visuais, 44 consultas de raridade e 1.841 perguntas derivadas. A ordem dos botões não conta como uma nova pergunta. O bot não depende de acesso à wiki durante as partidas.

[`data/media.json`](data/media.json) registra origem, forma, processamento, dimensões e hashes de 72 imagens, além das cópias de retratos com nomes neutros. Descrições ALT de miniaturas/galerias exibem apenas `.`. Os visuais atuais da wiki ilustram fatos históricos sem atualizá-los. Reconhecimentos sem retrato ficam fora do sorteio; perguntas de raridade podem continuar sem foto. Molduras que entregariam a raridade ficam ocultas até o resultado. Ícones de moedas, itens, traits e Time Machine ilustram seu contexto; seis imagens reservadas para etapas futuras não aparecem no quiz ativo.

[`data/ui_icons.json`](data/ui_icons.json) liga os dez ícones de interface aos arquivos transparentes da wiki e às cópias PNG de até 128px. O Discord os renderiza como imagens de aplicação nos lugares onde aceita apenas o campo técnico `emoji`; são as imagens originais do jogo, não símbolos Unicode. Nomes técnicos são neutros. A manutenção explícita é `python scripts/sync_ui_icons.py`, com `DISCORD_TOKEN` no ambiente. Essa ferramenta registra/reutiliza os ícones na aplicação do bot; não é executada no início nem nos testes e não cria emojis nos servidores. Ícones sem registro deixam o texto dos controles utilizável.

O acervo completo consultado contém 2.387 arquivos. Ele é uma biblioteca de referência, não uma promessa de que cada arquivo aparece no quiz: imagens que entregam respostas, cosméticos posteriores e vídeos sem contexto comprovado não são inseridos para aumentar essa contagem.

Ideias reservadas para depois estão em [`docs/roadmap.md`](docs/roadmap.md): configurações de idioma, histórico de atualizações e conexão entre Discord e site. O bot continua somente em português e com um único comando.

A pesquisa, suas limitações e a política para adicionar conteúdo estão em [`docs/release-research.md`](docs/release-research.md). As fontes históricas usadas foram preservadas em `docs/sources/`, com hashes no pacote. [`data/release_pending.json`](data/release_pending.json) registra candidatos, conflitos e conteúdo posterior; **esse arquivo não é carregado pelo quiz**.

Novos updates devem ganhar pacotes próprios. A lista de julho não é um inventário comprovadamente completo do instante do lançamento; os limites históricos estão documentados, e candidatos sem confirmação não foram apresentados como certeza.
