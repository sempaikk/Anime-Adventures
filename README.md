# Adventures — bot da comunidade

Três comandos, com controles privados:

- `/globalchat`: participação, meus envios, denúncias e controles adequados para membros, moderadores, administradores e dono do bot.
- `/setbanner`: consulta privada das imagens atuais; administradores escolhem **Enable / check this channel** para configurar o destino.
- `/dailychallenge`: consulta privada do desafio atual e configuração explícita pelo administrador.

Abrir um painel não altera destinos nem republica imagens. Cada banner tem sua própria votação com os emojis originais win, mid e lose. O desafio diário não recebe essas reações. As postagens dos feeds contêm apenas imagens estáticas, sem legenda, propaganda ou publicação automática pelo megafone.

## Hospedagem

Use Python 3.12 e `requirements.txt`. Preserve `DISCORD_TOKEN`, `SECONDARY_ACCOUNT_TOKEN` e o mesmo `DATA_DIR` existente. Execute `python bot.py`. O computador pessoal pode ficar desligado.

O bot principal usa discord.py 2.7.1. Quando ele tiver acesso autorizado aos dois canais oficiais, poderá ler por esse acesso. Sem essas permissões, mantém o leitor isolado 2.1.0 e a credencial existente. O bot não obtém acesso à origem por conhecer seu ID.

A cota padrão é 512 MiB de disco e 256 MiB de memória; `INSTANCE_DISK_LIMIT_MB` e `INSTANCE_RAM_LIMIT_MB` permitem informar limites reais diferentes. As reservas incluem preparos concorrentes, leitor, arquivos temporários e backups. Nunca publique segredos ou bancos reais.

`COMMUNITY_INVITE_URL` permite substituir o convite oficial confirmado pelo responsável: https://discord.gg/qwH7DvdtDZ. O botão de suporte usa esse convite por padrão; nenhum link foi inventado. O perfil do aplicativo e seu link de instalação descrevem somente os três recursos atuais, com permissões mínimas para uso normal.

## Atualizar sem perder dados

Pare o processo, substitua o pacote completo e reinicie preservando DATA_DIR e credenciais. Não apague o estado para resolver duplicações. O banco ativo é `bot.sqlite3`; uma base anterior reconhecida é migrada com cópia privada verificada antes de retirar estruturas sem uso. A cópia fica em `DATA_DIR/backups/before-cleanup.sqlite3`.

A versão acrescenta tabelas/colunas sem zerar configurações, consentimentos, recibos, pendências ou marcadores de W/M/L. Cache de imagens e histórico leve de entregas têm durações distintas. Reiniciar não reinicia votações. Consulte [a operação](docs/operations.md) para o pacote, a conferência e a restauração privada.

## Conferir e empacotar

```bash
python -m unittest discover -s tests -v
python scripts/build_release.py NOVA_VERSAO
python scripts/check_release.py
python scripts/build_package.py /tmp/Adventures-deploy.zip
```

O pacote inclui todos os arquivos exigidos pelo manifesto. Não inclui `.env`, estado real, backups, relatórios, ambientes Python ou arquivos históricos de Windows. O ZIP é reproduzível; mantenha dependências e Python nas versões indicadas. Não misture arquivos de entregas diferentes.

## Documentação

- [Banners e desafio diário](docs/banners.md)
- [Chat global](docs/global-chat.md)
- [Comunidade e avisos](docs/community-server.md)
- [Permissões da comunidade](docs/community-permissions-plan.md)
- [Operação e verificação](docs/operations.md)

O site separado permanece pausado. Termos e privacidade publicados continuam em https://www.adventureswiki.workers.dev/bot/termos/ e https://www.adventureswiki.workers.dev/bot/privacidade/.
