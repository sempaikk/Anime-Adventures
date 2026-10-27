# Perguntas, fontes e armazenamento

## Funcionamento de `/ask`

**Atualização posterior:** o responsável autorizou migrar o conhecimento para seu PC. O modo `KNOWLEDGE_MODE=pc` e a instalação em `D:\Armazenamento do Bot` estão descritos em [pc-knowledge.md](pc-knowledge.md). As seções de reserva de 64 MiB e armazenamento hospedado abaixo descrevem o modo local anterior, preservado até a migração ser ativada. Mudar o armazenamento não corrige a busca por upgrades/níveis.

O comando abre um formulário privado de até 500 caracteres. A resposta também é privada. Comandos, menus e avisos fixos ficam em inglês; **a resposta da IA segue o idioma da pergunta**. A localidade do Discord serve de apoio em perguntas ambíguas. Não traduzir mensagens autorais dos participantes no chat global.

`GROQ_API_KEY` é reutilizada. O modelo padrão é `openai/gpt-oss-120b`, substituível por `GROQ_MODEL`; o modelo roda na Groq, não nos 256 MB de RAM do bot. O programa seleciona trechos por pesquisa local e envia apenas esses trechos e a pergunta. Nunca envia a base inteira, nomes/IDs de usuários como metadados ou as credenciais. O modelo não recebe ferramentas para executar ações.

O retorno precisa conter citações das fontes selecionadas, com as mesmas palavras, pontuação, letras e números. A conferência normaliza apenas espaços/quebras de linha e composição Unicode canônica; não exige copiar a formatação de uma tabela. Citações traduzidas, inventadas, IDs desconhecidos, links/menções gerados pelo modelo e certas afirmações numéricas sem apoio continuam recusados. Uma resposta comunitária precisa citar a resposta, não a pergunta. Uma fonte apagada/alterada durante a inferência invalida o retorno. Isso reduz erros; não equivale a comprovar automaticamente a veracidade de toda conclusão da IA.

A fonte comunitária é sempre marcada como **não verificada**. Perguntas sem resposta não viram fatos; conversas e páginas da wiki são dados não confiáveis, nunca instruções de sistema. O modelo deve indicar conflitos, datas e incertezas e não inventar o patch atual. Perguntas feitas em `/ask` e as próprias respostas da IA não são adicionadas automaticamente ao acervo.

Para perguntas em outros idiomas, o modelo pode solicitar uma busca local adicional com termos em inglês. Uma citação fora do formato pode receber uma tentativa de correção usando as mesmas fontes e o mesmo idioma, sem enviar a resposta recusada como informação nova. Busca adicional e correção compartilham o limite de **duas chamadas por pergunta**, ambas debitadas; não existe terceira chamada. Não existe chamada à IA a cada mensagem recebida. Mantido o orçamento local compartilhado de **48 chamadas e 150 mil tokens por dia UTC**, além das cotas reais do provedor. Não são 48 respostas garantidas: tokens, consultas adicionais e cotas externas também limitam. Há intervalo de 20 segundos por pessoa e recusa temporária quando já há uma resposta em processamento. Sem chave, falha ou cota, não há fallback pago. Falhas de conferência geram somente um código técnico no console, sem pergunta, texto da fonte, resposta da IA ou credenciais.

## Acervo da wiki

`data/game_wiki.json` reúne **655 artigos com conteúdo** entre os 661 registros do acervo anterior. Os demais eram vazios/redirecionamentos. Os corpos de texto são completos dentro desse acervo, sem o corte inicial de 60 mil caracteres; o maior tem cerca de 95 mil caracteres. O JSON ocupa aproximadamente 4,2 MB. Fonte, revisão, data e licença permanecem registrados; links apresentados apontam à revisão arquivada.

Foi uma exportação somente por leitura de `source/wiki.json` e `source/rendered/*.json` já existentes no repositório do site. **Nenhum arquivo, configuração, publicação ou dado do site foi alterado.** O site continua congelado por tempo indeterminado. Não confundir o acervo com uma cópia garantida de toda a wiki atual na internet. As revisões históricas, muitas de 2025, não comprovam o balanceamento atual.

Textos da wiki seguem a licença CC-BY-SA registrada no arquivo, com atribuição à Anime Adventures Wiki/Fandom e à página/revisão de cada artigo. Não foram copiados cenários ou arquivos de mídia para a base de perguntas. Imagens dos feeds são tratadas separadamente.

## Arquivo de Questões

Única origem textual autorizada: **`994219170101219408`**. O leitor acompanha mensagens de texto e edições; não transfere fotos, vídeos ou arquivos desse canal para a IA. Extrai corpo, ID técnico, referência de resposta e data, sem acrescentar autor, avatar ou nome de servidor. Remove menções, URLs, e-mails, telefones reconhecíveis e padrões de credenciais antes do armazenamento. Isso é minimização, não garantia de anonimização de todo texto livre.

