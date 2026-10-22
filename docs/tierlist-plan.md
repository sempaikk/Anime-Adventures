# Escopo aprovado — imagem e tópico

Este documento registra a decisão mais recente de cada ponto. Substitui os fluxos
antigos de canais separados, adesão individual, quiz, notas e filtros.

## Interface e comandos

- Somente `/tierlist` e `/chatglobal`, sem argumentos. Chat global permanece inativo.
- `/tierlist` é exclusivo de Administrador/Gerenciar servidor, com permissão
  padrão do Discord e validação na execução. Membros veem a imagem, votam,
  sugerem retratos e consultam Meus envios pelos botões do tópico.
- Um painel oficial por servidor: mensagem permanente somente PNG, sem legenda
  ou botões. Enquetes temporárias aparecem no mesmo canal para facilitar o voto.
- Um tópico público ligado à imagem: resultados, revisões e histórico. Enquetes
  antigas já abertas no tópico terminam no local original.
- Índice editado no tópico: regras, situação real da análise, proposta aberta,
  última mudança e envio de imagens. A classificação aparece somente no PNG,
  sem exportação textual de posições. O TXT retratos-pendentes.txt é somente
  uma lista dinâmica para contribuir com fotos, sem tier ou força; desaparece
  quando não há pendências.
- Configuração/diagnóstico privado; sem menus de escolher canais de análise,
  adesão individual ou avisos de consentimento publicados pelo bot. O aviso aos
  participantes fica por conta da administração do servidor.
- Reutilização do painel/tópico em execuções concorrentes; recuperação de
  reinício, arquivamento e mensagens apagadas com instruções claras.
- PNG com arte original, Meta/Damage/Support/Buff/Farm, ordem esquerda→direita, linhas
  expansíveis e sem rodapé técnico. A data fica no índice; versões e contadores
  ficam no diagnóstico exclusivo do dono.
  Formas sem avaliação não são colocadas em E. Sem descrição ALT de ponto.

## Análise e fontes

- Coletar mensagens novas relevantes de humanos nos canais acessíveis ao bot;
  sem DMs, webhooks ou retransmissão. Fazer uma leitura inicial automática e
  limitada de até dez canais públicos, mil mensagens e vinte relatos, sem novo
  comando, botão de confirmação ou exportação pelo ADM.
- Usar 09/03/2025 como limite inferior provisório documentado na wiki (Update 20;
  a entrada posterior 20.4.1 está sem data). Preservar a data original e verificar
  compatibilidade por conteúdo; idade não determina validade. Retenção de sete
  dias após a coleta, deduplicação e até três tentativas de leitura interrompida.
- Registrar leitura concluída para não repetir no reinício; serializar leituras,
  conferir permissões em andamento, ignorar texto editado/apagado durante a
  consulta e cancelar o trabalho antes de fechar o banco. Estado privado do ADM.
- Pré-filtro local de unidades e contexto do jogo; IA confirma relevância.
- Deduplicação, limites por pessoa/servidor, fila justa e orçamento gratuito.
- Critérios: contribuição real para o time, custo, condições, funções,
  limitações, formas e atualizações; atributo isolado/popularidade não basta.
- Uma mudança explícita por proposta, argumento, condições, ressalva, fontes e
  antes/depois. Conflitos e fontes insuficientes preservam a classificação.
- Citações literais e números verificados, proteção contra instruções maliciosas,
  sem ferramentas ou controle direto do Discord pelo modelo.
- Wiki com revisões e hashes, sincronização periódica limitada e cache íntegro;
  diferenciar material antigo, novo e indisponível. Não inventar rankings,
  retratos, estatísticas ou aprendizado permanente do modelo.
- Estabilidade: exigir novas evidências para reabrir comparações recentes.

## Votações e revisão

- No máximo uma proposta global por hora. Dez minutos a partir da primeira
  publicação confirmada; cópias compartilham o mesmo prazo.
- Índice mostra a próxima disponibilidade de análise, relatos aguardando,
  análise em andamento, proposta pronta e prazo da votação atual. Horários
  relativos nativos do Discord, preservados no reinício; não prometer uma
  enquete por hora nem consumir IA para atualizar a contagem.
- Aprovar / Manter / Precisa de mais testes; mínimo cinco contas e dois terços
  a favor. Um voto por conta na rede; troca permitida até o prazo.
- Durante a votação mostrar só participantes; escolhas agregadas ao encerrar.
- Registro e publicação atômicos/idempotentes; comparar versões da classificação
  e fontes, recusar mensagens/votos falsificados ou vencidos.
- Resultado edita a própria proposta, mantendo histórico no tópico. Aprovação
  atualiza o PNG; rejeição/testes/ausência de votos preservam posições.
- Ao encerrar, salvar a proposta e o resultado no tópico; manter o aviso no
  canal por dois minutos e removê-lo somente após conferir o histórico e a
  identidade da mensagem. Reinício retoma a limpeza; falhas preservam o aviso.
- Confirmar uma cópia real da votação antes da apuração, inclusive após
  desconexão. API incerta adia a decisão sem renovar o prazo. Exclusões por
  moderação não criam novas cópias votáveis. Sem ping coletivo.
