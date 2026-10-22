# Anime Adventures

O bot tem **somente dois comandos, sem argumentos**:

- **`/tierlist`** — imagem da tier list global e configuração privada em **Opções**.
- **`/chatglobal`** — responde **Em breve**. O chat global não coleta, apaga nem retransmite mensagens.

Não há tier list do servidor, formulário de notas, filtros de alcance, comandos de avaliação, configuração, moderação ou atualizações. Administradores configuram os canais de análise dentro de **Opções**. Os comandos e sistemas das versões anteriores estão arquivados, sem execução no bot atual.

## Imagem e posições

A grade segue a referência fornecida: **Meta, S, A, B, C, D e E**. O bot compõe um PNG usando os retratos originais da wiki, sem nomes sobre os quadrados e sem gerar personagens por IA. Cada linha cresce quando precisa de mais espaço. Dentro do mesmo tier, a ordem é da esquerda para a direita; passar outro personagem não exige rebaixá-lo para a linha de baixo.

Existe uma única classificação global, exibida nos servidores. Administradores usam `/tierlist` para publicar um painel que o bot edita quando uma mudança é aprovada. **No canal da tier list aparece só a imagem: sem texto, embed ou botões de histórico/configuração.** O administrador recebe a confirmação e **Opções** em uma resposta privada. Há um painel oficial por servidor; publicar em outro canal transfere as atualizações para ele. Usar o comando novamente no mesmo canal edita a imagem existente. Membros consultam a mesma lista de forma privada.

Em **Opções → Canal de votações e atualizações**, o administrador escolhe um segundo canal. As propostas, fontes, votos e resultados ficam ali, formando o histórico no próprio Discord. A proposta encerrada é editada com o resultado, sem criar mensagens de resultado duplicadas. O canal da imagem não recebe essas mensagens. O banco também guarda um histórico de mudanças do Meta; unidades abaixo dele aparecem na imagem sem ficha detalhada permanente.

A lista começa vazia de classificações. Não usamos posições fictícias para aparentar atividade, nem importamos as antigas notas de jogadores. O catálogo contém 549 identidades/formas; há 455 retratos válidos e 94 pendências. Os placeholders azuis da própria wiki foram rejeitados. Imagem ausente é indicada sem substituir por outra evolução.

## IA propõe, comunidade decide

O ciclo é **no máximo uma proposta por hora**, com uma votação global de **10 minutos**:

1. A IA interpreta comentários autorizados e consulta trechos identificados da wiki.
2. Uma proposta válida aparece em uma **nova mensagem no canal de votações e atualizações**, com comparação, condições, justificativa e links das fontes. Sem um destino configurado, a análise automática não faz chamadas ao modelo.
3. Os botões são **Aprovar**, **Manter como está** e **Precisa de mais testes**.
4. Ao encerrar os dez minutos, são necessários **pelo menos cinco participantes** e **dois terços dos votos a favor**. Empate, participação insuficiente ou pedido predominante de testes mantêm a lista.
5. A aprovação publica a nova classificação e o bot edita a imagem, sem esperar o fim da hora. O próximo ciclo só começa uma hora depois do início da proposta anterior: aproximadamente cinquenta minutos após seu encerramento.

As cópias da enquete nos servidores pertencem à **mesma votação**. Uma pessoa conta uma vez na rede inteira e pode trocar a escolha antes do prazo. Os botões verificam conta humana com pelo menos sete dias e a mensagem/canal/servidor vinculados à enquete. Votos atrasados são recusados mesmo antes da próxima atualização visual.

A votação, o prazo e os votos sobrevivem ao reinício. Aprovação e nova classificação são gravadas na mesma transação para evitar aplicação duplicada. Se a fonte da wiki ou a classificação-base mudar durante a votação, a proposta antiga não é aplicada. Propostas rejeitadas com a mesma mudança e as mesmas evidências não são repetidas por 24 horas; novas fontes podem justificar outra análise. Se não houver proposta sustentada pelas fontes, não há enquete só para preencher horário.