O corpo de até 4.000 caracteres é armazenado comprimido com zlib em `DATA_DIR/knowledge.sqlite3`. O índice FTS5 é contentless: armazena os termos para busca sem duplicar o texto integral em claro. Na consulta, somente os registros selecionados são descomprimidos. O arquivo não é criptografado; a proteção da pasta e dos backups continua dependendo da hospedagem e do responsável.

**Não há exclusão por 5 mil mensagens nem por 30 dias.** Esse limite foi descartado após o pedido do responsável. O histórico recebido permanece pesquisável enquanto houver capacidade. Mensagens removidas na origem são retiradas ao receber o evento correspondente; isso não apaga instantaneamente backups anteriores. Registros anteriores ao início da coleta não são garantidos.

No primeiro uso, recupera até cem mensagens recentes como ponto de partida. Depois acompanha mensagens novas. Guarda um cursor apenas após processar o texto anterior. Após desconexão/reinício, busca as mensagens posteriores a esse cursor, em ordem, e mantém as chegadas ao vivo em espera até terminar a recuperação. Repetições não contam como mensagens novas. Apenas dados ainda disponíveis na API podem ser recuperados; não prometer recuperação de mensagens apagadas enquanto o leitor estava offline.

Perguntas e respostas ligadas pela referência de reply podem entrar como contexto comunitário. Textos sem associação suficiente ficam arquivados, sem promover automaticamente uma pergunta ou conversa ambígua a fato. Respostas numéricas curtas também são preservadas e podem ser citadas como relatos não verificados. O volume diário observado é registrado sem precisar consultar a IA.

## Capacidade da hospedagem

O painel informado em 26/10/2026 mostra **256 MB de RAM, 512 MB de disco e 92,9 MB de disco usados antes da entrega**. O responsável esclareceu que mil ou dez mil mensagens/dia eram estimativas; não usar nenhuma como medição real.

A reserva inicial do banco de conhecimento é **64 MiB**, incluindo seu índice/wiki. Pode ser ajustada entre 16 e 128 MiB com `KNOWLEDGE_MAX_MB`, considerando a cota da instância. Existe limite de páginas no próprio SQLite. A captura pausa antes do limite ou com armazenamento crítico, preservando os registros anteriores e o cursor. Não há limpeza automática para disfarçar falta de capacidade. A captura fica pausada até a próxima reinicialização; se a causa continuar, ela pausará novamente. Somente reiniciar ou baixar um backup não libera espaço.

`Bot status`, nos controles privados do dono em `/globalchat`, informa quantidade salva, uso/reserva e contagem por dia observado. O dono recebe alerta privado sustentado se a captura pausar. Novos banners, desafios e chat permanecem independentes do banco de conhecimento; um arquivo de conhecimento corrompido não é apagado/recriado e não deve impedir a inicialização dos outros recursos.

`instance_storage.py` mede os arquivos do projeto e de `DATA_DIR`, contando dependências/cache/backups e evitando duplicar hardlinks ou seguir diretórios externos por symlink. Usa a cota informada de 512 MiB, substituível por `INSTANCE_DISK_LIMIT_MB`. A saúde combina espaço físico e cota estimada da instância; espaço livre do disco compartilhado da máquina não é interpretado como cota ilimitada. O controle é conservador e não substitui as medições ou limites do provedor.

Exemplo de escala, **sem medir o canal real**: 10 mil mensagens/dia de 500 bytes representam 5 MB/dia, 150 MB/mês e cerca de 1,8 GB/ano antes de índices/backups. Compressão depende do conteúdo. O bot medirá o volume e bytes reais para orientar decisões. Não prometer guardar para sempre um canal movimentado em 512 MB.

## Backup e eventual HD pessoal

A manutenção faz uma cópia local consistente em **`DATA_DIR/knowledge-backup.sqlite3`**, rotacionada no máximo uma vez por dia, com verificação e substituição atômica. Essa cópia pode chegar ao tamanho do banco. Não está dentro do backup de retratos da tier list; preservar/exportar os dois arquivos. Uma cópia no mesmo volume não protege contra exclusão da hospedagem ou falha desse volume. Nenhum histórico real, banco, backup ou segredo deve ir para o GitHub.

No primeiro pedido, o **HD pessoal de 1 TB** ficou reservado como plano futuro. **O pedido posterior substituiu essa decisão:** implementar o programa do PC, manter o conteúdo de perguntas nele e deixar `/ask` indisponível enquanto o PC/programa estiver offline, sem outra cópia ativa de conhecimento na hospedagem. Pasta e endereço estão registrados no guia de PC. A execução no Windows, a transferência real e a remoção da base anterior ainda dependem das etapas guiadas; não confundir código preparado com dados já transferidos.

## Validação

Os testes locais cobrem escopo, minimização, consulta com fontes, respostas simuladas em português/espanhol/inglês/japonês, cotas, citações, deleção durante inferência, compressão, preservação além de 5 mil registros/30 dias, pausa sem perda, checkpoint, recuperação ordenada, backup, corrupção isolada e cota da instância. Testes simulados não comprovam a qualidade do modelo real em todos os idiomas nem a autenticação da conta/Groq na hospedagem. Conferir a primeira execução real depois de instalar esta versão.
