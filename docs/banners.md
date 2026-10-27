# Banners e desafio diário

Estado vigente definido pelo responsável em 26/10/2026. Esta entrega pertence somente ao bot; o site continua pausado por tempo indeterminado.

## Origem e destino

| Comando | Origem autorizada | Destino |
| --- | --- | --- |
| `/setbanner` | `993219350179876874` | canal onde um administrador executa o comando |
| `/dailychallenge` | `1326659593199423610` | canal onde um administrador executa o comando |

Cada servidor define um destino independente para cada feed. Os comandos de configuração exigem Gerenciar servidor ou Administrador, conferem novamente a permissão ao executar e respondem em particular. **Stop receiving** desativa somente aquele feed naquele servidor. Para trocar, execute o comando no novo canal. O bot precisa de Ver canal, Enviar mensagens, Anexar arquivos e Ler histórico. Não há argumento de ID do destino.

**Publicações dos dois feeds contêm somente arquivos de imagem estática**, sem legenda, texto, nome do autor, URL, embed, menção ou botão. São aceitos PNG, JPEG e WebP reais, validados pelo conteúdo. GIF, inclusive estático, APNG/WebP animado, vídeo e texto são rejeitados. O texto escrito por participantes no chat global permanece intacto; as regras de anexos desse chat são separadas.

**A partir da .7, cada imagem de banner é uma mensagem separada, com reações W/M/L independentes.** O desafio diário mantém o formato atual e não recebe essas reações. As reações são controles nativos do Discord; não há legenda, painel de votação ou placar adicional. O primeiro contador inclui a reação inicial do próprio bot, como na referência enviada. O usuário pode usar as reações nativas normalmente; não foi pedido um sistema que limite uma opção por conta.

## Emojis originais e banners antigos

