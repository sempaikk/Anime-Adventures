# Fechamento da tier list — 22/10/2026

## O que foi concluído

Esta revisão fecha o catálogo ativo, a colaboração com retratos e os caminhos
de recuperação. Mantém somente `/tierlist` e `/chatglobal`, sem novos comandos
ou configuração obrigatória. O chat global continua em breve.

- A mensagem permanente continua com um PNG, sem legenda, botões ou rodapé técnico.
  Enquetes temporárias aparecem no mesmo canal enquanto há uma proposta.
- O tópico reúne enquetes, resultados e histórico. Membros usam
  Sugerir imagem, Meus envios e Como funciona. Respostas pessoais são privadas.
- Administradores preparam ou conferem o próprio painel. Revisão global,
  correções, diagnóstico e testes continuam exclusivos do dono do aplicativo.
- O único TXT público é **retratos-pendentes.txt**, uma solicitação de fotos
  das formas exatas; não contém posições nem classificação por força.
  Aprovações válidas reduzem a lista; pendência/rejeição não a reduzem.
  Restauração pode recolocar um nome. O anexo desaparece ao completar as fotos.

## Catálogo e imagens

O catálogo histórico conserva **555 identidades**. A política explícita de
disponibilidade exclui **26 formas** pelo critério do dono de descartar as
silhuetas azuis substitutas, restando **529 formas ativas**. Há **458 retratos
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

Os 458 arquivos ativos passaram por abertura/verificação e conferência de
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

## Complemento final: interface V2, seis categorias e dois modos

Esta é a decisão final do dono e substitui a grade intermediária por função.
Cada modo tem **META Hill/Hybrid, META Ground, META Support, Good Hill/Hybrid,
Good Ground e Good Support**. Um PNG reúne Infinite e Casual em seções
identificadas. Cada forma ocupa uma única categoria por modo. As listas são
independentes, com ordem esquerda→direita e linhas expansíveis.

A migração preserva snapshots/votos e cancela propostas incompatíveis; não
adivinha colocação/função a partir de letras ou da antiga grade. Reversões
respeitam modo/versão e não atravessam formatos incompatíveis. A retenção
sempre conserva a versão atual de cada modo, mesmo com inatividade prolongada.

O ponto de partida é a revisão 46773 da Wiki de 18/04/2025, confirmada na
API em 22/10/2026: **71 formas em Infinite e 76 em Casual**. A auditoria
identificou todas as 151 entradas: 147 ativas e quatro ocorrências de formas
retiradas. Não restam nomes pendentes nessa fonte. A página ainda alerta
para possível imprecisão. A comprovação de identidades não valida o balanceamento.

Os antigos nomes foram vinculados pelos IDs nas revisões 33578 e 43960 do
módulo Names. A leitura de aspas simples recuperou seis formas; Ice Shaper
tem a silhueta azul e fica retirado. Cinco novos retratos válidos foram
incluídos. A auditoria detalhada está em tierlist-catalog-audit.md.

A base inicial e as correções administrativas não entram no histórico
público. A atualização remove somente cópias antigas verificadas, mantendo
os registros internos. A complementação automática só atua numa base inicial
ainda intacta e sem enquete aberta. Decisões da comunidade e correções humanas
são preservadas. Reiniciar não repete a importação nem fabrica votos.

Os cards usam Components V2 com seções, separadores, galerias, arquivos e
controles nativos. O PNG não tem cartão nem rodapé. Ícones originais só são
usados pelo significado, após conferir ID/nome; falha mantém o texto. Modais
usam Labels, upload e seleção de modo na correção. Os dados técnicos ficam
privados. Os anexos V2 são lidos dos componentes mesmo quando a API deixa
Message.attachments vazio; os bytes/hash são conferidos.

- **577 testes automatizados**, incluindo categorias/migração, protocolo V2,
  separação por modo, retenção, referência inicial e pacote de IA com fontes
  reais dentro da mesma cota de entrada. O prompt foi compactado, preservando
  as verificações locais e sem aumentar o orçamento gratuito.
