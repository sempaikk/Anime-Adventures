# Anime Adventures

Bot de comunidade para Discord: tier list por imagem, avaliações estruturadas, histórico de mudanças e chat global entre servidores que escolherem participar. O comando de perguntas foi arquivado; `bot.py` inicia a nova versão. Nenhum recurso fica conectado a canais antes da configuração por um administrador.

## Tier list

- **Servidor e global:** duas visões dos mesmos relatos. A pessoa decide se sua avaliação também entra no global.
- **Contexto separado:** unidade e forma exatas, função (dano, suporte, controle ou economia), modo e período de balanceamento. Um novo período não herda as notas antigas.
- **Imagem com os retratos originais da wiki:** tiers S, A, B, C e D; unidades sem relatos suficientes ficam em avaliação. Sem nomes sobre os retratos. Busca, detalhes, páginas e justificativas ficam disponíveis nos comandos e botões.
- **Um painel por servidor:** o bot edita a mesma mensagem a cada **30 minutos ou uma hora**, e só quando a imagem muda. Consultas particulares podem mostrar o cálculo mais recente. O painel público mostra a data da própria publicação.
- **Ordem dentro do tier:** nota média das avaliações elegíveis. No global, cada servidor tem o mesmo peso. Empates mantêm ordem estável pelo identificador da forma; posição não é prova de superioridade absoluta.
- **Consenso mínimo:** servidor exige cinco pessoas e pelo menos 70% das notas a até um tier do resultado. Global exige três servidores com pelo menos três pessoas cada; a mediana dos servidores define o tier, com dois terços das referências a até meio tier do resultado. Desempate entre tiers adjacentes favorece o inferior.
- **Estabilidade:** a primeira classificação elegível pode aparecer imediatamente. Mudanças posteriores precisam persistir por 15 minutos e respeitar uma hora desde a última mudança. Falta de participação ou concordância retira o rótulo comunitário. Curadoria permanece identificada e só é substituída por consenso estável.
- **Relatos dos últimos 30 dias:** uma pessoa tem uma avaliação vigente por contexto em cada servidor e um voto global, mesmo participando de vários servidores. Atualizações substituem o relato anterior; intervalo de um minuto entre avaliações e dez minutos para editar a mesma, até 40 relatos recentes por pessoa.
- **Sem API paga de IA:** comentários livres não são interpretados como evidência de que uma unidade é boa ou ruim. Canais de observação registram somente contagens de menções a nomes inequívocos. Menções não mudam notas. Motivos são relatos de jogadores, não análises inventadas pelo bot.

O catálogo contém **549 identidades/formas** do módulo de nomes da wiki, com fonte e snapshot em `data/community_catalog.json`. O manifesto de retratos registra separadamente as imagens disponíveis e as pendentes. Arquivos da wiki que exibem o boneco azul genérico foram rejeitados. Uma imagem ausente nunca é substituída pela de outra evolução. A presença no catálogo não afirma que uma unidade está disponível para obter na versão atual. Sem avaliações ou curadoria, a lista começa em avaliação.

## Configuração no Discord

A instalação precisa dos escopos `bot` e `applications.commands`. Habilite **Message Content Intent** no Developer Portal para capturar mensagens nos canais globais e contar menções. Formulários e comandos não precisam ler conversas. Não conceda Administrador ao bot: use permissões por canal.

1. `/configurar tierlist canal:#tier-list alcance:Global funcao:Dano modo:Infinito intervalo:30 minutos`
2. `/configurar global canal:#chat-global entrada:Escrever no canal`
3. Opcional: `/configurar observacao canal:#relatos`

Use canais diferentes para cada recurso. O bot precisa de **Ver canal, Enviar mensagens, Inserir links**. Para imagens, **Anexar arquivos**. No chat digitado, **Gerenciar mensagens** permite remover a original após a cópia. Participantes precisam poder enviar mensagens nesse canal; para um canal onde só o bot escreve, escolha a entrada por formulário e use `/global enviar`. Configure as permissões de membros do canal de tier list para deixá-lo somente leitura. O bot não altera permissões de membros automaticamente.

