# Serviço de perguntas no PC

Veja o passo a passo do responsável em [LEIA-ME-PC.md](../LEIA-ME-PC.md). O pedido posterior autorizou executar o plano que antes estava apenas reservado para o futuro. A pasta é `D:\Armazenamento do Bot`; o domínio fornecido é `https://7g2x14fnpa.apps.bot-hosting.cloud`, HTTPS ativo e porta de destino 25302 conforme captura do painel.

## Divisão de responsabilidades

- Hospedagem: bot Discord, slash commands, feeds de imagens, chat global e ponte autenticada `/knowledge/worker` no servidor HTTP existente. Em modo PC não cria/abre `knowledge.sqlite3`, não indexa a wiki e não chama a IA para responder perguntas. Perguntas/eventos circulam em RAM somente durante a operação, com fila limitada e prazos. O programa público de instalação ainda inclui o acervo da wiki; não confundir esse arquivo versionado com um arquivo ativo de histórico na hospedagem.
- PC: `knowledge_pc.py`, iniciado pelo Windows, faz conexão **de saída** HTTPS/WSS; não escuta uma porta nem compartilha uma pasta do HD. Guarda banco, índice, mensagens, cursor, controle de cota e cópias locais, consulta os trechos e chama a Groq com a chave privada configurada localmente. O modelo continua remoto na Groq, não é executado no PC.
- A conta leitora continua no processo isolado da hospedagem, sem transferir seu token ao PC. Eventos de Questões são confirmados somente depois de persistidos pelo PC. O cursor confirmado reside no PC e chega à ponte apenas como estado transitório. A conexão/desconexão do PC reinicia o leitor para ligar/desligar Questões com esse cursor; feeds de imagem usam os recibos/cache já existentes e podem passar por esse breve ciclo de reconexão.

## Ativação e ausência do PC

`KNOWLEDGE_MODE=pc` é explícito: instalar/atualizar o código sozinho preserva o comportamento local anterior até configurar o modo. Exige `KNOWLEDGE_BRIDGE_SECRET` de pelo menos 32 caracteres. Sem segredo válido o conhecimento falha fechado, sem abrir uma cópia local como alternativa. Não modificar `DATA_DIR` para um caminho do Windows: o caminho só existe no PC.

As rotas de conhecimento só são registradas em modo PC. Todas exigem `Authorization: Bearer` com segredo gerado aleatoriamente pelo instalador; nunca pôr o segredo numa URL. Os endpoints públicos `/health` e `/ready` continuam sem dados privados. O cliente aceita apenas origem HTTPS sem caminho, credenciais ou query; validação TLS permanece ligada. O proxy da hospedagem precisa permitir WebSocket. Não abrir porta no roteador nem criar túnel adicional.

Uma conexão de PC por vez, mensagens até 32 KiB, oito operações pendentes no máximo, uma inferência por vez e prazo de 110 segundos para até duas chamadas à Groq. Heartbeat de transporte e estado a cada cinco segundos, validade do último estado de vinte segundos. PC desligado/suspenso, programa fechado ou internet indisponível deixam `/ask` com aviso fixo em inglês; perguntas em andamento podem falhar. Sem resposta local alternativa, sem enfileirar perguntas por tempo indeterminado e sem armazenar a pergunta do usuário como fonte.

Ao retornar, o programa reconecta com espera progressiva; o leitor busca o que ainda estiver disponível depois do cursor confirmado. Não garantir recuperação de mensagens apagadas ou inacessíveis durante a ausência. Sem cursor inicial continua a carga recente limitada, conforme a política já existente.

## Transferência e finalização

`GET /knowledge/migration` exporta **somente** o banco de conhecimento congelado em modo PC e controles autorizados de cota/cooldown, sem o banco principal do bot. Usa snapshot SQLite consistente, `quick_check`, SHA-256, contagens de mensagens/artigos e cursor. A origem anterior de até 128 MiB é preservada. O ZIP possui somente três nomes fixos; importação limita tamanhos, confere manifestos e jamais extrai caminhos arbitrários nem sobrescreve uma base preexistente no PC. Uma interrupção parcial deixa os arquivos preservados para conferência manual.

O recibo local identifica a origem congelada e é exigido na apresentação do PC enquanto a base antiga existir. Novas mensagens podem continuar chegando ao PC após a importação. `FINALIZAR-MIGRACAO.cmd`, executado pelo responsável depois de testar `/ask`, solicita `POST /knowledge/migration/finalize`. A ponte exige autenticação, conexão ativa e recibo correspondente antes de remover apenas os nomes fixos do banco/backup de conhecimento e os controles de perguntas antigos. Mantém um pequeno recibo de conclusão sem texto de mensagens. Não remove o banco principal, configurações de servidores, arquivos de mídia ou o programa.

A remoção só ocorre na instância real quando o responsável executar essa etapa. Não houve acesso ao HD nem migração real pela máquina de desenvolvimento. Não apagar a cópia hospedada pelo simples fato de o pacote ter sido preparado.

## Capacidade, privacidade e manutenção

O PC não usa a reserva de 64 MiB. O SQLite cresce por demanda, com margem mínima de 1 GiB livre na unidade para pausar coleta sem exclusão por idade/quantidade. Não promete espaço infinito nem transforma o HD em RAM. O histórico continua comprimido e com FTS contentless; minimização e marcação de relatos comunitários permanecem. O orçamento gratuito da Groq continua 48 chamadas/150 mil tokens por dia UTC, guardado no PC, além das cotas do provedor. Guardar mais dados não aumenta essa cota.

O backup da base é consistente e rotativo; só inicia com margem para a cópia. O backup no mesmo HD não protege contra falha do dispositivo. Configuração, banco de controles e recibo também precisam de cópia privada para restauração completa. Não enviar bancos, segredo de conexão, chave Groq, arquivo `.private.*` ou histórico ao GitHub.

O início automático é opcional por atalho na inicialização do usuário do Windows; requer login e não é instalado ocultamente. Há trava de processo com `msvcrt` no Windows/`fcntl` no Linux para impedir dois escritores. O ambiente Python do PC é separado da biblioteca da conta leitora; não instalar `discord.py-self` nele.

## Limitações de qualidade e validação

A migração mantém a consulta/validação de fontes atual. **Não corrige a seleção insuficiente de trechos, os números colados na extração da wiki nem a identificação de upgrade/nível/buff.** Essas falhas foram diagnosticadas antes da migração e continuam pendentes a pedido do responsável, que priorizou armazenamento.

Testes de integração usam WebSocket real em loopback, bancos temporários e Groq simulada. Conferem autenticação, ausência de base/fallback hospedados, idioma no transporte, escrita/cursor no PC, desconexão, retomada, pausa, transferência, rejeição de pacotes inválidos e remoção guardada. O ZIP inclui somente fonte pública e corpus, com manifesto de hashes. A execução dos `.cmd` e a instalação no Windows real, proxy WSS/HTTPS da hospedagem, Groq e origem Discord ainda precisam de conferência após ativação. Não afirmar que testes Linux comprovam esses passos.
