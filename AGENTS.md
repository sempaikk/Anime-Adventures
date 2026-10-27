# Continuidade e escopo entre os dois chats

Leia `CONTINUIDADE.md`, confira `git status` e `origin/main` antes de editar e preserve trabalho pendente. Não usar reset destrutivo ou push forçado.

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
