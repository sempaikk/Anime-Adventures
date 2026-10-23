# Validação do chat global — 22/10/2026

Versão: `2026.10.22.5`. O teste utilizou a API oficial com o token do próprio bot,
sem iniciar outra conexão Gateway, usar conta humana, chamar Groq ou acessar o
banco de produção.

Resultado final: **628 testes na suíte completa**, **45 cenários novos do chat**
e **379 testes no perfil isolado da hospedagem**, todos aprovados. Integridade
conferida: `fd96a1fc0369`, 106 arquivos. A execução desse perfil aqui confirma seu
funcionamento isolado; o processo da hospedagem só muda após atualização/reinício.

## Discord real

Após a correção das permissões pelo dono, a API confirmou Administrador e Gerenciar
webhooks. Foram criados dois canais privados temporários no servidor de teste
autorizado. O webhook e o painel foram ativados pelo código novo, com estado em
SQLite temporário. As originais de teste foram publicadas pelo próprio bot e
adaptadas somente no ensaio como mensagens de um participante confirmado.

Passaram:

- Criação dos canais privados, permissões e identidade do aplicativo/dono.
- Ativação do webhook e publicação do painel em Components V2.
- Retransmissão de texto e Markdown, etiqueta Owner e ausência de ping everyone.
- Edição da cópia no mesmo ID, sem publicar uma segunda mensagem.
- Upload real de imagem spoiler e vídeo MP4 válido, com hashes idênticos aos
  anexos originais após download pelo CDN e reenvio pelo webhook.
- Exclusão real da original e remoção da cópia.
- Limpeza do texto temporário após avanço controlado de uma hora, preservando
  os anexos visíveis no Discord, recibos e confirmação da conta.
- Remoção dos dois canais e dos artefatos temporários ao terminar.

O ensaio usa **um servidor físico com dois destinos privados**, representando
dois servidores lógicos apenas no banco temporário. Confirma transporte HTTP,
webhook e comportamento da implementação, mas não é um teste com duas contas
humanas em dois servidores físicos. Não comprova reprodução de vídeo ou
legibilidade em todos os clientes. Esses pontos dependem de uso no Discord.

A conferência real revelou que o construtor parcial de webhook do discord.py
não herda o proxy do cliente. O relay agora mantém a mesma configuração de
transporte do bot; os downloads respeitam o proxy do ambiente. A repetição do
ensaio passou após a correção.

## Cenários automatizados

`tests/test_global_chat.py` cobre conversa em três servidores simulados,
confirmação global, bloqueios, controles privados, relatórios, mídias, edição e
exclusão, cópia removida por moderação, retenção, recuperação após reinício,
perda de confirmação de entrega, permissões revogadas durante envio, cache
concorrente, etiquetas por ID e restauração sem arquivar texto do chat.

A suíte completa mantém os testes anteriores da tier list e dos módulos
arquivados. O perfil isolado da hospedagem inclui o novo teste global e conserva
credenciais removidas e rede externa bloqueada. Nenhum ensaio fabrica votos ou
altera classificações oficiais.

## Ativação na hospedagem

O código publicado precisa ser atualizado e o processo reiniciado na hospedagem.
Só esse reinício registra a nova descrição/permissão de `/chatglobal` e inicia a
fila. Depois, um administrador ativa um canal por servidor e os participantes
confirmam pelos botões. O teste não deixou uma conexão pública ativa.
