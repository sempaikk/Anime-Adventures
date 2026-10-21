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

## Ao voltar o Railway

1. Verificar se o deploy automático usou o commit mais recente de `main`. Se necessário, abrir a paleta com **Ctrl+K / Cmd+K** e escolher **Deploy Latest Commit**. **Redeploy** repete o código/configuração do deployment selecionado; **Restart** só reinicia a versão atual. Confirmar o SHA do novo deploy.
2. Conferir volume em `/data`, `DATA_DIR=/data` e uma única réplica. O usuário já confirmou essa configuração; ainda falta observar o banco real depois de rodar esta versão.
3. Conferir nos logs caminho do banco, quantidade de perguntas, conexão com o Discord e manutenção de armazenamento. Não publicar tokens, logs com credenciais nem o arquivo de pontos em um repositório público.
4. Abrir novo `/adventures`. Jogar uma partida curta com um pequeno grupo em computador e celular, incluindo imagem, chat e alternativas. Conferir ritmo, leitura e cliques concorrentes.
5. Testar pausa/retomada, encerramento, falta de participação e jogar novamente. Depois testar 20/30 perguntas e contínua. Os testes offline cobrem essas durações; o teste real confirma o cliente e as permissões do servidor.
6. Ganhar um ponto, consultar o total, reiniciar e consultar novamente. Repetir após um novo deploy. O total deve continuar igual; repetir a mesma pergunta dentro de 24h só soma na partida.
7. Conferir uso real do volume após criar a cópia de segurança e manter uma exportação fora do Railway.

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

## Melhorias opcionais para decidir depois

- Dificuldade escolhida por curadoria, sem chamar uma unidade mítica de pergunta difícil automaticamente.
- Seleção mais específica de assuntos ou preferência por alternativas, mantendo o modo misto como padrão.
- Resumo de desempenho por assunto e revisão de erros no final, com critérios claros sobre quais tentativas contam.
- Botão para sinalizar pergunta ambígua/incorreta, com limite e fila de revisão; não apagar uma pergunta com base numa denúncia isolada.
- Definir controles quando o anfitrião sai, aviso de manutenção e eventual retomada de partidas após reinício. Hoje os pontos persistem; a partida encerra.
- Monitoramento externo de disponibilidade e alertas de armazenamento, com política de exportação de backups.

Novos comandos, site/leaderboard, idiomas, configurações gerais, updates logs e integração entre comunidades seguem no planejamento de `docs/roadmap.md`. Não precisam entrar para concluir a versão atual.

## Limites conhecidos

Primeiro significa o primeiro acerto válido processado pelo bot; a rede pode afetar a ordem. Antifarm não impede consulta à wiki, automação externa ou várias contas. A máquina de desenvolvimento não tem acesso ao computador do proprietário nem acesso administrativo ao Railway. Queda total do processo difere de desconexão: a partida encerra, embora os pontos já gravados permaneçam.
