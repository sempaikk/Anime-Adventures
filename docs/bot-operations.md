# Operação da versão 2026.10.23.2

## Interface e alcance

A imagem usa **Casual à esquerda e Infinite à direita**, com uma margem entre
os modos. Cada metade mantém dez retratos por linha e os pixels originais, sem
geração ou ampliação artificial. Categorias equivalentes têm a mesma altura;
entrada, saída e mudança de categoria expandem/reduzem as duas metades juntas.
A referência inicial tem 71 formas no Infinite e 76 no Casual e produz um PNG de
2212 × 1110 pixels, 1.170.013 bytes nesta revisão. Não representa votos novos.
No celular, a prévia fica menor; abrir/ampliar preserva os detalhes do arquivo.
O teto de publicação permanece em 8 MiB e uma falha preserva a imagem anterior.
Um ensaio extremo com as 529 formas ativas em cada modo, todas na mesma
categoria, produziu 2212 × 5622 pixels e 2.970.964 bytes, sem cortar retratos.

Os ícones ativos vêm de nove artes do jogo: estrela, mochila Unit Storage,
Summon Ticket, Star Fruit, Star Remnant, Gems, dano, SPA e alcance. A grade
`GUI_Tier-List_icon.png` pertence à interface do site e foi retirada do tema
ativo. As origens continuam registradas no manifesto histórico, sem exibição
da grade. Controles usam ícones relacionados à ação, rótulos legíveis e texto
quando o aplicativo não disponibiliza o emoji. As cópias do chat continuam
mensagens comuns, sem cartões decorativos por pessoa.

As regras, retenção e moderação do chat estão em [global-chat.md](global-chat.md).
Configuração, denúncias e informações técnicas ficam nos controles privados,
com ações locais de ADM e ações da rede reservadas ao dono.

## Atualizar sem reconfigurar os servidores

1. Pare a instância atual antes de trocar arquivos de programa.
2. Atualize o código e as dependências, preservando o diretório `DATA_DIR`,
   `tierlist.sqlite3`, mídias aprovadas e segredos da hospedagem.
3. Opcionalmente confira o pacote e o banco sem iniciar outra instância:
   `python scripts/check_release.py --data-dir ./state`.
   Use o caminho real se `DATA_DIR` for diferente. A verificação não lê
   credenciais, não chama APIs e abre o banco existente em modo de leitura.
   Um diretório novo é identificado como novo, sem inventar um banco recuperado.
4. Inicie uma única instância. Painéis existentes, confirmações, votos e canais
   configurados são recuperados. Não é necessário pedir `/tierlist` novamente
   em todos os servidores. Controles privados antigos podem ser reabertos.
5. Confira versão/integridade e a Verificação completa nos controles privados.

Em caso de problema, pare a instância e preserve o estado atual antes de
retornar ao último código compatível. Não misture uma versão antiga que não
entenda o esquema atual. Uma restauração de backup é outra operação e pode
perder alterações posteriores ao ponto restaurado; veja as instruções do README.
O backup completo fora da hospedagem continua adiado conforme decisão do dono.

## Ensaio local de fila

Reprodução: `python scripts/benchmark_global.py --guilds 100 --messages 60`.
O ensaio usa SQLite temporário, cinco origens artificiais e zero chamadas ao
Discord. O cenário de mil servidores usa os mesmos parâmetros, trocando `100`
por `1000`. Medições desta máquina, sem tráfego externo:

| Servidores simulados | Mensagens aceitas / limitadas | Entregas pendentes | Mediana de ingestão | Seleção de 8 destinos | Banco | Pico do processo |
| --- | --- | --- | --- | --- | --- | --- |
| 100 | 60 / 0 | 5.940 | 6,976 ms | 8,695 ms | 0,92 MiB | 14,62 MiB |
| 1.000 | 50 / 10 | 49.950 | 69,991 ms | 86,800 ms | 5,79 MiB | 16,36 MiB |

O segundo cenário para antes de ultrapassar 50 mil entregas pendentes. Os
números medem organização e limites do banco, não velocidade de entrega real,
memória do bot completo ou capacidade garantida da hospedagem gratuita.
Rede, tamanho de anexos, permissões e limites do Discord continuam determinantes.
Uma implantação que se aproxime desses limites precisa ser dimensionada com
métricas reais antes de aumentar a rede.

## Critério de verificação

Os testes locais cobrem dados temporários, concorrência, contexto/permissões,
decisões de denúncias, contenção expirada, pausa, alertas e preservação de
originais. O ensaio autorizado pela API usa dois canais privados de um servidor
físico, representando duas conexões lógicas, sem Gateway adicional, sessão
humana ou alterações de produção. Aparência no cliente e conversas entre
pessoas continuam com o dono e os participantes do servidor.

## Resultados desta revisão

Pacote `2026.10.23.2`, identificação `3834e825c845`, 114 arquivos conferidos.
A suíte completa passou em **674 testes**, incluindo 30 novos cenários de
operação/moderação. Verificação estática de nomes/importações e preflight do
pacote também passaram. O preflight local reconheceu estado novo; não consultou
o banco da hospedagem.
O perfil isolado usado pela Verificação completa também passou em **425 testes
neste ambiente**, com credenciais removidas e rede externa bloqueada.

O ensaio autorizado pela API passou em **13 conferências**, incluindo:

- identidade, permissões e nove ícones do jogo registrados no aplicativo;
- ativação sem painel público e migração seletiva preservando conversas;
- convite real por DM, remoção do convite e primeira mensagem mantida local;
- texto/Markdown, nome com uma etiqueta, edição e exclusão sincronizadas;
- PNG spoiler e MP4 válido com bytes idênticos após retransmissão;
- caixa de denúncias nativa, decisão temporária e edição da mesma mensagem;
- painel operacional privado e PNG horizontal enviado/lido/alterado no mesmo ID;
- expiração de conteúdo local preservando histórico e confirmação.

Os dois canais de ensaio e a DM foram removidos. Nenhum voto, retrato, ranking
ou consentimento de produção foi modificado. O aceite foi simulado somente no
banco temporário; não representa clique humano. Não houve chamada à Groq, nova
sessão Gateway ou teste com dois servidores físicos. A publicação do código no
GitHub não equivale a atualizar/reiniciar a instância da hospedagem.