Resultados agregados das votações entram como contexto nas análises seguintes. Isso **não treina nem altera os pesos do modelo de IA**. Uma votação também não transforma uma alegação em estatística oficial do jogo.

## Conectar a IA sem contratar API paga

A integração usa **Groq**, com `openai/gpt-oss-120b` como modelo inicial. A documentação atual lista esse modelo no plano gratuito. O código faz somente chamadas de inferência: não contrata plano, não ativa cobrança e não troca para outro provedor se a cota acabar. **Mantenha a conta da Groq no plano gratuito, sem ativar cobrança.** Os limites e a disponibilidade são definidos pelo provedor e podem mudar.

1. Crie uma chave em <https://console.groq.com/keys>.
2. No **Ambiente** do Bot-Hosting.net, adicione **`GROQ_API_KEY`** com a chave e marque **Segredo**. Não publique a chave no chat ou GitHub.
3. Recomendado: ative **Zero Data Retention** nos Data Controls da Groq antes de usar comentários da comunidade.
4. Mantenha Python 3.12 e `bot.py`. Reinicie com o pull automático do GitHub ativado.

A assinatura do ChatGPT não fornece uma conexão permanente desta conversa ao Discord nem crédito automático para a API da OpenAI. O bot chama seu próprio modelo pela API. Sem `GROQ_API_KEY`, a parte visual funciona, mas a análise fica aguardando conexão; não são simuladas análises de IA.

A integração limita pedidos e tokens por dia, usa lotes pequenos e respeita o intervalo. Cota excedida, erro, resposta inválida ou fonte insuficiente preservam a lista e os comentários pendentes para uma tentativa posterior. Não há fallback pago. A chave precisa ser de uma conta gratuita; o código não consegue determinar nem alterar o contrato de cobrança da conta do proprietário.

