# Critérios para divulgar /adventures

O código está preparado para validação em produção. Testes automatizados não comprovam renderização real do Discord, disponibilidade do Railway nem completude das fontes históricas.

## Preparado e testado

- Interface colorida com arte original, descrições de imagem neutras, controles nativos e limites dos cartões.
- Partidas de 10/20/30 perguntas ou contínuas; três tempos; chat, imagens e alternativas; pausa e encerramento por inatividade.
- Um vencedor por rodada, limite de tentativas, bloqueio de painéis/respostas antigos e antifarm global de 24 horas persistido.
- Até três partidas por servidor e 50 no processo. Uma simulação offline com 50 salas e 2.000 respostas manteve um vencedor em cada sala.
- Pausa durante desconexão, retomada com tempo preservado e rejeição de respostas do período desconectado. Pausas manuais não são desfeitas.
- Limpeza ao excluir canal/thread ou retirar o bot de um servidor. Expiração de lobbies e pausas abandonadas.
- Verificação de integridade ao iniciar, backup local diário, margem de espaço e retenção limitada de recibos. Falhas de backup não fecham o banco de pontos.
- Explicação privada para falhas de interação e tentativa de aviso de reinício com prazo limitado durante encerramento organizado.
- Dificuldade, formatos e categorias específicas; resumo por assunto e revisão privada; formulário com fila de moderação; transferência de anfitrião; recuperação após reinício; painel de estado, alertas e monitor externo preparado.

## Ao voltar o Railway

1. Verificar se o deploy automático usou o commit mais recente de `main`. Se necessário, abrir a paleta com **Ctrl+K / Cmd+K** e escolher **Deploy Latest Commit**. **Redeploy** repete o código/configuração do deployment selecionado; **Restart** só reinicia a versão atual. Confirmar o SHA do novo deploy.
2. Conferir volume em `/data`, `DATA_DIR=/data` e uma única réplica. O usuário já confirmou essa configuração; ainda falta observar o banco real depois de rodar esta versão.
3. Conferir nos logs caminho do banco, quantidade de perguntas, conexão com o Discord e manutenção de armazenamento. Não publicar tokens, logs com credenciais nem o arquivo de pontos em um repositório público.
4. Abrir novo `/adventures`. Jogar uma partida curta com um pequeno grupo em computador e celular, incluindo imagem, chat e alternativas. Conferir ritmo, leitura e cliques concorrentes.
5. Testar pausa/retomada, encerramento, falta de participação e jogar novamente. Depois testar 20/30 perguntas e contínua. Os testes offline cobrem essas durações; o teste real confirma o cliente e as permissões do servidor.
6. Ganhar um ponto, consultar o total, reiniciar e consultar novamente. Repetir após um novo deploy. O total deve continuar igual; repetir a mesma pergunta dentro de 24h só soma na partida.
7. Conferir uso real do volume após criar a cópia de segurança e manter uma exportação fora do Railway. Testar Retomar após reinício: placar/opções preservados, rodada interrompida sem acerto anulada e nenhum ponto duplicado.
8. Exercitar transferência de anfitrião e sinalização/revisão de um aviso com as permissões corretas. Configurar a URL pública do monitor externo conforme abaixo.

Essas etapas dependem do serviço voltar. Não foram executadas pela máquina de desenvolvimento durante a indisponibilidade; nenhuma mensagem de teste foi enviada ao Discord por ela.

## Cópia de segurança e recuperação

A rotina mantém `/data/backups/scores-latest.sqlite3`, com tentativa ao iniciar e atualização diária verificada a cada hora. Ela usa uma conexão separada em outra thread e a API de backup do SQLite. O snapshot contém totais, recibos e metadados de migração. A cópia anterior é preservada se faltar espaço, o arquivo falhar na validação ou a operação exceder o prazo.

Banco, backup e temporário ocupam o volume. Na medição anterior, o banco de 100 mil registros ocupava cerca de 22,61 MB; duas cópias adicionais desse tamanho durante a troca seriam aproximadamente 45,22 MB a mais. É estimativa, não garantia de capacidade. O backup exige ainda 16 MiB de margem livre e pode ser adiado por falta de espaço.

O operador pode verificar uma cópia sem iniciar o bot:

```bash
python scripts/backup_scores.py /data/backups/scores-latest.sqlite3
```

Para gerar uma cópia manual consistente, usar destino diferente do banco principal:

```bash
python scripts/backup_scores.py /data/scores.sqlite3 --output /data/backups/scores-latest.sqlite3
```

Exportar o arquivo validado para armazenamento privado fora desse volume. A cópia local não protege contra exclusão/perda do volume. O arquivo contém identificadores de jogadores e deve permanecer privado.

Para recuperar: parar o bot; preservar o arquivo danificado e uma cópia do backup; validar o backup; gerar o banco recuperado em um caminho novo com o mesmo utilitário. Conferir totais antes de substituir o principal, com o processo parado. Não restaurar automaticamente nem zerar o banco ao detectar corrupção. Uma recuperação volta ao instante do snapshot: pontos posteriores podem não estar nele.

