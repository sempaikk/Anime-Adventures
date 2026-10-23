# Estreia e verificação na hospedagem

## Recomendação para lançar esta versão

O fechamento atual está em [tierlist-launch-review.md](tierlist-launch-review.md):
catálogo ativo, lista dinâmica de retratos, proteções de envio e recuperação,
testes locais e ensaio real no Discord. Abaixo ficam os passos de operação
e os registros das verificações anteriores.

A recomendação é uma estreia beta em um a três servidores, sem esperar por
chat global ou novos módulos. O núcleo já tem testes isolados e validação real
de Discord/Groq; a carga e o comportamento de comunidades reais precisam ser
observados nessa estreia. Não há garantia de ausência total de erros.

Antes da divulgação geral:

1. Atualizar/reiniciar a hospedagem e conferir a permissão padrão de `/tierlist`.
   O verificador também valida essa permissão no registro real do Discord.
2. Conferir a visão de um membro: ler a imagem e o tópico, votar, consultar
   Como funciona, enviar retratos e abrir Meus envios; sem controles do dono.
   Conferir a enquete temporária no canal e o resultado completo no tópico.
   Após dois minutos, o aviso só sai do canal com o histórico confirmado.
3. Reunir ao menos cinco participantes reais para aprovar as primeiras posições.
   A lista começa com uma referência parcial identificada da Wiki; revisões dependem de relatos válidos e propostas fundamentadas;
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

## Fechamento da preparação para a estreia

Esta é a revisão completa das prioridades; o critério de conclusão é qualidade
da experiência e da operação, em vez de acrescentar funcionalidades sem fim.

- **Imagem e catálogo inicial:** há 529 formas ativas, 458 retratos e 71 formas
  sem retrato aprovado. As 26 formas com silhueta azul substituta informadas
  excluídas pelo critério do dono estão fora da análise, inclusive Gravity Hero
  apesar da foto antiga e Illusionist (Chrysalis), encontrado na revisão visual.
  O catálogo bruto e os históricos ficam preservados.
  Conferir retrato, evolução e legibilidade de todos os personagens
  que entrarem na classificação da estreia. Priorizar essas formas na revisão;
  uma imagem genérica ou de outra evolução não resolve a pendência. O índice
  oferece retratos-pendentes.txt, atualizado pelas aprovações e restaurações;
  esse arquivo não exporta a classificação.
- **Interface dos membros:** imagem permanente e enquetes temporárias no canal,
  decisões no tópico e ajuda privada. Ampliar pelo visualizador no celular. Confirmar
  que uma pessoa nova entende o sentido esquerda→direita, o voto, o resultado
  e o andamento de seu envio. Os controles de diagnóstico continuam privados.
- **Qualidade das decisões:** observar as primeiras propostas reais com
  jogadores experientes. A explicação precisa separar vantagem, condições,
  limitação e fonte da forma exata. Testes de código e confiança declarada pelo
  modelo não comprovam o balanceamento. A data final de 20.4.1 segue sem
  confirmação no trecho consultado da wiki.
- **Administração:** instalação com permissões mínimas e um `/tierlist`.
  Reinícios retomam o conjunto existente. O ADM consulta Conferir painel para
  entender falta de acesso; não recebe ferramentas de revisão global do dono.
- **Proteções e recuperação:** respeitar exclusão/edição, troca de permissão,
  conta duplicada na votação, limites e restauração de dados. A revisão fechou
  o reaproveitamento de contexto já processado sem acesso ao canal e verifica
  novamente o acesso ao retornar da IA, antes de aceitar a proposta.
  A suíte com essas duas regressões passou em **423 testes locais**.
- **Operação do dono:** acompanhar fila de relatos, cota local diária UTC,
  imagens/relatos pendentes e backup pelo diagnóstico privado. Manter cópia
  completa fora da hospedagem. Esses indicadores não garantem monitoramento
  externo enquanto o bot estiver totalmente desligado.