`/tierlist` permite escolher alcance, modo, função, página ou unidade exata. `/avaliar` abre a avaliação com aviso de visibilidade antes do formulário. `/atualizacoes` mostra mudanças do período e seus motivos. A lista fica vazia de classificações até reunir relatos suficientes ou curadoria explícita.

## Chat global

A primeira mensagem fica no servidor de origem e recebe uma confirmação explicando o compartilhamento de nome, servidor e texto. Só depois de confirmar, essa mensagem entra na fila; as seguintes são enviadas automaticamente. Confirmações expiram em dez minutos. Também é possível confirmar com `/global participar` e enviar por formulário.

Cada mensagem é publicada pelo **bot**, com autoria e servidor de origem visíveis. A cópia local precisa ter resposta de sucesso e recibo salvo antes de liberar as cópias dos outros servidores. A original só é apagada após isso. Falha na cópia local preserva a original. Novos servidores recebem mensagens novas a partir da ativação, sem importar conversas antigas.

A fila persiste em SQLite e retoma após reinício. Envios ainda pendentes expiram depois de 24 horas, preservando a original quando não houve cópia local, para evitar publicar conversas antigas após uma longa interrupção. Há cinco tentativas com espera crescente; falha em um destino não interrompe os outros. Nonce determinístico com `enforce_nonce` usa a deduplicação recente do Discord. Isso reduz duplicatas após perda de confirmação de rede, **sem prometer entrega exatamente uma vez sob qualquer queda ou atraso**. Pausar a rede preserva a fila; desligar canais, sair ou bloquear a pessoa cancela envios ainda não realizados. A rede inicial aceita até 100 servidores conectados e 10 mil cópias pendentes.

Só texto, até mil caracteres. Bots, webhooks, anexos, figurinhas e convites de servidores não são retransmitidos. Dez segundos entre mensagens por pessoa, até trinta mensagens por minuto por servidor. Menções são desativadas; texto de jogadores não vira formatação de administração. Contas precisam de sete dias para contribuir. Essas barreiras reduzem spam e manipulação; não provam identidade nem eliminam contas alternativas.

- `/global sair`: interrompe próximos envios automáticos e exige nova confirmação para voltar.
- `/global status codigo:...`: consulta privada das cópias enviadas, pendentes, canceladas ou com falha.
- `/global apagar codigo:...`: solicita a remoção das cópias de uma mensagem própria. O código aparece no rodapé.
- **Sinalizar:** formulário de denúncia ligado à cópia e ao servidor corretos, até cinco por pessoa por hora.
- `/configurar desativar`: desconecta o recurso deste servidor. O histórico já publicado permanece.

A pessoa deve usar `/global apagar` para remover uma mensagem da rede. Apagar manualmente uma cópia no Discord não é tratado como solicitação de exclusão em todos os servidores. Não há propagação de edições ou respostas encadeadas nesta primeira versão. As cópias já podem ter sido lidas ou salvas por terceiros.

## Moderação, privacidade e histórico

O proprietário do aplicativo e os IDs opcionais de `COMMUNITY_MODERATOR_IDS` moderam a rede. Administradores de um servidor configuram seus próprios canais e a curadoria local; não ganham permissão sobre outros servidores.

`/moderacao denuncias`, `resolver`, `bloquear`, `desbloquear` e `pausar_global` cuidam da rede. `/moderacao definir` registra uma nota **Curadoria** com justificativa, local ou global conforme a permissão. `/moderacao periodo` abre um novo período quando uma atualização real do jogo for confirmada; use um nome claro. O histórico dos períodos anteriores fica preservado no banco, sem contaminar as notas atuais. A interface de atualizações consulta o período atual.

