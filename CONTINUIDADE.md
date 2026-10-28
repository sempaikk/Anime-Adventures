# Entrega atual — 2026.10.28.3

O novo print do responsável confirma que a hospedagem puxou origin/main (8dd855f) e carregou **2026.10.28.2 · 31a98fa4b56e; files verified**, conectando aos quatro servidores. Isso confirma a ativação da correção, não a recuperação efetiva das consultas/entregas. O responsável autorizou expressamente uma mensagem de desculpas/retomada nos canais de banner E daily de TODOS os servidores, com linguagem clara e bem escrita. Essa é uma exceção pontual aos feeds somente com imagens e aos avisos usuais exclusivos da comunidade; não ampliar para divulgação/avisos recorrentes.

- feed_notices.py implementa a campanha fixa feed-recovery-2026-10-28, com tabela aditiva bot_feed_notices. Seleciona os destinos configurados existentes na primeira ativação verificada/online; uma mensagem por canal, combinada se ambos os feeds usarem o mesmo canal. Não inclui novos canais/servidores depois da seleção nem redireciona avisos se o destino/geração mudar. Expira em 04/11/2026 UTC para não virar boas-vindas de incidente antigo.
- Texto por feed: “Pedimos desculpas pela interrupção no envio de banners [ou desafios diários]. A falha foi corrigida, e os envios automáticos estão sendo retomados. Obrigado pela paciência e por continuarem usando o Adventures!” Sem cabeçalho, versão, ícones, menções, anexos ou W/M/L; sem megafone/crosspost.
- Só envia após consulta atual confirmada e recepção da imagem observada, quando houver. Verifica guild/canal exatos, permissões reais e geração da configuração. Cada feed independe do outro. Recibo e nonce são salvos antes do POST; ACK perdido/crash exige reconciliação do próprio bot no canal original, sem reenvio cego. Recusa explícita de permissão pode tentar novamente após reparo.
- Lote limitado a quatro canais por ciclo, dois pedidos simultâneos, timeouts de 25 s, pausa entre tentativas. O ciclo usa operations_loop existente; os feeds continuam em seus trabalhadores separados. O resumo privado aparece em Bot status → Feed recovery notice e no console, sem conteúdo privado ou credenciais.
- A campanha e os recibos sobrevivem a reinícios e versões novas. Configurações, imagens, votos e recibos dos feeds não são zerados. Logs regulares e feedback continuam só na comunidade oficial. data/community_updates.json permanece na .28.2 para não duplicar a nota da correção no update-log só por acrescentar o aviso solicitado.
- 285 testes offline passaram (12 novos) em Python 3.12: quatro guilds com os dois feeds, gates de integridade/readiness/fonte/bytes, expiração, canal compartilhado, configuração removida/movida, novos destinatários excluídos, reinício real, perda de ACK, cancelamento, falta de permissão e integração ao ciclo. Log: /tmp/adventures-feed-notices-tests.log. Preflight passou: 79 arquivos, fingerprint d1e528da180f (prefixo); nenhum segredo/banco real lido nem acesso ao Discord.
- Commit/CI desta entrega: registrar após o envio. Carregar o novo aviso requer **Reiniciar** uma vez e conferir **Running version 2026.10.28.3**. A sessão não tem acesso direto à hospedagem/Discord: avisos ainda não foram observados; o bot os enviará após carregar e confirmar as condições. Não pedir ZIP, recadastrar destinos ou apagar dados. A .28.2 já foi confirmada pelo print; não continuar dizendo que ela está pendente de ativação.

# Histórico da correção — 2026.10.28.2

O responsável relatou alertas privados desde a noite anterior: ambas as fontes sem consulta recente e banners com destinos atrasados/bloqueados. A captura mostra o bot online e avisos separados por uma hora, como o cooldown configurado, mas não informa versão, exceção ou permissões efetivas. Foi solicitado print do console e do Bot status; respondeu que vai enviar. Não afirmar que uma causa na hospedagem foi confirmada sem esses dados.

