# Chat global

## Instalação

1. Ative Message Content Intent no Developer Portal e atualize/reinicie o bot.
2. Em cada servidor, conceda ao bot Ver canal, Enviar mensagens, Ler histórico,
   Anexar arquivos e Gerenciar webhooks no canal escolhido.
3. Com Administrador ou Gerenciar servidor, use `/chatglobal` e Ativar neste canal.
4. Cada participante abre Participar e confirma. Depois escreve normalmente.

Há um canal por servidor. Canais com restrição de idade, tópicos e o canal da tier
list não podem ser escolhidos. O administrador pode pausar, retomar, conferir ou
trocar a conexão. Pausas não importam o que foi escrito durante a pausa. Usar o
comando novamente confere o webhook e repara o painel, sem criar cópias repetidas.
Configurações e botões públicos sobrevivem a reinícios; controles privados antigos
podem vencer, bastando reabrir o comando.

## Participação e aparência

A confirmação é por conta para toda a rede, incluindo servidores futuros.
Só canais globais ativados retransmitem mensagens. Conversas privadas e outros
canais não entram nesse relay. Não há importação de histórico anterior à
ativação/confirmação. A pessoa pode confirmar uma primeira mensagem pelo aviso
correspondente; isso não autoriza outras mensagens anteriores.

A original nunca é apagada para retransmitir. As cópias mostram nome, username,
avatar e servidor de origem. APP/BOT é uma identificação obrigatória do Discord;
o bot não se passa por uma conta humana. `[Owner]` usa o ID do responsável pelo
aplicativo; `[Tester]` usa `1401953040004550858`. São etiquetas de apresentação,
não cargos nem permissões. Prefixos iguais nos apelidos não concedem a etiqueta.
As etiquetas aparecem nas cópias, não alteram a original nem os cargos do membro.

## Compatibilidade

| Recurso | Comportamento |
| --- | --- |
| Texto, negrito, itálico, spoiler, código e links | Preservados em textos comuns; textos longos são divididos e a formatação pode atravessar partes. |
| Imagens, GIF, vídeo, áudio, PDF e TXT | Baixados do CDN do Discord e reenviados como arquivos, respeitando o limite de cada destino. |
| Spoiler de arquivo | Mantido. |
| Figurinhas PNG/APNG/GIF | Enviadas como imagens; Lottie é identificado por nome. |
| Emojis personalizados | A referência é preservada; renderização depende do Discord e disponibilidade do emoji. |
| Responder a mensagem compartilhada | Inclui citação ou link local conhecido, sem citar quem não compartilhou. |
| Menções | Convertidas em nomes; cópias não pingam pessoas, cargos ou everyone. |
| Edição/exclusão | Sincronização por até 30 dias enquanto os canais e o webhook estiverem acessíveis. |
| Reações, enquetes nativas, digitação, voz e tela | Permanecem locais; canais não são unidos nativamente. |

Arquivos executáveis, scripts, SVG e links externos usados como downloads não
são aceitos. Links no texto continuam sendo links. Um destino sem capacidade
para um anexo recebe uma indicação em vez de um arquivo incompleto.

## Controles e moderação

Meus envios é privado e mostra até cinco envios recentes e suas entregas. A pessoa
pode remover suas cópias, sem apagar a original. Parar de participar interrompe
novos envios em toda a rede e cancela os ainda não entregues; não promete desfazer
uma requisição que o Discord já esteja processando. Cópias anteriores continuam
disponíveis até exclusão pela original ou solicitação de remoção.

Denunciar recebe link/ID de uma mensagem conhecida neste chat e motivo. ADMs veem
denúncias locais e podem bloquear/desbloquear pessoas no próprio servidor. O dono
vê denúncias da rede e pode bloquear pessoas/servidores ou remover cópias na rede.
Permissões e identidade são revalidadas nas ações; o formulário não libera acesso
por ter sido aberto anteriormente. Uma cópia apagada pela moderação local não é
recriada em edições futuras da original.

Contas com menos de sete dias não participam. Envios têm limite de seis mensagens
por dez segundos por pessoa na rede, além de controle de repetição e denúncias.
Essas proteções reduzem abuso; não substituem a moderação humana do conteúdo.

## Retenção e recursos

Texto usado pela fila expira uma hora após o envio/edição, com limpeza periódica.
Anexos temporários sem entrega pendente são removidos na limpeza seguinte, com
uma margem mínima de 60 segundos. A limpeza preserva downloads e uploads em curso.
Pendências expiram após uma hora. IDs das originais/cópias e denúncias expiram em
30 dias; configurações e confirmações permanecem até alteração/saída.

O histórico visível fica no Discord e não é apagado por essa limpeza. Backups
locais preservam configurações e IDs, mas não o texto temporário nem o cache do
chat. Retratos da tier list têm armazenamento e política próprios.

Cache de anexos: 256 MiB, reserva para downloads concorrentes e espaço livre
mínimo. Novos envios também param por pressão no banco (128 MiB de páginas em
uso) ou 50 mil entregas pendentes. A hospedagem precisa ter espaço para o restante
do bot, suas dependências e retratos. Não existe garantia de sustentar milhares
de servidores na hospedagem gratuita: filas, rede e limites da API determinam a
capacidade real. O chat não utiliza Groq/IA ou uma API paga.

## Reinício e confirmação incerta

Recibos são persistidos após cada parte. Na volta, o bot verifica gradualmente
mensagens recentes da última hora e alterações de originais conhecidas, sem
importar conversas anteriores à confirmação. Revalida acesso e origem antes de
publicar; sair do servidor remove a configuração e credenciais locais do webhook.

Se a publicação chegou ao Discord mas a resposta se perdeu, o bot tenta
identificar aquela cópia antes de continuar. Uma entrega ambígua termina sem
reenviar às cegas, reduzindo duplicações. Meus envios mostra pendências/falhas.
O relay não promete entrega exatamente uma vez em toda falha possível.

## Validação

`python -m unittest discover -s tests -p 'test_global*.py' -v` usa bancos e arquivos
temporários, simula servidores, testa percursos de membro/ADM/dono, mídia, abuso,
perda de resposta, reinício, retenção e permissões. A Verificação completa do dono
também inclui esses testes e confere os dois comandos registrados no Discord.
Os testes da tier list continuam independentes das conversas reais do chat.

Testes simulados não comprovam permissões reais de webhook, legibilidade do
cliente ou conectividade entre dois servidores reais. Esses resultados devem ser
identificados separadamente no relatório de validação da versão.

Referências: [webhooks](https://docs.discord.com/developers/resources/webhook),
[conteúdo de mensagens](https://docs.discord.com/developers/resources/message),
[permissões](https://docs.discord.com/developers/topics/permissions).
