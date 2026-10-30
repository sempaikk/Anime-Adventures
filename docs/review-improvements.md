# Aplicação da segunda revisão de uma hora

Escopo da entrega 2026.10.29.1: chat global, banners, daily e infraestrutura compartilhada. Níveis continuam adiados. Site/wiki, artes W/M/L, fontes, destinos, credenciais e histórico de votação não são substituídos. Os testes usam bancos temporários e APIs simuladas.

| Proposta | Entrega / condição |
| --- | --- |
| 1. Retomar permissões | Rechecagem limitada, com espera, somente da imagem mais recente e ainda válida. Não ressuscita imagens confirmadas/apagadas. |
| 2. W/M/L além do cache | Retenta somente sementes faltantes nos recibos recentes conservados; não limpa votos. |
| 3. Destinos globais independentes | Até oito tarefas com quatro execuções; destino ocupado é excluído da seleção. FIFO por canal e remoções permanecem. |
| 4. Retirada/substituição da origem | Revalidação entre partes; preserva recibo aceito e não sobrescreve superseded como sent. |
| 5. Conciliação em canal movimentado | Cursor e candidatos persistentes, cem mensagens por rodada, ordem crescente e janela do instante original. Nenhum reenvio sem prova. |
| 6. Recusa × confirmação desconhecida | 413/tamanho, 403/acesso e 400/payload têm estados próprios; perdas de ACK continuam incertas. SDK respeita os limites do Discord. |
| 7. Integridade e URLs mistas | Verificação com decode completo limitado; pula URL externa inválida em banner sem buscá-la. Daily continua conjunto atômico. |
| 8. Incidentes quietos | Falha e recuperação estáveis; cooldown persistido após recuperação; incidentes de fonte agrupados. |
| 9. Gate por recurso | Notas declaram feeds exigidos e aguardam consulta/recepção atuais, além de integridade e W/M/L. |
| 10. RAM antes de preparar/enviar | Reservas conjuntas por dimensões e bytes antes de decode/BLOB/previews/uploads; sem editar as artes. |
| 11. Destinos privados do dono | Página de filas/bloqueios em todos os servidores configurados, sem expor a administradores de outras guilds. |
| 12. Diagnóstico e orientação | Resumo copiável com campos permitidos de um servidor; mensagens distinguem acesso, fonte, recursos e confirmação. |
| 13. Visão do servidor e consulta | Resumo de recursos, Check connection sem gravação, Enable explícito, confirmação para mover; Server status e Repair connection separados no global. |
| 14. Progresso pessoal | My messages separa preparação, fila, confirmação, envio parcial e falha. |
| 15. Manutenção por feed | Pausa privada do dono por 15 min/1 h, expiração automática, versão contra formulário antigo. |
| 16. Acompanhamento | My requests mostra denúncias próprias deste servidor e feedback próprio somente na comunidade oficial, com recibos. Não envia DMs. |
| 17. Moderação temporária | Durações de 15 min/1 h/1 dia, lista paginada local ou de rede e liberação explícita com motivo; seleção antiga revalida o registro. |
| 18. Celular | Seleção de dez mensagens recentes visíveis para denunciar, páginas pequenas e controles de texto. |
| 19. Texto longo | Fecha/reabre blocos de código apenas no transporte; texto original continua preservado e limites UTF-16 continuam válidos. |
| 20. Instalação de imagens | Link com permissões de imagens, sem Manage Webhooks; global continua verificando suas permissões próprias. |
| 21. Disco e retenção | Margem de 48 MiB para novos anexos globais; medidas de espaço reutilizável; limpeza limitada maior; compactador só offline sob lease e snapshot. |
| 22. Backup externo cifrado | Exportador age/X25519 preparado e roundtrip com chaves descartáveis testado. Instalar age e escolher destino/chave pública são condições externas ainda não fornecidas. Nada enviado. |
| 23. Idade e ensaio do backup | Idade no painel e leitura/migração de estado numa restauração descartável, comparando configurações/consentimentos/recibos/marcadores. |
| 24. Monitor independente | Readiness funcional melhorada e workflow existente preservado. URL pública e configuração externa ainda não confirmadas. |
| 25. CI do pacote | Testes combinados, preflight do manifesto real e montagem/verificação do pacote completo, sem estado de produção. |
| 26. Reinício consistente | Guard de manifesto antes de abrir estado, pacote completo verificado e fluxo GitHub → Reiniciar preservado. Não se alterou o painel para instalar um atualizador diferente. |
| 27. Dependências e comandos | Fixação de versões transitivas dos dois processos; sincronização de comandos em tarefa separada com espera/retry. |
| 28. Crescer por medidas | Volume de origens/cópias/24 h, idade/p95 já existente e espaço medido para acompanhar expansão. Limites de fila e armazenamento continuam; ensaio não é garantia de produção. |
| 29. Origem autorizada | Caminho nativo existente conservado e identificado no diagnóstico. Acesso real continua dependendo de autorização na origem; não é criado por conhecer IDs. |
| 30. Estudos condicionais | Descrições de anexos fornecidas por membros agora são preservadas. Migração de BLOBs para arquivos e nova política de citações ficam como estudos condicionados à medição; não demonstraram benefício que justifique trocar o armazenamento ou mudar mensagens já publicadas nesta entrega. |

## Verificação e limites

Os casos novos combinam permissão restaurada com versões antigas, retirada/edição no primeiro upload, W/M/L após 65 min, ACK perdido com mais de cem mensagens e reinício, destino parado com segundo recado em outro destino, falta de prova sem repetição, alerta oscilante, consulta sem gravação, confirmação antiga, isolamento entre usuários/servidores, startup com falha de sincronização, orçamento simultâneo e pacote com arquivo privado extra.

O exportador foi testado com o programa age 1.2.1 e chaves descartáveis; a verificação criptográfica não afirma que existe cópia fora da hospedagem. Compactação offline não roda em startup nem remove arquivos de produção. A sessão não dispõe de acesso administrativo a Discord/Bot-Hosting: CI, código e recibos simulados não comprovam reinício, novas permissões, entrega ou anúncio real.

Notas públicas contêm somente efeitos visíveis para participantes e administradores, em português, exclusivas do canal oficial já configurado. Detalhes de sistema/recursos ficam na documentação/painéis privados. A campanha de desculpas antiga mantém o mesmo ID, prazo e recibos; não se repete por versão nova.
