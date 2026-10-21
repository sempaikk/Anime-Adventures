# Teste final no Discord

O código de `/adventures` está fechado para esta etapa. A suíte offline verifica a lógica; este roteiro confirma o cliente Discord, as permissões e o volume real. Não foi executado durante a indisponibilidade do Railway.

## Preparação

Quando o Railway liberar builds, confirme que o novo deployment usa o commit mais recente de `main`. Se precisar iniciar manualmente, abra **Ctrl+K / Cmd+K → Deploy Latest Commit**. **Restart** mantém o código atual; **Redeploy** repete a versão do deployment selecionado.

O volume em `/data`, `DATA_DIR=/data` e a réplica única já foram confirmados pelo proprietário. Não é preciso refazer essa configuração.

Use um canal de teste, duas pessoas e, se possível, computador e celular. A segunda pessoa deve começar sem permissão de moderação. Os pontos obtidos são reais; este roteiro não apaga nem restaura o banco.

## Uma sessão de validação

| Etapa | O que fazer | O que conferir |
| --- | --- | --- |
| Preparação | Abrir `/adventures`, conferir menus e **Mais opções**. Pedir que a segunda pessoa tente mudar uma opção. | O resumo acompanha a seleção; só o anfitrião configura e inicia. Mensagens de orientação ficam privadas. |
| Imagens e texto | Em **Mais opções**, escolher **Imagens** e todos os níveis. Reconhecer uma unidade; tentar nome atual, antigo ou do anime cadastrado para a mesma forma. Consultar **Como jogar** e **Placar**. | A imagem aparece antes da resposta, com descrição `.`. Ajuda e pontos são privados. Não há nomes do anime usados como perguntas de biografia. |
| Alternativas e disputa | Encerrar essa partida e abrir outra com **Alternativas**. Em uma rodada, uma pessoa erra e tenta clicar de novo. Em outra, as duas tentam acertar juntas. | A escolha errada não pode ser trocada. Só um vencedor e um ponto por rodada. Abrir ajuda não bloqueia a resposta. |
| Pausa e controles | Pausar durante uma pergunta; esperar, tentar responder e retomar. Transferir o anfitrião em **Controles**, depois testar os botões com as duas pessoas. | Tempo congelado, respostas bloqueadas e tempo restante preservado. O novo anfitrião assume; o anterior perde o controle se não for moderador. |
| Resultado e avisos | Ver **Meu desempenho**. Em um resultado antigo, usar **Sinalizar pergunta** com um relato longo, deixando o detalhe principal no fim. Como moderador, abrir **Controles → Revisar avisos** e marcar revisado. | Revisão privada com resposta/imagem/fonte. O relato aparece completo, até 400 caracteres. A fila vazia fica explícita. Um resultado antigo permite consulta, sem controlar a rodada nova. |
| Encerramento | Em uma partida, pedir encerramento com a pergunta ativa; em outra, deixar uma rodada sem nenhuma tentativa. Usar **Jogar de novo**. | A pergunta ativa termina antes de encerrar. Sem tentativa, a partida acaba na primeira rodada. O canal fica livre para outra partida. |
| Pontos e reinício | Anotar o total global. Com uma partida em andamento, reiniciar o serviço uma vez; retomar pelo painel salvo e consultar o total. Depois de um novo deploy, consultar novamente. | Total preservado, configurações/placar recuperados. Rodada interrompida sem vencedor é anulada. Repetir a mesma pergunta dentro de 24h vale na partida, sem outro crédito global. |

Escolher o mesmo assunto/formato ajuda a reencontrar uma pergunta para conferir o antifarm; o sorteio não garante repetição imediata. As durações 10/20/30/contínua, expirações, concorrência e falhas de rede também são cobertas offline. Não é necessário esperar todos os prazos longos para concluir este teste de uso.

Se algo falhar, registrar a ação, o texto da pergunta e o resultado esperado; uma captura do painel ajuda. Não compartilhar token, banco de pontos ou arquivos privados. Animação, tamanho e quebra de linhas podem variar entre clientes do Discord.

## Operação após o teste

Os detalhes de backup, exportação privada e ativação do monitor externo estão em [release-checklist.md](release-checklist.md). A URL pública de `/ready` e a variável `BOT_HEALTH_URL` ainda precisam ser configuradas para o monitor externo funcionar. Novos comandos e o site continuam na etapa seguinte.
