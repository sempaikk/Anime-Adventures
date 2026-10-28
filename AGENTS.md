# Escopo atual

Leia CONTINUIDADE.md, confira git status e origin/main antes de editar. Preserve trabalho pendente. Não usar reset destrutivo nem push forçado.

- Trabalhar somente neste bot. O repositório Anime-Adventures-Wiki e sua publicação permanecem congelados por tempo indeterminado. Não alterar nem documentos legais do site.
- O responsável pediu remover integralmente os recursos que não existem mais no bot, incluindo seu código, arquivos, nomes, mensagens e testes específicos. Manter somente chat global, banners, desafio diário e infraestrutura compartilhada. Não reintroduzir modos arquivados, IA, perguntas, programa do PC ou comandos extras.
- Comandos atuais: /globalchat, /setbanner e /dailychallenge. Os feeds abrem consulta privada sem gravar configuração; habilitar/parar exige administrador. Moderar localmente aceita Gerenciar mensagens ou Moderar membros, sem conceder configuração ou sanções de rede. Interface e mensagens fixas em inglês. Notas públicas em português. Preservar textos escritos pelos participantes do chat global.
- Testes sempre privados: APIs simuladas, bancos temporários ou canal restrito verificado. Não enviar testes à rede pública, mudar destinos de produção, criar cargos ou alterar permissões só para testar.
- O responsável autorizou implementar todas as melhorias da revisão de uma hora e confirmou depois que níveis continuam adiados. Feedback oficial, consultas, moderação local, diagnóstico, filas, formato de anexos, recursos, pacote e recuperação estão no escopo. Revisão de cargos é privada e só aplica mudanças quando o dono aciona o plano revisado no próprio bot; não alterar permissões em startup.
- Esta sessão de desenvolvimento não possui acesso direto ao Discord/hospedagem. O ID do servidor e os relatórios não equivalem a uma sessão administrativa. Não afirmar envios, reinícios, edições ou limpeza de mensagens reais sem execução observada.

# Comunidade e avisos

- Servidor oficial: 1554953245204422807; canal de atualizações: 1564498826423959652. O servidor de testes antigo foi excluído. Usar IDs, não redirecionar para canais de nome parecido.
- Avisos e eventual feedback exclusivos da comunidade oficial. Cada atualização percebida pelos membros recebe uma mensagem NOVA, com tópicos em português, sem cabeçalho, versão técnica ou data. Falar somente do que o player vê/usa; nada de diagnóstico privado, arquivos internos, testes ou administração exclusiva do dono.
- Publicar somente após os arquivos da versão serem verificados e as tarefas ativas de atualização estarem concluídas. O gate de conclusão do W/M/L vale em todos os destinos de banners ativos. Não usar atraso fixo como prova de conclusão.
- A única correção editorial antiga é a nota fixa em data/community_notice_correction.json, com recibo da versão .6; não acrescentar novidades nela. Avisos novos nunca editam conteúdo anterior para agregar mudanças.
- Relatórios da estrutura/permissões são privados e não devem ir ao Git. Não exportam mensagens ou segredos.

# Feeds e entrega

