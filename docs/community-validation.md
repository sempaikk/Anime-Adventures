# Verificação antes de abrir a comunidade

A validação local não publica mensagens e não substitui este teste com dois servidores de teste. Use participantes informados de que as mensagens serão compartilhadas entre os dois canais.

1. Reinicie no Bot-Hosting.net, confira Python 3.12, `bot.py` e logs sem falhas. Confirme que aparecem os novos comandos e que `/adventures` saiu da lista após a atualização dos comandos globais do Discord.
2. Ative um canal de tier list em cada servidor, um com alcance do servidor e outro global. O painel inicial deve mostrar unidades em avaliação, retratos disponíveis e pendências explícitas. Teste navegar, detalhes de formas parecidas e Atualizações em computador e celular.
3. Faça uma avaliação local, confira que ela não aparece nos detalhes globais e apague-a com `/privacidade`. Não use votos fictícios para inflar uma classificação pública. Os limiares de cinco pessoas e três servidores são testados automaticamente; o teste real pode usar participantes de teste em ambiente isolado.
4. Ative os dois canais globais. Escreva antes de confirmar: a original permanece só no servidor de origem. Confirme com a conta correta: o bot publica a cópia local e depois a remota. Outro participante não consegue confirmar em seu lugar.
5. Após confirmar, escreva normalmente. Verifique autoria, origem, ausência de ping com `@everyone`, limite de tamanho, intervalo entre mensagens e preservação local de anexos. Confira que mensagens de outros bots não geram ciclos.
6. Remova temporariamente Gerenciar mensagens: a cópia pode ser enviada, mas a original permanece. Retire Enviar mensagens de um destino: o outro continua recebendo. Restaure as permissões e confira os logs. Permissões inválidas na configuração devem ser recusadas.
7. Use `/global sair`, tente escrever e confira a nova confirmação. Use `/global apagar` no código de uma mensagem própria, verifique remoção nos dois servidores e recusa quando outra pessoa tenta apagar. Teste Sinalizar e consulte a denúncia com a moderação da rede.
8. Desative um canal global e confira que ele deixa de receber. Administrador local não deve conseguir usar comandos de moderação da rede ou curadoria global sem autorização.
9. Reinicie a implantação: configurações, consentimentos, avaliações e painel salvo devem sobreviver. Registre o caminho `./state/community.sqlite3`. Não recrie ou exclua a implantação para testar persistência.
10. Verifique o intervalo de 30 ou 60 minutos sem mensagens duplicadas de painel; a data deve permanecer a da última mudança real. Confira RAM e disco no painel, download de backup e lembrete de renovação gratuita.

Limites desta primeira versão: interpretação de comentários livres por IA, comparação textual automática entre duas unidades, imagens ausentes, propagação de edição/respostas e importação do histórico para novos servidores não são recursos implementados. Não anunciar o bot como IA autônoma que entende conversas. A curadoria explícita e as avaliações estruturadas já permitem iniciar a comunidade sem esses recursos.