- **Piloto de lançamento:** usar um a três servidores durante 24–48 horas para
  observar votos, qualidade dos argumentos, edições da imagem, memória/CPU e
  cotas. Formar as primeiras posições com votos reais antes da divulgação
  ampla. O piloto é a validação que a suíte isolada não substitui.

Com esses critérios atendidos, a recomendação é encerrar a preparação da
primeira versão e corrigir os problemas observados no uso real. Chat global,
site e outros módulos continuam no planejamento posterior.

## Caminho curto para quem cuida do bot sozinho

1. No Bot-Hosting.net, confirme **Python 3.12**, **`bot.py`**, pull automático e as variáveis já cadastradas: `DISCORD_TOKEN`, `GROQ_API_KEY` e `DATA_DIR=./state`. Reinicie após a atualização do GitHub. Não recrie a implantação nem apague `state`.
2. Habilite **Message Content Intent** no Developer Portal. No canal de texto, confira Ver canal, Enviar mensagens, Ler histórico, Inserir links, Anexar arquivos, Criar tópicos públicos e Enviar mensagens em tópicos.
3. Como administrador, use **`/tierlist`**. O resultado público deve ser uma imagem e o tópico **Votações e histórico**. Enquetes válidas aparecem temporariamente no mesmo canal; o resultado completo permanece no tópico. A confirmação e os controles são privados. Não há seleção de canais de análise ou confirmação individual de participação.
4. Como responsável pelo aplicativo, clique **Verificação completa** na confirmação privada e aguarde o relatório. Administradores recebem **Conferir painel**, sem informações técnicas globais.
5. Clique **Confirmar teste de interação** no relatório. Um clique real passa pelo código de voto com banco temporário. Não reúne cinco jogadores nem altera a votação global.

O bot testa registro real dos comandos, envio/leitura/edição de imagem, componentes, criação/arquivamento/retomada de tópico e resposta real da Groq. Uma conexão válida recente pode ser reutilizada para não consumir outra chamada. Existe intervalo de cinco minutos entre verificações completas.

O tópico **Verificação técnica · temporária** é privado, com convite ao dono, separado da classificação/histórico. O teste exige Criar tópicos privados e não cai para um tópico público se faltar essa permissão. O bot apaga suas próprias mensagens; com Gerenciar tópicos, apaga também o tópico vazio. Se alguém tiver escrito nele, preserva a conversa e arquiva. Sem essa permissão, o tópico técnico vazio permanece arquivado. As permissões administrativas do Discord continuam valendo nos tópicos privados.

Use **Testar personagens na imagem** nos controles do dono, ou **Ver alterações de personagens** no relatório, para navegar nas dez etapas. **Executar todas** mostra entrada, ordem, mudança de tier, expansão, substituição e restauração. A mesma sequência é enviada e baixada pela verificação da API, com comparação dos arquivos. As posições são artificiais, claramente sinalizadas, e o banco oficial não é modificado.

Baixe `verificacao-tierlist.json` para acompanhar falhas. O relatório diferencia isolado, Discord real, Groq real e não testado. A suíte roda com credenciais removidas, importação de `.env` desativada, rede externa bloqueada e estado temporário. Falha não é escondida como aprovação. Uma interrupção cancela o subprocesso antes de fechar o banco.

A suíte isolada da hospedagem cobre `test_tier*.py`, `test_runtime_health.py` e
`test_storage_maintenance.py`: o bot ativo e seus recursos compartilhados.
Ela tem orçamento total de oito minutos, compartilhado pelos três processos
sequenciais. Os módulos antigos de quiz e comunidade continuam na suíte
completa executada pelo GitHub, sem consumir CPU da hospedagem ativa.
O JSON identifica esse perfil e seus padrões de seleção. Se a hospedagem não terminar nesse prazo, o relatório
mostra a quantidade de testes concluídos, conserva o progresso e identifica a
execução como incompleta. Falhas já encontradas continuam marcadas como falha;
os testes reais do Discord seguem em seguida. Um limite de tempo não comprova
que todos os testes passaram. Erros da API mostram a etapa, o status HTTP e o
código do Discord, sem incluir o corpo da resposta ou dados de autenticação.

