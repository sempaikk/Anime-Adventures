# Comunidade central e revisão dos comandos

É o servidor oficial tanto do bot quanto da comunidade. O responsável reforçou que os avisos e a opção de feedback são exclusivos dele; não disponibilizar essa opção aos outros servidores. Os avisos já respeitam esse limite. O ciclo atual não implementa comando/canal novo de feedback nem altera as denúncias existentes do chat global. As recomendações de cargos/canais estão no [plano de permissões](community-permissions-plan.md); esse plano ainda não foi aplicado no Discord.

## Relatório privado do servidor

Depois de atualizar a hospedagem, o dono do aplicativo que também tem Gerenciar servidor abre `/globalchat` no servidor central, escolhe **Bot status** e **Server report**. Não é necessário ativar ou mover o chat global para usar o diagnóstico. A resposta e o arquivo `community-server-report.json` são privados.

O relatório inclui canais/categorias, finalidade indicada nos tópicos, cargos, permissões do bot por canal, sobreposições de cargos, destinos configurados e estado dos feeds. Informa a visibilidade de `@everyone`; isso **não certifica que um canal é privado**, porque outros cargos/sobreposições individuais podem conceder acesso. Não exporta histórico de mensagens, lista de membros, identidades de sobreposições individuais, tokens, URLs de webhook ou bancos. É uma fotografia do cache recebido pelo Gateway; reconexões e mudanças posteriores podem torná-la desatualizada. Revisar antes de compartilhar, e nunca versionar o relatório de produção.

A máquina de desenvolvimento não recebe acesso ao Discord por conhecer o ID do servidor. Sem conector/credenciais disponibilizados a esta sessão, a análise real depende do relatório compartilhado pelo responsável. Não pedir segredos nem reinstalar Python no PC para obtê-lo.

## Atualizações para os membros

O relatório privado da instância confirmou o canal de anúncios **1564498826423959652**. A versão .3 procurava `update-log` no singular e não reconheceu o nome real `updates-logs`. A partir de .4, o bot usa exclusivamente o ID confirmado dentro do servidor central. Renomear esse canal não altera o destino; nomes parecidos em outros canais não redirecionam a publicação. Precisa de Ver canal, Enviar mensagens e Ler histórico. Não usa um destino de banner, desafio ou chat global para esse fim. Se o canal for excluído ou ficar inacessível, aguarda correção em vez de publicar em outro lugar.

As notas ficam em `data/community_updates.json`, com a versão exata e mudanças relevantes ao uso. O público é um membro casual usando o bot em qualquer servidor. Incluir apenas novidades que ele consiga perceber ou usar; diagnósticos privados do dono, configuração/controles administrativos, roteamento do canal de updates, testes e implementação não são assunto de aviso público. Cada entrega com mudança percebida pelos membros precisa atualizar essa lista e o manifesto. Revisões internas sem efeito para os membros não recebem anúncio. Só a versão que estiver rodando com arquivos verificados pode publicar; testes locais não anunciam nada.

Por pedido posterior do responsável, os avisos são **em português e começam diretamente pelos tópicos**. Não incluir cabeçalho com nome do bot, “Update”, número de versão, data ou título técnico. A versão serve internamente para conferir o pacote e deduplicar, permanecendo nos diagnósticos privados. A interface dos comandos continua em inglês.

**Cada atualização futura é uma mensagem nova**, inclusive uma melhoria pequena com um único tópico. Não adicionar novidades editando avisos antigos; conservar cada conteúdo e seu horário no Discord. Reiniciar a mesma versão não duplica o aviso.

Há uma **única exceção de edição autorizada**, para reduzir o aviso .5/.4 aos dois benefícios de uso. Seu texto imutável fica em `data/community_notice_correction.json`, com recibo identificado por `NOTICE_CORRECTION_VERSION` (.6). Esse ajuste é independente das notas atuais: se a hospedagem pulou a .6, a .7 pode concluir exatamente essa correção antiga e publicar W/M/L em uma mensagem NOVA. Confere recibo, canal/autoria/ausência de webhook e corpo conhecido; confirmações perdidas são reconciliadas. Novidades nunca são acrescentadas ao texto da correção, nem campos `replaces` das notas futuras determinam edições. Mensagens alheias ou apagadas não são modificadas/recriadas.

**O aviso só sai depois da aplicação confirmada da atualização na hospedagem.** A partir da .12, ter os emojis prontos não basta: todos os destinos ativos de banners precisam ter preparação e varredura histórica concluídas, sem banners pulados pelo limite de reações, reparos W/M/L incompletos ou reações pendentes em imagens já entregues e vigentes. A verificação é somente de leitura, usa o progresso persistido e inclui os servidores dos jogadores. Falta de permissão, erro ou processo ainda em andamento mantém o motivo no painel privado; não anuncia uma conclusão parcial. Uma segunda conferência imediatamente antes de criar o recibo de envio evita anunciar se outro trabalho começar durante uma operação assíncrona anterior.

