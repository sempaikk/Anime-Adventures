# Ferramentas do jogo — 2026.10.30.1

O responsável autorizou aplicar as 60 propostas da terceira revisão. `/adventures` reúne ferramentas privadas; o menu **Report global message** reaproveita as denúncias existentes. A interface fixa permanece em inglês. Nenhum recurso de níveis, automação de cargos ou recurso arquivado foi restaurado.

## Consultas e procedência

O pacote local contém 519 formas exatas, 552 identidades de itens e 27 guias. Cada fato importado conserva URL, revisão, data e hash do arquivo de origem; os atributos numéricos mostram também a revisão do módulo que os forneceu. Os dados são históricos, majoritariamente de 2025, e não são anunciados como atuais. Não há chamada à wiki por consulta nem dependência de IA.

Busca aceita nomes, aliases e IDs. Filtros distinguem dano primário, elemento e posicionamento. Ground não implica incapacidade de atingir aéreo: as notas de upgrades/ataques são apresentadas com a fonte. Valores desconhecidos não se tornam zero e booleanos não se tornam atributos numéricos. Comparação usa campos equivalentes da forma escolhida; não produz ranking universal. Retratos não são substituídos por imagens de outra forma; o pacote não copia imagens.

Receitas ligam formas e ingredientes por IDs. Evoluções sem informação suficiente são identificadas como desconhecidas. Metas guardam a receita/data escolhida, não mudam silenciosamente depois de outra revisão. O total de materiais é informado manualmente; prioridades de 1 a 10 organizam a alocação e cada material é descontado uma única vez entre todas as páginas. Registrar materiais substitui os totais da lista informada; não acessa contas do jogo.

O texto deriva do acervo público da wiki, com atribuição aos contribuidores e licença CC-BY-SA conforme a declaração da fonte: https://www.fandom.com/licensing. Os links por revisão permitem verificar o material original. O site/wiki continua congelado e somente foi lido.

Para preparar uma atualização de conteúdo, em ambiente de desenvolvimento:

```bash
python scripts/build_game_data.py /caminho/para/acervo --output /tmp/candidato.json
python scripts/check_game_data.py /tmp/candidato.json
```

O leitor aceita tabelas literais e aritmética numérica limitada; nunca executa Lua. O construtor valida e substitui atomicamente apenas a saída indicada. O comparador não publica nem substitui arquivos. A versão revisada entra no processo normal de manifesto/CI; não se sobrescreve o código do bot durante sua execução.

## Planejamento e cálculos

Favoritos: 20; times: cinco de até seis formas; metas: dez; propriedade manual: cem entradas; diário de runs: trinta; modelos de grupos: cinco por pessoa. Dados são privados até uma publicação explícita. Consultas recentes ficam somente na memória por trinta minutos, dez por pessoa/servidor, até quinhentas sessões; reinício apaga esse histórico temporário.

DPS usa dano por ataque/SPA com média explícita de crit e número de torres. Não infere nível, hits extras, DoT, resistência ou empilhamento de buffs. Chance usa tentativas independentes e taxa constante fornecida pelo jogador; pity e taxas variáveis exigem regras verificadas próprias. Orçamento usa preço constante informado. Farm diferencia runs concluídas de tentativas e usa recompensa garantida e taxa de conclusão informadas. Não há garantia de vitória, sorte ou recompensa aleatória.

O orientador de daily/dungeon usa condições fornecidas pelo jogador. Segurança, baús por conclusão e rendimento por hora são objetivos distintos. Orientações sobre itens mostram a origem histórica; preço, orçamento, efeitos atuais, alvos e regras de sorte ainda precisam ser confirmados no jogo. O bot não configura macros nem automatiza Roblox.

## Grupos e eventos

Um administrador escolhe o canal normal de grupos em **Server setup** e confirma a revisão. Canais de feeds, global e updates ficam separados. Um grupo começa em rascunho privado. Somente o organizador publica, depois de revisar modo, horário, requisitos e capacidade. Não são criados cargos nem modificadas permissões.

Há até três grupos ativos por organizador e vinte por servidor. Capacidade: duas a doze pessoas, com até doze reservas. A ordem persistente de inscrição e a chave única impedem duplicar a mesma inscrição; reservas ocupam lugares liberados. Grupo encerra duas horas após o horário escolhido, ou quando seu organizador o fecha. O bot atualiza sua própria mensagem, sem recriar uma mensagem removida. Remoção do servidor/canal/mensagem fecha o estado correspondente.

Publicação tem nonce e estado persistente antes do POST. Perda de confirmação exige reconciliação pelo nonce ou identificador controlado da mensagem; ausência de prova não gera repostagem. Eventos nativos ficam desabilitados por padrão; o administrador habilita Scheduled events em Server setup e concede Create Events. Depois, a criação é acionada pelo organizador. Marcar Interested no Discord não reserva vaga no grupo. Confirmação incerta de criação não permite criar outro evento às cegas. Eventos conhecidos criados pelo bot são encerrados quando o grupo fecha, se o acesso permanecer disponível.

