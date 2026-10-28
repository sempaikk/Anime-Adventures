# Operação, atualização e recuperação

## Fluxo da hospedagem existente

O histórico registra Bot-Hosting.net, Python 3.12, entrada bot.py e pull automático do GitHub ao iniciar. O print do responsável confirmou o pull e a carga da .28.2 com arquivos verificados. Para acrescentar o aviso autorizado nesta entrega, clicar em **Reiniciar** depois de a nova entrega chegar a origin/main e conferir **Running version 2026.10.28.3** no console. Não pedir envio de ZIP ou escolha do método novamente. O ZIP completo é alternativa de implantação manual, não uma etapa adicional obrigatória.

No incidente relatado depois da .28.1, a captura mostrou alertas privados das duas fontes sem consulta recente e de destinos de banner atrasados/bloqueados. O console posterior confirmou .28.1 com reconexões do Gateway; a .28.2 corrige uma interrupção reproduzida após DISCONNECT seguido de RESUMED. O print seguinte confirma .28.2 e conexão aos quatro servidores, mas ainda não confirma as consultas/entregas dos feeds. A .28.3 mantém essa correção e acrescenta o aviso pontual descrito em [comunidade](community-server.md). Conferir o resumo privado Feed recovery notice; não afirmar envio sem recibo. A sessão de desenvolvimento não inspecionou ao vivo as configurações da hospedagem nem executou o restart.

## Conferir uma entrega

1. Execute os testes offline e gere data/build.json somente depois de finalizar código, dados e testes.
2. `python scripts/check_release.py` verifica arquivos, banco e margem sem ler credenciais ou publicar mensagens.
3. `python scripts/build_package.py /tmp/Adventures-deploy.zip` gera um pacote completo e reproduzível, excluindo dados privados.
4. Pare a instância. Preserve DATA_DIR e segredos; substitua o pacote inteiro e mantenha o comando `python bot.py`. Evite sobrepor uma parte dos arquivos em versões antigas.
5. Inicie e confira Bot status: versão, consultas das fontes, imagens observadas/verificadas e confirmações por destino. Não repetir comandos de configuração apenas para consultar.

Testes simulados e CI não comprovam publicação real. Para um ensaio com API, validar privacidade de todos os cargos e sobreposições; não fabricar mensagens na rede pública.

## Capacidade

O orçamento considera dependências, leitor, banco, cache, temporários e backups, com margem de operação. Disco crítico ou memória alta adiam novos arquivos. Isso não apaga histórico ou reinicia votos. Medição de RSS inclui processos filhos quando o ambiente Linux permite; sem medição, mostrar indisponibilidade em vez de inventar um valor.

Ensaio da fila global, sem rede:

```bash
python scripts/benchmark_global.py --guilds 100 --messages 40
```

Ensaio de imagens, reações, filas e latência simulada, sem Discord:

```bash
python scripts/benchmark_feeds.py --guilds 50 --delay-ms 5
```

O segundo usa PNGs artificiais, HTTP simulado e banco temporário; não lê fontes reais, autentica ou envia mensagens. Seu pico de memória não inclui um leitor real. Nenhum desses números garante capacidade de produção. Acompanhar p95 das últimas entregas por destino, idade de filas e crescimento dos recibos de 30 dias antes de ampliar muito a rede. Limites da API são respeitados; não adicionar contas/tokens para contorná-los.

## Backups

Há um snapshot diário verificado, com texto temporário de chat removido. O backup de antes da limpeza de estruturas antigas permanece separado. Configurações, credenciais de webhook, recibos e marcadores continuam privados; não anexar os arquivos a canais ou ao Git.

**Check backup restore** no painel do dono restaura um snapshot em diretório descartável e verifica integridade/tabelas, sem substituir a base viva. Alternativa offline:

```bash
python scripts/check_restore.py /caminho/privado/backups/bot-latest.sqlite3
```

Uma cópia privada criptografada fora da hospedagem protege contra perda da instância. O destino e a chave precisam ser escolhidos pelo responsável; não há envio automático para um serviço desconhecido. Nesta entrega permanece o backup local: um destino externo ainda não foi informado. Sem ele, perder toda a hospedagem/pasta pode também perder as cópias locais; isso não impede o funcionamento do bot. Defina retenção e teste restauração antes de retirar qualquer cópia anterior.

## Reverter uma entrega

Parar o processo e preservar uma cópia privada atual. Restaurar código somente quando o esquema for compatível; não restaurar automaticamente um banco anterior, pois isso pode perder consentimentos e recibos ou repetir envios. A restauração de estado é uma operação offline explícita e deve ser ensaiada em cópia descartável.

SIGTERM/SIGINT interrompem trabalhadores e preservam tentativas incertas. O snapshot de manutenção iniciado termina antes da liberação normal da base. Falta de espaço, corrupção ou migração ambígua preserva os originais; consultar o diagnóstico, não apagar DATA_DIR.

## Perfil e acesso externo

O aplicativo descreve apenas os três recursos atuais e sugere permissões mínimas de instalação. O próprio bot pode ler as duas origens somente se tiver acesso autorizado nelas; não recebe acesso por ID. O leitor existente continua disponível como fallback. Verificação do aplicativo, Message Content Intent e autorização dos responsáveis pela origem são condições externas que o desenvolvimento não pode conceder.

O convite confirmado da comunidade é https://discord.gg/qwH7DvdtDZ. COMMUNITY_INVITE_URL permite substituí-lo por outro convite confirmado. A revisão de cargos da comunidade só é aplicada pelo dono dentro do painel privado; verificar depois as permissões efetivas nos canais.
