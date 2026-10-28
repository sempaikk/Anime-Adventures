# Recomendações para a comunidade oficial

Estado: **plano preparado, ainda não aplicado no Discord**. O responsável autorizou configurar seu servidor e pediu recomendações porque não conhece a configuração do Discord. Não pedir essa autorização geral novamente. A análise usa o relatório privado e as capturas; não versionar o relatório real. A sessão de desenvolvimento não dispõe de conexão direta ao Discord.

## Ordem de trabalho

1. Concluir o formato dos avisos: português, somente tópicos, sem nome/versão no cabeçalho. A correção está preparada na .5 para a próxima carga necessária.
2. Separar as ferramentas de moderação local do chat global dos controles de configuração do servidor, antes de retirar Administrador dos Mods.
3. Aplicar a organização de cargos/categorias abaixo, preservando membros atribuídos, histórico e destinos dos feeds.
4. Validar com o dono e com uma conta comum: acesso aos chats, canais de leitura, comandos e privacidade. Diagnósticos/testes por respostas privadas.
5. Só depois retomar a discussão dos níveis; o responsável ainda não autorizou implementar XP/cargos de progressão agora.

## Cargos

| Cargo | Finalidade | Permissões propostas |
| --- | --- | --- |
| Assinantes | Membros normais | Ver canais liberados, ler histórico, conversar/responder, reagir, anexar arquivos, usar comandos e participar de voz quando houver uma sala de conversa liberada. Sem moderação/administração ou menções coletivas. |
| Angelic e Artista | Identificação visual | Nenhuma permissão extra. Seus membros usam Assinantes para o acesso normal. |
| Mods | Moderação | Permissões de membro e ferramentas para gerenciar mensagens/tópicos, aplicar timeout, expulsar/banir, gerenciar apelidos, silenciar/ensurdecer/mover em voz e consultar auditoria. Sem Administrador, Gerenciar cargos, Gerenciar servidor ou Gerenciar webhooks por padrão. |
| Adventures | Bot | Preservar o cargo próprio já criado e atribuído pelo dono, acima dos cargos que vai gerenciar. Exibição separada desligada. Não duplicar nem mudar a permissão atual nesta correção de avisos. |
| Bots | Organização visual | Manter o grupo embaixo, separado da posição técnica do cargo Adventures. Revisar permissões de outros bots caso a caso; não remover integrações ou alterar suas necessidades por suposição. |
| @everyone | Acesso inicial | Leitura de regras/comunicados liberados. Conversa e recursos de membro ficam em Assinantes; garantir esse cargo aos participantes existentes antes de restringir categorias. |

A conta proprietária mantém seus poderes de dono mesmo usando só Assinantes. Não adicionar Administrador a Assinantes para dar acesso ao proprietário.

O cargo Angelic não estava no relatório original. A captura mais recente ainda exibia Rlks. Antes de qualquer alteração desse cargo, identificar o alvo por um relatório atualizado; não presumir que são o mesmo, renomear ou criar duplicado.

## Condição antes de mudar Mods

O relatório atual mostrava **Administrador** em Mods. O bot usa **Gerenciar servidor** para abrir sua administração do chat global, inclusive denúncias/restrições locais. Se apenas retirar Administrador e não adaptar a interface, os moderadores perderão esses controles.

Primeiro preparar um acesso de moderação local baseado em permissões como Gerenciar mensagens/Moderar membros, com telas específicas de denúncias e restrições do próprio servidor. Configurar/mover/pausar conexões permanece administrativo. Ações sobre toda a rede continuam exclusivas do dono do bot. Não aplicar a retirada de Administrador antecipadamente; a mudança ainda não foi executada.

## Canais e categorias

Preservar as três áreas existentes e o padrão visual **emoji + `┃` + nome**, sem fontes decorativas ou canais adicionais sem finalidade.

| Área/canal | Membro normal | Moderação e bot |
| --- | --- | --- |
| Regras e comunicados | Ver e ler; sem publicar mensagens | Publicações do dono/equipe autorizada. |
| Updates | Ver e ler; sem publicar mensagens | O bot publica suas notas em português. Canal exclusivo da comunidade oficial. |
| Banner e daily challenge | Ver e ler; sem publicar mensagens | O bot continua enviando apenas as imagens. Preservar IDs/configurações atuais. |
| Chat geral | Conversar, responder, reagir e anexar dentro dos limites | Moderação local. |
| Chat global | Mesmo acesso normal, compartilhamento só após o consentimento existente do bot | Denúncias/moderação locais; administração da conexão separada. |
| Moderator-only existente | Oculto de membros comuns | Dono/equipe; sem recriar um canal que já existe. |

Aplicar as regras na categoria e sincronizar os canais pertinentes, preservando exceções justificadas. Sobreposições dos feeds precisam manter Ver canal, Enviar mensagens, Anexar arquivos e Ler histórico para o bot. Não bloquear a publicação ao transformar um canal em somente leitura.

O canal de voz do relatório tem finalidade/nome promocional e bloqueios específicos para Assinantes. Não convertê-lo em sala pública nem liberar acesso por suposição. Uma sala para conversar em voz seria uma decisão futura separada, sem contagem de XP em call.

## Feedback, testes e prioridades

Feedback/sugestões do bot ficam exclusivamente no servidor oficial; não criar esse recurso nos demais servidores. Antes de implementar um comando/canal novo, distinguir sugestões do usuário dos avisos automáticos e das denúncias existentes do chat global. Não apagar ou restringir essas denúncias por causa da exclusividade dos updates.

Priorizar respostas privadas para testes. Bloquear @everyone em um canal não o esconde de Administradores; conferir cargos e sobreposições antes de qualquer ensaio que publique. Não mover os feeds públicos nem colocar mensagens artificiais na rede para testar.