## Pesquisa ainda aberta

Continuar a confirmação histórica de personagens sem data inicial corroborada, receitas de evolução, inimigos/variantes e conflitos de `data/release_pending.json`. Não importar estatísticas atuais para preencher lacunas de 2022. As 2.199 perguntas incluem variações calculadas dos mesmos fatos e não comprovam um inventário exaustivo do primeiro dia.

Ampliar retratos somente com imagens reais da forma correta, disponíveis e revisadas. Novas mídias não devem revelar a resposta por moldura, nome ou contexto. Vídeos/animações só entram quando forem úteis para uma pergunta e tiverem origem/compatibilidade verificadas.

## Recursos incluídos

- **Dificuldade:** 98 fáceis, 1.297 médias e 804 difíceis. `data/difficulty.json` documenta as perguntas manuais; famílias derivadas usam esforço de recordação/cálculo. Não é uma medição científica de dificuldade; pode ser ajustada por feedback sem inventar fatos.
- **Filtros:** quatro grupos/14 categorias, mais misto/alternativas/texto/imagens. Seleções vazias não iniciam.
- **Desempenho:** contagem por assunto, primeiros acertos e revisão com imagem/resposta/fonte. Texto digitado não é armazenado. Só rodadas concluídas e próprias, sem revelar a pergunta ativa.
- **Avisos:** formulário após a resposta, cinco por pessoa/24h e um por pergunta. Fila privada de cada servidor; até cinco mil registros por 30 dias. Marcar revisado não modifica o banco de conteúdo ou a pontuação.
- **Anfitrião:** transferência para membro humano do mesmo servidor; assumir após saída confirmada. A consulta é periódica e por REST, sem exigir intent privilegiado. Fechar o aplicativo ou ficar invisível não significa sair do servidor.
- **Recuperação:** checkpoint após transições/pontos e a cada cinco segundos se houver dados novos. Confirmação para retomar em até 24h, baralho/placar/opções preservados e rodada sem acerto anulada. Recibos reconciliam um acerto cuja partida ainda não tinha sido salva. Dados incompatíveis/corrompidos são isolados; pontos não são zerados.
- **Armazenamento limitado:** revisão de até 50 rodadas, histórico de até sete dias/500 partidas/32 MiB, checkpoints até 512 KiB, 200 participantes e 50 partidas abertas. Contextos de mensagem ficam até sete dias e são limitados a 20 mil após a limpeza. Os totais globais permanecem.

## Ativar monitoramento externo quando o Railway voltar

O painel **Controles → Estado do bot** já está no código. Moderadores veem backup/armazenamento; os logs avisam ao atingir 70% e 90% de uso do filesystem, ou menos de 16 MiB livres. O servidor HTTP usa `PORT`, com 8080 como padrão. `/health` indica vida do processo; `/ready` retorna 200 quando Gateway/banco estão disponíveis e o armazenamento não está crítico, ou 503 caso contrário. Nenhum endpoint expõe jogadores, token ou caminhos.

Para uma verificação de fora da hospedagem:

1. No serviço Railway, habilitar um domínio público em Networking apontando para PORT/8080. Isso ainda não pôde ser feito pela máquina de desenvolvimento: a plataforma está indisponível e não há acesso administrativo via API aqui.
2. Abrir `https://SEU_DOMINIO/ready` e confirmar `{"status":"ready"}` depois do bot conectar.
3. No GitHub do repositório, em **Settings → Secrets and variables → Actions → Variables**, criar **`BOT_HEALTH_URL`** com essa URL HTTPS completa. É uma URL pública, não o token do bot.
4. Executar uma vez o workflow **Bot availability** por **Run workflow**. Depois ele é agendado a cada 15 minutos (agendamento de melhor esforço do GitHub), com três tentativas antes de falhar.

O workflow fica sem executar o job enquanto a variável não existir. Notificações de falhas dependem das preferências de Actions do proprietário; não há DMs automáticas. Essa ativação e a primeira consulta externa bem-sucedida continuam pendentes da URL pública. O código e os testes do monitor já estão preparados.

A consulta de variáveis de Actions pela integração disponível retornou HTTP 403 (`Resource not accessible by integration`). A variável não foi configurada por esta entrega; o procedimento acima usa a interface do proprietário no GitHub.

Novos comandos, site/leaderboard, idiomas, configurações gerais, updates logs e integração entre comunidades seguem no planejamento de `docs/roadmap.md`. Não precisam entrar para concluir a versão atual.

## Limites conhecidos

Primeiro significa o primeiro acerto válido processado pelo bot; a rede pode afetar a ordem. Antifarm não impede consulta à wiki, automação externa ou várias contas. A máquina de desenvolvimento não tem acesso ao computador do proprietário nem acesso administrativo ao Railway. Queda de conexão preserva o relógio; reinício recupera a partida mediante confirmação e anula rodada sem vencedor. Uma restauração do arquivo inteiro de backup volta ao instante daquele snapshot.
