# Interface do quiz

A interface usa **Discord Components V2**, disponíveis em discord.py 2.7.1. O quiz é focado no jogo e combina resposta pelo chat, reconhecimento de imagem do jogo e três alternativas por botões. O conteúdo continua restrito ao lançamento e a cenários derivados dos valores documentados.

## Telas e interação

1. **Painel inicial:** banner com “P2W” enviado pelo usuário e título em um cartão próprio. Outro cartão reúne resumo da partida, menus numerados de assunto e duração, **Começar quiz** e **Fechar painel**. O painel expira após dois minutos sem iniciar e libera o canal. Não repete o nome da etapa nem a data em cabeçalhos.
2. **Pergunta:** categoria e número no cabeçalho, acompanhados do ícone original do sistema; enunciado em destaque, imagem contextual e indicação de como responder. Perguntas com alternativas mostram três botões neutros A/B/C, um por linha. Relógio e controles ficam em outro cartão. Raridade só aparece quando ela é uma pista.
3. **Resultado:** vencedor ou fim do tempo, resposta comentada e imagem correspondente, total acumulado quando salvo, placar da sessão, próxima etapa e botão da revisão histórica usada como fonte.
4. **Pausa:** congela imediatamente a pergunta ou o intervalo. Mostra os segundos restantes sem um prazo relativo que continue se movendo. **Retomar** usa o mesmo tempo restante, sem reiniciar a contagem. Respostas enviadas durante a pausa são rejeitadas, mesmo se entregues após a retomada. Um acerto recebido antes do pedido de pausa continua valendo. Após dez minutos de pausa, encerra e libera o canal; retomar cancela o encerramento agendado. Cliques repetidos não estendem essa pausa.
5. **Encerramento:** banner de Summon enviado pelo usuário, resumo e **Jogar de novo**. Encerrar uma pergunta ativa aguarda seu desfecho para preservar o ponto em disputa; em pausa ou fora da pergunta, encerra imediatamente.
6. **Ajuda e pontos:** cartões privados para quem clica. Não enviam novas mensagens públicas, não alteram o prazo e não contam como tentativa.

## Escolhas de uso

- Tempo: **30, 45 ou 60 segundos**, com 45 como padrão. Intervalo de 8 segundos entre perguntas.
- Alternativas: uma escolha por pessoa e rodada; o primeiro clique correto processado recebe o ponto. Escolhas erradas recebem feedback privado, sem revelar a resposta. Repetir o clique, pausar ou retomar não devolve a tentativa. Mensagens no chat não substituem um botão nesse formato.
- Chat: até três respostas diferentes por pessoa e rodada, conforme informado na pergunta e na ajuda. Maiúsculas, pontuação e acentos não tornam uma resposta repetida em uma nova tentativa. Pausar não limpa o limite; a pergunta seguinte limpa. Mensagens vazias, só pontuação ou acima de 160 caracteres não contam como participação nem consomem tentativa.
- A ordem das alternativas muda a cada rodada e fica estável durante atualizações do relógio e pausa/retomada. Botões ficam desabilitados durante a pausa; cliques atrasados da pausa não contam depois de retomar. IDs dos controles não indicam qual alternativa é correta.
- Assuntos: **Tudo junto**, **Personagens**, **Mundos e chefes**, **Sistemas do jogo**. A escolha filtra somente o pacote Release antes de embaralhar.
- O anfitrião escolhe opções e inicia. Anfitrião e moderadores com Administrador, Gerenciar Servidor ou Gerenciar Canais podem pausar, retomar e encerrar. Outros jogadores mantêm acesso a respostas, ajuda e placar.
- Uma sessão por canal, inclusive durante a configuração. Dois cliques simultâneos em começar não criam duas partidas.
- Abertura de painel: intervalo de três segundos por jogador, compartilhado entre canais. Ajuda e pontos têm intervalos independentes de 750ms por pessoa; repetições são reconhecidas silenciosamente. Esses limites não atrasam respostas do quiz nem consultas de outros jogadores. O registro de limites tem memória limitada a 4.096 chaves.
- Controles antigos não podem modificar uma sessão nova nem uma pergunta ainda em publicação. Ajuda, pontos e revanche têm encaminhamento persistente após reinícios; sessões em andamento não sobrevivem a reinícios.
- Apagar o painel, inclusive em pausa, libera o canal. Se uma resposta correta já foi recebida, o crédito é concluído antes de encerrar. Apagar o canal também encerra sua sessão.
- Botões de cada pergunta e resultado são aposentados quando o jogo avança. O aviso da próxima pergunta vira “Rodada concluída”, para não continuar exibindo um horário relativo no passado. Links das fontes continuam disponíveis.

