# Anime Adventures

Tier list global com retratos originais, análise de relatos e decisões da comunidade. **Somente dois comandos, sem argumentos:**

- **`/tierlist`** — exclusivo de quem tem **Administrador** ou **Gerenciar servidor**; publica ou confere o painel. Membros votam no canal da imagem e usam o tópico para histórico, ajuda e sugestões de retrato.
- **`/chatglobal`** — responde **Em breve.** Nenhuma conversa é apagada ou retransmitida por esse comando.

## Um canal, uma imagem e um tópico

O administrador usa `/tierlist` em um canal de texto. A mensagem permanente é **somente um PNG**, sem texto, embed ou botões, com o tópico **Votações e histórico** ligado a ela. Quando há uma proposta válida, uma enquete temporária aparece no mesmo canal, com motivo, posições antes/depois, condições, ressalva, fontes, prazo e botões para votar. Oferece atalhos para a imagem e o histórico, sem ping coletivo. Repetir o comando reutiliza o conjunto, inclusive em execuções concorrentes. O painel oficial existente é preservado se o comando for usado em outro canal.

O tópico contém o índice editável, resultados completos e revisões. O índice oferece **Sugerir imagem**, **Meus envios**, **Como funciona** e atalhos para a votação aberta e decisões recentes. Ao encerrar, o bot desativa os votos e salva a proposta completa e seu resultado no tópico. O aviso do canal permanece por dois minutos e só é removido após confirmar o histórico. Falha de arquivo, acesso ou limpeza preserva o aviso encerrado para uma nova tentativa. Enquetes anteriores a essa atualização terminam no local original, sem duplicar votos ou renovar o prazo.

A classificação é apresentada somente na imagem, sem exportação textual de posições. O único TXT público é **retratos-pendentes.txt**, com as formas que precisam de foto; ele se atualiza após aprovações/restaurações e desaparece quando não há pendências. O canal retorna à imagem depois da limpeza das enquetes; a própria imagem não recebe botão de histórico e não há segundo canal obrigatório.

Os retratos mantêm os pixels originais, sem ampliação artificial ou geração de personagens. A imagem reúne duas seções independentes: **Infinite** e **Casual — Story/Raids/Portals/Stages**. Cada seção tem **META Hill/Hybrid, META Ground, META Support, Good Hill/Hybrid, Good Ground e Good Support**, em ordem da esquerda para a direita e com linhas expansíveis. Cada forma ocupa uma categoria por modo. **A imagem não tem rodapé técnico.** Datas, fontes e regras ficam no tópico; contadores, versões e conexão ficam no diagnóstico exclusivo do dono. O arquivo não recebe a descrição artificial de ponto que causava um indicador ALT desnecessário.

O catálogo ativo inicial tem **524 identidades/formas, 453 retratos e 71 pendências**. O arquivo histórico preserva 549 identidades: **25 formas com silhueta azul substituta foram retiradas por orientação expressa do dono**, incluindo Gravity Hero, que ainda tinha uma foto antiga reaproveitada. A política explícita em `data/tier_availability.json` impede a wiki/cache de reativá-las automaticamente; um personagem normal ser azul não é critério de exclusão. As formas sem classificação ficam fora da imagem e não recebem uma categoria arbitrária. Um retrato ausente usa um marcador, sem tomar a imagem de outra evolução. A classificação começa com uma **referência parcial e atribuída da Wiki**, revisão 46773 de 18/04/2025: **37 formas identificadas em Infinite e 37 em Casual**, sem votos fictícios. A própria página avisa que pode estar imprecisa. Há **76 entradas (47 nomes distintos)** sem correspondência exata comprovada com o catálogo; ficam pendentes, sem aproximações por nome/skin. Uma entrada reconhecida como retirada também foi excluída. A origem e a limitação aparecem no tópico. A ordem inicial acompanha a fonte, sem alegar uma nova medição de desempenho. As mudanças seguintes exigem propostas e votos.

