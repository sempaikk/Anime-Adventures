# Estreia e verificação na hospedagem

## Caminho curto para quem cuida do bot sozinho

1. No Bot-Hosting.net, confirme **Python 3.12**, **`bot.py`**, pull automático e as variáveis já cadastradas: `DISCORD_TOKEN`, `GROQ_API_KEY` e `DATA_DIR=./state`. Reinicie após a atualização do GitHub. Não recrie a implantação nem apague `state`.
2. Habilite **Message Content Intent** no Developer Portal. No canal de texto, confira Ver canal, Enviar mensagens, Ler histórico, Inserir links, Anexar arquivos, Criar tópicos públicos e Enviar mensagens em tópicos.
3. Como administrador, use **`/tierlist`**. O resultado público deve ser uma imagem e o tópico **Votações e histórico**. A confirmação e os controles são privados. Não há seleção de canais de análise ou confirmação individual de participação.
4. Como responsável pelo aplicativo, clique **Verificação completa** na confirmação privada e aguarde o relatório. Administradores dos servidores recebem somente o diagnóstico.
5. Clique **Confirmar teste de interação** no relatório. Um clique real passa pelo código de voto com banco temporário. Não reúne cinco jogadores nem altera a votação global.

O bot testa registro real dos comandos, envio/leitura/edição de imagem, componentes, criação/arquivamento/retomada de tópico e resposta real da Groq. Uma conexão válida recente pode ser reutilizada para não consumir outra chamada. Existe intervalo de cinco minutos entre verificações completas.

Um tópico **Verificação técnica · temporária** aparece durante o teste, separado da classificação/histórico. O bot apaga suas próprias mensagens; com Gerenciar tópicos, apaga também o tópico vazio. Se alguém tiver escrito nele, preserva a conversa e arquiva. Sem essa permissão, o tópico técnico vazio permanece arquivado.

Baixe `verificacao-tierlist.json` para acompanhar falhas. O relatório diferencia isolado, Discord real, Groq real e não testado. A suíte roda com credenciais removidas, importação de `.env` desativada, rede externa bloqueada e estado temporário. Falha não é escondida como aprovação. Uma interrupção cancela o subprocesso antes de fechar o banco.

## O que observar na interface

- Somente `/tierlist` e `/chatglobal`, sem campos adicionais. Chat global responde **Em breve.**
- Uma imagem oficial por servidor. Repetir `/tierlist`, até em outro canal, reutiliza a imagem existente. A consulta de um membro é privada.
- O tópico tem índice, classificação textual, Sugerir imagem, propostas, resultados e revisões. A mesma proposta é editada com o encerramento.
- Ninguém é classificado só para preencher a grade. **Sem avaliação** é diferente de E. O horário do rodapé é o da classificação aprovada; trocar retrato atualiza somente a revisão de mídia.
- Votos abertos mostram participantes, sem distribuição. Encerrados revelam os totais. A conta tem um voto na rede; trocar não soma outro.
- O formulário pede personagem/forma exatos e aceita arquivos estáticos validados. A imagem só é substituída após revisão do responsável. Meus envios mostra o andamento em particular.

A verificação por API não reproduz a tela de uma pessoa. Uma olhada em celular/computador e, quando possível, o envio de uma sugestão real continuam úteis. **Não é necessário executar manualmente centenas de testes ou inventar cinco contas.** Disputa, reinício, rejeição, empate, poucos votos e adulterações já são exercitados em bancos isolados.

## Quando algo não funcionar

| Situação | Interpretação e ação |
| --- | --- |
| Chave carregada, sem teste válido | A variável existe, mas falta uma resposta real. Use Testar conexão da IA ou Verificação completa. |
| Cota ou orçamento atingido | O bot mantém posições e espera a próxima janela. Confira a conta Groq Free; não precisa ativar cobrança. |
| Wiki indisponível | O último conjunto válido continua em cache. Não significa consulta em tempo real ao jogo. |
| Nenhuma proposta | Sem relato relevante e fonte suficiente, não há enquete obrigatória. A classificação inicial pode permanecer vazia. |
| Tópico arquivado | O bot tenta retomar um tópico destrancado. Se estiver trancado, a administração precisa destrancar. |
| Mensagem do painel apagada | Use `/tierlist` novamente. O bot informa se é preciso repetir a criação. |
| Tópico original apagado, imagem existente | O Discord pode impedir outro tópico na mesma mensagem. Apague somente a imagem antiga do bot e execute `/tierlist` novamente, conforme a instrução privada. |
| Botão privado venceu ou veio de outra pessoa | Abra seus próprios controles usando `/tierlist`. |
| Falta de espaço ou backup falhou | Confira Diagnóstico e o disco. Não apague o banco. Exporte a cópia anterior completa antes de mexer na hospedagem. |
| Comandos antigos no cliente | Atualize o Discord após a sincronização. O teste real verifica os comandos registrados na API. |

## Primeira votação e persistência

Os comentários relevantes são identificados nos canais acessíveis ao bot, fora do próprio painel/tópico. A administração informa esse funcionamento aos membros. Não é preciso compartilhar dados pessoais ou enviar comentários artificiais para provocar posições.

Uma proposta real precisa de fonte, condições e ressalva. A votação dura dez minutos desde a primeira publicação confirmada, no máximo uma por hora. Menos de cinco participantes, aprovação abaixo de dois terços ou pedido predominante de mais testes preservam o ranking. O responsável pode revisar um problema e reverter publicação incorreta com justificativa pública.

Reiniciar preserva prazos, votos, classificação e retratos aprovados. Não execute duas instâncias. Confirme que `state` continua após reiniciar e exporte uma geração de backup inteira, incluindo `manifest.json` e `media/`. A restauração offline está no README e é coberta pela suíte.

## Limites da validação fora da produção

A suíte local e o GitHub validam o código com APIs simuladas. O ensaio de capacidade compôs os 549 lugares usando posições artificiais apenas fora da produção: aproximadamente 4 MB de PNG. Isso não mede carga simultânea de todos os servidores nem garante os limites de memória específicos da hospedagem.

O ambiente de desenvolvimento não confirmou acesso autenticado à API do Discord e não tem a chave Groq cadastrada na hospedagem. Os testes reais são executados pelo botão **Verificação completa** no próprio bot e registrados no relatório. Uma suíte verde não substitui essa confirmação de produção.
