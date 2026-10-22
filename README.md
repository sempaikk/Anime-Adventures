# Anime Adventures

Tier list global com retratos originais, análise de relatos e decisões da comunidade. **Somente dois comandos, sem argumentos:**

- **`/tierlist`** — publica o painel para administradores; membros consultam a classificação em uma resposta privada.
- **`/chatglobal`** — responde **Em breve.** Nenhuma conversa é apagada ou retransmitida por esse comando.

## Um canal, uma imagem e um tópico

O administrador usa `/tierlist` em um canal de texto. O bot publica **somente um PNG**, sem texto, embed ou botões na mensagem pública, e cria o tópico **Votações e histórico** ligado a ela. Repetir o comando reutiliza esse conjunto, inclusive quando várias pessoas executam juntas. O painel oficial existente é preservado se o comando for usado em outro canal.

O tópico contém um índice editável, propostas, votações, resultados e revisões. O índice oferece **Sugerir imagem**, **Como funciona** e atalhos para decisões recentes. A classificação é apresentada somente na imagem, sem arquivo de texto. O resultado aparece na própria proposta encerrada. O canal principal continua com a mesma imagem editada; não há botão de histórico nela nem segundo canal obrigatório.

Os retratos mantêm os pixels originais, sem ampliação artificial ou geração de personagens. A grade segue **Meta, S, A, B, C, D e E**, com ordem da esquerda para a direita e linhas que crescem. **A imagem não tem rodapé técnico.** A data da classificação fica no índice; contadores, versões e conexão ficam no diagnóstico exclusivo do dono. O arquivo não recebe a descrição artificial de ponto que causava um indicador ALT desnecessário.

O catálogo inicial tem **549 identidades/formas, 455 retratos válidos e 94 pendências**. As formas sem classificação ficam fora da imagem e não são colocadas em E. Um retrato ausente usa um marcador, sem tomar a imagem de outra evolução. A classificação inicial é vazia: não publicamos posições fictícias.

**Como funciona**, no tópico, explica em particular a leitura da imagem, votos, resultados, formas sem avaliação e envio de retratos. O dono recebe controles técnicos exclusivos. Outros administradores recebem **Conferir painel**, com links e orientações de permissões do próprio servidor, sem dados internos da IA, banco ou revisões globais.

## Análise e votação global

O bot considera **mensagens futuras** sobre Anime Adventures nos canais aos quais tem acesso. Não há seleção de canais de análise, confirmação individual, importação de conversas antigas ou avisos automáticos de participação. A administração comunica esse funcionamento à comunidade e controla o acesso do bot pelas permissões do Discord.

O filtro local identifica nomes/formas e contexto do jogo. A IA confirma se a conversa realmente trata de Anime Adventures e compara relatos com fontes da wiki. DMs, bots, webhooks, mensagens encaminhadas/citações isoladas e o próprio painel/tópico são excluídos. Editar ou apagar o original retira o relato de análises futuras; isso não desfaz automaticamente uma decisão publicada.

1. **No máximo uma proposta global por hora**, com motivo, condições, ressalva, fontes e posições antes/depois. Sem evidência suficiente, não aparece uma votação para preencher horário.
2. **Dez minutos de votação**, contados da primeira publicação confirmada no Discord. Todas as cópias compartilham o prazo.
3. **Aprovar / Manter / Mais testes.** São necessários pelo menos **cinco participantes e dois terços a favor** para publicar. Outras situações preservam a lista.
4. Uma conta conta uma vez na rede e pode trocar seu voto até o prazo. A conta precisa ter pelo menos sete dias. Durante a votação aparece somente o total de participantes; a distribuição é revelada ao encerrar.
5. Uma aprovação edita a imagem sem esperar o fim da hora. Reiniciar não apaga votos nem renova o prazo. Registro e publicação são atômicos, evitando aplicar uma aprovação duas vezes.

A IA considera contribuição para o time, custo, mecânicas, funções, condições e limitações. Popularidade ou um atributo isolado não bastam. São exigidos IDs conhecidos, a forma mencionada no relato, confiança mínima, citações literais e números presentes nas citações. Passar outro personagem no mesmo tier exige referência dele também. Fontes ou classificação-base alteradas invalidam uma proposta incompatível.