As mensagens de enquete, resultado, ajuda e controles usam **Components V2**, com seções, separadores, retratos e botões nativos. Os ícones são da wiki do jogo e só são usados quando combinam com a ação; falhas de verificação mantêm o texto legível sem ícones. Os formulários usam Labels e upload nativo, explicando o destino privado das sugestões.

**Como funciona**, no tópico, explica em particular a leitura da imagem, votos, resultados, formas sem avaliação e envio de retratos. O dono recebe controles técnicos exclusivos. Outros administradores recebem **Conferir painel**, com links e orientações de permissões do próprio servidor, sem dados internos da IA, banco ou revisões globais.

## Análise e votação global

O bot considera **mensagens novas** sobre Anime Adventures nos canais aos quais tem acesso. Ao entrar no servidor, também faz **uma leitura inicial automática e limitada do histórico público**. Não exige exportar arquivos, escolher canais nem confirmar uma importação. A administração comunica esse funcionamento à comunidade e controla o acesso do bot pelas permissões do Discord.

Na leitura inicial, o bot busca as mensagens mais recentes em até **dez canais públicos**, até **cem mensagens por canal**, **mil mensagens lidas** e **vinte relatos aproveitados**. Ignora canais adultos, canais privados, tópicos e o canal do painel. Aplica os mesmos filtros de relevância, identidade, repetição e frequência das mensagens novas; não envia todo o histórico à IA nem altera posições por coletar um relato. A data original acompanha os comentários na análise; antiguidade, sozinha, não significa desatualização.

