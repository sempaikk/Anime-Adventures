# Continuidade e escopo entre os dois chats

Leia [CONTINUIDADE.md](CONTINUIDADE.md) antes de trabalhar. Confira `git status` e `origin/main` e preserve alterações do outro chat; não use reset destrutivo nem push forçado.

**Decisão explícita do responsável em 26/10/2026:** daqui para frente, ambos os chats trabalham **somente neste bot**. O site `sempaikk/Anime-Adventures-Wiki` ficará com fundo desfocado e **Em breve / Coming soon por tempo indeterminado, até o responsável pedir a retomada**. A publicação dessa tela é a última alteração de site autorizada neste ciclo. Depois dela, não modificar arquivos, configuração, publicação ou visual do site sem novo pedido explícito.

Não tratar planos antigos de wiki/redesign ou acesso aos dois repositórios como autorização para mexer no site. Preserve os documentos legais existentes do bot publicados em `/bot/termos/` e `/bot/privacidade/`.

## Bot vigente

- Comandos: `/globalchat`, `/setbanner`, `/dailychallenge`, `/ask`. `/tierlist` está desativado, com código/dados arquivados; não reativar por iniciativa própria. Interface fixa em inglês; `/ask` responde no idioma da pergunta. Preservar o texto autoral dos participantes no relay.
- Ler `docs/banners.md` e `docs/knowledge.md` antes de alterar leitor, fontes, armazenamento ou IA. IDs autorizados estão em `game_sources.py`; não ampliar canais por suposição.
- O segredo vigente é `SECONDARY_ACCOUNT_TOKEN`, já renomeado no painel. Não solicitar/exibir valores. `DISCORD_TOKEN` e `GROQ_API_KEY` têm funções separadas. Não instalar `discord.py-self` no ambiente principal: ele colide com `discord.py` e precisa permanecer no processo/venv isolado.
- Hospedagem informada: 256 MB RAM / 512 MB disco. Conhecimento: SQLite separado e comprimido, reserva inicial de 64 MiB, backup próprio, sem exclusão por idade/quantidade; falta de espaço pausa e avisa. Não presumir captura/armazenamento infinitos nem enviar histórico real, banco ou backup ao GitHub.
- HD pessoal de 1 TB é **plano futuro aprovado para ficar pendente**, sem implementar agente, túnel, VPN, exportação ou acesso ao PC nesta entrega.

Ao encerrar um ciclo no bot, registre em `CONTINUIDADE.md` o que foi efetivamente alterado, conferido e enviado, junto das pendências. Não registre segredos nem afirme publicação sem evidência.