- Botão Sinalizar problema com motivo e revisão privada pelo responsável.
- Reversão emergencial restrita ao responsável, com justificativa pública,
  preservação de histórico e invalidação de propostas incompatíveis.

## Imagens da comunidade

- Catálogo ativo inicial: 524 formas, 453 retratos e 71 pendências. Excluir as
  25 formas com silhueta azul substituta excluídas pelo critério do dono, incluindo
  Gravity Hero apesar do retrato antigo. Preservar registros históricos e
  impedir reativação pela wiki/cache, propostas, coleta ou reversão.
- Manter a lista pública de fotos pendentes no índice do tópico. Remover uma
  solicitação somente após aprovação válida; restauração e arquivos inválidos
  podem recolocá-la. Não acrescentar exportação textual da classificação.
- Formulário no tópico: identidade/forma/skin, motivo, retrato e print opcional.
- Validar arquivo real, tamanho, resolução, animação, metadados e armazenamento;
  limitar spam e duplicatas antes de baixar/processar e novamente ao registrar.
  Sem executar arquivos ou buscar URLs arbitrárias.
- Comparação privada com imagem atual; aprovação/rejeição pelo responsável.
- Preparar enquadramento/transparência sem inventar detalhes ou trocar formas;
  remoção de fundo uniforme opcional e revisável.
- Preservar versão anterior e fonte; permitir desfazer. Mídia aprovada atualiza
  todos os painéis sem alterar posições ou fingir novo balanceamento.
- Conferir hash da mídia aprovada; preservar a atual se o predecessor da
  restauração estiver corrompido. Detectar reparo de arquivo sem alterar posições.

## Operação e aceitação

- SQLite migrado preservando classificações/votos existentes, retenção limitada,
  backup validado e procedimento de restauração testado, incluindo arquivos de mídia.
- Proteções de espaço, uso de memória, cotas, erros de rede e segredos; diagnóstico
  privado e estado discreto no índice, sem mensagens repetidas de indisponibilidade.
- Testes de aprovação/rejeição/empate/testes/poucos votos, concorrência, chamadas
  simuladas, permissões, identidade, reinício, fonte alterada e restauração.
- Validação real no Discord/Groq é distinta da suíte local e do GitHub; nunca
  declarar integração ou desempenho em produção confirmados apenas por mocks.
- Manter as limitações e verificações de estreia documentadas. Não prometer
  detecção perfeita de contas alternativas ou correção semântica absoluta.
- Verificação completa privada: suíte com banco temporário, credenciais removidas
  e rede externa bloqueada; registro real de comandos, tópico técnico separado,
  imagem, componentes, arquivamento/retomada e resposta real da Groq.
- Relatório distingue isolado/real/não testado. Um clique humano passa pelo
  callback de voto com banco temporário, sem fabricar votos públicos.
- Encerramento cancela verificações/subprocessos antes de fechar o estado.
- Ajuda contextual privada para jogadores; conferência do próprio painel para
  administradores, sem expor banco, chave, orçamento ou controles do dono.
- Demonstração visual exclusiva do dono, com dez etapas e reprodução automática;
  arquivos recebidos do Discord comparados aos enviados. Usa somente estado
  temporário. Testes da API criam tópico privado, sem fallback público.
- Verificador repete cinco transições de retratos/TXT no Discord real usando
  banco isolado. Índice apagado é reparado; confirmação perdida não duplica
  mensagens e a recuperação publica a lista mais recente.

## Interface e categorias por função

- Cards públicos e privados usam Components V2: Containers, Sections, TextDisplay,
  Separators, MediaGallery, File e ActionRow; a mensagem permanente segue só PNG.
- Textos mantêm prazo e decisão visíveis. Títulos, negrito, citações e texto de
  apoio organizam a leitura. Spoiler fica reservado ao glossário opcional.
- Ícones originais têm ID e nome conferidos na aplicação. Classificação e prazo
  recebem ícones correspondentes; falta de ícone adequado deixa só o texto.
- Modal de retrato tem cinco Labels e upload nativo. Informa revisão privada e
  acompanhamento em Meus envios. Nenhum anexo altera a imagem sem aprovação.
- Cada forma tem uma avaliação: tier META com função principal, ou a própria
  função DAMAGE/SUPPORT/BUFF/FARM. Meta aparece nas duas linhas por projeção,
  sem duplicar votos, catálogo, pendências de foto ou decisões.
- Meta ocupa primeiro a sua função, preservando a ordem relativa; as demais
  funções são grupos de uso e não notas de força entre si. Support é controle
  e debuff; Buff é melhoria de aliados; Farm é economia; Damage é dano.
- Notas antigas continuam no histórico. A migração não adivinha funções e não
  restaura uma grade incompatível durante uma correção.

A proposta de usar a Wiki como base inicial por modo é uma decisão posterior
a esta revisão. A implementação atual ainda forma posições por votação. A
fonte coletada distingue Infinite e Casual, e avisa que pode estar imprecisa;
uma importação futura precisa identificar revisão, modo e origem das posições.