## O que observar na interface

- Somente `/tierlist` e `/chatglobal`, sem campos adicionais. Chat global responde **Em breve.**
- `/tierlist` é restrito a Administrador/Gerenciar servidor, tanto na permissão padrão quanto na execução. Uma imagem oficial por servidor; repetir o comando, até em outro canal, reutiliza a imagem existente. Membros usam a imagem e os botões, sem comandos.
- O tópico tem índice, Sugerir imagem, Meus envios, Como funciona, propostas e resultados. A classificação fica somente no PNG. A mesma proposta é editada com o encerramento.
- retratos-pendentes.txt contém somente as formas que precisam de foto. Envios pendentes/rejeitados não diminuem a lista; uma aprovação válida diminui, e uma restauração pode recolocar a solicitação. Ao completar todas as fotos, o anexo desaparece.
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
| Nenhuma proposta | Sem relato relevante e fonte suficiente, não há enquete obrigatória. A referência inicial é preservada; formas ainda não avaliadas podem ficar fora da imagem. |
| Tópico arquivado | O bot tenta retomar um tópico destrancado. Se estiver trancado, a administração precisa destrancar. |
| Índice do tópico apagado | O bot repara automaticamente. Uma exclusão durante a desconexão é encontrada na primeira conferência após reiniciar ou na conferência periódica. |
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

## Atualização final V2 e modos — 22/10/2026

A suíte atual tem **577 testes**, com UI nativa, privacidade, anexos, seis
categorias, migração, separação por modo e referência inicial. O PNG reúne
Infinite e Casual; cada modo usa META/Good × Hill/Hybrid, Ground, Support.
Uma forma aparece uma vez em cada modo.

O ensaio direto reúne 20 etapas, com a API real em espaços privados do servidor
autorizado, com banco temporário: índice convertido na mesma mensagem, enquete
e atalhos, atualização sem duplicação, resultado arquivado, aprovação só em
Casual preservando Infinite, PNG editado e baixado, limpeza após reinício, dez
alterações visuais, cinco transições de TXT, cartões V2 e limpeza de avisos
administrativos preservando registros internos, posições e votos. Não envia dados à
Groq nem altera a produção.

Uma etapa identifica o pacote local; as demais exercitam os cenários de integração.
O fechamento acrescenta registro privado de balanceamentos, pausa persistente,
corte pela data original dos relatos, cancelamento de enquetes em andamento e
descarte de resposta da IA iniciada antes da mudança. A simulação na API confirmou
o resultado cancelado, os votos preservados e a retomada em banco temporário.
O relatório privado identifica o pacote instalado e a versão em execução;
divergência de arquivos ou falta de reinício impede aprovar essa conferência.
O relatório executado pelo dono na hospedagem ainda precisa ser conferido após
instalar esta versão. Testes diretos da API não executam o processo da hospedagem.

V2 pode guardar arquivos em File/MediaGallery e deixar a lista tradicional
de anexos vazia. O verificador lê componentes e confere bytes recebidos, sem
confundir thumbnails externos com uploads. Ator/servidor/mensagem oficial
continuam validados. Modais usam Labels e FileUpload; correção tem modo.

A referência inicial da revisão Wiki 46773 tem 71 formas ativas em Infinite
e 76 em Casual. Todas as 151 entradas foram identificadas; quatro ocorrências
são de formas retiradas. Fontes e avisos administrativos ficam internos, sem
contar como resultados da comunidade. A complementação preserva decisões,
correções e enquetes em andamento. Detalhes em tierlist-catalog-audit.md.
A fonte mantém o aviso de possível imprecisão. Arquivos/identidades não
comprovam balanceamento; a API não comprova aparência em cada cliente ou o
envio humano de arquivos. O dono pode confirmar uma interação humana pelo
verificador e conferir os primeiros argumentos com jogadores.
