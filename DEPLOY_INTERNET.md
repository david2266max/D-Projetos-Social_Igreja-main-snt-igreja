# Publicar na internet (sem usar seu PC ligado)

Este projeto já está preparado para deploy em nuvem.

## Opção recomendada: Render (mais simples)

### 1) Subir projeto para GitHub
1. Crie um repositório no GitHub.
2. Envie os arquivos deste projeto para lá.

### 2) Criar serviço no Render
1. Acesse: https://render.com
2. Clique em **New +** → **Blueprint**.
3. Conecte seu GitHub e selecione o repositório.
4. O Render vai ler o arquivo `render.yaml` automaticamente.
5. Clique em **Apply** para criar o serviço.

### 3) URL pública
- Ao finalizar o deploy, você recebe um link como:
  - `https://snt-igreja.onrender.com`
- Esse link funciona para qualquer pessoa, sem seu PC ligado.
- Se o serviço no Render estiver com o nome `snt-igreja`, o link padrão é exatamente:
  - `https://snt-igreja.onrender.com`
- Se o nome do serviço for diferente, o subdomínio também muda.

### 4) Persistência de dados
- O `render.yaml` já cria um disco (`/var/data`) para:
  - Banco SQLite: `/var/data/social_igreja_web.db`
  - Fotos: `/var/data/uploads`

### 5) Verificação
- Abra:
  - `/health` para checar se está no ar
  - `/` para login
  - `/register` para cadastro

---

## Se quiser domínio próprio
No painel do Render:
1. **Settings** → **Custom Domains**
2. Adicione seu domínio
3. Configure os DNS indicados

---

## Observação importante
- No plano gratuito do Render, o app pode "dormir" após inatividade.
- Em uso real contínuo, vale migrar para plano pago.
- Confirme que o arquivo `render.yaml` está na raiz do repositório conectado ao Render.