O responsável forneceu três PNGs RGBA 40×40 em `Nova pasta.zip`. Os bytes originais ficam em `assets/banner-votes/`, verificados por SHA-256 em `data/banner_votes.json` e no manifesto da versão. Foram copiados sem recortar, recolorir ou redesenhar. Na primeira inicialização com banners configurados, o bot registra/reutiliza esses três emojis no próprio aplicativo. A partir da .8, seus nomes são **win, mid e lose**, sem sufixos. Emojis já cadastrados com hash são renomeados no mesmo ID, preservando as reações existentes. A associação do hash ao ID persiste no banco antes da renomeação; uma confirmação perdida é recuperada sem recriar o emoji. Cadastros novos usam o identificador técnico somente até concluir essa etapa. Não ocupa vagas de emoji dos servidores nem depende de Nitro ou software no PC. A documentação oficial permite emojis do aplicativo sem Use External Emojis: [Application-owned emoji](https://docs.discord.com/developers/resources/emoji#emoji-object-applicationowned-emoji).

Além das permissões existentes, o bot precisa de **Adicionar reações** para iniciar W/M/L. Ler histórico também é necessário, como já era para os feeds. Uma falha de cadastro/permissão/reação não interrompe nem republica as imagens. O diagnóstico privado do comando informa a situação e o progresso do histórico.

A .9 confirma os nomes por uma nova consulta ao registro de emojis do Discord, depois da renomeação. Só informa **Discord-confirmed names: win, mid, lose** após conferir os três IDs; se o Discord ainda devolver outro nome, mostra os nomes reportados e tenta novamente sem interromper as imagens. Na primeira configuração bem-sucedida desta correção, reabre uma única vez a varredura do histórico para conferir reações antigas. Quando o nome antigo estiver presente, retira e recoloca **somente a própria reação do bot**, no mesmo ID e com o nome atual. Nunca limpa as reações do emoji nem remove votos dos membros. Confirmação perdida conserva o cursor para restaurar a própria reação na próxima tentativa. A mudança visível no cliente real ainda precisa ser conferida depois de carregar a versão.

O trabalho de reações roda separado a cada dez segundos. Primeiro cuida dos novos banners confirmados; depois confere um canal do histórico por ciclo, em páginas de até vinte mensagens e até três banners por etapa. O cursor persiste no SQLite e a leitura continua após reiniciar. **Não há corte de idade para o histórico acessível**: só verifica autoria do próprio bot, ausência de webhook e nomes reconhecidos dos anexos. Não guarda textos ou identidades/votos dos membros. Mensagens antigas permanecem no mesmo lugar/horário; reações já presentes do próprio bot são preservadas. Arquivos, mensagens alheias e conversas não são alterados.

Em mensagens antigas que agrupavam várias imagens, há um W/M/L para o conjunto; não é possível reagir separadamente a anexos da mesma mensagem sem reenviá-los. O responsável foi informado dessa diferença. Os novos banners são enviados separados. Se banner e daily compartilham um canal, arquivos antigos com o mesmo padrão não são classificados por suposição; o envio novo e seus recibos continuam identificados. Mensagem apagada não é recriada, e um limite de reações em uma mensagem é registrado sem bloquear o restante do histórico.

## Credenciais e instalação

- **`SECONDARY_ACCOUNT_TOKEN`** é o nome vigente do segredo da conta leitora, já renomeado pelo responsável no painel da hospedagem. `BANNER_READER_TOKEN` fica somente como alternativa de compatibilidade, com prioridade para o nome novo. Não solicitar o valor pela conversa.
- `DISCORD_TOKEN` continua sendo o token do bot que publica/responde. `GROQ_API_KEY` continua sendo a chave da IA; não participa da retransmissão de imagens.
- Cadastrar como **Segredo** no painel do Bot-Hosting.net. `.env` privado é alternativa. **`.env.example` é versionado e nunca deve conter valores reais.** Não substituir os segredos existentes nem o `DATA_DIR` atual.
- Atualizar os arquivos a partir da main e reiniciar a instância existente com Python 3.12 e `bot.py`. Somente cadastrar o segredo não instala a atualização.
- Na primeira inicialização habilitada, `banner_reader.py` prepara `discord.py-self==2.1.0` em `DATA_DIR/.banner-reader-venv`. Precisa de acesso ao PyPI e suporte a venv/pip; a preparação pode levar alguns minutos. A instalação isolada medida nesta sessão ocupou cerca de 80 MiB, sem incluir isso como garantia para outros sistemas.
- O processo principal permanece com `discord.py==2.7.1`. O segredo da conta é passado por stdin, fora dos argumentos do processo. Os segredos do bot/Groq não entram no ambiente do subprocesso; logs privados do cliente não são repassados.
- Automação de conta comum é self-bot, proibida pelos termos do Discord e sujeita a suspensão, como explicado ao responsável. Não tentar ultrapassar permissões ou resolver CAPTCHA por evasão. Uma verificação exigida pelo Discord interrompe a autenticação; o responsável precisa conferir a conta no aplicativo oficial.

A conta atua como leitora e **o bot publica com a própria identidade**. O bot não herda permissão para entrar ou ler o servidor de origem. A conexão da conta pode receber metadados de outras áreas conforme o protocolo; o código vigente processa somente as duas origens de imagens autorizadas. Não afirmar que o token fica limitado a elas. O leitor não envia mensagens, reações ou comandos pela conta.

## Entrega, cache e limites

- `game_sources.py` centraliza as origens. O leitor ativo acompanha somente criação/edição de imagens nas duas origens; a captura de Questões está encerrada. `banner_relay.py` mantém tabelas separadas `banner_*` e `daily_*` no SQLite do bot.
- Ao conectar, procura a última imagem recente em no máximo dez mensagens por feed. Um destino novo recebe a mais recente disponível em cache; depois recebe as novas imagens. Não prometer atraso zero: rede, disponibilidade e limites do Discord afetam a entrega.
- Configurações e recibos sobrevivem a reinícios. Repetir o comando não duplica uma imagem já confirmada. Trocar/desativar cancela trabalhos não enviados e conserva recibos confirmados ou incertos enquanto recentes.
- A .7 mantém recibos individuais por mensagem de origem, hash da imagem e destino. Alterar outra imagem ou reordenar anexos não republica uma imagem já confirmada da mesma publicação. Reinício no meio do envio reconcilia cada imagem; confirmação perdida não gera reenvio cego. Lotes antigos confirmados/incertos não são transformados em novos uploads na migração. Recibos individuais seguem a janela dos banners; o cursor histórico de reações é separado.
- Até dez imagens, 8 MiB por arquivo, 16 MiB por conjunto, 32 MiB de cache e até 64 conjuntos recentes por feed. Até 20 milhões de pixels e dimensão máxima de 8.192 pixels. O limite de upload do servidor também é conferido. Os bytes aprovados são mantidos, sem reconstruir artes ou cortar imagens.
- Cache/recibos expiram em 65 minutos para banners e 26 horas para desafios; configurações persistem. Essas expirações não se aplicam ao histórico de Questões.
- Nonce estável com enforce_nonce e reconciliação de respostas incertas pelo próprio autor e nonce/nome dos anexos. Não reenviar cegamente uma entrega desconhecida. Se não puder confirmar, aquele conjunto pode ficar sem entrega, em vez de gerar duplicação; o estado aparece na resposta privada. Imagens seguintes são independentes.
- A cota de disco considera o projeto, dependências, cache e backups, com base nos 512 MB informados pelo responsável. Essa medida local não substitui o painel do provedor. Armazenamento crítico pausa novos anexos; o original é preservado.

## Conhecimento e testes

O recurso de perguntas foi cancelado em 27/10/2026. O processo normal não coleta Questões nem armazena conhecimento/abre conexão com o PC. Banners e desafios dependem apenas da hospedagem.

Os testes usam bancos temporários, imagens artificiais e APIs simuladas. A importação isolada da biblioteca foi conferida sem login. O responsável confirmou a entrega real dos banners; painel/relatório posteriores confirmam também recibos do desafio diário. Capturas dos tooltips confirmam as três reações reais do bot. O relatório privado posterior confirma a .8 íntegra, W/M/L pronto e 37 mensagens históricas conferidas, mas os nomes antigos continuaram aparecendo no cliente. Isso não comprova a causa exata do nome persistente; a .9 adiciona consulta independente e atualização da própria reação antiga. Não atribuir automaticamente à atualização incorreta do responsável ou ao cache sem evidência. Evidências estão em `CONTINUIDADE.md`.

Na revisão `2026.10.27.3`, cada feed tem seu próprio ciclo de entrega. Queda do leitor compartilhado afeta o estado dos dois feeds; falta de acesso a uma origem permanece individual. Excluir um destino desativa só aquele feed. O dono confere destinos, estado de origem e último recibo recente em **Bot status**, privado. [Servidor central e testes privados](community-server.md).

## Correção do recebimento em 27/10/2026

A biblioteca 2.1.0 documenta que servidores com mais de 75 mil membros precisam de `typing=True` para inscrição. O código anterior usava todos os recursos como `False`, cancelando a inscrição de eventos. A chamada foi corrigida, mantendo membros/atividades/tópicos desligados. Isso não exige abrir Discord no PC. O leitor também confere a imagem recente a cada 30 segundos em até 50 mensagens, respeitando retenção e limites da API. Uma assinatura CDN renovada não é uma imagem nova; deduplicação permanece antes da emissão e nos recibos do bot.

Estado de origem é separado para banner e desafio; falha numa não deve mascarar a outra. Ao configurar o desafio, a imagem recente disponível pode ser entregue imediatamente, sem esperar o próximo dia. Se não houver imagem dentro da janela de 26 horas, aguarda a próxima publicação. Logs/estado não comprovam entrega real sem conferir o canal de destino após a atualização.
