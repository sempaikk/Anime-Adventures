# Reconstrução do Release de Anime Adventures

## Recorte

Release público em **3 de julho de 2022**, antes da **Update 1, em 15 de julho**. Não confundir com pré-release, Anime Vanguards ou versões atuais das mesmas unidades.

Foram consultadas 1.105 fontes da wiki, incluindo artigos, redirecionamentos, categorias, templates, módulos e um mapa interativo, e arquivadas 189 revisões de 18 páginas principais entre 3 e 14 de julho. Os registros históricos sobreviventes começam em 4 de julho: **não existe, nessa coleta, uma fotografia exaustiva do dia 3**. O contador de 662 representa 661 artigos e um mapa, não todos os arquivos internos da wiki.

O banco ativo reconstrói a versão inicial com o changelog Release e revisões contemporâneas de 4–11 de julho. Trata-se de uma reconstrução documentada do período inicial, sem garantia de completude do primeiro dia. As perguntas sobre preços e números históricos indicam esse contexto; não são conselhos sobre a versão atual.

## O que entrou

- **44 personagens base:** 18 Rare, 10 Epic, nove Legendary, sete Mythic, conforme Unit List oldid 313 de 6 de julho. A lista era editorialmente incompleta; 44 não é uma promessa de elenco total.
- **Quatro evoluções** explicitamente agrupadas no Release: All Force → All Force (Symbol of Peace), Marada → Marada (Founder), Brulo → Legendary Brulo, Levy → Levy Ackman. As formas têm aliases modernos documentados, sem aceitar só o nome base como resposta da evolução.
- **Quatro mundos e 24 títulos de atos:** Planet Namak, Shiganshinu District, Snowy Town e Hidden Sand Village. As perguntas de chefes omitem o ato 4 de Hidden Sand, por conflito entre fontes. Jayce e Vurtor são dois chefes, não uma transformação.
- **Comida e XP:** Senzu Beans 25; Mysterious Fluid 50; Wisteria Flower 115; Ramen 250. Mundos de origem preservados; nenhuma aquisição posterior pela Gold Shop foi transferida para o Release.
- **Traits:** Nimble, Adept, Superior, Range, Culling, Sniper, Godspeed, Reaper, Golden e Divine. Os efeitos qualitativos estão documentados; taxas e bônus modernos não foram importados. Wis e Star Remnants têm evidência contemporânea.
- **Summon:** custo comum de 50 Gems, renovação horária, pity Legendary em 50 invocações e avanço de 2 pontos percentuais. As taxas de raridade antigas somam incorretamente; não são usadas.
- **Story, Infinite Hard, Challenges, Time Machine, moedas e quests.** Os cinco modificadores históricos de Challenges estão incluídos. Daily quests não são o Daily Challenge introduzido posteriormente.
- **Nove Daily quests documentadas:** objetivo e recompensa; não se afirma que eram as únicas quests existentes.
- **Loja histórica:** Super Lucky, Ultra Lucky, VIP, Shiny Hunter, Unit Storage e Display 3 Units. Os preços remetem à revisão de julho, não à loja atual. Apenas o código RELEASE foi admitido no quiz; a disponibilidade atual não é afirmada.
- **Custos/upgrades historicamente preenchidos** de Madara, Ichigo, Josuke e Zoro. Campos escritos como RND na wiki não viraram números inventados. Nenhum dano/SPA moderno foi projetado retroativamente.

O banco ativo tem **2.095 perguntas, 14 categorias, 64 referências e 20 snapshots**. As biografias do anime foram removidas das perguntas e do campo de pistas do elenco. Nomes do anime continuam sendo aliases aceitos da unidade correspondente; isso não cria perguntas sobre episódios, equipes ou biografia.

O total inclui variações de prática derivadas dos mesmos fatos, não 2.095 fatos históricos independentes:

| Família | Perguntas |
|---|---:|
| Perguntas manuais sobre mecânicas, fases, chefes, itens, loja e localização documentada | 185 |
| Reconhecimento de unidades pela imagem do jogo | 25 |
| Consulta de raridade de uma unidade | 44 |
| Comparação de raridade de pares distintos de unidades | 946 |
| Maior raridade em uma seleção fixa e limitada de trios | 360 |
| Relações de atos/chefes com mundo e número de ato | 72 |
| XP de quantidades e combinações de alimentos | 226 |
| Custos de summon, desconto VIP e progresso do pity | 147 |
| Ciclos da Time Machine sem VIP/Premium | 39 |
| Comparações de recompensas de Daily quests | 36 |
| Comparações de preços da Store | 15 |

