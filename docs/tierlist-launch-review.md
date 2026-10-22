# Fechamento da tier list — 22/10/2026

## O que foi concluído

Esta revisão fecha o catálogo ativo, a colaboração com retratos e os caminhos
de recuperação. Mantém somente `/tierlist` e `/chatglobal`, sem novos comandos
ou configuração obrigatória. O chat global continua em breve.

- A mensagem permanente continua com um PNG, sem legenda, botões ou rodapé técnico.
  Enquetes temporárias aparecem no mesmo canal enquanto há uma proposta.
- O tópico reúne resultados completos, revisões e histórico. Membros usam
  Sugerir imagem, Meus envios e Como funciona. Respostas pessoais são privadas.
- Administradores preparam ou conferem o próprio painel. Revisão global,
  correções, diagnóstico e testes continuam exclusivos do dono do aplicativo.
- O único TXT público é **retratos-pendentes.txt**, uma solicitação de fotos
  das formas exatas; não contém posições nem classificação por força.
  Aprovações válidas reduzem a lista; pendência/rejeição não a reduzem.
  Restauração pode recolocar um nome. O anexo desaparece ao completar as fotos.

## Catálogo e imagens

O catálogo histórico conserva **549 identidades**. A política explícita de
disponibilidade exclui **25 formas** pelo critério do dono de descartar as
silhuetas azuis substitutas, restando **524 formas ativas**. Há **453 retratos
disponíveis e 71 pendências iniciais**, antes de sugestões aprovadas na hospedagem.

Das exclusões, 23 já estavam entre as pendências anteriores. Gravity Hero tinha
uma foto antiga reaproveitada. A conferência visual final encontrou também
Illusionist (Chrysalis) com o boneco genérico azul, anteriormente contado como
retrato válido; a imagem foi rejeitada e removida dos arquivos ativos. A cor
azul em um personagem normal não determina exclusão. Não usamos essa cor para
classificar automaticamente a disponibilidade de unidades futuras.

A política está em `data/tier_availability.json`. Nem o cache nem uma nova
consulta à wiki reativam esses IDs. Coleta, propostas, revisão de retratos e
reversão respeitam o catálogo ativo. Se uma forma retirada já estiver numa
classificação existente, a migração cria uma revisão auditada e mantém a ordem
relativa das demais; preserva snapshots, votos e histórico anterior. Não cria
posições para preencher a imagem de estreia.

Os 453 arquivos ativos passaram por abertura/verificação e conferência de
transparência não vazia. Isso valida os arquivos, sem comprovar balanceamento
ou substituir a revisão da forma/skin no jogo. Retratos aprovados recebem
conferência de hash; arquivos ausentes/corrompidos não escondem pendências. Uma
restauração recusa predecessor corrompido e preserva a imagem atual. O renderer
reconhece arquivo reparado sem precisar alterar posições.

## Proteções e recuperação revisadas

- Limites de sugestões são verificados antes do download/processamento e ao
  registrar. Arquivos inválidos e duplicados também consomem uma reserva de
  tentativa: seis por pessoa, trinta por servidor e mil na instância em dez
  minutos. A janela fica no banco e sobrevive ao reinício. Os limites anteriores
  de sugestões válidas, conta, tamanho, formato, fila e armazenamento continuam.
- A saída do servidor durante o processamento impede gravar a sugestão. Os
  controles permanecem vinculados ao ator, servidor e tópico corretos.
- O índice apagado é reparado sem substituir a imagem principal. Uma
  conferência após iniciar, e depois periodicamente, encontra exclusões que
  aconteceram durante uma desconexão.
- A confirmação perdida da API reaproveita a mensagem já enviada e atualiza a
  lista para o estado mais recente, sem criar outro índice.
- O ensaio real descobriu que o arquivo de um PATCH que falhou podia estar
  esgotado ao ser reaproveitado num POST. A recuperação agora cria outro fluxo
  de bytes; o teste de regressão reproduz o consumo antes do erro.
- Nonces incluem a identidade persistente do banco. Caso o Discord retenha um
  nonce de mensagem apagada, a entrega tenta uma nova geração uma única vez,
  preservando os bytes e mantendo a proteção contra confirmação perdida.
- Criação das tabelas de entrega fica na inicialização do banco, inclusive em
  ferramentas isoladas. Migrações são transacionais e não apagam o estado.
- Cache da wiki com estrutura inválida usa as referências de reserva sem
  impedir a inicialização. Datas inválidas/futuras do cache são ignoradas para
  não congelar as próximas consultas.