- **20 etapas de verificação**, com a API real em dois espaços privados autorizados
  e identificação local do pacote:
  índice convertido na mesma mensagem, enquete/atalhos, atualização sem
  duplicação, participantes, resultado arquivado, alteração só em Casual, PNG
  editado/baixado, retenção/limpeza após reinício, dez etapas visuais, cinco
  transições de TXT e cartões V2. A nova conferência removeu cópias administrativas
  legadas/V2, preservou auditoria/posições/votos e confirmou o índice sem links técnicos.
  O ensaio adicional identificou o pacote e simulou cancelamento/retomada após
  balanceamento, com resultado no Discord e dados anteriores ao corte rejeitados.
- Estado temporário com votos artificiais identificados, sem Gateway extra,
  chamadas à Groq ou mudanças na classificação oficial. API não reproduz
  aparência nos aplicativos, seleção humana de arquivo ou qualidade dos
  argumentos do jogo. O clique humano continua uma etapa separada.

No ensaio local extremo com 524 formas artificiais em cada modo (1.048
posições visuais), a imagem foi de **5.640.666 bytes**, **1098×11244**, cerca
de **6,61 s**, e o processo atingiu **168,9 MiB**. Cabeu no limite local de
8 MiB por PNG. Isso não mede a hospedagem, outros processos ou concorrência
real de servidores; a base inicial é bem menor.

## O que ainda depende da estreia

O desenvolvimento deste fechamento está concluído. Para ativar a versão,
reinicie o bot na hospedagem e rode Verificação completa nos controles privados.
Os administradores dos outros servidores não precisam repetir `/tierlist`.

Antes de ampliar a divulgação, guarde um backup completo fora da hospedagem e
observe o uso em um a três servidores. As primeiras revisões da base da Wiki exigem propostas
fundamentadas e cinco participantes reais; testes não fabricam essa votação.
Confira os argumentos e os retratos das primeiras formas classificadas. A
comunidade pode completar as 71 fotos ao longo do uso.

Essa etapa comprova o funcionamento nos ambientes exercitados. A qualidade dos
argumentos sobre o jogo, aparência no cliente e carga real continuam sendo
validações de uso, sem novos módulos obrigatórios para lançar o piloto.

## Correção do verificador na hospedagem — 2026.10.22.3

O relatório real da versão 2026.10.22.2 confirmou o pacote, a Groq, os comandos
e a publicação do PNG. A edição seguinte falhou: a mensagem técnica já usava
Components V2, mas aquela chamada ainda enviava texto no campo legado. A API
real reproduziu a recusa com HTTP 400, código 50035. A edição agora usa o mesmo
conversor V2 das demais mensagens. O adaptador de testes também recusa essa
mistura, impedindo que um ensaio local a aceite silenciosamente.

A suíte isolada passa de três para cinco minutos de orçamento total. O processo
filho registra cada teste concluído. No limite, o pai encerra e recolhe o
processo, preserva contagem, falhas e último teste em vez de descartar a saída.
Os registros intermediários são condensados para não esconder os rastros de
erro. Suíte incompleta permanece atenção, ou falha se já houver um erro; não
vira aprovação. Os testes reais continuam após esse limite. Uma falha da API
agora identifica etapa, HTTP e código Discord, sem copiar o corpo da resposta.

O clique humano confirmado pelo dono na hospedagem é evidência própria do
callback de voto. O ensaio por HTTP não o substitui nem usa token de pessoa.

Na versão corrigida, **582 testes isolados passaram**. O mesmo `verify` chamado
pelo painel foi executado com HTTP real no servidor autorizado, banco
temporário e resposta privada simulada: registro dos comandos, tópico privado,
envio/leitura/edição do PNG, dez etapas de personagens, cinco de retratos/TXT,
botões, arquivamento/retomada e limpeza passaram. O pacote foi identificado como
`2026.10.22.3 · 9c7ebe36b61a`. Não houve Gateway adicional, chamada à Groq ou
alteração de posições oficiais. O limite de tempo foi reproduzido com processo
real controlado; contagem parcial e encerramento do filho foram conferidos.
