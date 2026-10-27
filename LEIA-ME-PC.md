> **CANCELADO EM 27/10/2026:** o responsável removeu `/ask` e toda a integração com o PC. Este documento é histórico; não seguir as instruções de instalação/migração. Veja `LEIA-ME-REMOCAO.txt`.

# Base de perguntas no seu Windows

Pasta de dados escolhida: **`D:\Armazenamento do Bot`**.
Endereço do bot: **`https://7g2x14fnpa.apps.bot-hosting.cloud`**.
O site não participa desta configuração.

## Atualização de uma instalação existente

Se o programa já conectou e importou seus dados, a correção `.3` pode ser instalada pelo ZIP pequeno de atualização: feche a janela, copie somente `game_knowledge.py` e `knowledge_pc.py` para a pasta onde está `INICIAR-PC.cmd`, substitua esses dois arquivos e abra o programa novamente. Veja `LEIA-ME-ATUALIZACAO.txt`. Não precisa executar a configuração outra vez nem mudar variáveis/chaves. Bancos e arquivos privados permanecem no lugar. Teste “Como conseguir gemas?” antes de finalizar a migração. A busca por upgrade/nível do Dark Mage continua sendo uma pendência separada.

## Primeira instalação

1. Instale **Python 3.12 para Windows**, com o Python Launcher, se ainda não estiver instalado. A versão 3.12 da hospedagem não instala Python no seu computador.
2. Extraia este pacote numa pasta permanente, por exemplo `D:\Armazenamento do Bot\programa`. Não execute os arquivos de dentro do ZIP.
3. Abra **`CONFIGURAR-PC.cmd`**. Ele instala as dependências num ambiente separado em `D:\Armazenamento do Bot\.pc-venv` e pede sua chave Groq atual. A digitação fica oculta. Cole a chave localmente; não envie aqui ou ao GitHub.
4. Abra localmente `D:\Armazenamento do Bot\HOSTING-SETUP.private.txt`. Ele contém as duas variáveis para cadastrar no painel **Ambiente** da instância existente: `KNOWLEDGE_MODE=pc` e `KNOWLEDGE_BRIDGE_SECRET` com o valor gerado. Marque a segunda como **Segredo**. Não envie captura desse arquivo. Preserve `DATA_DIR`, `DISCORD_TOKEN` e `SECONDARY_ACCOUNT_TOKEN`.
5. Atualize o código hospedado para a versão desta entrega e reinicie. O `/ask` fica indisponível até o programa do PC conectar; o arquivo antigo continua preservado para transferência.
6. Abra **`INICIAR-PC.cmd`**. A primeira execução baixa uma cópia consistente do conhecimento antigo, verifica integridade/hash/quantidades e importa a base. A mensagem **Import verified** mostra as quantidades. Depois, **Connected** confirma a conexão do programa.
7. Teste `/ask` no Discord. Feche o programa e teste novamente: deve aparecer o aviso de indisponibilidade. Abra o programa e confirme a reconexão. Reinicie o programa mais uma vez para conferir que o histórico permanece.
8. Depois desses testes, mantenha `INICIAR-PC.cmd` aberto e execute **`FINALIZAR-MIGRACAO.cmd`** em outra janela. O servidor confere o recibo da importação e a conexão ativa antes de remover somente `knowledge.sqlite3` e seu backup antigo da hospedagem. Se a verificação falhar, os arquivos permanecem preservados. Não apague a pasta `DATA_DIR`.
9. A chave `GROQ_API_KEY` passa a ser usada pelo programa do PC. Após concluir a migração, ela pode ser retirada da hospedagem; mantenha a chave em `pc-knowledge.private.json` no PC. Não mova o token do bot ou da conta leitora para o PC.

## Uso diário

Deixe `INICIAR-PC.cmd` aberto quando quiser disponibilizar perguntas. PC desligado, suspenso, sem internet ou programa fechado deixam o `/ask` indisponível. A conexão é monitorada; uma queda é reconhecida em aproximadamente vinte segundos, além dos tempos da rede. Uma pergunta em andamento pode falhar durante a queda. Ao reconectar, a coleta tenta recuperar mensagens ainda disponíveis após o último cursor confirmado.

Para iniciar ao entrar no Windows: pressione **Win+R**, digite `shell:startup` e coloque nessa pasta um **atalho** para `INICIAR-PC.cmd`. Não mova o programa original. Isso inicia ao fazer login, não antes. Remova o atalho quando quiser desativar esse início automático.

O PC armazena wiki, índice, histórico, cursor, orçamento da Groq e backups. O bot hospedado só encaminha perguntas/respostas e mensagens recebidas enquanto conectado; não mantém outro arquivo de Questões nem usa a IA como alternativa local. O acervo público da wiki ainda acompanha o pacote de código para instalação, mas não é indexado/utilizado na hospedagem em modo PC.

A IA continua na Groq e recebe somente trechos selecionados. O HD maior não corrige automaticamente a busca por upgrades/níveis; essa melhoria permanece pendente. O acervo atual tem revisões históricas e não comprova os atributos do patch atual.

Não há exclusão por idade/quantidade nem a reserva anterior de 64 MiB no PC. O arquivo cresce conforme o conteúdo; a coleta pausa com menos de 1 GiB livre, sem apagar registros. Os limites reais são espaço, desempenho e disponibilidade. O backup local rotativo continua; mantenha também uma cópia privada em outro dispositivo para proteger contra falha do HD.

## Arquivos privados

- `pc-knowledge.private.json`: configuração com chave Groq e segredo da conexão.
- `HOSTING-SETUP.private.txt`: segredo que foi cadastrado no painel.
- `knowledge.sqlite3` e `knowledge-controls.sqlite3`: base e controles de perguntas.
- `knowledge-backup.sqlite3`: cópia rotativa da base.
- `migration-receipt.json`: conferência da transferência.

Não publique esses arquivos. O programa não abre seu HD como pasta compartilhada nem aceita comandos de shell pela conexão; somente operações de perguntas, coleta e confirmação do cursor. Nenhuma porta do roteador precisa ser aberta.
