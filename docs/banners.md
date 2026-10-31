# Banners e desafio diário

## Consulta e configuração

`/setbanner` e `/dailychallenge` abrem painéis privados para membros e administradores. **View current images** consulta os arquivos atuais sem modificar configurações. Exige que o membro possa ver e ler o histórico do destino configurado. Uma imagem expirada, retirada da origem ou aguardando verificação não é anunciada como atual.

Somente Gerenciar servidor ou Administrador permite **Enable in this channel** e **Stop receiving**. **Check connection** consulta sem reconfigurar. A habilitação confere Ver canal, Enviar mensagens, Anexar arquivos e Ler histórico, antes de gravar o destino. W/M/L também exige Adicionar reações. Gerenciar mensagens é uma necessidade separada para a correção única de reações antigas, não para enviar novos banners.

**Open last delivery** e **Recent deliveries** abrem recibos locais já confirmados, sem reenviar arquivos. **Delivery status** distingue última consulta, recepção e entrega deste servidor. **Report image issue** prepara detalhes para feedback privado na comunidade oficial; não publica denúncias nos feeds. Horários silenciosos já configurados continuam sendo respeitados na entrega: podem suprimir push/desktop sem atrasar a imagem nem prometer ocultar badges de não lidas.

Cada servidor tem seus próprios destinos. Painéis antigos verificam a geração da configuração; um painel anterior não desliga uma configuração refeita no mesmo canal. Cliques são confirmados em particular antes de esperar operações. Uma requisição já aceita pelo Discord pode terminar durante a desativação.

Fontes exclusivas: banners 993219350179876874 e desafio diário 1326659593199423610. O bot usa seu próprio acesso autorizado quando disponível. Sem acesso, mantém o leitor isolado com SECONDARY_ACCOUNT_TOKEN, sem exigir PC ligado. Não encaminha texto, autores ou outras conversas da origem.

Postagens normais e encaminhamentos são aceitos nas mesmas fontes. O leitor verifica os anexos e imagens dos snapshots incluídos no encaminhamento, sem buscar a mensagem ou o canal original. Só os arquivos de imagem passam à entrega; textos, autores, menções, referência e indicação de encaminhamento não são publicados. A identidade e o horário continuam sendo os da postagem no canal oficial, inclusive para edições, retiradas e controle de duplicatas. Os limites de formato, idade e quantidade são os mesmos.

## Receber e entregar

Eventos ao vivo são complementados por consultas de 30 segundos, até 50 mensagens por origem. A inscrição do leitor isolado em servidor grande mantém typing=True. As consultas e os dois trabalhadores de recepção são independentes, com filas limitadas. Ver uma versão nova do daily persiste uma barreira antes de confirmar a origem ou baixar arquivos; uma revisão anterior não passa por essa barreira.

As consultas HTTP continuam durante uma reconexão do Gateway, quando o acesso à origem ainda funciona. Uma sessão RESUMED confere as duas fontes imediatamente e mantém um único trabalhador periódico; não depende de receber outro READY. Falhas reais de acesso continuam sendo informadas, sem tratar um heartbeat do processo como confirmação de consulta.

Apenas PNG/JPEG/WebP estáticos verificados são aceitos. GIF, APNG/WebP animado e vídeo não são publicados nos feeds. Cada imagem de banner vira uma mensagem separada; o daily mantém o lote e não tem W/M/L. Formato incompatível não elimina outras imagens válidas. Falha temporária em uma imagem de banner permite entregar as válidas e recuperar a que falta, sem confirmar a recepção inteira prematuramente. O daily mantém a validação conjunta para não duplicar partes de um desafio.

SHA-256 local compara bytes, com identidade da postagem de origem e recibos de cada destino. Uma postagem genuinamente nova pode reutilizar a mesma arte. Cache expira sem apagar imediatamente a memória leve dos envios. O histórico de origem e os recibos por canal são limitados, com marcos que impedem reabrir publicações antigas já compactadas. Uma edição de texto não transforma um banner antigo em novidade. Uma origem retirada interrompe novos envios; mensagens e votos já publicados permanecem.

