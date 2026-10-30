# Operação, atualização e recuperação

## Fluxo da hospedagem existente

O histórico registra Bot-Hosting.net, Python 3.12, entrada bot.py e pull automático do GitHub ao iniciar, confirmado pelo print que carregou a .28.2. A entrega atual é **2026.10.29.1**. Depois de chegar a origin/main, o fluxo continua sendo clicar em **Reiniciar** e conferir a versão no console. DATA_DIR, credenciais e destinos são preservados. Não há upload de ZIP a fazer. O programa confere o manifesto antes de abrir o estado; um checkout incompleto não é iniciado como uma versão válida.

No incidente relatado depois da .28.1, a captura mostrou alertas privados das duas fontes sem consulta recente e de destinos de banner atrasados/bloqueados. O console posterior confirmou .28.1 com reconexões do Gateway; a .28.2 corrige uma interrupção reproduzida após DISCONNECT seguido de RESUMED. O print seguinte confirma .28.2 e conexão aos quatro servidores, mas ainda não confirma as consultas/entregas dos feeds. A .28.3 mantém essa correção e acrescenta o aviso pontual descrito em [comunidade](community-server.md). Conferir o resumo privado Feed recovery notice; não afirmar envio sem recibo. A sessão de desenvolvimento não inspecionou ao vivo as configurações da hospedagem nem executou o restart.

## Conferir uma entrega

1. Execute os testes offline, finalize os arquivos e gere data/build.json.
2. `python scripts/check_release.py --data-dir /caminho/privado` confere arquivos, banco e margem sem ler credenciais ou publicar mensagens. A CI usa um diretório vazio e verifica o manifesto real.
3. A CI monta e confere o pacote completo em diretório temporário. Esse ensaio não muda o fluxo de GitHub da hospedagem.
4. Envie a entrega a origin/main sem forçar. Na hospedagem existente, **Reiniciar** faz a atualização habitual; não enviar um ZIP por cima.
5. Confira a versão, consultas, recepção verificada e confirmações por destino no painel privado. Abrir Check connection ou Server status não muda configurações. Repair connection e Enable in this channel são ações explícitas; mover um feed pede confirmação.

requirements-runtime.txt fixa as dependências transitivas testadas do processo principal; requirements-reader.txt fixa as do leitor isolado. O leitor verifica todas as versões antes de reutilizar seu ambiente. Falha na sincronização dos comandos não bloqueia os trabalhadores existentes: tenta novamente com espera limitada e expõe o resultado privado.

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

**Check backup restore** no painel do dono restaura um snapshot em diretório descartável e verifica integridade, tabelas e inicialização dos leitores de estado do aplicativo, comparando configurações, consentimentos, recibos e marcadores preservados. Não inicia cliente Discord nem substitui a base viva. Alternativa offline:

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


## Diagnóstico e manutenção privados

Bot status → Destinations lista filas e bloqueios dos destinos configurados em todos os servidores, com páginas pequenas. Só o dono acessa essa visão. Copy diagnostics nos painéis copia campos permitidos de um único servidor; exclui tokens, URLs de anexos, corpos de mensagens, exceções e dados de outros servidores. O transporte autorizado do bot e o leitor isolado são identificados, sem presumir acesso novo à origem.

Feed maintenance pausa banners ou daily por 15 minutos ou uma hora. A pausa termina automaticamente, conserva destinos/recibos e não reenvia imagens vencidas. Mudanças concorrentes invalidam o formulário antigo. Uma requisição aceita por Discord pode concluir durante a pausa. Alertas exigem falha e recuperação estáveis por dois minutos; a recuperação não zera o intervalo de uma hora para novos alertas da mesma categoria. Problemas de consulta/recepção das fontes são agrupados em um incidente privado.

Uploads novos de chat global deixam 48 MiB de margem; os demais trabalhos que gravam arquivos deixam 16 MiB. Reservas de RAM cobrem decodificação completa, BLOBs e preparação dos uploads/previews. Uma imagem fora do orçamento aguarda em vez de ser reencodificada. O cache e a retenção de recibos continuam limitados. W/M/L pendente usa os metadados leves retidos, até 48 recibos recentes por destino, independentemente dos 65 minutos de bytes de banners.

O painel mede páginas alocadas/reutilizáveis do SQLite, registros de cópias, pendências de limpeza e volume agregado em 24 horas. A estimativa de cópias por dia usa mensagens de origem × demais servidores ativos, antes das restrições. Ela não garante capacidade. A limpeza remove até 512 origens vencidas por ciclo, sem encurtar a retenção de 30 dias. Só compactar offline se a folga recuperável justificar e houver margem suficiente:

```bash
python scripts/compact_state.py /caminho/privado/DATA_DIR
```

O comando exige lease exclusivo (recusa instância em execução), snapshot novo verificado e margem para cópia e VACUUM. Não deve ser usado como solução automática quando o disco já está cheio. Reutilização de páginas internas normalmente dispensa compactação.

## Preparação do backup externo e do monitor

A ferramenta `scripts/export_backup.py` usa o formato age/X25519 para cifrar um snapshot verificado com a chave PÚBLICA do responsável. Requer o programa age instalado. Não cria ou armazena a chave privada na hospedagem, não escolhe serviço e não envia nenhum arquivo. O caminho de saída deve ser novo; arquivos anteriores não são sobrescritos. Exemplo administrativo, somente depois de definir destino e chave:

```bash
python scripts/export_backup.py /privado/backups/bot-latest.sqlite3 /privado/copia-nova.age --recipient age1CHAVE_PUBLICA_CONFIRMADA
```

A cópia só pode ser considerada externa quando transferida ao destino privado escolhido e restaurada com a chave privada guardada fora da hospedagem. A ferramenta foi ensaiada com chaves descartáveis e restauração de banco sintético, sem upload. Nenhum destino/chave de produção foi informado; o backup externo não está ativo.

`/ready` agora detecta também recepção parada apesar de consultas recentes; pausas deliberadas não são falhas. `.github/workflows/availability.yml` continua pronto para uma URL pública HTTPS de `/ready` em `BOT_HEALTH_URL`. O endpoint publica apenas ready/unavailable. Não se configura uma URL com base em IDs, prints ou suposições sobre o painel. Esta sessão não conseguiu consultar as variáveis do GitHub pela API; não confirmou monitor externo ativo.

[Mapa da revisão e limites externos](review-improvements.md).
