# Continuidade e escopo entre os dois chats

Leia `CONTINUIDADE.md`, confira `git status` e `origin/main` antes de editar e preserve trabalho pendente. Não usar reset destrutivo ou push forçado.

## Comunidade central e testes — orientação posterior de 27/10/2026

- Servidor central/comunidade: **1554953245204422807**. O servidor antigo Testes foi excluído; não reutilizar seus destinos nem presumir acesso direto ao Discord por ter o ID. O bot hospedado e a sessão de desenvolvimento têm acessos diferentes.
- Todo teste deve ser privado: respostas ephemeral, bancos temporários e, se um ensaio real precisar publicar, canal restrito cuja permissão seja conferida antes do envio. Não mover destinos públicos de produção, compartilhar mensagens de teste na rede global, criar cargos ou mudar permissões para ensaiar. Nunca publicar testes em um canal público como alternativa a acesso privado indisponível.
- O responsável autorizou publicar em **update log** as mudanças relevantes para quem usa o bot. `community_hub.py` publica somente notas curadas da versão executada/verificada, uma vez por versão, exclusivamente no servidor central e se encontrar um único canal de texto com esse nome normalizado. Não publicar logs técnicos, relatórios privados ou resultados de testes ali. Duplicidade de nome/permissão insuficiente bloqueia a publicação; não escolher outro canal por suposição.
- Relatório da estrutura/permissões: `/globalchat` → **Bot status** → **Server report**, exclusivo do dono do aplicativo que também administra o servidor central. Exporta metadados conhecidos pelo Gateway; não lê mensagens, membros ou credenciais. O arquivo é privado e não deve ser versionado. Recebê-lo é necessário para analisar a estrutura real quando esta sessão não dispõe de acesso ao Discord.
- **Somente ideia futura, sem implementação agora:** níveis por mensagens com tema das passivas de Anime Adventures, culminando em Unique. Sem loja/moedas/compras, XP, cargos automáticos ou contagem de call neste ciclo. O responsável corrigiu e adiou explicitamente essa parte.
- O responsável confirmou entrega real e pontual dos banners. Desafio diário ainda aguarda confirmação real; não deduzir sucesso só porque o banner funciona.

## Decisão mais recente — 27/10/2026

- O responsável cancelou `/ask`, a IA de perguntas e todo o programa/armazenamento no PC. Não continuar ajustes de Dark Mage/citações, migração ou pesquisa de outra IA como tarefa ativa. Decisões anteriores estão preservadas como histórico em `CONTINUIDADE.md` e foram substituídas por este pedido.
- Comandos ativos: `/globalchat`, `/setbanner`, `/dailychallenge`. `/tierlist` e `/ask` não são registrados. O argumento `archived_knowledge=True` existe apenas para testes históricos, não como configuração normal; nenhuma variável de ambiente reativa o serviço de perguntas. O bot normal não abre banco de conhecimento, coleta Questões, conecta ao PC ou expõe suas rotas.
- Interface e mensagens fixas em inglês. Não traduzir mensagens autorais dos participantes do chat global. Feeds publicam somente imagens estáticas PNG/JPEG/WebP, sem GIF/vídeo/texto/legenda.
- Fontes vigentes: banners `993219350179876874` e desafio diário `1326659593199423610`. Não ampliar fontes por suposição. A conta secundária conecta pela hospedagem; não precisa ficar aberta no Discord do PC do responsável. `SECONDARY_ACCOUNT_TOKEN` é o segredo principal do leitor; preservar também `DISCORD_TOKEN` e o `DATA_DIR` atual. Não pedir/exibir valores.
- O leitor usa `discord.py-self==2.1.0` no processo/venv isolado, nunca no ambiente principal de `discord.py`. A inscrição de servidor grande requer `typing=True`; colocar todas as flags como False cancela a inscrição. Poll de 30 s e deduplicação complementam eventos. Estado de acesso é separado por fonte; não alegar entrega real sem observar o destino após atualizar.
- Hospedagem: 256 MB RAM / 512 MB disco. Não instalar software ou exigir PC ligado para os feeds. Histórico antigo de conhecimento hospedado permanece inativo e não é apagado automaticamente ao retirar o comando.

## Remoção Windows — alerta do Defender

**Em 27/10/2026 o responsável mostrou “Vírus detectado” no ZIP automático de remoção.** O pacote, launcher, PowerShell e gerador foram retirados da main. Não oferecer outra versão/EXE, renomear/reempacotar para escapar da detecção, pedir para restaurar/permitir ou desativar o antivírus. A causa/nome da detecção ainda precisam de informação do Histórico de proteção; não afirmar falso positivo, infecção ou segurança total com base na simulação/CI. Não confundir testes funcionais com análise antimalware.

A autorização de limpar o PC permanece: orientar desinstalação em Configurações > Aplicativos e exclusão manual das pastas/arquivos conhecidos, conforme `LEIA-ME-REMOCAO.txt`, sem novos downloads de limpadores. O responsável quer remover Python, pacotes, ZIPs e arquivos desta configuração. Não apagar arquivos alheios, Windows/Installer, WindowsApps ou runtimes embutidos em outros programas. Site e hospedagem ficam separados da limpeza do PC.

## Site congelado

Ambos os chats trabalham somente no bot. `sempaikk/Anime-Adventures-Wiki` permanece com **Em breve / Coming soon por tempo indeterminado, até novo pedido explícito**. Não modificar seus arquivos, configuração ou publicação. Preservar os documentos legais do bot em `/bot/termos/` e `/bot/privacidade/`. Consultar histórico não autoriza retomar redesign.

Ao encerrar um ciclo, registrar em `CONTINUIDADE.md` o que foi feito, testado, enviado e o que depende da instância/Windows reais. Não publicar segredos, bancos ou backups reais.