Referências oficiais: [limites gratuitos](https://console.groq.com/docs/rate-limits), [modelos](https://console.groq.com/docs/models), [dados e ZDR](https://console.groq.com/docs/your-data).

## Ativar os canais, sem outro comando

1. Um administrador publica `/tierlist` no canal escolhido para o painel.
2. Na confirmação privada, em **Opções → Canal de votações e atualizações**, escolhe outro canal para propostas, votos, resultados e histórico. Não é possível escolher o canal da imagem. Para trocar o destino durante uma enquete já publicada no servidor, aguarde seu encerramento.
3. Em **Opções**, usa **Ativar análise em um canal** para selecionar conversas existentes sobre o jogo. O bot publica o aviso de funcionamento nesse canal antes de ativar a coleta. O canal da imagem não pode ser uma fonte de conversa.
4. Cada participante confirma uma vez em **Opções → Participar da análise**. Só mensagens futuras dessa pessoa nos canais ativados são consideradas.
5. Para interromper, use **Desativar análise em um canal** ou **Parar e apagar meus comentários** em Opções.

O bot precisa de **Ver canal, Enviar mensagens, Inserir links, Anexar arquivos** no painel e **Ver canal, Enviar mensagens, Inserir links** no canal de votação. Nos canais de análise, precisa ver o canal, ler histórico e enviar o aviso. Habilite **Message Content Intent** no Developer Portal. A instalação usa os escopos `bot` e `applications.commands`. Não é necessário dar Administrador ou Gerenciar mensagens ao bot. Ele não cria canais nem altera permissões de membros; configure o painel e o canal de votação como somente leitura para manter a organização. Botões continuam permitindo votar sem enviar mensagens. O terceiro canal, de chat global, fica para uma etapa futura.

Nomes, IDs do Discord e nomes dos servidores não são anexados ao pedido da IA. Menções, links, emails e padrões de telefone são removidos dos trechos antes do envio. Isso não é uma promessa de anonimização de todo texto livre: participantes devem evitar dados pessoais. O provedor recebe os trechos consentidos para inferência, com as condições de dados escolhidas na conta.

Comentários locais duram até sete dias; edição ou exclusão do original os retira de análises futuras. Registros individuais de votos duram até trinta dias. Sair da análise apaga os próprios comentários e registros de votos; resultados agregados já encerrados permanecem. Backups locais podem conter dados apagados até serem substituídos diariamente. Os comentários não são retransmitidos entre servidores.

## Verificação de fontes e limites da análise

`data/tier_evidence.json` contém 1.038 fontes de texto para as 549 identidades/formas, com revisão, URL e hash. As fontes são snapshots atribuídos da wiki, **não consultas automáticas em tempo real ao jogo ou à wiki a cada mensagem**. Para atualizar o conjunto de referência, o mantenedor executa `python scripts/build_tier_evidence.py --corpus /caminho/do/corpus` a partir de uma coleta revisada e publica a atualização.

O modelo recebe somente os trechos relevantes de um pequeno conjunto de unidades. Ele deve distinguir forma, condições, mecânicas e limitações; um atributo isolado não prova superioridade geral. O código exige IDs conhecidos, tier permitido, comentário de origem, confiança mínima, citação literal existente e fonte da própria forma. Para ultrapassar um concorrente, também exige fonte dele. Números da explicação precisam aparecer nas citações.

Comentários e páginas são dados não confiáveis, nunca instruções de execução. O modelo não recebe ferramentas, acesso ao Discord, shell ou banco. Sua resposta só pode propor uma mudança no formato esperado. Essas verificações reduzem citações e números inventados; não provam automaticamente toda interpretação semântica. A enquete existe para revisar a recomendação, inclusive quando a wiki está incompleta ou desatualizada.

## Operação

Variáveis no Bot-Hosting.net:

```dotenv
DISCORD_TOKEN=segredo_do_bot
DATA_DIR=./state
GROQ_API_KEY=segredo_da_conta_gratuita
```

O estado atual fica em `tierlist.sqlite3`, separado dos bancos anteriores. `scores.sqlite3` e `community.sqlite3` não são apagados nem importados como ranking. As versões anteriores estão em `quiz_legacy.py` e `community_legacy.py`; nenhuma fila antiga do chat global é executada. Bancos arquivados precisam ser exportados ou removidos pelo proprietário conforme a política que desejar manter para aqueles dados.

Use uma instância do bot por vez. `./state` precisa ser persistente na hospedagem; confirme com um reinício antes de depender do armazenamento. O plano gratuito da hospedagem exige renovação manual conforme as regras do provedor. A integração gratuita de IA não substitui a hospedagem.

Verificação de integridade ao iniciar, encerramento por SIGTERM, manutenção e backup SQLite validado diário em `backups/tierlist-latest.sqlite3`. Uma cópia no mesmo armazenamento não protege contra exclusão da implantação: exporte-a pelo painel. Limites de coleta, votos e retenção reduzem crescimento. A primeira instância limita painéis a 100 servidores, propostas a 256 KiB e conserva até 50 snapshots de propostas encerradas, além do histórico independente do Meta. Endpoints mínimos `/health` e `/ready` usam `PORT`, depois `SERVER_PORT`, depois 8080, sem dados de pessoas.

## Testes

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

A suíte usa SQLite temporário, composições locais de imagens e respostas simuladas das APIs. **Não chama o modelo real, não usa token de produção, não sincroniza comandos nem publica mensagens de teste.** Cobre comandos exatos sem argumentos, imagem pública sem botões, configuração privada, separação do canal de votação, chat inativo, consentimento, fontes, citações, números, orçamento, cota, propostas, prazos, votos na rede, reinício, aplicação única, ordem dos retratos, crescimento das linhas e atualização da mesma mensagem.

A validação real, após cadastrar a chave e reiniciar, está em [docs/community-validation.md](docs/community-validation.md). Até essa etapa, não considerar a integração da Groq e as permissões do Discord confirmadas em produção.
