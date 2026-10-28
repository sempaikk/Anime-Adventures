# Banners e desafio diário

## Configurar

| Comando | Origem | Destino |
| --- | --- | --- |
| `/setbanner` | 993219350179876874 | canal onde o administrador executa o comando |
| `/dailychallenge` | 1326659593199423610 | canal onde o administrador executa o comando |

Cada servidor configura seus próprios destinos. Gerenciar servidor ou Administrador são necessários para configurar; respostas e controles de configuração são privados. Stop receiving desativa apenas aquele feed. Para trocar, execute o comando no novo canal. O bot precisa de Ver canal, Enviar mensagens, Anexar arquivos e Ler histórico; Adicionar reações também é necessário para W/M/L.

As publicações contêm somente arquivos PNG/JPEG/WebP estáticos verificados, sem legenda, texto, URL, embed ou menção. GIF, APNG/WebP animado e vídeo são rejeitados. Cada imagem de banner é enviada separadamente. O desafio diário mantém seu lote e não recebe W/M/L.

Não há encaminhamento automático pelo megafone para servidores que seguem o canal. A entrega automática é feita pelo bot instalado/configurado em cada servidor. O tipo do canal e seu botão manual nativo não são alterados.

## Recebimento, comparação e entrega

DISCORD_TOKEN autentica o bot principal. SECONDARY_ACCOUNT_TOKEN autentica o leitor privado das duas origens, executado na hospedagem em ambiente isolado com biblioteca 2.1.0. O principal usa discord.py 2.7.1. Segredos não são enviados em argumentos ou logs. O PC do responsável pode ficar desligado.

A inscrição de guild grande mantém typing=True. Eventos ao vivo são complementados por poll de 30 segundos, até 50 mensagens recentes. Falha de acesso é separada por origem; queda do leitor afeta ambas. O leitor permite nova tentativa de recepção a cada 60 segundos, com limite de 256 identidades. A conta leitora nunca publica mensagens.

SHA-256 compara os bytes do arquivo, junto da identidade da publicação. Não é IA nem serviço externo; recompressão pode mudar a assinatura. Uma rotação nova pode reutilizar uma arte e ainda ser uma entrega legítima. Cada destino mantém suas próprias filas e confirmações. A recepção só avança depois de todos os bytes/validação/filas serem salvos. Uma recepção confirmada não exige baixar de novo, inclusive após reiniciar ou renovar assinaturas CDN.

Nonce estável, enforce_nonce e reconciliação por autor/nonce/arquivos protegem as entregas. Um resultado incerto é conferido antes de qualquer outro envio; não há reenvio cego. Excluir um post do bot não o recria. Edições/reordenações da origem não repetem imagens já confirmadas da mesma publicação.

## Desafio atual e reinícios

Somente a imagem mais recente do daily é candidata à recuperação, mesmo quando já vista. As 26 horas de cache não são uma fila de desafios a republicar. A escolha segue a ordem da origem, sem presumir meia-noite local ou UTC.

A versão recebida/validada e a postagem mais nova observada são registros separados. Ver uma origem nova bloqueia o desafio anterior enquanto o novo download precisa de outra tentativa. Uma edição de texto em postagem antiga não ultrapassa uma mais nova nem torna sua imagem novamente entregável depois da expiração. Uma mudança real de imagem na mesma postagem continua válida.

Ao reiniciar/reconectar, o daily aguarda confirmar a origem antes de enviar o cache. Pendências de versões anteriores são substituídas; recibos antigos de resultado incerto permanecem sem outro upload. Preservar DATA_DIR mantém essas proteções. Não apagar bancos ou repetir comandos para resolver uma entrega duplicada.

## W/M/L

As três artes originais RGBA 40×40 de Nova pasta.zip ficam em assets/banner-votes, verificadas por SHA-256 e sem edição. São emojis do próprio aplicativo com nomes exatos win, mid e lose. Cadastro/renomeação recupera os IDs existentes e só declara prontidão depois de nova consulta ao Discord. Não recria emojis para trocar nomes.

Novos banners recebem W/M/L independentemente. A contagem é a nativa, incluindo a reação inicial do bot; não se exige uma opção por conta. Mensagens antigas que agrupam várias imagens têm uma avaliação para o conjunto e não são divididas/repostadas.

O histórico acessível dos destinos configurados é conferido em páginas de 20, até três banners por etapa, com cursor persistido. Somente mensagens próprias com anexos reconhecidos recebem reações; mensagens alheias, webhooks e lotes ambíguos em canais misturados não são classificados por suposição.

A correção única de ordem autorizada pelo responsável vale para TODOS os servidores com banners configurados. Só as três reações antigas afetadas podem ser zeradas, com Gerenciar mensagens. Imagens, mensagens e outros emojis permanecem. Corte temporal por canal e fases persistidas impedem nova limpeza após começar a recriar as reações, preservando votos novos. Falta de permissão pausa só o destino afetado, sem interromper os outros ou as imagens.

## Limites e diagnóstico

Até dez imagens por conjunto, 8 MiB por arquivo, 16 MiB por lote, 32 MiB de cache e 64 conjuntos recentes por feed; até 20 milhões de pixels e dimensão máxima de 8.192. O limite de upload do servidor também é respeitado. O original aprovado não é reconstruído ou recortado.

Cache/recibos de banners expiram em 65 minutos; os do daily em 26 horas. Limpeza é por validade e uso, sem apagar arquivos por relógio às 00h50 ou remover posts no Discord. Configurações e os marcadores duráveis de proteção permanecem. Armazenamento crítico pausa novas imagens, considerando a cota da instância, dependências e backups.

Bot status mostra, em particular, destinos, estado de cada origem, progresso das reações e último recibo disponível. Leitor conectado significa acesso confirmado; não prova que uma imagem foi recebida ou entregue. Testes usam bancos temporários e APIs simuladas; o efeito real depende de atualizar a hospedagem e observar os destinos.
