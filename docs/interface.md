# Interface do quiz

A interface usa **Discord Components V2**, disponíveis em discord.py 2.7.1. A pesquisa foi feita na documentação oficial do Discord e do discord.py. O conteúdo do Release continua no mesmo banco: esta mudança trata da apresentação e dos controles.

## Telas e interação

1. **Painel inicial:** arte original de portal, identidade em turquesa/dourado, título, resumo do pacote, menus de assunto e duração. O anfitrião confirma em **Começar aventura**. O painel expira após dois minutos sem iniciar e libera o canal.
2. **Pergunta:** categoria e número, enunciado com hierarquia visual, raridade quando ela é uma pista, recompensa, barra de tempo e prazo relativo. As respostas continuam abertas no chat.
3. **Resultado:** vencedor ou fim do tempo, resposta comentada, total acumulado quando salvo, placar da sessão, próxima etapa e botão da revisão histórica usada como fonte.
4. **Pausa:** preserva a sessão e o placar; **Retomar** abre o intervalo antes da próxima pergunta. Pedidos de pausa feitos durante uma pergunta aguardam o desfecho, sem congelar o ponto em disputa.
5. **Encerramento:** resumo e botão **Jogar novamente**. Um pedido durante uma pergunta deixa essa pergunta terminar; fora dela, encerra imediatamente.
6. **Ajuda e pontos:** cartões privados para quem clica. Não enviam novas mensagens públicas, não alteram o prazo e não contam como tentativa.

## Escolhas de uso

- Tempo: **30, 45 ou 60 segundos**, com 45 como padrão. Intervalo de 8 segundos entre perguntas.
- Assuntos: **Aventura completa**, **Personagens**, **Mundos e chefes**, **Sistemas do jogo**. A escolha filtra somente o pacote Release antes de embaralhar.
- O anfitrião escolhe opções e inicia. Anfitrião e moderadores com Administrador, Gerenciar Servidor ou Gerenciar Canais podem pausar, retomar e encerrar. Outros jogadores mantêm acesso a respostas, ajuda e placar.
- Uma sessão por canal, inclusive durante a configuração. Dois cliques simultâneos em começar não criam duas partidas.
- Controles antigos não podem modificar uma sessão nova. Ajuda, pontos e revanche têm encaminhamento persistente após reinícios; sessões em andamento não sobrevivem a reinícios.
- Botões de cada pergunta e resultado são aposentados quando o jogo avança. Links das fontes continuam disponíveis.

## Escrita e aparência

Títulos, subtítulos, negrito, texto secundário, separadores e emojis dão hierarquia sem transformar o texto em caracteres Unicode que imitam fontes. A fonte, o fundo e as dimensões finais são definidos pelo cliente Discord e pelo tema do usuário; bots não aplicam CSS próprio às mensagens.

Cores de raridade só aparecem quando a raridade já é uma pista. **Perguntas que pedem a raridade não revelam a resposta pela cor.** A arte de abertura é uma ilustração original gerada para a identidade do quiz, sem personagens nem dados de gameplay; não é uma imagem histórica do jogo de 2022.

A arte usa URL pública estável do próprio repositório. Não exige permissão de anexar arquivos nem dependência adicional de uma hospedagem de imagens. O envio das mensagens usa `AllowedMentions.none()`, e nomes exibidos são escapados para preservar a leitura do placar.

As prévias abaixo foram renderizadas localmente a partir dos componentes serializados. São estudos de composição; o Discord aplica a renderização nativa.

- [Prévia em tela grande](interface-desktop.png)
- [Prévia em celular](interface-mobile.png)

## Contratos verificados

- Components V2 usa a flag `IS_COMPONENTS_V2` (`32768`) e não mistura `content`/`embeds` nas mensagens dos painéis.
- Limite de **40 componentes** por mensagem e **4.000 caracteres de exibição**; nenhuma pergunta do banco excede os limites nas telas de pergunta e resultado.
- IDs de controles únicos por mensagem, até cinco botões por Action Row; cada menu ocupa sua própria linha.
- Interações recebem resposta ou deferimento antes de operações de atualização; edições usam a mensagem normal do bot, sem depender de um token de interação antigo para sessões longas.
- Edições de relógio e controles são serializadas. Erros de atualização não alongam o prazo; o primeiro acerto continua sendo decidido antes de qualquer await.
- Casos de teste incluem pausa/retomada, encerramento com ponto em disputa, cliques concorrentes, controle de acesso, painéis antigos, expiração, ajuda privada, respostas tardias, falhas do Discord e pontuação transacional.

## Referências oficiais

- [Visão geral de Components](https://docs.discord.com/developers/components/overview)
- [Componentes: Text Display, Container, Media Gallery, Action Row, Button e String Select](https://docs.discord.com/developers/components/reference)
- [Interações: resposta inicial em 3 segundos e tokens de 15 minutos](https://docs.discord.com/developers/interactions/receiving-and-responding)
- [Formatação Markdown do Discord](https://support.discord.com/hc/en-us/articles/210298617-Markdown-Text-101-Chat-Formatting-Bold-Italic-Underline)
- [discord.py: LayoutView e componentes](https://discordpy.readthedocs.io/en/stable/interactions/api.html#discord.ui.LayoutView)