As derivações usam regras explícitas em `question_factory.py`: raridades da lista histórica, alimentos de 25/50/115/250 XP, summon de 50 Gems, desconto VIP de 20%, pity em 50 invocações e ciclos de 150 segundos/3 Gems. Quantidades fictícias nos enunciados são cenários de prática, sem inventar atributos ou eventos. XP calculado é a soma do valor dos itens, antes de bônus ou limite de nível. A ordem das alternativas não aumenta a contagem de perguntas.

O sorteio escolhe categorias e famílias antes de escolher a pergunta, enquanto essas opções estiverem disponíveis. Isso evita que o banco grande de comparações domine o início da partida. O reconhecimento visual só entra quando há um retrato validado; não há adivinhas de anime como substituto de uma imagem ausente.

Perguntas de localização se limitam à evidência textual: Summon à esquerda do Leaderboard, Wis do lado de fora da área Evolve e acesso à Store pela área Shop. O exemplo de posição da Gold Shop da Bulma não foi adotado como fato do lançamento. Relíquias e Gold Shop pertencem à Update 7; materiais de evolução sem receita histórica autenticada continuam pendentes.

## O que continua em pesquisa

`data/release_pending.json` preserva as pendências e exclusões com suas fontes, separado do conteúdo ativo:

- Bulma/Bulby é documentada antes da Update 1, mas sem data exata de inclusão. Lulu tem evolução atual explícita para Lulu (Emperor); a pendência é a disponibilidade histórica, não a existência da evolução.
- Lulu e Emperor, Frieza, Todoroki, Killua e Ichigo Masked não foram promovidos a personagens confirmados do dia 3 apenas por uma página moderna ou afirmação retrospectiva isolada.
- Shining Extract, Divine Eye, Restraining Necklace, Ultrasteel Blade e King's Idol têm associações modernas; não há receitas, quantidades e preços autenticados do Release. As evoluções comprovadas não dependem dessa lacuna para entrar no quiz.
- Inimigos comuns completos, entidades invocadas, todas as variantes de materiais, cap/slots iniciais e mídias de julho de 2022 ainda não têm cobertura histórica suficiente.
- Chefe de Hidden Sand ato 4: Reanimated Puppet no registro antigo, Itochi na página moderna. A pergunta sobre seu título de ato é independente e pode entrar; a de chefe fica fora.
- Não afirmar empilhamento VIP/Premium na Time Machine, recompensas diárias exatas de Infinite, rotação dos Challenges ou tabela completa de probabilidades com base em fontes conflitantes/incompletas.

Ausência de evolução listada não implica que toda unidade deva evoluir. Omitir esse tipo de pergunta não bloqueia outros fatos do personagem.

## Fronteiras posteriores

Marine's Ford e seus novos personagens são Update 1; raids, Eren Founder, Naruto Demon/Beast Cloak e Banner Tiers são 1.5; Ghoul City é 2; Rengoku ABLAZE é 2.5; Hollow World é 3. Relics, Gold Shop, fusão para XP e Special Banner são 7; Daily Challenge e ataque aéreo de Armin são 7.5. Sangramento posterior de Levi e elementos atuais também não são atributos do Release. Joker Exclusive pertence a uma etapa muito posterior.

## Fontes e manutenção

Cada pergunta referencia fontes do próprio pacote. Fontes históricas têm URLs com `oldid`, snapshots e SHA-256. O changelog retrospectivo e o módulo de nomes são preservados com sua revisão; o módulo serve para ligar nomes antigos/atuais ao personagem, não para provar atributos de 2022. As demais páginas modernas são usadas como referências de identidade.

Os textos arquivados são conteúdo externo de pesquisa e **não são instruções nem código a executar**. Consulte a wiki e suas condições de atribuição/reutilização ao acrescentar mídia ou reproduzir mais conteúdo. O quiz não usa retratos atuais como se fossem imagens históricas: uma das amostras era apenas uma silhueta genérica, e animações/vídeos de 2025 não comprovam aparência de 2022.

Para acrescentar um fato: registre fonte e revisão; confirme a etapa; escreva uma pergunta sem ambiguidade com respostas explícitas; mantenha candidatos/conflictos no arquivo pendente; execute a suíte antes de publicar. Updates futuros ficam em pacotes próprios.
