# Adventures — bot da comunidade

O bot oferece três comandos:

- `/globalchat`: participação no chat global e controles privados de administração/moderação.
- `/setbanner`: envio automático de banners no canal configurado. Cada imagem tem sua votação W/M/L.
- `/dailychallenge`: envio automático do desafio diário mais recente.

A publicação pelo megafone para seguidores de canais fica desativada. Os feeds são entregues diretamente pelo bot instalado em cada servidor. Menus e respostas fixas usam inglês; as notas públicas de atualização são em português, somente no servidor oficial.

## Executar

Use Python 3.12 e instale `requirements.txt`. Configure `DISCORD_TOKEN`, `SECONDARY_ACCOUNT_TOKEN` e o mesmo `DATA_DIR` já usado pela hospedagem. Inicie `python bot.py`. Nunca publique os valores dos segredos.

O leitor de imagens usa um ambiente isolado na hospedagem, criado automaticamente quando necessário. O computador pessoal pode permanecer desligado. O processo principal usa discord.py 2.7.1; o leitor usa sua biblioteca isolada 2.1.0.

## Atualizar preservando os dados

Pare o processo, atualize o pacote completo mantendo DATA_DIR e os segredos, e reinicie. O banco ativo passa a se chamar `bot.sqlite3`. Uma base anterior é reconhecida por suas tabelas dos serviços ativos, copiada e verificada; configurações, consentimentos, imagens e recibos são mantidos. Antes de retirar estruturas sem uso, uma cópia privada fica em `DATA_DIR/backups/before-cleanup.sqlite3`. Falta de espaço, corrupção, conflito ou mais de uma base candidata interrompe a migração sem substituir os dados originais.

Não apague o diretório persistente nem seus registros para resolver reenvios. As cópias de segurança não preservam o texto temporário do chat global. Guarde backups em local privado; contêm configurações, identificadores e credenciais de webhooks.

## Verificar

```bash
python -m unittest discover -s tests -v
python scripts/check_release.py
```

A verificação de versão usa `data/build.json`, sem ler segredos. Para uma nova entrega, gere o manifesto com `python scripts/build_release.py NOVA_VERSAO` após finalizar o código e os testes.

O dono consulta **Bot status** em particular para verificar a versão, fontes, destinos e últimas entregas. Testes reais ficam restritos a canais privados. Os testes automatizados usam estado temporário e APIs simuladas.

## Documentação

- [Banners e desafio diário](docs/banners.md)
- [Chat global](docs/global-chat.md)
- [Servidor oficial e avisos](docs/community-server.md)
- [Papéis dos cargos](docs/community-permissions-plan.md)

O site separado continua pausado. Os documentos legais publicados permanecem em https://www.adventureswiki.workers.dev/bot/termos/ e https://www.adventureswiki.workers.dev/bot/privacidade/.
