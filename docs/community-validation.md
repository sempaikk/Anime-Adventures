# Estreia e verificação na hospedagem

## Recomendação para lançar esta versão

A recomendação é uma estreia beta em um a três servidores, sem esperar por
chat global ou novos módulos. O núcleo já tem testes isolados e validação real
de Discord/Groq; a carga e o comportamento de comunidades reais precisam ser
observados nessa estreia. Não há garantia de ausência total de erros.

Antes da divulgação geral:

1. Atualizar/reiniciar a hospedagem e conferir a permissão padrão de `/tierlist`.
   O verificador também valida essa permissão no registro real do Discord.
2. Conferir a visão de um membro: ler a imagem e o tópico, votar, consultar
   Como funciona, enviar retratos e abrir Meus envios; sem controles do dono.
   Manter o canal principal reservado ao painel e a discussão no tópico.
3. Reunir ao menos cinco participantes reais para aprovar as primeiras posições.
   A lista começa vazia e depende de relatos válidos e propostas fundamentadas;
   apresentar como classificação comunitária em construção, sem preencher
   posições artificiais para a divulgação.
4. Publicar o aviso sobre a análise de comentários e a leitura inicial limitada
   do histórico público; informar que wiki, IA e votos comunitários podem precisar
   de correção.
5. Exportar um backup completo para fora da hospedagem. No primeiro período,
   acompanhar diariamente cota gratuita, disponibilidade, pendências de revisão
   e eventuais relatos; expandir após observar uso estável.

Para esta estreia, os controles de segurança, revisão e recuperação já fazem
parte do produto. Evitar adicionar novos comandos, painéis técnicos públicos,
aprovação automática de retratos ou aumentar a frequência das votações antes
de medir o uso real. Não há estimativa validada de capacidade para dezenas de
servidores no plano gratuito.

## Caminho curto para quem cuida do bot sozinho

1. No Bot-Hosting.net, confirme **Python 3.12**, **`bot.py`**, pull automático e as variáveis já cadastradas: `DISCORD_TOKEN`, `GROQ_API_KEY` e `DATA_DIR=./state`. Reinicie após a atualização do GitHub. Não recrie a implantação nem apague `state`.
2. Habilite **Message Content Intent** no Developer Portal. No canal de texto, confira Ver canal, Enviar mensagens, Ler histórico, Inserir links, Anexar arquivos, Criar tópicos públicos e Enviar mensagens em tópicos.
3. Como administrador, use **`/tierlist`**. O resultado público deve ser uma imagem e o tópico **Votações e histórico**. A confirmação e os controles são privados. Não há seleção de canais de análise ou confirmação individual de participação.
4. Como responsável pelo aplicativo, clique **Verificação completa** na confirmação privada e aguarde o relatório. Administradores recebem **Conferir painel**, sem informações técnicas globais.
5. Clique **Confirmar teste de interação** no relatório. Um clique real passa pelo código de voto com banco temporário. Não reúne cinco jogadores nem altera a votação global.

O bot testa registro real dos comandos, envio/leitura/edição de imagem, componentes, criação/arquivamento/retomada de tópico e resposta real da Groq. Uma conexão válida recente pode ser reutilizada para não consumir outra chamada. Existe intervalo de cinco minutos entre verificações completas.

O tópico **Verificação técnica · temporária** é privado, com convite ao dono, separado da classificação/histórico. O teste exige Criar tópicos privados e não cai para um tópico público se faltar essa permissão. O bot apaga suas próprias mensagens; com Gerenciar tópicos, apaga também o tópico vazio. Se alguém tiver escrito nele, preserva a conversa e arquiva. Sem essa permissão, o tópico técnico vazio permanece arquivado. As permissões administrativas do Discord continuam valendo nos tópicos privados.

Use **Testar personagens na imagem** nos controles do dono, ou **Ver alterações de personagens** no relatório, para navegar nas dez etapas. **Executar todas** mostra entrada, ordem, mudança de tier, expansão, substituição e restauração. A mesma sequência é enviada e baixada pela verificação da API, com comparação dos arquivos. As posições são artificiais, claramente sinalizadas, e o banco oficial não é modificado.

Baixe `verificacao-tierlist.json` para acompanhar falhas. O relatório diferencia isolado, Discord real, Groq real e não testado. A suíte roda com credenciais removidas, importação de `.env` desativada, rede externa bloqueada e estado temporário. Falha não é escondida como aprovação. Uma interrupção cancela o subprocesso antes de fechar o banco.

## O que observar na interface

