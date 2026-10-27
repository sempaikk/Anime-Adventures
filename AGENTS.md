# Continuidade e escopo entre os dois chats

Leia [CONTINUIDADE.md](CONTINUIDADE.md) antes de trabalhar. Confira `git status` e `origin/main` e preserve alterações do outro chat; não use reset destrutivo nem push forçado.

**Decisão explícita do responsável em 26/10/2026:** daqui para frente, ambos os chats trabalham **somente neste bot**. O site `sempaikk/Anime-Adventures-Wiki` ficará com fundo desfocado e **Em breve / Coming soon por tempo indeterminado, até o responsável pedir a retomada**. A publicação dessa tela é a última alteração de site autorizada neste ciclo. Depois dela, não modificar arquivos, configuração, publicação ou visual do site sem novo pedido explícito.

Não tratar planos antigos de wiki/redesign ou acesso aos dois repositórios como autorização para mexer no site. Preserve os documentos legais existentes do bot publicados em `/bot/termos/` e `/bot/privacidade/`.

## Bot vigente

- Comandos: `/globalchat`, `/setbanner`, `/dailychallenge`, `/ask`. `/tierlist` está desativado, com código/dados arquivados; não reativar por iniciativa própria. Interface fixa em inglês; `/ask` responde no idioma da pergunta. Preservar o texto autoral dos participantes no relay.
- Ler `docs/banners.md` e `docs/knowledge.md` antes de alterar leitor, fontes, armazenamento ou IA. IDs autorizados estão em `game_sources.py`; não ampliar canais por suposição.
- O segredo vigente é `SECONDARY_ACCOUNT_TOKEN`, já renomeado no painel. Não solicitar/exibir valores. `DISCORD_TOKEN` e `GROQ_API_KEY` têm funções separadas. Não instalar `discord.py-self` no ambiente principal: ele colide com `discord.py` e precisa permanecer no processo/venv isolado.
- Hospedagem informada: 256 MB RAM / 512 MB disco. Conhecimento: SQLite separado e comprimido, reserva inicial de 64 MiB, backup próprio, sem exclusão por idade/quantidade; falta de espaço pausa e avisa. Não presumir captura/armazenamento infinitos nem enviar histórico real, banco ou backup ao GitHub.
- **Pedido posterior do responsável:** a migração do conhecimento para o PC agora está autorizada. Pasta escolhida: `D:\Armazenamento do Bot`. URL pública fornecida: `https://7g2x14fnpa.apps.bot-hosting.cloud`. Consulte `LEIA-ME-PC.md` e `docs/pc-knowledge.md`. Em `KNOWLEDGE_MODE=pc`, o processo hospedado não abre/cria o banco de conhecimento nem consulta a Groq para `/ask`: o programa Windows inicia WSS autenticado, armazena/pesquisa/responde e a ausência dele deixa o serviço indisponível. Não confundir preparação do código com instalação/acesso ao PC.
- Preservar a base hospedada até a importação verificar hash/integridade/contagens. Finalização só por operação explícita do programa após teste, com recibo e PC conectado; nunca apagar `DATA_DIR` ou `tierlist.sqlite3`. Segredo de pareamento e chave Groq ficam privados, fora do GitHub/chat. O limite anterior de 64 MiB se aplica ao modo local, não ao PC; neste a coleta pausa com margem de 1 GiB livre.
- A falha de busca por upgrades/níveis (Dark Mage e possivelmente outras unidades) foi reproduzida: o trecho selecionado não inclui o upgrade e a extração mistura valores/buffs. **Continua pendente e não é resolvida por aumentar o HD.** O responsável pediu priorizar armazenamento; não afirmar que esta migração corrige aquela falha.

Ao encerrar um ciclo no bot, registre em `CONTINUIDADE.md` o que foi efetivamente alterado, conferido e enviado, junto das pendências. Não registre segredos nem afirme publicação sem evidência.
