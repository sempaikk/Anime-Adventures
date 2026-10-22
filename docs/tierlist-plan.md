# Escopo aprovado — imagem e tópico

Este documento registra a decisão mais recente de cada ponto. Substitui os fluxos
antigos de canais separados, adesão individual, quiz, notas e filtros.

## Interface e comandos

- Somente `/tierlist` e `/chatglobal`, sem argumentos. Chat global permanece inativo.
- Um painel oficial por servidor: somente PNG, sem embed ou botões públicos.
- Um tópico público ligado à mensagem: propostas, votos, resultados e histórico.
- Índice editado no tópico: regras, situação real da análise, proposta aberta,
  última mudança, versão textual da classificação e envio de imagens.
- Configuração/diagnóstico privado; sem menus de escolher canais de análise,
  adesão individual ou avisos de consentimento publicados pelo bot. O aviso aos
  participantes fica por conta da administração do servidor.
- Reutilização do painel/tópico em execuções concorrentes; recuperação de
  reinício, arquivamento e mensagens apagadas com instruções claras.
- PNG com arte original, Meta/S/A/B/C/D/E, ordem esquerda→direita, linhas
  expansíveis e sem rodapé técnico. A data fica no índice; versões e contadores
  ficam no diagnóstico exclusivo do dono.
  Formas sem avaliação não são colocadas em E. Sem descrição ALT de ponto.

## Análise e fontes

- Coletar apenas mensagens futuras relevantes de humanos nos canais de texto
  acessíveis ao bot; sem DMs, webhooks, leitura histórica ou retransmissão.
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
- Aprovar / Manter / Precisa de mais testes; mínimo cinco contas e dois terços
  a favor. Um voto por conta na rede; troca permitida até o prazo.
- Durante a votação mostrar só participantes; escolhas agregadas ao encerrar.
- Registro e publicação atômicos/idempotentes; comparar versões da classificação
  e fontes, recusar mensagens/votos falsificados ou vencidos.
- Resultado edita a própria proposta, mantendo histórico no tópico. Aprovação
  atualiza o PNG; rejeição/testes/ausência de votos preservam posições.
- Botão Sinalizar problema com motivo e revisão privada pelo responsável.
- Reversão emergencial restrita ao responsável, com justificativa pública,
  preservação de histórico e invalidação de propostas incompatíveis.

## Imagens da comunidade

- Formulário no tópico: identidade/forma/skin, motivo, retrato e print opcional.
- Validar arquivo real, tamanho, resolução, animação, metadados e armazenamento;
  limitar spam e duplicatas. Sem executar arquivos ou buscar URLs arbitrárias.
- Comparação privada com imagem atual; aprovação/rejeição pelo responsável.
- Preparar enquadramento/transparência sem inventar detalhes ou trocar formas;
  remoção de fundo uniforme opcional e revisável.
- Preservar versão anterior e fonte; permitir desfazer. Mídia aprovada atualiza
  todos os painéis sem alterar posições ou fingir novo balanceamento.

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
