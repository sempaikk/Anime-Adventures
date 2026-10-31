# Comunidade oficial

Servidor oficial do bot e da comunidade: 1554953245204422807. Atualizações somente no canal confirmado 1564498826423959652, por ID. Renomear não muda o destino. Não usar outro canal de nome parecido nem misturar com feed/chat global.

## Feedback

**Feedback** aparece apenas nos painéis da comunidade oficial. Membros podem enviar erro ou sugestão em formulário privado, com recibo, limite por conta e deduplicação. Nada é publicado automaticamente em canal público. O dono abre **Review feedback**, escolhe um item e resolve ou descarta. Uma decisão antiga não sobrescreve uma nova.

Descrições têm limite de 800 caracteres. Ficam até 30 dias, com limite total de 3.000 registros. O formulário informa o uso privado e orienta a não incluir segredos. Esse recurso não altera as denúncias do chat global, que continuam disponíveis em todos os servidores participantes.

## Notas públicas

Notas em data/community_updates.json têm a versão exata e somente efeitos que o membro consegue perceber: consulta, mensagens, entrega e participação. Filas, diagnóstico, backup, testes e administração exclusiva do dono ficam privados. Texto em português, diretamente em tópicos, sem cabeçalho, versão técnica ou data.

Cada atualização é uma mensagem NOVA, inclusive pequena. Reiniciar a mesma versão não duplica o aviso; confirmação incerta é reconciliada no canal original. Nunca acrescentar novidades editando conteúdo anterior. A única correção editorial antiga autorizada continua imutável em data/community_notice_correction.json.

Publicar exige arquivos verificados, versão correspondente e conclusão do trabalho ativo. Preparação e varredura do W/M/L precisam terminar em TODOS os destinos configurados, incluindo servidores de jogadores. Permissão ausente, reparo incompleto ou limite de reações impede anunciar sucesso. Não usar atraso fixo nem esperar a próxima imagem do jogo como prova. O perfil do aplicativo, se estiver aguardando confirmação, também aparece como pendência privada.

As notas não fazem crosspost, não mencionam cargos/membros e não vão a outros servidores. Testes offline não publicam notas.

## Aviso pontual de retomada

Em 28/10/2026, o responsável autorizou uma exceção: pedir desculpas pela interrupção e informar a retomada diretamente nos canais configurados de banners e desafio diário de todos os servidores existentes. O texto é em português, sem menções, anexos, votação ou publicação pelo megafone. Se os dois feeds compartilham um canal, enviar um aviso combinado.

A campanha fixa feed-recovery-2026-10-28 grava destinatários e recibos na primeira ativação verificada. Não inclui canais novos/reconfigurados depois dessa seleção, não muda destinos e não reinicia a cada release/restart. Antes de enviar, exige consulta recente bem-sucedida da fonte e recepção da imagem observada, quando houver; a permissão real do destino também é conferida. Uma fonte indisponível não impede o aviso do outro feed.

Envio incerto é reconciliado pelo nonce ou conteúdo próprio no canal original, sem republicação cega. O prazo termina em 04/11/2026 UTC para não apresentar um incidente antigo como boas-vindas em instalações futuras. **Bot status → Feed recovery notice** mostra o total confirmado, pendente e incerto em particular. Os logs normais de atualização e o feedback permanecem exclusivos da comunidade oficial. A .28.3 acrescenta apenas essa campanha; não duplica a nota pública da correção .28.2 no update-log.

## Aviso do incidente de encaminhamentos

O responsável autorizou separadamente um aviso em português nos canais de banners de todos os servidores configurados, explicando que parte das imagens passou a chegar por encaminhamento e não era reconhecida, o que causou atrasos e ausência de alguns banners. O texto informa que o suporte foi corrigido e os envios estão sendo retomados com imagens recentes; não promete republicar todo o histórico perdido. Não inclui detalhes internos, menções, anexos, votação ou crosspost e não vai aos canais exclusivos de daily.

A campanha banner-forwarded-recovery-2026-10-30 usa a mesma estrutura de recibos, com chave/nonce próprios e destinatários congelados na primeira ativação verificada. Fonte consultada recentemente, recepção da imagem observada, acesso ao canal e geração da configuração são revalidados. Uma entrega incerta só é reconciliada no canal original, sem reenvio cego. O aviso não se repete em novos releases/reinícios, não acompanha mudanças de canal nem vira boas-vindas para instalações futuras. Expira em 06/11/2026 UTC.

**Bot status → Banner forwarding notice** informa o progresso em particular. O ciclo operacional existente conduz o aviso sem acrescentar outro trabalhador periódico. A campanha anterior de 28/10 mantém sua chave, texto, prazo e recibos intactos. Esta entrega acrescenta somente o aviso solicitado; não cria outra nota regular de atualização nem repete a da correção de encaminhamentos.

## Aviso do incidente de recepção

Em 31/10/2026, o responsável solicitou novo aviso de desculpas e resolução pela interrupção dos banners. A campanha banner-reception-recovery-2026-10-31 é exclusiva dos destinos de banners existentes, com seleção congelada, nonce e recibo próprios. O texto em português diz que o canal voltou a receber imagens recentes, sem detalhes de memória/hospedagem, menções, anexos, votação ou megafone. Não republica o histórico antigo.

Além de consulta recente e bytes da imagem atual verificados, o envio exige que o último evento da origem observada tenha um trabalho confirmado como sent com ID de mensagem no destino exato. Sucesso em outro servidor, metadados, versão parcial, imagem anterior ou confirmação incerta não liberam o aviso. Permissões/geração continuam sendo revalidadas, e ACK desconhecido só reconcilia a própria tentativa no canal original. Reinício/release não repete o aviso nem inclui destinos adicionados depois. Expira em 07/11/2026 UTC.

**Bot status → Banner reception notice** mostra o progresso privado. O ciclo operacional existente processa a nova campanha. As campanhas de 28/10 e 30/10 mantêm seus textos, recibos, prazos e destinatários; o print de produção de 31/10 confirmou respectivamente 4/4 e 2/2 entregues. A nota regular da nova correção continua exclusiva da comunidade oficial e respeita todos os gates existentes.

## Diagnóstico e permissões

O dono com Gerenciar servidor abre **Bot status** e **Server report** para obter o relatório privado. Ele inclui estrutura e permissões, sem histórico, credenciais, URLs de webhook ou lista de membros. Ver a visibilidade de @everyone não certifica privacidade: sobreposições de outros cargos e indivíduos também importam. Nunca versionar relatório real.

**Review role permissions** prepara o plano de Assinantes, Artista/Angelic e Mods. Só o dono pode aplicar o plano após revisá-lo; não há alteração automática de cargos no startup. Nomes, membros, cores, hierarquia e sobreposições de canais são preservados. Detalhes e limites: [permissões](community-permissions-plan.md).

Testes reais exigem ambiente privado verificado; respostas efêmeras são preferidas. O único ícone decorativo do jogo permanece uma miniatura em Bot status. Outros controles são em texto; imagens de conteúdo e W/M/L funcionais são preservados.

O desenvolvimento não tem sessão administrativa direta no Discord/hospedagem. O efeito real depende de carregar o pacote e observar os canais. Níveis por mensagens permanecem expressamente adiados, sem XP, loja, moedas ou contagem de call.