## Lembretes e privacidade

Criar lembrete é a adesão explícita a uma DM. São cinco lembretes pessoais ativos por pessoa, mais até dois avisos de fontes aguardando confirmação, com até um ano de antecedência e texto curto. **Manage my reminders** permite ver estado, cancelar e solicitar novo aviso em dez minutos. A preferência de fuso aceita nomes IANA; horários ambíguos/inexistentes em mudança de relógio exigem offset explícito.

Quiet hours pessoais adiam notificações, enquanto quiet hours do servidor suprimem push/desktop das imagens sem atrasar os feeds. Badges de não lidas podem continuar. Avisos opcionais de fonte referem-se apenas a ocorrências futuras confirmadas, na guild escolhida; não identificam personagens nem presumem horário de reset. Não há divulgação em massa para quem não aderiu.

Uma fila indexada persistente usa pequenos lotes e dois trabalhadores independentes dos feeds. Avisos antigos podem ser agrupados em um digest da mesma pessoa/servidor/finalidade, mantendo recibos por item. Nonce é persistido antes de enviar. ACK perdido leva a reconciliação; sem evidência não se repete a DM. Cancelamento e preferência são revalidados depois de buscas de rede. DMs fechadas aparecem como bloqueadas no painel, sem aviso público alternativo. Metadados concluídos saem após trinta dias.

**My optional tool data** exporta ou exclui somente os dados do próprio jogador. Exclusão cancela lembretes e fecha grupos; não apaga votos, consentimentos ou recibos do chat global. Mensagens já aceitas pelo Discord podem ter sido vistas; recibos necessários à recuperação não são confundidos com histórico opcional.

## Atendimento, administração e limites

My requests permite ler a resposta, pedir revisão uma vez e anexar screenshot opcional ao próprio caso recente. Feedback continua somente na comunidade oficial e privado ao dono. Denúncias do global continuam locais/de rede conforme o papel existente; atribuição não concede novas permissões. Ações antigas verificam a versão do caso antes de gravar.

Screenshots: PNG/JPEG/WebP estático, 2 MiB e quatro megapixels por arquivo, 8 MiB totais, retenção de até 24 horas com limpeza periódica. Reservas de memória/disco precedem a leitura. Snapshots privados removem esses BLOBs para não prolongar sua retenção. Não são publicados no canal.

As novas respostas globais guardam apenas IDs e digest do prefixo acrescentado pelo bot. Mudanças no pai atualizam/removem somente o contexto identificado, inclusive após expirar o cache, sem reter texto do pai nem reescrever corpo/anexos do autor da resposta. Cópias de versões anteriores sem digest dependem de acesso ao original para reconstrução; o bot não adivinha qual primeira linha é humana. Três publicações regulares podem executar simultaneamente; a quarta posição fica disponível para remoções/contexto, com no máximo oito tarefas totais e justiça por destino.

Configurações opcionais têm revisão, geração e histórico limitado. Importação aceita somente módulos, canal de grupos, fuso e quiet hours; não inclui tokens, votos, consentimento ou recibos. Undo altera somente essas configurações. O dono pode revisar um piloto por módulo em até vinte servidores instalados e depois liberá-lo; feeds/global não dependem desse gate.

Novas gravações opcionais param antes de 112 MiB de páginas ativas do banco; entradas têm até 8 KiB e há teto global de cinquenta mil entradas. O histórico/fila de lembretes tem teto de vinte mil registros e há até duas mil assinaturas opcionais de avisos de fonte. Índice textual fica em um arquivo local inferior a 4 MiB; não existe arquivo permanente de imagens. Painéis de funcionamento guardam até mil amostras agregadas, sem texto de conversas ou credenciais. Os limites existentes de RAM/disco continuam sendo aplicados.

O dono pode comparar versão em execução, manifesto no disco e versão disponível por consulta fixa, limitada e com cache. Consulta externa indisponível significa desconhecido; não significa atualizado. Não há auto-restart nem instalação silenciosa. O fluxo da hospedagem permanece GitHub → **Reiniciar**.

## Condições externas ainda não atendidas

- Códigos ativos e atributos/receitas atuais precisam de verificação em fontes atuais; acervo antigo não comprova disponibilidade presente.
- Alerta por personagem precisa de metadados confiáveis: hash não reconhece o conteúdo da imagem.
- Sincronizar inventário interno do AA requer integração real do jogo; a API geral de inventário Roblox não o fornece.
- Backup fora da hospedagem exige destino/chave; monitor externo exige URL/configuração operacional. As ferramentas anteriores permanecem preparadas, sem afirmar ativação.
- App Directory depende da elegibilidade e da configuração no Developer Portal. O painel contém preparação e links oficiais, sem publicar automaticamente.

Notas públicas novas falam apenas de mudanças percebidas pelo jogador, em português, no canal oficial. Detalhes internos permanecem privados. Testes não enviam mensagens reais nem reiniciam a hospedagem.