## Escrita e aparência

Textos curtos e naturais em português explicam o que fazer, sem forçar gírias. Títulos, subtítulos, negrito, texto secundário, separadores e imagens originais do jogo dão hierarquia. A interface não usa emojis Unicode. O placar usa posições numeradas; alternativas usam A/B/C. Pontos, perguntas e acertos respeitam singular e plural. Nomes de jogadores têm Markdown, menções, quebras de linha e controles direcionais tratados para não imitarem outras linhas de placar. A fonte, o fundo e as dimensões finais são definidos pelo cliente Discord e pelo tema do usuário; bots não aplicam CSS próprio às mensagens.

Dez imagens de interface vêm diretamente da wiki: mochila, unidade, Summon, evolução, traits, ranking, poder, dano, SPA e alcance. Todas as originais escolhidas já possuem transparência; não houve reconstrução nem geração de fundo. Versões PNG RGBA de até 128px preservam o canal alfa para uso nos controles. Dentro de textos, botões e menus, o Discord exige o recurso técnico de ícone de aplicação/custom emoji. Os pixels são dos arquivos da wiki, com identificadores e nomes neutros registrados em `data/ui_icons.json`; a aplicação os usa sem criar emojis nos servidores. Controles mantêm seus rótulos e funcionam como texto quando um registro de ícone está ausente.

As respostas aceitam nomes atuais e antigos do jogo e do anime quando cadastrados para a mesma unidade e forma. Vinte perguntas de chefes ganharam equivalências conferidas no módulo da wiki; a fonte de identidade fica em `alias_sources`, separada da fonte do fato histórico. Nomes da forma base não substituem uma transformação. Mundos e alimentos mantêm seus equivalentes já registrados.

Roxo e dourado remetem à identidade da wiki. Cores de raridade só aparecem quando a raridade já é uma pista. **Perguntas que pedem a raridade não revelam a resposta pela cor.**

**Somente os dois banners autorizados pelo usuário ou imagens da wiki de Anime Adventures podem ser usados. Nenhuma imagem gerada por IA.** A antiga ilustração gerada foi removida. Os dois banners foram preservados como arquivos originais; o primeiro foi baixado pelo link de anexo fornecido no chat e o segundo foi localizado na miniatura oficial do jogo e conferido visualmente.

O manifesto [`data/media.json`](../data/media.json) registra 72 imagens: dois banners, logotipo da wiki, 28 formas de unidades, quatro cenários, quatro alimentos, 17 ícones de sistemas/itens, dez ícones de interface e seis imagens reservadas para pesquisa de etapas futuras. Cada registro guarda página e URL de origem, dimensões, hashes e eventual recorte. Há 25 cópias idênticas em `assets/quiz/` com nomes neutros para reconhecer unidades sem expor o nome no link. A revisão descartou placeholders. O índice da wiki contém 2.387 arquivos; isso não significa que todos foram selecionados ou revisados visualmente. Vídeos e GIFs só devem ser exibidos quando a unidade, a forma e o contexto estiverem confirmados; efeitos modernos não comprovam mecânicas do lançamento.

Reconhecimento de uma unidade usa sua imagem no Anime Adventures, sem pista de biografia do anime. Sem retrato validado, esse reconhecimento fica fora do sorteio; outras perguntas sobre a unidade, como raridade, continuam válidas sem foto. Inosuke ainda não tem um retrato validado na biblioteca: a ausência na captura enviada pelo usuário não era uma tentativa de carregar uma imagem quebrada.

**Toda descrição de miniatura/galeria enviada ao Discord é apenas `.`**, inclusive banners, unidades, itens, ícones, mapas e resultados. O botão ALT pertence ao cliente do Discord; seu conteúdo não inclui relatos do chat nem detalhes de pesquisa. Ícones inline/de botão usam nomes técnicos neutros, exigidos pelo Discord. A origem completa continua apenas no registro de mídia. Nomes públicos dos arquivos de reconhecimento são neutros. Retratos pequenos ficam em miniatura, com ampliação ao clicar; arquivos maiores podem aparecer em destaque.

