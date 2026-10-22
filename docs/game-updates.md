# Quando o jogo receber um balanceamento

O processo é global e exclusivo do responsável pelo aplicativo. Os administradores
dos servidores continuam usando somente `/tierlist`; membros usam os botões.
Uma edição na Wiki não registra automaticamente uma atualização do jogo.

## Registrar a mudança

1. Abra seus controles privados de `/tierlist` e escolha **Atualizações do jogo**.
2. Escolha **Registrar atualização**. Informe o nome confirmado, a data e a hora
   em que entrou no jogo, no horário de Brasília, e o que precisa ser revisado.
3. Confira a prévia. Só **Confirmar atualização e pausar** aplica a alteração.

O registro pausa propostas, cancela enquetes ainda abertas ou na fila e conserva
os votos no resultado cancelado. Os painéis continuam mostrando a classificação
anterior; as decisões encerradas e os retratos são preservados. O tópico explica
a pausa. As enquetes canceladas recebem o motivo e seguem o arquivamento normal.
Não é criado um aviso administrativo no histórico da comunidade.

## Conferir e retomar

Confira as referências das formas e mecânicas afetadas. O módulo Names identifica
formas; ele sozinho não prova alteração de dano, habilidade ou superioridade.
Revisões da Wiki e sinais de jogadores precisam corresponder ao jogo atualizado.

Nos mesmos controles, **Retomar análise** pede que você registre o que conferiu.
O formulário recusa a confirmação se as fontes mudarem enquanto estiver aberto.
A retomada não muda posições: novas mudanças continuam passando pelas enquetes
de dez minutos, cinco participantes e dois terços a favor.

O bot mantém o corte pela data original da mensagem. Mensagens novas e histórico
com data original anterior ao corte não sustentam novas análises. Uma resposta da IA
iniciada na versão anterior é descartada mesmo se chegar depois da retomada.
Resultados anteriores deixam de compor o feedback de decisões da nova versão.
Eles continuam no histórico, com os votos preservados.

Reiniciar conserva a pausa, o corte e as posições. A referência inicial anterior
da Wiki não é reaplicada depois que uma atualização do jogo é registrada.
Formulários antigos, confirmações repetidas e confirmação/cancelamento concorrentes
não registram outra atualização nem desfazem uma atualização já confirmada.

# Conferir a versão na hospedagem

Após atualizar o conjunto completo de arquivos e reiniciar, execute
**Verificação completa** nos controles privados. A versão deste fechamento é
**2026.10.22.2**. O relatório inclui:

- versão e impressão digital do pacote;
- conferência dos arquivos de programa, dados e testes contra o manifesto;
- comparação com a versão carregada ao iniciar o processo;
- cenários isolados e testes reais da API, separados no resultado.

O manifesto não lê `.env`, tokens ou bancos de jogadores. Os detalhes ficam no
relatório privado e no diagnóstico do responsável. O relatório identifica o
pacote em execução; confirmar que ele é a versão publicada exige compará-lo ao
identificador informado na entrega. Ele não substitui os testes de permissões,
resposta da IA e entrega no Discord executados pelo próprio verificador.

Arquivos divergentes ou alterados sem reiniciar fazem a conferência falhar.
Atualize todos os arquivos e reinicie; não apague o diretório persistente.
Os administradores dos outros servidores não precisam repetir `/tierlist`.

Para manter a identificação depois de um novo desenvolvimento, rode
`python scripts/build_tier_release.py NOVA_VERSAO` após finalizar código, dados
e testes e antes de publicar. O manifesto versionado é `data/tier_build.json`.
