# Estado vigente — limpeza do pacote

Este documento descreve somente o bot atual. O histórico completo anterior está no [registro da versão .16](https://github.com/sempaikk/Anime-Adventures/blob/34c1e2fec9067bf4657aec36c0bb5878256c6113/CONTINUIDADE.md), preservado no Git.

## Pedido atual

O responsável pediu retirar todo o código, nomes, textos e arquivos de funções que não existem mais no bot, deixando apenas os recursos atuais. O pedido substitui a decisão anterior de manter implementações arquivadas dentro do pacote. Remoção autorizada sem nova confirmação. Dados ativos dos servidores precisam permanecer preservados.

## Funções que permanecem

- /globalchat: consentimento, relay por webhooks, moderação por escopo, privacidade, denúncias e controles privados do dono.
- /setbanner: imagens estáticas separadas, W/M/L originais, recuperação e correção única do histórico em todos os servidores.
- /dailychallenge: só o desafio atual; fonte observada separada de recebimento confirmado, proteção de reinício e de posts apagados.
- Sem encaminhamento automático pelo megafone, IA, perguntas ou dependência do PC. Hash SHA-256 local e recibos por servidor continuam em uso.
- Interface fixa em inglês. Notas públicas em português, só efeitos para players, mensagem nova por atualização e somente no canal oficial. Ícone de jogo uma única vez no painel privado.

## Identidades e configuração preservadas

- Servidor oficial 1554953245204422807. Bot 1561527465657114644.
- Atualizações 1564498826423959652; banners 1564496491635282060; daily 1564497284580773919; chat global 1563614865677885574.
- Fontes: banners 993219350179876874; daily 1326659593199423610.
- DISCORD_TOKEN, SECONDARY_ACCOUNT_TOKEN e DATA_DIR existentes. Não exibir valores, mudar pasta persistente ou pedir reinstalação no PC.
- Primário discord.py 2.7.1; leitor 2.1.0 isolado. Poll 30 s, reemissão de recepção 60 s, páginas de 50. Preservar typing=True para inscrição de guild grande.
- Cache 65 min nos banners e 26 h no daily. Até 10 imagens, 8 MiB/arquivo, 16 MiB/lote, 32 MiB/cache por feed. Só estáticos verificados, sem legendas.
- Cada destino usa seus nonces/recibos; resultado incerto é reconciliado. O reset de W/M/L é autorizado uma vez por banner antigo afetado em todos os destinos, com corte por canal e sem repetir após começar a recriar reações.

## Implementação concluída

- community_bot.py foi reduzido às três funções atuais e aos seus ciclos. Não há mais carregamento de catálogo, análise, painéis ou modos arquivados.
- Infraestrutura compartilhada recebeu nomes genéricos: bot_store, bot_storage, bot_domain, bot_ui, bot_views, bot_style e bot_release. data/build.json substitui o manifesto antigo. Scripts atuais têm nomes genéricos.
- Status usa apenas o ícone clock já registrado, com atribuição em data/status_icon.json; PNGs originais W/M/L permanecem intactos. Arquivos/catálogos/artes e testes de funções retiradas saíram do pacote.
- Banco atual bot.sqlite3. Sob lease que também respeita locks anteriores, uma base antiga é reconhecida pelas tabelas de serviços ativos. Snapshot privado antes da limpeza, cópia verificada e migração dos metadados por esquema; tabelas global_*, banner_* e daily_* são mantidas. Apenas depois da nova cópia verificada o arquivo original é substituído. A cópia anterior fica em DATA_DIR/backups/before-cleanup.sqlite3.
- O texto temporário do chat global é mantido na base viva e removido dos snapshots, conforme a política anterior. Consentimentos, webhooks, nonces, pendências e marcadores de W/M/L não são zerados. Erros de integridade, espaço, colisão de metadados ou várias bases candidatas preservam os originais e interrompem a migração.
- Foram mantidos e portados 221 testes de recursos atuais. Doze testes de migração/backup e um de startup offline ampliam o conjunto para 234. A migração preserva também os registros de moderação global que compartilhavam o esquema anterior; dados de funções retiradas ficam apenas na cópia privada.
- Não houve acesso direto à hospedagem nem mudanças reais no Discord. Site separado intocado. Níveis continuam adiados.

## Arquivo Windows separado

O único pacote histórico de remoção expressamente restaurado pelo dono permanece intacto em downloads/Remover-Python-e-Bot-Windows.zip, SHA-256 d4c68ff5626d5ab46bc48b5c746fdf4065a29441bd924deaa37616a2db0ada29. O alerta original do Defender não foi diagnosticado; não indicar bypass ou classificar como falso positivo. Os antigos instaladores do PC não fazem parte do bot atual.

## Validação da entrega

- Versão 2026.10.27.17; fingerprint c258b79484da3696a14c07f74778ff88baae377d46bbdaa04963022d96966b78; manifesto com 58 arquivos.
- `python -m unittest discover -s tests -v`: 234 testes passaram, incluindo startup sem rede, dados ativos, entrega, privacidade e falhas de migração.
- Ensaio adicional com o esquema real anterior, obtido do Git: 48 tabelas reconhecidas; configurações dos três serviços e metadados preservados na nova base, com estruturas inativas somente no backup privado.
- Preflight passou: arquivos verificados e margem de armazenamento; não leu credenciais nem usou rede. Busca nos arquivos atuais não encontrou os nomes retirados; `git diff --check` passou. Site separado sem alterações.
- Implementação enviada em [95b323f558c1d92a7d9af3dca19f198f3257f3bf](https://github.com/sempaikk/Anime-Adventures/commit/95b323f558c1d92a7d9af3dca19f198f3257f3bf). O [Bot checks desse commit](https://github.com/sempaikk/Anime-Adventures/actions/runs/40623238775) concluiu com sucesso no GitHub; os 234 testes passaram também no Python 3.12 do CI. Registro final de continuidade em commit separado de documentação, sem mudança no manifesto ou runtime.

## Ativação pendente

Parar o processo, atualizar o pacote completo e reiniciar a hospedagem mantendo DATA_DIR e segredos. A migração é automática; não apagar os dados nem repetir os comandos. Verificação local/CI não comprova uma execução real já atualizada. Não foi feito reinício da hospedagem ou alteração direta de mensagens do Discord nesta sessão.
