# Auditoria do catálogo e da base inicial — 22/10/2026

Foram conferidos o módulo de identidades, os nomes antigos, as entradas das
duas listas e os retratos recuperados. As consultas à API via leitor público
retornaram as mesmas revisões já arquivadas: Names 46960, de 27/04/2025,
e Tier Lists 46773, de 18/04/2025. Isso confirma o conteúdo retornado pela
Wiki nesta consulta, sem representar uma verificação dentro do jogo.

## O que foi corrigido

O importador aceitava apenas aspas duplas no campo `name` de Lua. Seis
declarações válidas com aspas simples eram ignoradas. O parser compartilhado
agora atende o catálogo offline e a atualização da Wiki em execução, sem
executar Lua nem aceitar expressões como identidade.

| Forma exata | ID | Resultado |
| --- | --- | --- |
| Ice Shaper | geten | Identidade preservada no histórico; silhueta azul excluída pelo critério do dono |
| Supersound | sonic | Ativa, retrato original incluído |
| Tamiki | tatsumaki | Ativa, retrato original incluído |
| Ghosty (Sacrifice) | himeno_evolved | Ativa, retrato original incluído |
| Blood (Unleashed) | power_evolved | Ativa, retrato original incluído |
| Cowardly (Scared) | kobeni_evolved | Ativa, retrato original incluído |

O catálogo histórico passa de 549 para **555 identidades**, com cobertura de
todos os IDs declarados no Names consultado. A política explícita retira
**26 formas**, restando **529 ativas, 458 retratos e 71 pendências** antes de
substituições aprovadas na hospedagem. Os cinco novos retratos foram abertos,
verificados e inspecionados visualmente. Uma imagem normal ter azul não
determina exclusão.

O cruzamento adicional com o módulo Data não transformou entidades auxiliares
em personagens independentes. Wall Titan, a entidade do Founding Titan e os
espíritos Taurus/Aquarius/Leo são invocações; `kite_evolved` é a apresentação
genérica de uma escolha aleatória entre as quatro bênçãos já cadastradas.
Esses IDs não foram adicionados como novas formas de inventário.

## Cobertura das listas

Os nomes antigos foram ligados aos IDs nas revisões **33578** e **43960** do
mesmo módulo Names. Por exemplo, Daky (Obi) corresponde a `daki_evolved`,
atualmente Saka (Ribbon); Kiroto (Dual) corresponde a `kirito_evolved`,
atualmente Gamer (Dual). A forma base não substitui a evolução.

As **151 entradas** das seis categorias foram identificadas:

- **71 formas ativas em Infinite**;
- **76 formas ativas em Casual**;
- **quatro ocorrências excluídas**: Flame Hero e Luffo evoluídos, em ambos os modos;
- **zero nomes pendentes de correspondência** nessa página.

A ordem dentro de cada categoria acompanha a Wiki. Isso resolve a cobertura
da fonte; não estabelece um novo ranking por medições do jogo. A própria
página mantém o aviso de possível imprecisão. As formas do catálogo que não
estão nessa tier list não recebem uma posição inventada.

Dois retratos usados nessa base continuam pendentes: **Dracula (Unholy King)**
e **Fiend Girl (Buttterfly)**, grafia do Names. A consulta aos arquivos exatos
da Wiki não encontrou esses PNGs; não usamos a foto da forma base ou de uma
skin diferente. Podem ser enviados pelo fluxo de sugestão e revisão.

## Atualização e histórico

A base inicial não representa uma decisão da comunidade. Sua origem,
importações, correções manuais e manutenção ficam em registros internos.
O tópico público apresenta enquetes e seus resultados. Avisos administrativos
antigos só são removidos após conferir autor do bot, marcador e servidor;
erros da API preservam o recibo para tentar depois. Registros de auditoria,
votos, classificações e resultados de enquetes são preservados.

No reinício, a referência completa pode substituir a importação anterior
somente quando ela continua intacta: mesma versão marcada, modelo inicial,
mesmas categorias e ordem relativa, sem enquete aberta. Uma decisão posterior
da comunidade ou correção humana impede essa substituição. Enquetes abertas
mantêm a base e o prazo; a complementação pode ocorrer em outro reinício após
o encerramento. Repetir o processo não cria versões ou votos extras.

## Reprodução

Os snapshots e hashes ficam no repositório, com atribuição nos manifestos:

- `docs/sources/46960.wiki`: identidades atuais da fonte;
- `docs/sources/tier-names-33578.wiki` e `tier-names-43960.wiki`: nomes antigos;
- `docs/sources/tierlist-46773.wiki`: posições por modo e categoria;
- `data/tier_initial_wiki.json`: nome original, linha, ID e origem de identidade;
- `data/community_portraits.json`: URLs e arquivos dos retratos.

`scripts/build_community_catalog.py` e `scripts/build_tier_baseline.py`
reproduzem o catálogo e a base sem rede ou IA. As revisões da Wiki não são
apresentadas como votos ou notificações públicas do bot.
