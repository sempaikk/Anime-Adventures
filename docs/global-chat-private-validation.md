# Chat global privado — 23/10/2026

Versão `2026.10.23.1`, identificação `d2dec285fa92`, 107 arquivos conferidos.

## Comportamento entregue

- A configuração é privada para ADMs. Funções da rede continuam exclusivas do dono.
- `/chatglobal` também abre controles pessoais privados para membros, sem liberar
  configuração, bloqueios administrativos ou funções do dono.
- O primeiro envio de uma pessoa ainda não participante gera uma única tentativa
  de convite por DM. O registro persiste entre servidores e reinícios, incluindo
  recusa, falha de entrega e DMs bloqueadas. Não há resposta pública de convite.
- O convite é removido após aceitar/recusar. O aceite pelo comando também remove
  uma DM pendente. Não há compartilhamento retroativo da primeira mensagem.
- DMs bloqueadas têm alternativa pelo comando. Erros de envio também são privados.
- Cópias novas mostram `Nome`, `Nome [Owner]` ou `Nome [Tester]`, sem acrescentar
  username ou servidor. Origem e IDs permanecem internos para moderação.
- Avisos públicos anteriores são retirados gradualmente, após conferir autor,
  componentes e ausência de webhook. Canais pausados também são migrados.
- Nomes de cópias antigas já publicadas não são reescritos: a API não permite
  trocar o username de uma mensagem de webhook existente. Elas são preservadas
  para manter a conversa e seus IDs. Novas publicações usam o formato atualizado,
  inclusive quando vierem de uma fila gravada pela versão anterior.

## Automação e segurança

A suíte completa passou em **644 testes**, incluindo **60 cenários de chat**.
O perfil isolado usado pela verificação da hospedagem passou em **395 testes**
neste ambiente, com credenciais removidas e rede externa bloqueada.
Os novos casos cobrem convite único durante rajadas, DM bloqueada com alternativa
privada, recusa, botões forjados por outra conta/canal/mensagem, perda de acesso,
pausa durante consulta de membro, cancelamento durante envio da DM, confirmação
em paralelo, expiração do convite e limpeza paginada preservando conversas.

O consentimento permanece global e as regras da tier list não mudaram. A primeira
mensagem fica local; só mensagens posteriores ao aceite entram na rede. Os botões
privados da DM sobrevivem ao reinício, com identidade e acesso revalidados.

## Discord real

Foram usados dois canais privados temporários no servidor autorizado, token do
próprio bot, banco temporário e nenhuma conexão Gateway adicional. Passaram nove
conferências: permissões, ativação sem painel público, limpeza seletiva de aviso
antigo, envio e remoção de convite real por DM, texto/Markdown com `SIMULAÇÃO
[Owner]`, edição no mesmo ID, imagem spoiler e MP4 com bytes idênticos, exclusão
sincronizada e limpeza local preservando o histórico.

Os dois canais foram removidos ao terminar. A DM de teste também foi removida.
Nenhum consentimento ou ranking de produção foi alterado. O aceite do ensaio foi
simulado em estado temporário; ele não comprova um clique humano real no cliente.
Os dois destinos pertencem a um servidor físico: conectividade entre dois
servidores físicos continua sendo uma validação de uso após a atualização.

## Atualização

Atualizar os arquivos e reiniciar a hospedagem carrega a versão nova, sincroniza
o acesso ao comando e inicia a remoção dos avisos antigos. Canais configurados e
confirmações anteriores são preservados; ADMs não precisam configurar novamente.
Se um servidor tiver restringido `/chatglobal` manualmente nas configurações de
integração, a administração precisará permitir seu uso pelos membros para que
eles possam abrir os controles pessoais privados.