- Fontes exclusivas: banners 993219350179876874; desafio diário 1326659593199423610. Credenciais existentes DISCORD_TOKEN e SECONDARY_ACCOUNT_TOKEN; preservar DATA_DIR. Não pedir/exibir valores nem exigir PC ligado.
- discord.py 2.7.1 no processo principal; biblioteca do leitor 2.1.0 isolada. Preferir acesso autorizado do próprio bot às duas origens quando existir; manter o leitor como fallback e não inventar acesso/IDs novos. Inscrição de servidor grande requer typing=True. Poll de 30 s, até 50 mensagens; tentativas de recepção limitadas a 60 s.
- Somente PNG/JPEG/WebP estáticos, sem legenda/texto/GIF/vídeo. Imagens de banners novas separadas. Daily recupera só a imagem mais recente; não cair para o desafio anterior quando o atual já foi visto ou precisa de outra tentativa.
- SHA-256 local, identidade da origem e recibos por destino; sem IA. Confirmar depois de validar/salvar ou receber o ACK. Nonces, estados incertos e reconciliação impedem reenvio cego. Não apagar registros nem programar exclusão às 00h50. Retenção de cache: banners 65 min, daily 26 h; limites de arquivo/lote/cache existentes preservados. Registros leves de origem/entregas sobrevivem à expiração do arquivo, com limites e marcos de compactação. Recebimento e envio são independentes e limitados por recursos; versões novas observadas do daily bloqueiam versões anteriores antes do download.
- Publicação automática pelo megafone removida em todos os servidores. Não reativar sem pedido explícito. Não converter canais, apagar mensagens ou alterar seguidores/botão manual. Entrega direta aos servidores com bot instalado permanece ativa.
- Artes W/M/L originais em assets/banner-votes, sem edição. Nomes do aplicativo exatamente win, mid, lose. Daily não recebe W/M/L. Histórico antigo não é reenviado nem dividido.
- Correção única autorizada da ordem W/M/L alcança TODOS os servidores com banners configurados, inclusive jogadores. Só as reações antigas afetadas podem ser zeradas; manter corte por canal, fases/recibos, outros emojis e votos novos. Falta de Gerenciar mensagens pausa só aquele destino. Reinício não repete a limpeza.
- Ícone decorativo do jogo apenas uma miniatura em Bot status, uma vez. Demais controles em texto. Preservar imagens de conteúdo e as reações funcionais pedidas.

# Dados e operação

- Hospedagem existente: Bot-Hosting.net, Python 3.12, entrada bot.py, com pull automático do GitHub na inicialização registrado no histórico. O fluxo usual do responsável é clicar em Reiniciar após o envio a origin/main. Não pedir escolher GitHub/ZIP ou reenviar pacote nesse fluxo. Conferir no console Running version 2026.10.28.2 depois do restart; se continuar antiga, diagnosticar a atualização automática. Não afirmar inspeção ao vivo das configurações do painel.
- Banco ativo: bot.sqlite3. Migração por reconhecimento de esquema, sob lease exclusivo, com backup e verificação. Não esvaziar configurações, consentimentos, recibos, marcadores de W/M/L ou estado do daily. Bases antigas e tabelas sem uso só saem do arquivo vivo após existir cópia privada verificada.
- Hospedagem: 256 MB RAM e 512 MB disco. Medir dependências/cache/backups, respeitar margem e falhar preservando o estado. Nenhum segredo, SQLite real, backup ou relatório real vai ao repositório.
- Assinantes são membros normais; Angelic e Artista decorativos; Mods moderadores. O dono já criou o cargo Adventures no topo e o atribuiu ao bot. Não duplicar cargos nem presumir outras alterações feitas por esta sessão.
- Sistema de níveis por mensagens permanece somente ideia adiada, sem XP, loja, moeda ou cargos automáticos.
- O pacote Windows histórico downloads/Remover-Python-e-Bot-Windows.zip foi expressamente restaurado pelo dono; não alterar/reempacotar/retirar nem orientar bypass do Defender. Não afirmar falso positivo ou malware sem evidência. Esse pacote separado não é parte do runtime.
- Feedback usa formulário e revisão privados, só na comunidade oficial, com retenção de 30 dias e limite total. Não enviar feedback ou backups automaticamente a canais/serviços externos. O convite confirmado pelo responsável é https://discord.gg/qwH7DvdtDZ; não perguntar novamente nem inventar outro. Nenhum destino externo de backup foi informado; manter snapshot privado local e explicar que perda total da hospedagem pode levar as cópias locais junto.
- Ao fechar a entrega, atualizar CONTINUIDADE.md com mudanças, testes, commit/CI e ativação real pendente. Manter histórico anterior no Git, sem trazer código inativo de volta.