Foi reproduzida uma falha concreta do leitor isolado: DISCONNECT desativava image_ready; o poll continuava emitindo heartbeat, mas ignorava todas as consultas; RESUMED não executa outro READY e não restaurava o estado. Os dois testes de recuperação falharam antes da correção, com zero imagens recebidas de ambas as fontes. Agora o poll HTTP não depende da conexão do Gateway e RESUMED faz consulta imediata com o mesmo tracker/poller, reativando um trabalhador encerrado quando necessário. Não muda fontes, credenciais, cache, recibos, votos, destinos ou limites; login/verificação continuam sem contorno. A correção vale para todos os servidores que usam esses feeds.

- 273 testes offline passaram em Python 3.12, incluindo três cenários novos: retomada RESUMED sem duplicar imagens/trabalhadores, consulta HTTP durante desconexão do Gateway e retomada de poll encerrado. O wheel público discord.py-self 2.1.0 foi inspecionado fora do repositório e confirma que parse_resumed despacha resumed, sem chamar READY; nenhuma conta real foi usada.
- Manifesto: 2026.10.28.2, 77 arquivos, fingerprint 31a98fa4b56e (prefixo). Log local: /tmp/adventures-reader-recovery-tests.log.
- Nota pública preparada com um único tópico em português sobre a interrupção de banners/daily após reconexão; mensagem nova somente na comunidade oficial, com os gates existentes. Não editar avisos anteriores, publicar detalhes privados ou reativar megafone.
- Implementação enviada em [41e1643562f6fdbf68d1e7fa367bd8da57432361](https://github.com/sempaikk/Anime-Adventures/commit/41e1643562f6fdbf68d1e7fa367bd8da57432361). O [Bot checks](https://github.com/sempaikk/Anime-Adventures/actions/runs/40703234011) concluiu com sucesso (Python 3.12). Este registro final é somente documental; não muda o manifesto nem exige outro reinício.
- A ativação real ainda depende de **Reiniciar** na Bot-Hosting e conferir **Running version 2026.10.28.2**; não pedir ZIP nem refazer destinos. Continuar o diagnóstico com o console prometido se os alertas persistirem. Não afirmar reinício ou recuperação observada por esta sessão.

# Histórico da entrega — 2026.10.28.1

O responsável autorizou implementar todas as melhorias da revisão de uma hora e confirmou expressamente que níveis continuam adiados. O estado anterior está no [registro da .17](https://github.com/sempaikk/Anime-Adventures/blob/b353214b940ea4a4be15b0bfceafa9fc43c3d459/CONTINUIDADE.md); manter histórico no Git, sem reintroduzir funções retiradas.

## Autorizações, limites e informações novas

- Somente /globalchat, /setbanner e /dailychallenge, com funções dentro dos painéis. Interface fixa em inglês, notas públicas em português, textos dos participantes preservados. Sem XP, loja, moeda, call ou IA.
- Servidor oficial 1554953245204422807, bot 1561527465657114644, updates 1564498826423959652, banners 1564496491635282060, daily 1564497284580773919 e global 1563614865677885574.
- O responsável confirmou o convite público https://discord.gg/qwH7DvdtDZ. Está no botão da comunidade e no perfil do aplicativo, com opção de substituição por COMMUNITY_INVITE_URL. Não perguntar novamente por um convite.
- Para backup externo, perguntou o efeito de não configurar. Foi explicado que o bot e o snapshot local continuam funcionando, mas perder a hospedagem/pasta pode também perder as cópias locais. Nenhum destino externo foi informado; não escolher serviço, enviar arquivo ou inventar credenciais. A entrega mantém backup privado local e ensaio de restauração.
- Sem sessão direta de Discord/hospedagem. Todos os testes desta entrega são privados/offline; nenhum envio, alteração de cargo, reinício ou perfil real foi executado por esta máquina. Site separado permanece intocado e congelado.

## Mudanças implementadas

### Sete correções reproduzidas

- Memória leve de origem/recibos sobrevive ao cache: edição de texto em banner antigo não republica a mesma arte. Nova postagem genuína pode reutilizá-la. Histórico é limitado e compactado com marcos, sem arquivo de imagens permanente.
- Geração dos feeds protege Stop receiving e a configuração contra painéis antigos, inclusive quando o canal não muda. Cliques são confirmados antes de esperar trabalho.
- Espaço de anexo conhecido é reservado pelo tamanho real, sem exigir todo o limite máximo de upload do servidor. Reservas paralelas não ultrapassam o orçamento do cache.
- Formato incompatível não elimina imagens válidas do mesmo banner. Falha temporária permite recuperar a parte faltante; recibos por imagem impedem repetir as confirmadas. Daily mantém validação conjunta.
- Mudança de restrição de idade em canal global pausa somente aquela conexão. Verificação também ocorre antes de retransmitir.
- Limpeza de caracteres invisíveis precede a remoção das etiquetas reservadas Owner/Tester; autorização continua por IDs.
- Filtro de endereço disfarçado também verifica domínio exibido sem protocolo e normaliza domínio, preservando rótulos descritivos e código.

### Feeds, origem e votos

- Recepção independente por feed, filas de até 64 eventos e barreira persistente para nova versão do daily, inclusive imagem editada na mesma postagem. Queda/timeout não permite liberar uma versão anterior enquanto a nova aguarda validação.
- Acesso autorizado do bot às duas origens pode substituir a conta leitora. Sem acesso, continua o leitor isolado. Casos mistos preservam o feed nativo quando a conta secundária falha. Não conceder ou presumir acesso externo.
- Fontes fixas 993219350179876874 e 1326659593199423610. Poll de 30 s, até 50 mensagens; typing=True preservado no leitor 2.1.0. Heartbeat/watchdog detecta leitor travado, e autenticação/verificação de conta não entra em tentativas de contorno.
- Até dois uploads por feed; tarefas por canal continuam sem prender os demais destinos. Tentativa incerta conserva o primeiro instante/nonce e confere páginas ao redor do envio, sem reupload cego. Origem retirada bloqueia envios novos, preservando publicações existentes.
- W/M/L continua nativo, com os PNGs originais e nomes win/mid/lose. Trabalhadores limitados processam novos votos antes de histórico. A correção antiga única continua em TODOS os servidores configurados, com corte, fases e preservação de votos novos; não foi reiniciada.
- Limites de arquivo/lote/cache anteriores preservados. Cache: 65 min banners, 26 h daily; recibos/metadados separados. Não apagar posts nem programar limpeza às 00h50. Publicação pelo megafone continua desativada.

### Usabilidade e comunidade

- Comandos de feed abrem consulta privada sem gravar destino. Membros veem prévia/ajuda; administradores têm configuração, status e parada explícitos. Prévia verifica acesso ao destino, atualidade e limite, sem publicar no canal ou mudar a configuração.
- Ajuda curta, link de instalação com permissões mínimas e convite oficial; limites de componentes/texto dos painéis conferidos. Perfil do aplicativo usa só as funções atuais e aguarda confirmação, com nova tentativa limitada.
- Mods com Gerenciar mensagens ou Moderar membros acessam denúncias/restrições locais. Não ganham configuração, diagnóstico do dono ou sanções de rede. Administradores e dono conservam seus escopos.
- Última tentativa do membro mostra motivo/horário em particular, mesmo com DM fechada, sem guardar o texto original nesse registro e com expiração de uma hora.
- Feedback apenas na comunidade oficial, formulário privado de erro/sugestão, recibo/deduplicação/limite e caixa de revisão exclusiva do dono. Retenção de 30 dias, até 3.000 entradas. Denúncias do global continuam em todos os servidores.
- Antiflood proporcional distingue repetição coordenada de celebrações isoladas; excesso concentrado em uma conta não restringe todo o servidor. Sem banimento permanente automático.
- Review role permissions prepara Assinantes como membro, Artista/Angelic como visual e Mods como moderação. Só aplica quando o dono aciona o plano privado revisado; não muda cargos durante startup. Membros, nomes, hierarquia, @everyone e sobreposições de canais são preservados. Angelic precisa ser inequívoco; não presumir Rlks. Efeito de permissões depende de aplicar e conferir o canal real.

### Operação e dados

- Diagnóstico por feed distingue última consulta, imagem observada, bytes verificados e entrega confirmada; resumo do dono mostra filas, destinos e p95 recente por destino. Alertas privados têm persistência/cooldown e separam falta de novidade de recepção/entrega bloqueada.
- Cota conjunta de disco e memória considera processos filhos, downloads, arquivos temporários, leitor e backups. Limites padrão 512/256 MiB; orçamento faz reserva antes do preparo. Logs controlados não imprimem tokens, URLs privadas ou corpos de mensagens.
- Snapshot de manutenção é aguardado no encerramento normal. Check backup restore usa diretório descartável, sem substituir a base viva. CLI equivalente em scripts/check_restore.py. Backups não arquivam texto temporário do chat global.
- Limpeza de IDs expirada é feita em lotes e com índices; metadados desnecessários de tentativa concluída saem da linha. Recibos/consentimentos/pendências não são zerados. Banco bot.sqlite3 permanece, com adições de esquema compatíveis.
- scripts/build_package.py produz pacote completo e reproduzível sem .env, estado, backups, relatórios, ambientes ou arquivos históricos de Windows. Documentação atual foi refeita, com links válidos e procedimento de atualização/recuperação. scripts/check_release.py reconhece estado anterior sem migrar durante a conferência.

## Notas públicas

Somente benefícios percebidos pelos players, em português e sem cabeçalho/versão/data. Mensagem nova após integridade e conclusão do trabalho ativo em todos os destinos. O perfil pendente também bloqueia o anúncio; nada de atraso fixo como prova. A única correção editorial antiga em community_notice_correction.json ficou intacta.

## Validação

- 270 testes offline passaram; 36 testes a mais que a .17, com casos de independência, falha parcial, cancelamento, privacidade, escopos, feedback, quotas, restauração e pacote. A adequação dos testes antigos acompanha a configuração explícita e trabalhadores em segundo plano, preservando as verificações de recuperação.
- Ensaio com 50 servidores simulados, três imagens por rotação e 5 ms de latência simulada: 150 uploads, 450 reações, aproximadamente 1,3 s, banco 0,62 MiB, pico do processo 60,13 MiB sem leitor real. Nenhum acesso externo. Não é garantia de capacidade/tempo da hospedagem ou da API real.
- Manifesto 77 arquivos, versão 2026.10.28.1, fingerprint 196f625dd282d521b98d65ac204413fbff720094b405c76cd01cc64c08a1854c.
- Pacote /tmp/Adventures-2026.10.28.1.zip com 87 arquivos, 206.679 bytes, SHA-256 5551f19b87fdc3f91acc14e27f463631c8c3d3e4ba7715ff675942fd012198b1. Preflight passou também após extrair o ZIP; não leu credenciais ou banco real.
- git diff --check e busca por nomes retirados passaram; arte W/M/L e pacote Windows histórico de remoção intactos. downloads/Remover-Python-e-Bot-Windows.zip mantém SHA-256 d4c68ff5626d5ab46bc48b5c746fdf4065a29441bd924deaa37616a2db0ada29; não reempacotar ou orientar bypass do Defender.
- Implementação enviada em [140a729475f8c86e335b0c77fddeb399ac14aba0](https://github.com/sempaikk/Anime-Adventures/commit/140a729475f8c86e335b0c77fddeb399ac14aba0). O [Bot checks](https://github.com/sempaikk/Anime-Adventures/actions/runs/40635309854) concluiu com sucesso; os 270 testes passaram também no CI com Python 3.12. Este registro final fica em commit separado de documentação, sem mudança no runtime, manifesto ou pacote.

## Ativação real pendente

O responsável lembrou que seu procedimento usual é só clicar em Reiniciar e mostrou a Bot-Hosting.net. O histórico anterior confirma Python 3.12, entrada bot.py e pull automático do GitHub ao iniciar. A orientação genérica de reenviar ZIP e perguntar GitHub/ZIP foi desnecessária; preservar esse contexto. O fluxo esperado agora é **Reiniciar** e conferir **Running version 2026.10.28.1** no console. A captura enviada ainda mostra .27.17, antes da confirmação da atualização. Não afirmar que o restart ou a conferência real já aconteceram. Se a versão continuar antiga depois do restart, investigar o pull automático antes de pedir upload manual.

Manter DATA_DIR e credenciais; não apagar dados nem refazer destinos para consultar. Perfil e avisos só têm efeito após a instância carregar a entrega. Para cargos, usar Bot status → Review role permissions e conferir permissões efetivas; não afirmar que foram aplicadas automaticamente. Esta correção é somente documental, sem nova versão do bot ou alteração no manifesto.
