# Aplicação da terceira revisão — 2026.10.30.1

Todas as 60 propostas autorizadas são rastreadas abaixo. “Implementada” descreve o código entregue, não ativação observada na hospedagem. A base do jogo é histórica, com campos desconhecidos preservados; não existe integração presumida com inventário, códigos atuais ou reconhecimento de personagens.

| Nº | Proposta | Implementação / condição |
| --- | --- | --- |
| 1 | Central de ferramentas do jogo | adventure_views.ToolsHome |
| 2 | Busca por nome e apelido | game_knowledge.Knowledge.search |
| 3 | Ficha curta de unidade | Knowledge.card |
| 4 | Filtros de unidades | Knowledge.search + filtros |
| 5 | Comparação de duas unidades | Knowledge.compare |
| 6 | Evoluções por etapas | Knowledge.evolution + ramificações |
| 7 | Receitas de evolução | Knowledge.recipe |
| 8 | Onde conseguir um item | Knowledge.card(item) + linhas de obtenção/crafting arquivadas |
| 9 | Guia rápido de mecânicas | GlossaryView |
| 10 | Detalhes por upgrade | Knowledge.upgrades |
| 11 | Favoritos privados | DetailView.favorite / SavedView |
| 12 | Fonte e validade dos dados | source/stats_source e indicação histórica |
| 13 | Times salvos manualmente | ToolForm(team) / SavedView |
| 14 | Verificador de cobertura do time | Knowledge.coverage, com capacidades desconhecidas explícitas |
| 15 | Orientador de daily | advisor(daily), condições manuais |
| 16 | Orientador de dungeon por objetivo | advisor(dungeon), objetivo e condições explícitos |
| 17 | Metas de evolução | ToolForm(goal) |
| 18 | Ingredientes compartilhados | allocate + GoalPlan paginado/prioridades |
| 19 | Lista de unidades desejadas | ToolForm(owned) |
| 20 | Calculadora de DPS | game_calculators.dps |
| 21 | Calculadora de chance | game_calculators.chance, taxa constante; pity não inferido |
| 22 | Orçamento de tentativas | game_calculators.budget |
| 23 | Estimativa de farm | game_calculators.farm |
| 24 | Histórico pessoal de runs | ToolForm(run) |
| 25 | Criar grupo para jogar | party draft / PartyPreview |
| 26 | Entrar e sair por botão | PartyAction join/leave |
| 27 | Pronto e reserva | ready + inscrições ordenadas e reservas |
| 28 | Modelos de grupos | templates + expiry / close |
| 29 | Evento nativo do Discord | módulo events opcional + Create Events |
| 30 | Compartilhar time escolhido | SavedView.share_team + ShareResult |
| 31 | Lembretes pessoais | reminders / cancel / snooze |
| 32 | Preferências de lembretes | IANA timezone, quiet hours, digest persistente |
| 33 | Abrir a postagem atual | feed_tools.latest |
| 34 | Consultar entregas recentes | feed_tools.records |
| 35 | Status simples para jogadores | feed_tools.status |
| 36 | Relatar imagem errada ou antiga | Report image issue / contexto privado |
| 37 | Imagens com notificações silenciosas | silence_payload em ambos os formatos de entrega |
| 38 | Aviso voluntário de nova atualização | feed_notifications, source_ref, adesão explícita |
| 39 | Navegação consistente | Home/Back + RecentLookups temporário |
| 40 | Publicar consulta somente após revisão | ShareResult, canal normal e confirmação |
| 41 | Denunciar pelo menu da mensagem | Report global message |
| 42 | Prévia do compartilhamento global | ConsentView.preview, sem adesão/envio público |
| 43 | Casos com responsável | CaseReview claim + idade/revisor no inbox |
| 44 | Resposta privada no protocolo | CaseForm read + My requests |
| 45 | Recurso de moderação | CaseForm appeal |
| 46 | Print opcional no relato | upload privado validado, retenção curta e snapshot sem BLOB |
| 47 | Citações acompanham edição/remoção | reply_id, quote_hash e refresh_context |
| 48 | Remoções com capacidade reservada | três publicações regulares + capacidade reservada |
| 49 | Controle de dados pessoais | export_user / erase_user, consentimentos e recibos preservados |
| 50 | Instalação guiada | SetupView / FeedSetupReview / SettingsConfirm |
| 51 | Configuração por módulo | módulos + link de instalação de consultas sem permissões extras |
| 52 | Histórico e desfazer configuração | histórico/undo de configurações opcionais, com geração |
| 53 | Exportar preferências sem segredos | import/export allowlist e confirmação |
| 54 | Dados do jogo com revisão | build_game_data + check_game_data; sem sobrescrever runtime |
| 55 | Publicação gradual de funções | PilotForm / PilotConfirm, módulos isolados dos feeds |
| 56 | Limites por recurso | cotas, reservas e filas limitadas |
| 57 | Tendência de funcionamento | amostras agregadas privadas em bot_tool_events |
| 58 | Apresentação pública correta | README/docs e perfil do aplicativo; About do GitHub depende de API |
| 59 | Preparação para descoberta | ToolOperations.discovery; publicação depende do Portal |
| 60 | Atualização e reinício pendentes claros | release_status compara processo, disco e repositório; desconhecido se offline |

Os requisitos externos permanecem explícitos: fontes atuais verificadas, metadados de personagens, integração real do jogo, destino de backup, URL de monitor e elegibilidade do App Directory. O About do GitHub não pôde ser editado nesta sessão: a API GraphQL retornou Forbidden; os textos revisados do perfil e README foram preparados no código. Não foram solicitadas credenciais.

Os testes são offline com estado temporário e APIs simuladas. Site/wiki e pacote Windows histórico permanecem intocados. Ver [guia de ferramentas](game-tools.md) para limites, privacidade, dados e recuperação.