A referência inicial é **09/03/2025**, data explícita do Update 20 no [Update Log, revisão 46886](https://animeadventures.fandom.com/wiki/Update_Log?oldid=46886). A entrada posterior **20.4.1 — Fool’s Hunt** não informa data; essa referência é um limite inferior provisório, não a data comprovada do último update. O filtro por conteúdo e as fontes continuam necessários. A leitura não cobre todo o servidor nem garante encontrar todos os relatos antigos.

Uma execução concluída fica registrada no banco e **não se repete a cada reinício**. Permissões ausentes são rechecadas automaticamente; uma execução interrompida tem até três tentativas, separadas por uma hora, com deduplicação. Um servidor é lido por vez, por até um minuto. As mensagens novas continuam sendo coletadas; novas análises aguardam a leitura ativa terminar. Conferir painel/Diagnóstico mostra o andamento de forma privada. Não há um botão adicional para o ADM configurar essa leitura.

O filtro local identifica nomes/formas e contexto do jogo. A IA confirma se a conversa realmente trata de Anime Adventures e compara relatos com fontes da wiki. DMs, bots, webhooks, mensagens encaminhadas/citações isoladas e o próprio painel/tópico são excluídos. Editar ou apagar o original enquanto o bot recebe esses eventos retira o relato de análises futuras; isso não desfaz automaticamente uma decisão publicada. Uma edição/exclusão durante a leitura inicial também impede reintroduzir o texto antigo já recebido no lote. A API e os eventos não garantem descobrir alterações ocorridas enquanto o bot estava desconectado.

1. **No máximo uma proposta global por hora**, com motivo, condições, ressalva, fontes e posições antes/depois. Sem evidência suficiente, não aparece uma votação para preencher horário.
2. **Dez minutos de votação**, contados da primeira publicação confirmada no Discord. Todas as cópias compartilham o prazo.
3. **Aprovar / Manter / Mais testes.** São necessários pelo menos **cinco participantes e dois terços a favor** para publicar. Outras situações preservam a lista.
4. Uma conta conta uma vez na rede e pode trocar seu voto até o prazo. A conta precisa ter pelo menos sete dias. Durante a votação aparece somente o total de participantes; a distribuição é revelada ao encerrar.
5. Uma aprovação edita a imagem sem esperar o fim da hora. Reiniciar não apaga votos nem renova o prazo. Registro e publicação são atômicos, evitando aplicar uma aprovação duas vezes.

Antes de apurar, a entrega confere pela API que pelo menos uma cópia da votação continua disponível e corresponde à proposta. Isso cobre exclusão ocorrida durante uma desconexão. Indisponibilidade incerta adia a apuração, sem renovar o prazo ou aceitar novos votos. Avisos só são apagados quando o resultado salvo e a própria mensagem do bot passam pela conferência; cópias removidas por moderação não são republicadas como votações. Pendências de arquivo/limpeza aparecem nos controles privados do dono e na conferência do painel do respectivo ADM.

O índice do tópico mostra **quando uma nova análise ficará disponível**, se há relatos aguardando, análise em andamento ou proposta pronta. Com uma votação aberta, mostra também quanto falta para encerrá-la. Os horários usam a contagem relativa do próprio Discord e os prazos persistidos no banco, sem edições por segundo nem chamadas extras à IA. **O contador não garante uma enquete:** sem proposta fundamentada, as posições são preservadas. Pausas de análise não impedem concluir uma votação já aberta.

A IA considera contribuição para o time, custo, mecânicas, funções, condições e limitações. Popularidade ou um atributo isolado não bastam. São exigidos IDs conhecidos, a forma mencionada no relato, confiança mínima, citações literais e números presentes nas citações. Passar outro personagem no mesmo tier exige referência dele também. Fontes ou classificação-base alteradas invalidam uma proposta incompatível.

Resultados recentes entram como contexto; **isso não treina os pesos da IA** nem comprova uma estatística do jogo. Comparações recentes sem evidência nova têm uma janela de estabilidade de 24 horas. O modelo não recebe ferramentas, shell, banco ou controle do Discord. Essas restrições reduzem erros; não garantem interpretação perfeita nem impedem todas as contas alternativas.

## Wiki, retratos e revisão

`data/tier_evidence.json` inclui **1.038 referências** com revisão, URL e hash. São fontes comunitárias, não telemetria do jogo. O bot consulta a API oficial da wiki de maneira limitada: módulos de identidades/dados diariamente e artigos relevantes em lotes pequenos. Durante uma votação, a atualização das fontes é adiada. Falhas preservam o último cache válido e são indicadas no diagnóstico/índice. Uma sincronização parcial não significa que toda a wiki foi revisada naquele instante.

**Sugerir imagem** abre um formulário com personagem/forma, skin, motivo, retrato e print opcional do jogo. São aceitos PNG, JPG e WebP estáticos, até 4 MB por arquivo e quatro milhões de pixels. Os limites de envio são conferidos antes de baixar/preparar arquivos e novamente antes do registro. O processamento aplica a orientação da foto, remove metadados e limita dimensões, duplicatas, frequência e armazenamento. Não executa anexos nem busca URLs fornecidas pelo usuário.

Somente o responsável pelo aplicativo aprova ou rejeita. A revisão privada compara o retrato atual com a sugestão; um recorte de fundo uniforme pode ser experimentado e desfeito antes da aprovação. Não é uma reconstrução da arte por IA. As versões anteriores são preservadas para restauração. Alterar retratos **não altera posições**. Membros consultam **Meus envios** no tópico; a resposta com o andamento é privada.

A lista de contribuição usa o catálogo ativo e os retratos disponíveis, incluindo aprovações locais. Um envio pendente ou rejeitado não remove uma solicitação. Arquivos aprovados são conferidos por hash; se estiverem ausentes ou corrompidos, não escondem a pendência. A restauração recusa uma versão anterior corrompida para preservar o retrato atual. O índice apagado é reparado automaticamente; perda de confirmação da API reaproveita a mensagem já enviada. Uma conferência periódica também encontra exclusões ocorridas enquanto o bot estava desconectado.

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

O bot não anexa nomes, IDs do Discord ou nomes de servidores aos pedidos de análise. Menções, URLs, emails e padrões de telefone são removidos do texto antes do envio. Isso não garante anonimização de qualquer texto livre. Comentários locais ficam até sete dias **após a coleta**, inclusive os vindos do histórico; a data original é preservada separadamente. Votos individuais, relatos e sugestões encerradas têm retenção limitada. Backups locais podem conservar dados removidos até sua rotação. Resultados agregados e mensagens públicas de histórico permanecem.

Ative **Message Content Intent** no Developer Portal. A instalação no servidor usa `bot` e `applications.commands` e exige autorização de alguém com **Gerenciar servidor** ou **Administrador**. `/tierlist` tem permissão padrão de Gerenciar servidor e valida essa permissão novamente ao executar; habilitar o comando para outro cargo nas configurações do Discord não libera a criação do painel. Membros não precisam executar comandos para usar os botões. No canal do painel, conceda ao bot:

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
- testa cinco etapas da lista de retratos: pendência, envio, aprovação, restauração e rejeição, incluindo remover/recolocar o TXT na mesma mensagem e conferir o arquivo baixado;
- verifica uma resposta real da Groq, respeitando cota e intervalo;
- limpa as próprias mensagens técnicas e entrega um relatório JSON privado;
- oferece **Confirmar teste de interação**, usando um clique real no código de voto com banco temporário.

**Testar personagens na imagem** abre uma demonstração privada com Anterior, Próxima etapa e Executar todas. Também está disponível como **Ver alterações de personagens** no relatório. Posições artificiais recebem o aviso SIMULAÇÃO e nunca são gravadas no ranking global. Os retratos substituídos no ensaio ficam em bancos temporários. A execução automática pode ser interrompida com segurança no encerramento do bot.

O teste da API exige **Criar tópicos privados**. Sem essa permissão, ele informa a limitação e não publica um teste público. A demonstração privada por interação continua disponível. As permissões de moderação do Discord continuam valendo nos tópicos privados.

O subprocesso preserva os caminhos das bibliotecas carregadas pelo bot, incluindo instalações em `.local`, mesmo com HOME temporário. Mantém credenciais removidas, `.env` desativado e rede externa bloqueada. Zero testes é falha, não aprovação.

**Não é preciso reunir cinco pessoas para os testes automatizados.** Os cenários de disputa usam participantes artificiais somente em bancos temporários, sem fabricar votos ou posições públicas. A ferramenta não se passa por uma conta humana. Aparência no celular/computador e seleção humana de anexos são identificadas como verificações do cliente ainda não executadas.

O relatório distingue **isolado, Discord real, Groq real e não testado**. Um log dizendo que a chave foi carregada não confirma a integração. Orientações de estreia e falhas comuns: [docs/community-validation.md](docs/community-validation.md).

O [fechamento da versão](docs/tierlist-launch-review.md) registra a revisão do catálogo, os testes e as etapas que dependem do uso com jogadores.

## Estado, backup e restauração

Mudanças de categorias são transacionais e auditadas. Versões e votos antigos continuam no banco/histórico, mas notas por letras ou as antigas funções não viram Hill/Ground/Support por suposição. A inicialização importa a referência da Wiki uma única vez por modo, somente se não houver lista atual compatível; nunca sobrescreve decisões existentes ou reverte correções humanas. Reinícios não repetem essa importação. Propostas, aprovação, reversão e retenção respeitam o modo. A limpeza sempre mantém a versão atual de cada lista. Uma reversão não atravessa a fronteira entre formatos incompatíveis.

`tierlist.sqlite3` guarda o sistema atual; bancos do quiz e da comunidade antiga não viram ranking. As versões antigas permanecem arquivadas, sem executar seus comandos ou filas de chat global. A migração de disponibilidade preserva snapshots, votos e histórico: caso uma forma retirada já estivesse classificada, cria uma revisão auditada removendo-a e mantém a ordem relativa das demais. Cancela propostas incompatíveis e impede a reversão de reintroduzir essas formas. Retratos antigos ficam registrados para histórico/backup; sugestões pendentes dessas formas deixam a fila ativa. Os antigos controles individuais não fazem parte da interface ativa.

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

A base reproduzível está em `data/tier_initial_wiki.json`, com nomes da fonte,
linhas, origem da identidade e pendências. Os snapshots e redirecionamentos
estão em `docs/sources`; `python scripts/build_tier_baseline.py` refaz o artefato
sem rede ou IA. A revisão está fixada: não foi confirmada como a revisão mais
recente nesta execução. Atualizar a Wiki não sobrescreve automaticamente os
votos da comunidade.