Há até dois uploads ativos por feed e fila limitada por canal. Um destino lento não mantém todos os outros esperando. A ordem dentro do canal é preservada. Timeouts deixam tentativas identificáveis, com nonce estável e reconciliação ao redor do primeiro envio. O bot não reenvia cegamente uma confirmação incerta. Apagar uma imagem entregue não a recria.

## Atualidade do daily

Somente a imagem mais recente da origem é candidata à recuperação. Não cair para ontem quando a atual já foi vista ou ainda precisa de nova tentativa. A versão observada é separada da versão recebida, incluindo alterações de imagem na mesma postagem. Uma edição antiga não ultrapassa uma origem nova. Reiniciar aguarda a confirmação da fonte antes de liberar pendências em cache.

A retenção de 26 horas é uma política de armazenamento, não um horário de virada do jogo. As telas mostram o horário real da publicação/edição da origem e o da confirmação de entrega.

## W/M/L

As artes originais RGBA ficam em assets/banner-votes, verificadas por SHA-256 e sem edição. Os nomes do aplicativo são exatamente win, mid e lose. IDs existentes são preservados; registro/renomeação só declara prontidão após consulta independente ao Discord.

A contagem nativa inclui a reação inicial do bot e permite mais de uma opção por pessoa. A versão não troca as reações por botões de outra votação. Banners antigos agrupados continuam com uma avaliação para o conjunto, sem dividir ou republicar o histórico.

A correção única autorizada da ordem vale para TODOS os destinos configurados. Só as reações antigas afetadas podem ser zeradas; corte por canal e fases persistidas preservam votos novos e outros emojis. Reiniciar não repete a limpeza. Falta de permissão pausa o destino afetado; não impede imagens nos outros servidores.

Reações novas têm prioridade sobre a varredura histórica. Trabalhadores limitados por canal e pela API continuam em segundo plano; não aguardam todos os servidores para concluir uma rodada. A varredura acessível usa cursor persistido, identifica somente imagens próprias conhecidas e não adivinha lotes ambíguos em canais misturados.

## Recursos e diagnóstico

Limites por feed: 10 imagens, 8 MiB por arquivo, 16 MiB por conjunto, 32 MiB de cache, 64 conjuntos recentes, 20 milhões de pixels e dimensão máxima de 8.192. O limite real de upload de cada servidor também se aplica. As imagens aprovadas não são redesenhadas ou recortadas.

Cache: 65 minutos nos banners e 26 horas no daily. A limpeza não apaga posts do Discord nem ocorre por relógio às 00h50. Reservas de disco e memória consideram preparos paralelos, dependências, instalação do leitor e backups. Pressão de recursos adia novos arquivos preservando dados.

A recepção mantém a reserva de disco de 32 MiB por trabalhador, mas a RAM acompanha os arquivos: comprimento informado antes da leitura, crescimento incremental quando ausente/incorreto e orçamento separado pelos pixels antes do decode. Os buffers ficam cobertos até a confirmação no banco, com liberação em falha/cancelamento. Não há mais reserva fixa adicional de 32 MiB de RAM por feed; ela bloqueava imagens pequenas com 203 MiB já ocupados, pois 235 MiB ultrapassam a margem de 90% dos 256 MiB. O limite da instância e a proteção contra imagens grandes continuam.

**Status** diferencia consulta da origem, observação da imagem, bytes verificados e entrega confirmada. O dono vê ainda destinos, filas, falhas e latência recente por destino. Alertas privados distinguem ausência de novidades de falha de recebimento ou entrega. Não há alerta só porque o jogo não publicou imagem nova. Um leitor silencioso é detectado; falhas de autenticação/verificação de conta aguardam ação do responsável, sem contornar verificações.

Uma consulta bem-sucedida dos metadados não apaga falha de recepção: erros de RAM, disco e download permanecem até os bytes da versão atual serem verificados. Um recibo mais antigo também não limpa o erro nem avança o horário de recepção da imagem atual. O alerta de fonte considera acesso/consulta, e o de recepção considera a imagem observada ainda pendente, com estabilidade/cooldown preservados. **Last issue** no painel privado identifica espera por memória ou armazenamento.

A publicação automática pelo megafone permanece desativada em todos os servidores. O botão manual e os seguidores nativos do canal não são alterados.