## Evidências da revisão

- **457 testes locais aprovados**, incluindo 34 novos cenários de regressão
  do fechamento; lint de erros Python, formatação e diff conferidos.
- A verificação isolada repete a mesma suíte em três processos sequenciais,
  sem credenciais de produção, `.env` ou rede externa. Não são outros 457
  cenários diferentes: é o caminho de execução usado pela hospedagem.
- **Discord real**, no servidor de teste autorizado: dois comandos e permissão
  padrão de `/tierlist`; índice com três botões; lista 71→70→71 na mesma
  mensagem; reparo após exclusão; confirmação perdida sem duplicação; dez
  mudanças visuais de PNG; cinco transições de retratos/TXT, conferindo os
  arquivos baixados. Usou estado local temporário e nenhuma conexão Gateway
  adicional. A classificação de produção foi preservada.
- O relatório real ficou neste
  [tópico privado de validação](https://discord.com/channels/1561531259484901489/1562852510442586213),
  acessível conforme as permissões do servidor de teste. Artefatos técnicos
  intermediários foram removidos e o tópico foi arquivado.
- O verificador do bot inclui as cinco transições de retratos/TXT para o dono
  repetir o ensaio depois. O clique humano no voto continua sendo uma etapa
  própria; testes por API não se passam por uma conta humana.
- Ensaio local com 524 posições artificiais na mesma linha expansível: PNG de
  **2.749.300 bytes**, **1098×5664**, cerca de **2,47 s** de renderização e pico
  do processo de **87,1 MiB**. Não mede a hospedagem gratuita, clientes móveis
  ou vários servidores concorrentes e não determina uma capacidade garantida.

A chave Groq está somente na hospedagem. Esta rodada direta não fez chamadas
à Groq. A verificação completa, depois de reiniciar a versão atualizada, testa
a resposta real respeitando o orçamento. A validação anterior dessa integração
continua distinta das verificações locais desta revisão.

## Complemento: acompanhamento da próxima enquete

O índice de Votações e histórico distingue relatos aguardando avaliação,
preparação, análise em andamento, proposta pronta, votação aberta e apuração.
Quando existe intervalo a cumprir, mostra a próxima disponibilidade de análise
usando o horário relativo nativo do Discord. Uma enquete continua condicionada
a uma proposta fundamentada; a contagem não promete uma votação por hora.
O prazo usa os mesmos registros e regras do motor de análise, permanece após
reiniciar e não exige novas chamadas de IA nem edições por segundo.

- **479 testes locais aprovados**, incluindo 22 cenários novos de prazo,
  reinício, cotas, cancelamento e atualização do índice.
- **11 verificações na API real do Discord**, no tópico privado de teste:
  estados entregues/editados na mesma mensagem, componentes e anexo preservados,
  contagem estável sem PATCH a cada passagem de tempo, reabertura do banco,
  proposta em fila, início/fim de votação e pausa sem horário prometido.
- Estado temporário, sem Gateway adicional, chamadas à Groq ou posições/votos
  oficiais alterados. A API confirma a entrega dos horários relativos, sem
  reproduzir a tela de uma conta humana.

## Complemento: enquete visível no canal

A enquete aberta aparece no canal da tier list para facilitar a participação.
Mostra a mudança proposta, condições, ressalva, fontes, prazo e participantes,
com atalhos para a imagem e o histórico. As escolhas continuam ocultas até
encerrar. A confirmação do voto é privada e informa o prazo para trocar.
Resultados encerrados têm título e cor próprios. Não há ping coletivo nem
configuração obrigatória adicional.

Após a apuração, a proposta completa e a contagem final são guardadas no tópico.
O aviso do canal permanece por dois minutos; antes de apagá-lo, o bot confirma
o resultado salvo e a identidade da própria mensagem. Falha, acesso ausente,
arquivo removido por moderação ou cópia antiga ainda sem edição final preservam
o aviso encerrado. Reinícios retomam a limpeza sem renovar o prazo. O dono
acompanha pendências globais no diagnóstico privado; o ADM recebe orientação
do próprio servidor em Conferir painel. Votações antigas abertas no tópico
terminam no local original.

A apuração também consulta a API antes de aceitar uma cópia como disponível.
Exclusão ocorrida sem evento Gateway não permite aplicar a mudança usando uma
mensagem inexistente. Se a API estiver incerta, a decisão é adiada, preservando
as posições e o prazo já encerrado. A organização dessa entrega ficou em
`tier_delivery.py`; os registros de votos e prazos existentes são preservados.

- **503 testes automatizados**, incluindo 24 cenários novos de publicação,
  limpeza, moderação, API incerta, reinício e visão de membros. O índice com
  votação aberta, aprovação anterior, revisão, manutenção e todos os atalhos
  foi conferido no limite de mensagem do Discord.
- **Nove verificações pela API real**, usando dois espaços privados no servidor
  autorizado: enquete, atalhos, repetição sem duplicar, participantes ocultando
  escolhas, arquivo completo, PNG original editado e comparado ao download,
  espera de dois minutos, reabertura do banco e limpeza idempotente.
- O ensaio usou votos e posições artificiais apenas no banco temporário, sem
  Gateway adicional, chamadas à Groq ou alteração da classificação oficial.
  Não reproduz a tela ou cliques de uma conta humana.
- O [resultado privado de demonstração](https://discord.com/channels/1561531259484901489/1562890170913792051)
  permanece arquivado para o dono conferir conforme as permissões do Discord.

## Complemento: interface V2 e classificação por função

A grade agora tem **Meta, Damage, Support, Buff e Farm**. Cada forma continua
com um único registro: Meta também aparece na função principal. As funções
não são notas de força. O renderer preserva ordem, pixels originais e linhas
expansíveis. O ensaio visual de dez etapas inclui as quatro funções, destaque
Meta, mudança de ordem, retirada de Meta e troca/restauração de retrato.

A migração cria uma fronteira auditada quando há notas antigas: preserva os
snapshots, votos, painéis e histórico; cancela propostas incompatíveis e
aguarda decisões por função. Não converte S/A/B/C/D/E em papéis do time.
Reinícios não repetem a operação e uma reversão não restaura o formato antigo.

Enquetes, resultados, índice, ajuda, confirmações, controles privados e
verificação usam **Components V2**, com seções, separadores, retratos, botões,
galerias e anexos nativos. O PNG principal continua sem cartão nem rodapé.
Títulos/negrito/citações organizam o texto; o glossário opcional pode ficar
em spoiler. Informações necessárias ao voto ficam visíveis. Os ícones da
wiki são verificados na aplicação e usados pelo significado. Sem verificação,
o bot mantém os rótulos em texto. Formulários usam Labels e FileUpload e
explicam destino e acompanhamento das sugestões.

- **534 testes automatizados aprovados**, incluindo 21 novos cenários de
  protocolo/UI e dez de categorias, projeção e migração.
- **13 verificações na API real** em dois espaços privados autorizados:
  migração do índice na mesma mensagem, enquete, botões/atalhos, participantes,
  arquivo do resultado, edição/download do PNG, retenção/limpeza após reinício,
  dez etapas visuais, cinco transições de TXT e cartões do dono/ajuda.
- O ensaio de API usa a nova grade, com uma proposta Meta/Buff artificial
  apenas em banco temporário. Não altera o estado oficial, não abre Gateway e
  não faz chamadas à Groq. Os anexos V2 são lidos dos componentes, inclusive
  quando a API deixa Message.attachments vazio; os bytes/hash são conferidos.
- A entrega pela API não reproduz a tela do aplicativo nem um envio humano
  de formulário. Clique humano, aparência no celular e seleção de arquivos
  continuam distinguíveis das verificações de protocolo.

A importação inicial de posições da Wiki e a divisão por modo continuam uma
proposta a definir; esta revisão não apresenta posições da Wiki como votos
da comunidade. A página coletada avisa que sua lista pode estar imprecisa.

## O que ainda depende da estreia

O desenvolvimento deste fechamento está concluído. Para ativar a versão,
reinicie o bot na hospedagem e rode Verificação completa nos controles privados.
Os administradores dos outros servidores não precisam repetir `/tierlist`.

Antes de ampliar a divulgação, guarde um backup completo fora da hospedagem e
observe o uso em um a três servidores. As primeiras posições exigem propostas
fundamentadas e cinco participantes reais; testes não fabricam essa votação.
Confira os argumentos e os retratos das primeiras formas classificadas. A
comunidade pode completar as 71 fotos ao longo do uso.

Essa etapa comprova o funcionamento nos ambientes exercitados. A qualidade dos
argumentos sobre o jogo, aparência no cliente e carga real continuam sendo
validações de uso, sem novos módulos obrigatórios para lançar o piloto.