- Somente `/tierlist` e `/chatglobal`, sem campos adicionais. Chat global responde **Em breve.**
- `/tierlist` é restrito a Administrador/Gerenciar servidor, tanto na permissão padrão quanto na execução. Uma imagem oficial por servidor; repetir o comando, até em outro canal, reutiliza a imagem existente. Membros usam a imagem e os botões, sem comandos.
- O tópico tem índice, Sugerir imagem, Meus envios, Como funciona, propostas, resultados e revisões. A classificação fica somente no PNG. A mesma proposta é editada com o encerramento.
- Ninguém é classificado só para preencher a grade. **Sem avaliação** é diferente de E. A imagem não tem rodapé técnico; o índice mostra a última classificação. Contadores, conexão e revisão de mídia ficam no diagnóstico do dono.
- Votos abertos mostram participantes, sem distribuição. Encerrados revelam os totais. A conta tem um voto na rede; trocar não soma outro.
- O formulário pede personagem/forma exatos e aceita arquivos estáticos validados. A imagem só é substituída após revisão do responsável. Meus envios mostra o andamento em particular.

A verificação por API não reproduz a tela de uma pessoa. Uma olhada em celular/computador e, quando possível, o envio de uma sugestão real continuam úteis. **Não é necessário executar manualmente centenas de testes ou inventar cinco contas.** Disputa, reinício, rejeição, empate, poucos votos e adulterações já são exercitados em bancos isolados.

## Quando algo não funcionar

| Situação | Interpretação e ação |
| --- | --- |
| Chave carregada, sem teste válido | A variável existe, mas falta uma resposta real. Use Testar conexão da IA ou Verificação completa. |
| Zero testes e erro de dotenv | Atualize o bot: o verificador preserva os caminhos de dependências da hospedagem mesmo usando HOME temporário. Não é necessário reinstalar ou trocar a chave. |
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

Os comentários relevantes são identificados nos canais acessíveis ao bot, fora do próprio painel/tópico. A leitura inicial do histórico público ocorre automaticamente, sem botão ou arquivo enviado pelo ADM: até dez canais, mil mensagens e vinte relatos aproveitados. O ponto de partida provisório é 09/03/2025 (Update 20 explicitamente datado na wiki; a entrada posterior 20.4.1 está sem data). Uma execução concluída não se repete no reinício. Conferir painel/Diagnóstico mostra o estado privado. A administração informa esse funcionamento aos membros. Não é preciso compartilhar dados pessoais ou enviar comentários artificiais para provocar posições.

Uma proposta real precisa de fonte, condições e ressalva. A votação dura dez minutos desde a primeira publicação confirmada, no máximo uma por hora. Menos de cinco participantes, aprovação abaixo de dois terços ou pedido predominante de mais testes preservam o ranking. O responsável pode revisar um problema e reverter publicação incorreta com justificativa pública.

Reiniciar preserva prazos, votos, classificação e retratos aprovados. Não execute duas instâncias. Confirme que `state` continua após reiniciar e exporte uma geração de backup inteira, incluindo `manifest.json` e `media/`. A restauração offline está no README e é coberta pela suíte.

Os painéis públicos e seus botões permanentes são retomados automaticamente. Não
é necessário pedir aos administradores que executem `/tierlist` a cada reinício.
Somente controles privados temporários precisam ser reabertos quando vencem.

## Limites da validação fora da produção

A suíte local e o GitHub validam o código com APIs simuladas. O ensaio de capacidade compôs os 549 lugares usando posições artificiais apenas fora da produção: aproximadamente 4 MB de PNG. Isso não mede carga simultânea de todos os servidores nem garante os limites de memória específicos da hospedagem.

Na validação de 22/10/2026, o relatório fornecido pelo dono confirmou a conexão real da Groq e os testes da API; a captura de tela confirmou um clique humano no callback de voto. Depois, uma execução direta pela API do Discord, sem outra conexão Gateway, confirmou dez mudanças visuais e o download de cada PNG em tópico privado do servidor de teste autorizado. A classificação oficial foi preservada. A falha de carregamento das bibliotecas do subprocesso foi reproduzida por teste de regressão. Após atualizar a hospedagem, rode Verificação completa para registrar o resultado da nova versão naquele ambiente. A chave Groq permanece somente na hospedagem.

O ajuste de permissões, ferramentas de membros e leitura automática passou em
**421 testes locais**, incluindo migração do banco, retenção após a coleta,
histórico de 2025, ausência/perda de permissões, deduplicação, edição/exclusão,
reinício, limites de leitura, timeout e encerramento. Um teste adicional leu
**uma mensagem real de um canal público** do servidor de teste pela API: nenhum
relato foi aproveitado nessa amostra. Usou banco temporário, nenhuma chamada
à Groq, nenhuma conexão Gateway e nenhuma publicação no Discord. Confirma o
caminho de consulta, sem afirmar validação semântica de todos os relatos reais.
