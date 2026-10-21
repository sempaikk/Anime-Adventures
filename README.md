# Anime Adventures · Release Quiz

Quiz de respostas abertas no Discord, restrito à versão inicial de julho de 2022, antes da Update 1. Use **`/adventures`** em um canal do servidor, escolha as opções no painel e toque em **Começar aventura**. Todos podem responder, e só o primeiro acerto recebe um ponto.

- **251 perguntas em 14 categorias:** unidades, raridades, evoluções, mundos, chefes, atos, comida e XP, traits, summon, economia, modos, missões, loja e códigos, upgrades.
- **44 unidades base e quatro relações de evolução documentadas.** Nomes do anime e nomes antigos/atuais documentados são aceitos nas perguntas de identidade. Perguntas sobre uma evolução exigem o nome da forma evoluída.
- **Interface Components V2:** os dois banners fornecidos pelo usuário, identidade roxa/dourada e cartões separados para pergunta, relógio e resultado. Retratos de unidades, mapas e alimentos vêm da wiki; nenhuma imagem gerada por IA. Ajuda e placar são consultas privadas.
- **Tempo configurável:** 30, 45 (padrão) ou 60 segundos por pergunta; intervalo de 8 segundos. Edições do relógio a cada 10 segundos; uma edição lenta não aumenta o prazo.
- **Assuntos configuráveis:** aventura completa, personagens, mundos e chefes, ou sistemas do jogo. A escolha filtra o banco Release antes de embaralhar, sem introduzir outros updates.
- **Pausa imediata:** congela o relógio da pergunta ou do intervalo; retomar preserva exatamente o tempo restante. Respostas enviadas em pausa não contam, inclusive se chegarem depois da retomada. Só o anfitrião escolhe opções/inicia; anfitrião e moderadores com Administrador, Gerenciar Servidor ou Gerenciar Canais controlam pausa/fim.
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

Os testes não usam token, não sincronizam comandos e não enviam mensagens reais. Cobrem concorrência, pausa/retomada, respostas atrasadas da pausa, exclusão de painéis, prazo, publicação/edição lenta, inatividade, falhas do Discord, permissões, baralho, conteúdo, fontes, seleção de imagens, migração e escrita transacional da pontuação.

As decisões visuais e as referências oficiais estão em [`docs/interface.md`](docs/interface.md). O painel inicial expira após dois minutos sem iniciar. Botões antigos de ajuda, pontos e revanche têm tratamento após reinícios; controles de uma sessão encerrada nunca controlam outra.

## Railway

O `Procfile` inicia o worker com `python bot.py`. `.python-version` fixa a série Python 3.12, e as dependências estão fixadas nas versões verificadas. O serviço precisa executar uma única réplica: os bloqueios de sessão são locais ao processo.

**Persistência:** monte um volume no serviço. O bot usa `DATA_DIR`, depois `RAILWAY_VOLUME_MOUNT_PATH`, depois a pasta do projeto, nessa ordem. Nesse diretório ficam `scores.sqlite3` e os registros de crédito. O arquivo legado é procurado primeiro ali e depois ao lado de `bot.py`; não é modificado durante a importação. Um arquivo legado danificado impede o início para evitar apagar pontos silenciosamente.

Sem volume, o disco do container é temporário e os totais podem ser perdidos em um redeploy, assim como no bot anterior. A sessão em andamento e seu placar não atravessam reinícios. Nunca versione o token, o banco nem o arquivo de pontuação.

## Conteúdo e próximas etapas

O pacote ativo está em [`data/release.json`](data/release.json); o carregador gera as perguntas de identidade e raridade a partir do elenco, além das perguntas específicas. O bot não depende de acesso à wiki durante as partidas.

[`data/media.json`](data/media.json) registra a origem, a forma da unidade, o processamento e os hashes de cada imagem. Visuais atuais da wiki podem ilustrar perguntas históricas, sem alterar os fatos do Release. Perguntas de identidade ocultam o retrato até a resposta; evoluções só usam a forma correspondente. Imagens ausentes ou substituídas por placeholders na wiki ficam de fora.

A pesquisa, suas limitações e a política para adicionar conteúdo estão em [`docs/release-research.md`](docs/release-research.md). As fontes históricas usadas foram preservadas em `docs/sources/`, com hashes no pacote. [`data/release_pending.json`](data/release_pending.json) registra candidatos, conflitos e conteúdo posterior; **esse arquivo não é carregado pelo quiz**.

Novos updates devem ganhar pacotes próprios. A lista de julho não é um inventário comprovadamente completo do instante do lançamento; os limites históricos estão documentados, e candidatos sem confirmação não foram apresentados como certeza.