`/privacidade` explica os dados usados. A opção de remover avaliações apaga os relatos da pessoa e os próximos cálculos deixam de usá-los. O histórico agregado de mudanças continua sem autoria. Dados de conversa usados para envio são minimizados depois de sete dias; IDs de autoria, mensagens e destinos permanecem para moderação e exclusão. As cópias no Discord não expiram automaticamente. Contagens de menções duram sete dias, sem guardar texto, usando identificador pseudônimo para limitar repetição. Backups locais podem conter dados apagados até serem substituídos no próximo ciclo diário.

## Rodar e atualizar no Bot-Hosting.net

Use **Python 3.12**, arquivo de entrada **`bot.py`**, e o comando padrão que instala `requirements.txt` antes de iniciar. Variáveis:

```dotenv
DISCORD_TOKEN=preencha_apenas_no_painel_da_hospedagem
DATA_DIR=./state
# Opcional: IDs de confiança separados por vírgulas.
# COMMUNITY_MODERATOR_IDS=123456789,987654321
```

Mantenha o token como segredo. Nunca o coloque em commits ou prints. O caminho precisa estar no armazenamento persistente oferecido pela hospedagem. O serviço atual usa `./state`; confirme persistência com um reinício e exporte backups antes de apagar/recriar a implantação.

Com **pull automático a cada reinício** ativado, reinicie a implantação para buscar a última `main` e instalar a dependência de imagens. O GitHub atualizado não prova que a hospedagem já executa essa versão. Execute só uma instância do bot por vez. O plano grátis atual exige renovação manual conforme o aviso do provedor; não existe garantia de disponibilidade contínua.

O estado novo fica em `community.sqlite3`, separado de `scores.sqlite3`. Os pontos e arquivos do antigo comando não são apagados nem importados como avaliações. O código anterior está em `quiz_legacy.py` e sua documentação em [`docs/quiz-archive.md`](docs/quiz-archive.md).

Verificação de integridade ao iniciar, fila persistente, encerramento por SIGTERM e uma cópia diária validada em `backups/community-latest.sqlite3`. A cópia local não substitui um backup externo: a exclusão da implantação pode remover ambos. Escritas de coleta param antes de ultrapassar 128 MiB de banco ou com menos de 16 MiB livres; limites de registros e fila também impedem crescimento sem controle. O bot nunca apaga o banco automaticamente para liberar espaço.

A manutenção mede o espaço a cada 15 minutos. Endpoints mínimos `/health` e `/ready` usam `PORT`, depois `SERVER_PORT`, depois 8080; não exibem dados de pessoas. Readiness exige Gateway, banco consultável e armazenamento fora do nível crítico. Esses endpoints não são um site público e não exigem abrir uma porta para o bot se conectar ao Discord.

## Validação

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Os testes usam SQLite temporário, imagens locais e mocks do Discord, sem token, sincronização ou envio real. Cobrem isolamento servidor/global/período/forma, privacidade, consenso, ordem interna, votos repetidos, consentimento, recibos antes de exclusão, falhas e retomada da fila, nonce, moderação, backups e limites dos painéis. A suíte anterior continua cobrindo o código arquivado.

Antes de abrir a comunidade, faça o roteiro de dois servidores em [`docs/community-validation.md`](docs/community-validation.md). Os testes locais não confirmam permissões, renderização final e latência no Discord real.

## Atualizar as fontes de imagem

`python scripts/build_community_catalog.py` reconstrói o catálogo a partir do snapshot incluído. `python scripts/sync_community_portraits.py --inventory /caminho/all_wiki_images.json` importa o inventário público `allimages` da wiki, associa apenas nomes/formas exatos e rejeita os placeholders revisados. Sem `--inventory`, usa o manifesto já incluído para baixar arquivos ausentes. Isso é uma tarefa de manutenção, não uma dependência de cada mensagem. Novos nomes/arquivos precisam de revisão; o bot não navega autonomamente pela wiki nem executa o código dela.