Nas perguntas de raridade, um retrato só aparece antes da resposta se o manifesto o marca explicitamente como `rarity_safe`. As 15 imagens com moldura azul ficam ocultas nesse contexto até o resultado. A ausência desse campo também oculta a imagem: uma nova imagem não é considerada segura por padrão.

Em evolução, o enunciado pode mostrar a unidade base e o resultado só mostra a forma evoluída quando há uma imagem correspondente. A imagem base nunca substitui uma evolução ausente. Identificação de mundos e alimentos mantém as imagens ocultas antes do resultado, conforme o tipo de pergunta.

Recortes determinísticos removem nomes, rótulos de raridade e taxas que poderiam entregar a resposta. Não há geração de pixels por IA. Perguntas de mecânica podem funcionar sem ilustração; reconhecimentos visuais exigem imagem. Visuais atuais da wiki não alteram fatos do Release nem comprovam aparência de julho de 2022.

Os arquivos usam URLs públicas do repositório. O bot não precisa consultar o Fandom durante uma partida e não depende da validade do link temporário do anexo do Discord. Não exige permissão de anexar arquivos. O envio usa `AllowedMentions.none()`, e nomes exibidos são escapados para preservar a leitura do placar.

As prévias abaixo foram renderizadas localmente a partir dos componentes serializados. São estudos de composição; o Discord aplica a renderização nativa.

- [Prévia em tela grande](interface-desktop.png)
- [Prévia em celular](interface-mobile.png)

## Contratos verificados

- Components V2 usa a flag `IS_COMPONENTS_V2` (`32768`) e não mistura `content`/`embeds` nas mensagens dos painéis.
- Limite de **40 componentes** por mensagem e **4.000 caracteres de exibição**; nenhuma pergunta do banco excede os limites nas telas de pergunta e resultado.
- IDs de controles únicos por mensagem, até cinco botões por Action Row; cada menu ocupa sua própria linha.
- Interações recebem resposta ou deferimento antes de operações de atualização; edições usam a mensagem normal do bot, sem depender de um token de interação antigo para sessões longas.
- Edições de relógio e controles são serializadas. Erros de atualização não alongam o prazo; o primeiro acerto continua sendo decidido antes de qualquer await.
- Atualizações de controle com o mesmo estado são agrupadas: quarenta cliques repetidos de pausa não geram quarenta edições. Um erro de edição não marca o estado como publicado, então um novo clique pode recuperar o painel.
- Casos de teste incluem tempo congelado além do prazo original, ciclos de pausa, resposta atrasada da pausa, acerto simultâneo, exclusão de painel, cliques concorrentes, controle de acesso, expiração, falhas do Discord e pontuação transacional.
- Hashes dos arquivos e política de origem são conferidos. Testes da seleção de mídia protegem identificação de unidades, raridades e formas evoluídas.
- Casos específicos verificam Tanjiro sem moldura na pergunta de raridade, Uraraka com imagem e metadados neutros e a exclusão de reconhecimento sem retrato.
- Testes de alternativas incluem 40 acertos simultâneos com um único crédito, tentativa única, ordem preservada na pausa, cliques antigos, respostas tardias, falha no aviso privado e bloqueio de atalhos pelo chat.
- Testes de abuso incluem limite de chat sem bloquear outro jogador, tentativas preservadas na pausa e limpas na pergunta seguinte, 40 consultas repetidas com uma única leitura do banco, abertura concorrente em vários canais e pausa abandonada antes/depois de um acerto. Todos os cartões do banco são conferidos sem emojis Unicode, com cores neutras em perguntas de raridade e com os ícones originais registrados.

## Referências oficiais

- [Visão geral de Components](https://docs.discord.com/developers/components/overview)
- [Componentes: Text Display, Container, Media Gallery, Action Row, Button e String Select](https://docs.discord.com/developers/components/reference)
- [Interações: resposta inicial em 3 segundos e tokens de 15 minutos](https://docs.discord.com/developers/interactions/receiving-and-responding)
- [Formatação Markdown do Discord](https://support.discord.com/hc/en-us/articles/210298617-Markdown-Text-101-Chat-Formatting-Bold-Italic-Underline)
- [discord.py: LayoutView e componentes](https://discordpy.readthedocs.io/en/stable/interactions/api.html#discord.ui.LayoutView)
- [Anime Adventures Wiki](https://animeadventures.fandom.com/wiki/Anime_Adventures_Wiki)
