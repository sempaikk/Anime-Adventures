# AA Visual Editor

Personalize textos, números, imagens e aparência da página do Anime Adventures no seu navegador.

## [Baixar o atualizador automático para Windows x64 (.zip)](https://raw.githubusercontent.com/sempaikk/Anime-Adventures/refs/heads/aa-visual-editor-downloads/AA-Atualizador-v1.0.0-Windows-x64.zip)

Configure uma vez:

1. No editor atual, use **Perfis e cenas → Exportar todos os perfis** e guarde o backup.
2. Extraia o ZIP do atualizador e abra **AA-Atualizador.exe**.
3. Clique em **Escolher pasta** e selecione a **mesma pasta AA-Visual-Editor já instalada**, que contém `manifest.json`. Se precisar, confira a pasta de origem nos detalhes da extensão, em **Carregada de**.
4. Clique em **Ativar atualização automática**.

O programa inicia quando você entra na conta do Windows, verifica novas versões a cada minuto e atualiza os arquivos na mesma pasta. Depois de uma nova versão, clique em **Recarregar** na extensão e dê **F5** no site. Mantenha a extensão instalada.

No menu Iniciar, procure **Atualizador AA Visual Editor** para usar **Verificar agora** ou **Desativar automático**. O atualizador guarda três cópias anteriores do código e não lê nem modifica os perfis e imagens do Chrome. Os pacotes são conferidos por assinatura Ed25519 e SHA-256. O executável inicial não possui assinatura Authenticode.

**Validação do atualizador:** 19 testes do núcleo com 36 verificações incluindo subtestes, detector de concorrência e pacote real da extensão. O executável Windows x64, a interface GUI e a solicitação `asInvoker` foram compilados/conferidos estaticamente. A janela, o menu Iniciar e a inicialização na conta do Windows não foram executados neste ambiente Linux.

[Código-fonte do atualizador (.zip)](https://raw.githubusercontent.com/sempaikk/Anime-Adventures/refs/heads/aa-visual-editor-downloads/AA-Atualizador-v1.0.0-FONTE.zip).

## [Baixar a versão corrigida 2.0.1 (.zip)](https://raw.githubusercontent.com/sempaikk/Anime-Adventures/refs/heads/aa-visual-editor-downloads/AA-Visual-Editor-v2.0.1.zip)

### Atualizar mantendo seus dados

1. No editor atual, abra **Perfis e cenas → Exportar todos os perfis** e guarde o backup JSON.
2. Baixe o ZIP e escolha **Extrair Tudo** no Explorador de Arquivos do Windows.
3. Copie os arquivos novos para **dentro da mesma pasta AA-Visual-Editor já instalada**, substituindo os anteriores. Mantenha o caminho da pasta.
4. Abra `chrome://extensions` e clique em **Recarregar** na extensão existente. Atualize a página do Anime Adventures com F5.
5. Se uma alteração antiga estiver pendente, clique em **Ativar seleção por clique**, selecione novamente o campo e use **Aplicar texto**.

Mantenha a extensão instalada durante a atualização para conservar seu armazenamento.

### Primeira instalação

Extraia o ZIP. Em `chrome://extensions`, ative **Modo do desenvolvedor**, escolha **Carregar sem compactação** e selecione a pasta **AA-Visual-Editor** que contém `manifest.json`. Atualize a página do Anime Adventures e clique no botão **AA Editor** no canto inferior direito.

No Edge, use `edge://extensions`.

### Correções incluídas

- Aplicar e reaplicar texto/números, contadores sem ID, mudanças de posição e troca de nós pelo site.
- Seleção em grupo, campos rápidos, aparência avançada, unidades e restauração dos valores reais.
- Prévias de texto e imagem, confirmação de imagem por link, cancelamento e transformação remota quando o servidor permite CORS.
- Backup completo com alterações ainda não salvas, proteção das imagens das cópias de recuperação e mensagens corretas de salvamento/importação.
- Detecção tardia do rodapé do BetterBLOX e validação de atalhos importados.

O formato dos dados e as três permissões da extensão foram mantidos. As alterações são locais à página do jogo 8304191830. Guia completo incluído no ZIP.

**Verificação:** 102 testes aprovados, incluindo os 76 anteriores. Ensaio com 1.800 alterações e 360 recriações de contador. Os testes usam Chromium com página sintética e APIs Chrome simuladas; instalação real, captura nativa e BetterBLOX instalado não foram executados neste ambiente.

**Pacote:** 75.092 bytes; 19 arquivos. SHA-256: `b0650eaf0565871ebfcb90a39f11919271e5366b0b03457acf8bdae8480bd547`.