Resultados recentes entram como contexto; **isso não treina os pesos da IA** nem comprova uma estatística do jogo. Comparações recentes sem evidência nova têm uma janela de estabilidade de 24 horas. O modelo não recebe ferramentas, shell, banco ou controle do Discord. Essas restrições reduzem erros; não garantem interpretação perfeita nem impedem todas as contas alternativas.

## Wiki, retratos e revisão

`data/tier_evidence.json` inclui **1.038 referências** com revisão, URL e hash. São fontes comunitárias, não telemetria do jogo. O bot consulta a API oficial da wiki de maneira limitada: módulos de identidades/dados diariamente e artigos relevantes em lotes pequenos. Durante uma votação, a atualização das fontes é adiada. Falhas preservam o último cache válido e são indicadas no diagnóstico/índice. Uma sincronização parcial não significa que toda a wiki foi revisada naquele instante.

**Sugerir imagem** abre um formulário com personagem/forma, skin, motivo, retrato e print opcional do jogo. São aceitos PNG, JPG e WebP estáticos, até 4 MB por arquivo e quatro milhões de pixels. O processamento aplica a orientação da foto, remove metadados e limita dimensões, duplicatas, frequência e armazenamento. Não executa anexos nem busca URLs fornecidas pelo usuário.

Somente o responsável pelo aplicativo aprova ou rejeita. A revisão privada compara o retrato atual com a sugestão; um recorte de fundo uniforme pode ser experimentado e desfeito antes da aprovação. Não é uma reconstrução da arte por IA. As versões anteriores são preservadas para restauração. Alterar retratos **não altera posições**. Membros consultam **Meus envios** na resposta privada de `/tierlist`.

Propostas têm **Sinalizar problema**. Os relatos entram na revisão privada, sem acrescentar votos ou modificar posições. O responsável pode suspender uma proposta aberta, reverter a última classificação e restaurar retratos, com registros públicos de correção. Administradores de outros servidores não alteram a classificação global diretamente.

## Hospedagem e IA gratuita

No Bot-Hosting.net, use **Python 3.12**, arquivo inicial **`bot.py`**, pull automático do GitHub e estas variáveis:

```dotenv
DISCORD_TOKEN=segredo_do_bot
DATA_DIR=./state
GROQ_API_KEY=segredo_da_conta_gratuita
```

Marque as chaves como **Segredo**. Mantenha a conta Groq no plano **Free**, sem ativar cobrança. O modelo inicial é `openai/gpt-oss-120b`; a assinatura do ChatGPT não fornece esse serviço. O bot não contrata planos e não tem fallback pago. Ele não consegue determinar se o proprietário mudou o contrato de cobrança da conta.

Há um orçamento local de **48 chamadas e 150 mil tokens por dia UTC**, com entradas limitadas e intervalo entre análises. Testes de conexão também consomem esse orçamento. Cota excedida, chave ausente, resposta inválida ou indisponibilidade preservam posições. Os limites reais são definidos pela Groq e podem mudar. Recomendamos configurar Zero Data Retention nos controles da conta.

O bot não anexa nomes, IDs do Discord ou nomes de servidores aos pedidos de análise. Menções, URLs, emails e padrões de telefone são removidos do texto antes do envio. Isso não garante anonimização de qualquer texto livre. Comentários locais ficam até sete dias; votos individuais, relatos e sugestões encerradas têm retenção limitada. Backups locais podem conservar dados removidos até sua rotação. Resultados agregados e mensagens públicas de histórico permanecem.

Ative **Message Content Intent** no Developer Portal. A instalação usa `bot` e `applications.commands`. No canal do painel, conceda ao bot:

- Ver canal, Enviar mensagens e Ler histórico;
- Inserir links e Anexar arquivos;
- Criar tópicos públicos e Enviar mensagens em tópicos.

**Gerenciar tópicos é opcional**, usado para apagar o tópico técnico vazio após a verificação. Sem isso, ele fica arquivado. Um tópico trancado depende da administração para destrancar. Não é necessário conceder Administrador ou Gerenciar mensagens. O bot não altera permissões do canal; a administração pode impedir mensagens no canal principal e permitir os botões/tópico.

O plano gratuito da hospedagem exige renovação conforme suas regras. `./state` precisa persistir entre reinícios; exporte backups antes de excluir a implantação. Uma segunda instância com o mesmo diretório é recusada pelo bloqueio de processo.

## Verificar sozinho, incluindo Discord real

O responsável pelo aplicativo recebe **Verificação completa** na resposta privada de `/tierlist`. Ela:

- executa a suíte automatizada em subprocesso com estado temporário, sem credenciais nem rede externa;
- confere os dois comandos registrados na API real;
- cria um tópico técnico **privado**, convida o dono, publica/lê/edita uma imagem, confere botões e arquivamento/retomada;
- testa dez etapas visuais: entrada/remoção, ordem, mudança de tier, expansão/redução da linha, troca de retrato e restauração, comparando cada PNG baixado do Discord com o arquivo enviado;
- verifica uma resposta real da Groq, respeitando cota e intervalo;
- limpa as próprias mensagens técnicas e entrega um relatório JSON privado;
- oferece **Confirmar teste de interação**, usando um clique real no código de voto com banco temporário.

**Testar personagens na imagem** abre uma demonstração privada com Anterior, Próxima etapa e Executar todas. Também está disponível como **Ver alterações de personagens** no relatório. Posições artificiais recebem o aviso SIMULAÇÃO e nunca são gravadas no ranking global. Os retratos substituídos no ensaio ficam em bancos temporários. A execução automática pode ser interrompida com segurança no encerramento do bot.

O teste da API exige **Criar tópicos privados**. Sem essa permissão, ele informa a limitação e não publica um teste público. A demonstração privada por interação continua disponível. As permissões de moderação do Discord continuam valendo nos tópicos privados.

O subprocesso preserva os caminhos das bibliotecas carregadas pelo bot, incluindo instalações em `.local`, mesmo com HOME temporário. Mantém credenciais removidas, `.env` desativado e rede externa bloqueada. Zero testes é falha, não aprovação.

**Não é preciso reunir cinco pessoas para os testes automatizados.** Os cenários de disputa usam participantes artificiais somente em bancos temporários, sem fabricar votos ou posições públicas. A ferramenta não se passa por uma conta humana. Aparência no celular/computador e seleção humana de anexos são identificadas como verificações do cliente ainda não executadas.

O relatório distingue **isolado, Discord real, Groq real e não testado**. Um log dizendo que a chave foi carregada não confirma a integração. Orientações de estreia e falhas comuns: [docs/community-validation.md](docs/community-validation.md).

## Estado, backup e restauração

`tierlist.sqlite3` guarda o sistema atual; bancos do quiz e da comunidade antiga não viram ranking. As versões antigas permanecem arquivadas, sem executar seus comandos ou filas de chat global. A migração preserva classificações e votos existentes; os antigos controles individuais não fazem parte da interface ativa.

Há integridade ao iniciar, manutenção periódica, limites de coleta/votos/mídia e proteção contra espaço insuficiente. O backup diário inclui **SQLite, manifesto e arquivos de mídia verificados**, em `state/backups/tierlist-<instante>/`. `backups/latest.json` aponta a geração atual; uma geração anterior é mantida. Exporte a pasta inteira. Uma cópia no mesmo disco não protege contra exclusão da hospedagem.

Para restaurar, **pare o bot** e execute, usando o nome real da pasta:

```bash
python scripts/restore_tierlist.py --snapshot ./state/backups/tierlist-<instante> --data-dir ./state --replace
```

A restauração verifica banco e imagens antes de trocar o estado, recusa uma instância ativa e preserva `pre-restore.sqlite3` quando substitui um banco existente. A próxima inicialização atualiza os painéis. Também existem `/health` e `/ready`, sem dados de jogadores, usando `PORT`, depois `SERVER_PORT`, depois 8080. O workflow opcional de disponibilidade depende de `BOT_HEALTH_URL` no GitHub e de um endereço HTTP exposto pela hospedagem.

## Desenvolvimento e limites da validação

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

A suíte local/GitHub usa bancos temporários e APIs simuladas. Cobre fluxos de jogador, concorrência, fraude de interação, permissões, arquivos hostis, quota, prazos, reinício, persistência, rollback e restauração. **Passar nela não confirma acesso de produção ao Discord/Groq.** Isso é medido separadamente pelo botão de verificação na hospedagem.

Escopo consolidado: [docs/tierlist-plan.md](docs/tierlist-plan.md). Fontes oficiais: [tópicos do Discord](https://docs.discord.com/developers/topics/threads), [componentes e upload](https://docs.discord.com/developers/components/reference), [limites da Groq](https://console.groq.com/docs/rate-limits), [controles de dados](https://console.groq.com/docs/your-data). Retratos e trechos da wiki mantêm atribuições/URLs nos manifestos.
