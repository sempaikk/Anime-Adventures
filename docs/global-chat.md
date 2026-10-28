# Chat global

## Instalar e participar

1. Ative Message Content Intent no Developer Portal e confirme os requisitos de verificação do aplicativo antes de ampliar as instalações. Esta configuração externa não é feita pelo código.
2. No destino, conceda ao bot Ver canal, Enviar mensagens, Ler histórico, Anexar arquivos e Gerenciar webhooks.
3. Com Gerenciar servidor, abra `/globalchat` e escolha **Enable in this channel**. A rede não aceita canal com restrição de idade; uma mudança posterior de política pausa a conexão afetada.
4. O membro recebe uma única tentativa de convite por DM. Com DMs fechadas, abre `/globalchat` no canal e escolhe **Join** em particular.

A confirmação é persistente por conta e vale para toda a rede, incluindo servidores futuros. Só canais ativados compartilham; não há importação de mensagens anteriores ao aceite. A primeira mensagem permanece local. **Leave** interrompe novos compartilhamentos e cancela pendências; uma requisição já aceita pelo Discord pode terminar.

As originais nunca são apagadas para retransmitir. Cópias usam nome de exibição/avatar, sem acrescentar username ou servidor. O rótulo APP/BOT pertence ao Discord. Owner e Tester são calculados por IDs autorizados; a limpeza de nomes ocorre antes de retirar etiquetas reservadas. A etiqueta visual não substitui a autorização das ações.

## Controles

- Membros: participação, meus envios, ajuda curta, denúncias e remoção das próprias cópias. A última tentativa mostra motivo/horário em particular, inclusive com DMs fechadas; não mantém o texto da mensagem nesse registro.
- Moderadores com Gerenciar mensagens ou Moderar membros: caixa de denúncias e restrições locais, sem configurar o servidor ou atingir outros servidores.
- Administradores: ativação, mudança ou pausa da conexão e moderação local.
- Dono do bot: moderação da rede, diagnósticos e alertas privados.

As ações revalidam conta, servidor e capacidade. Painéis antigos não alteram uma geração nova. Denúncias têm páginas, filtros e decisões com motivo, responsável e controle de versão. Moderadores locais não aplicam sanções à rede. Trechos só aparecem se o revisor tiver acesso ao canal e histórico; conteúdo expirado não é arquivado pela denúncia.

## Conteúdo

Texto e formatação comuns permanecem. Mensagens longas são divididas. Respostas incluem contexto de uma mensagem conhecida. Menções são convertidas em nomes e as cópias não notificam pessoas, cargos ou everyone.

Anexos suportados: imagens, GIFs, vídeos, áudio, PDF e TXT, com CDN do Discord, limites e verificação limitada do formato real. Spoilers são preservados. A verificação não é um antivírus. Arquivos disfarçados e tipos não aceitos são recusados em particular. Uma cópia sem capacidade para um arquivo recebe indicação de tamanho, preservando a original.

Figurinhas compatíveis viram arquivos; formatos nativos não transportáveis são identificados por nome. Emojis personalizados dependem da disponibilidade no Discord. Reações, enquetes nativas, voz, tela e digitação permanecem locais.

## Proteção e restrições

Contas precisam ter sete dias. Há limites de seis mensagens por dez segundos por conta e doze edições por dez segundos, controle de repetição, tamanho e fila por origem. Links cujo domínio exibido diverge do destino são verificados mesmo sem protocolo no rótulo; rótulos descritivos e exemplos de código continuam possíveis. O filtro não promete detectar todo golpe.

A contenção é proporcional: repetição coordenada com links/convites ou tentativas repetidas pode restringir uma origem por dez minutos; alto volume concentrado em uma conta pode restringir essa conta por cinco minutos. Uma conversa movimentada não vira banimento permanente. Cumprimentos ou celebrações iguais, isoladamente, não bloqueiam o servidor inteiro. Dono pode revisar a contenção e o membro vê a condição em particular.

## Dados, recursos e recuperação

Texto e anexos temporários da fila expiram em uma hora, com limpeza periódica. A última tentativa também expira em uma hora. IDs necessários para sincronização e denúncias ficam até 30 dias. Confirmações e configurações persistem até mudança/saída. Convites resolvidos são removidos da DM quando possível; a tentativa mínima evita convites repetidos.

Limites existentes: cache de anexos 256 MiB, 128 MiB de páginas ativas do banco, 50 mil entregas pendentes, até 128 MiB de preparo por mensagem. Reservas conjuntas respeitam a cota real da instância. O orçamento usa o tamanho conhecido do arquivo, sem exigir o limite inteiro de upload de um servidor para um arquivo pequeno.

Destinos são alternados, com até quatro entregas paralelas, ordem por canal e prioridade para remoções. Estado concluído não mantém detalhes desnecessários da tentativa. A pausa de emergência cancela novos compartilhamentos; remoções continuam. Conversas do período pausado não são importadas ao retomar.

Recibos são gravados por parte. Após reiniciar, originais conhecidas são conferidas gradualmente, sem importar conversas anteriores ao consentimento. Um resultado incerto é reconciliado antes de continuar; não há promessa de entrega exatamente uma vez em toda falha possível. Uma cópia removida localmente não é recriada por edição da original.

O crescimento é medido por filas, registros, disco, memória e API. Um teste local do banco não comprova capacidade da hospedagem nem permissões reais. Ensaio e procedimento: [operação](operations.md).
