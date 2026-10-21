# Fechamento de /adventures

Esta entrega fecha a interface, a duração das partidas e as regras de disputa do comando atual. O único comando continua sendo `/adventures`; site, novos comandos, idiomas e histórico de updates ficam em etapas próprias.

## Experiência entregue

- Dez ícones coloridos da wiki, transparência e os dois banners autorizados. Sem arte gerada ou recoloração. O original da mochila foi preservado antes de remover seu fundo.
- Nome público Anime Adventures, sem os símbolos decorativos anteriores. Painéis sem “Quiz” e sem cabeçalhos repetindo o nome do bot.
- Três menus: assuntos, tempo e 10/20/30 perguntas ou partida contínua. Seleções iniciais: tudo junto, 45 segundos, dez perguntas.
- Pergunta, alternativas A/B/C, relógio, controles e resultado separados. Avanço da partida e resumo final com reconhecimento de empates.
- Chat e imagens com até três tentativas diferentes por pessoa; alternativas com uma tentativa. Primeiro acerto vale um ponto na partida. Maiúsculas, acentos e separadores são normalizados; nomes aproximados não são aceitos.
- Anfitrião configura/inicia; anfitrião e moderação pausam/encerram. Uma rodada sem participação encerra a partida. Pausa máxima de dez minutos.

## Conteúdo

O banco contém **2.199 perguntas em 14 categorias**: 2.000 com alternativas, 25 visuais e 174 de texto. São 289 perguntas manuais, 25 reconhecimentos, 44 consultas de raridade e 1.841 comparações/cenários derivados. Essa contagem não significa 2.199 fatos históricos independentes.

Foram preservados os 44 personagens base, quatro relações de evolução, quatro mundos e 24 atos documentados. A revisão acrescentou 104 perguntas de mecânicas com as mesmas fontes históricas; não acrescentou informações de updates posteriores nem biografias de anime. Imagens atuais podem ilustrar o jogo sem provar aparência ou atributos de 2022.

A reconstrução usa registros sobreviventes de 4–11 de julho e um changelog retrospectivo. **Não é um inventário comprovadamente exaustivo do instante do lançamento em 3 de julho.** Pendências em `data/release_pending.json` incluem personagens sem data inicial corroborada, receitas de evolução não autenticadas e conflito do chefe de Hidden Sand ato 4. Estatísticas RND e números sem contexto de nível não foram inventados. Ausência de um dado não prova que o conteúdo não existia.

Retratos ausentes não geram reconhecimento visual. Molduras de raridade e ícones que dariam a resposta são ocultados. Todas as descrições de galerias/miniaturas são `.`; ícones de aplicação têm nomes técnicos neutros.

## Pontuação e abuso

- Crédito único por mensagem, com o vencedor decidido antes de qualquer await. O ponto aceito é gravado antes da confirmação visual; o cancelamento da tarefa depois disso não remove o crédito já persistido.
- A mesma pergunta e etapa soma no total global de cada jogador **uma vez a cada 24 horas**, mesmo em outro canal/partida. Repetições continuam valendo no placar da partida, com aviso no resultado. O limite sobrevive a reinícios e não é estendido por repetições rejeitadas.
- SQLite serializa a decisão de elegibilidade e escrita. Migrações preservam os totais e os registros legados.
- Botões de painéis antigos, respostas tardias, webhooks, bots e mensagens editadas não dão pontos. Pausar não recupera tentativas.
- Cooldowns limitados em memória protegem ajuda, consultas de pontos e abertura de lobbies. Atualizações repetidas com o mesmo estado são agrupadas.
- Até três partidas por servidor e 50 no processo, com reserva de vaga antes de qualquer await. Remover threads/canais ou retirar o bot do servidor libera as sessões correspondentes.
- Quedas do Gateway pausam o relógio e a reconexão retoma apenas as pausas automáticas, bloqueando respostas antigas recebidas depois. Pausas manuais e o limite de dez minutos são preservados. Quedas durante publicação de pergunta/resultado também são cobertas.
- Erros de comando e interface recebem explicação privada, quando o Discord está disponível. SIGTERM inicia encerramento organizado, com tentativa de aviso nos painéis por até três segundos. Reinícios preservam pontos gravados, mas encerram partidas.
- As proteções não estabelecem identidade única entre contas e não impedem consulta externa à wiki. O banco público também não deve ser apresentado como um segredo inacessível aos jogadores.

## Armazenamento

O proprietário confirmou por imagens o volume de **500 MB**, montado em **`/data`**, `DATA_DIR=/data` e serviço online. Os pontos de teste anteriores podiam ser reiniciados, por autorização expressa. O banco usa `/data/scores.sqlite3`; imagens e código não ocupam esse volume.

Recibos novos de disputa/antifarm são mantidos por **30 dias**. A limpeza é feita em lotes de até mil registros, sem apagar os totais; páginas livres são reutilizadas pelo SQLite. Recibos Discord expirados são rejeitados para não recreditar eventos removidos. Registros legados sem identidade de conteúdo não são descartados automaticamente.

Uma medição local com 100 mil registros e mil jogadores ocupou aproximadamente **22,61 MB**. É uma referência sintética, não uma garantia de capacidade. Monitorar uso real do volume e manter margem para operações do banco.

O banco passa por `quick_check` ao iniciar. Uma tarefa fora do loop de interações verifica espaço a cada hora e mantém uma cópia diária em `/data/backups/scores-latest.sqlite3`. Ela lê um snapshot consistente pela API do SQLite e verifica integridade/schema antes da troca atômica. Exige espaço para a cópia temporária mais 16 MiB de margem. Erro, demora ou falta de espaço preservam a cópia anterior, sem fechar o banco principal. Durante a troca coexistem banco, cópia anterior e temporário. Não há restauração automática.

Essa cópia está no mesmo volume: exportação externa continua recomendada. O procedimento está em `docs/release-checklist.md`.

## Validação e próximos passos

A suíte verifica limites nativos de todas as perguntas, inclusive com nomes longos e Markdown, rodadas fixas/contínuas, disputa simultânea, tentativa única, janela de 24h, reinício, duas conexões concorrentes, migração de schema, retenção sem perda de totais e cancelamento após acerto.

Também cobre reconexão, publicação concorrente com queda, exclusão de threads, capacidade, erros privados, backups e encerramento organizado. Uma simulação com 50 salas e 2.000 respostas registrou exatamente 50 vencedores; não equivale a teste de carga real da rede do Discord.

Antes de anunciar para mais servidores, recomenda-se uma partida real com um pequeno grupo para avaliar leitura das imagens, ritmo e dificuldade, além de conferir uma estratégia de backup do volume. Isso complementa os testes automatizados e as prévias simuladas; não houve envio de mensagens reais de teste pela máquina de desenvolvimento.

Novos dados históricos devem continuar exigindo fontes e tratamento de conflitos. Funcionalidades como dificuldade ajustável e revisão de erros são opcionais; não precisam bloquear o próximo projeto.