Essa conferência vale para todo aviso novo, mesmo sem a opção `requires_banner_reactions` nas notas. Novas tarefas assíncronas de atualização devem expor sua conclusão em `CommunityHub.update_complete`; não usar um atraso fixo como prova. Trabalho já confirmado não é refeito para liberar o aviso. Banners/desafios continuam sendo entregues pelas tarefas independentes; não se aguarda a próxima imagem do jogo nem o próximo desafio diário para anunciar uma atualização aplicada. Registro do aplicativo, filas, diagnóstico e configuração ficam privados.

O encaminhamento automático de imagens para seguidores, introduzido na .13, foi retirado na .16 por pedido do responsável. Pendências antigas de crosspost ficam inertes e não entram no gate dos novos avisos. Permanecem as conferências de integridade/versão e de conclusão do trabalho ativo de W/M/L. Os avisos continuam exclusivos deste canal oficial e descrevem somente efeitos percebidos pelos players; detalhes de hashes, filas ou diagnóstico privado não entram nas notas públicas.

Há um recibo persistente por versão no banco existente. Reiniciar ou renomear o canal não duplica o aviso. A confirmação perdida é pesquisada no canal original; sem conseguir confirmar, não reenvia cegamente. O envio não menciona membros/cargos e não faz crosspost de anúncios. **Bot status** informa se houve publicação, falta de canal/permissão ou confirmação pendente. A verificação ocorre a cada 30 s; indisponibilidades são reavaliadas em até cinco minutos.

## Testes privados

Os testes automatizados usam estado temporário e APIs simuladas. Nenhuma mensagem de teste deve ir aos canais públicos ou à rede global real. Se futuramente um ensaio pela API exigir publicação, conferir as permissões de todos os cargos/sobreposições no canal restrito antes de enviar; não basta constatar que `@everyone` está bloqueado. Não alterar o destino público dos feeds para ensaiar, não fabricar participação/consentimento e não criar papéis/XP de produção. Sem espaço de teste privado confirmado, limitar-se ao diagnóstico em particular e aos testes offline.

## Revisão entregue em 2026.10.27.3

- Banner e desafio têm ciclos separados; uma exceção de entrega em um não impede o ciclo do outro. Compartilham apenas o processo leitor e a persistência já existentes.
- Queda do processo leitor muda os dois estados para indisponível. Falha de acesso a uma origem continua específica daquele feed. Reconexão bem-sucedida reinicia a espera progressiva.
- O diagnóstico privado informa destino, estado da origem e última confirmação recente. Só considera recibos do destino atual; a ausência de recibo dentro da retenção não significa que nunca houve entrega.
- Excluir um canal de destino desativa somente a configuração daquele feed. Excluir/sair de um servidor já remove suas conexões, sem copiar configuração do servidor antigo para outro.
- Pausa/retomada do chat global é serializada por servidor e confere novamente a geração da configuração após confirmar a interação; um painel antigo não modifica uma configuração nova.
- Mensagens de permissões do chat global permanecem em inglês, como o restante da interface.

O responsável confirmou banners chegando no horário. O relatório privado posterior e a captura de Bot status comprovam .3 com arquivos íntegros, chat global ativo, destinos de ambos os feeds e recibos confirmados de banner e desafio diário. A máquina de desenvolvimento não executou publicações reais. A correção do destino de atualizações na .4 ainda precisa ser carregada na hospedagem e o anúncio conferido.

## Ícones e organização do servidor

Por preferência posterior do responsável, apenas **Bot status** pode exibir uma miniatura decorativa do jogo, uma vez no início do cartão. Os demais menus, botões e campos usam texto, sem recolocar o mesmo ícone em títulos, confirmações ou listas. Os feeds continuam com suas imagens originais; o texto e os emojis escritos pelos participantes não são alterados.

O responsável definiu **Assinantes** como membros normais, **Angelic** e **Artista** como cargos decorativos e **Mods** como moderadores. Disse que excluiria seu cargo pessoal e continuaria com Assinantes; a conta proprietária mantém os poderes de dono independentemente desse cargo. O relatório antigo não tinha um cargo chamado Angelic; não inferir identidade a partir de outro nome.

A captura posterior mostra o cargo **Adventures**, criado pelo responsável, atribuído ao bot, no topo e com Administrador. A posição habilita gerenciamento de cargos abaixo. Desativar **Exibir membros deste cargo separadamente** em Adventures mantém a organização visual pelo cargo Bots inferior. Não duplicar o cargo nem alterar permissões dos outros cargos automaticamente. O relatório anterior tinha Mods com Administrador; a proposta de moderação com permissões específicas ainda não foi aplicada. Autorização do dono não disponibiliza acesso técnico direto ao Discord nesta sessão.

## Ideia futura de níveis

O responsável descreveu progressão **por mensagens**, com os níveis representados por passivas de Anime Adventures, começando nas mais fáceis e culminando em **Unique** após bastante participação. Não é uma loja ou sistema de moedas/compras. Contagem de call foi considerada e deixada fora. **A implementação foi expressamente adiada**; não foram criados comandos, cargos, tabelas, XP ou coleta de mensagens para isso. Fórmula, antifarm e lista exata das passivas ficam para uma decisão futura.
