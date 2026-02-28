# Rede Social Igreja (Web) - Servidor no seu PC

## 1) Instalar dependências

No PowerShell, dentro da pasta do projeto, execute:

```powershell
pip install -r requirements-web.txt
```

## 2) Iniciar o servidor local

```powershell
uvicorn web_server:app --host 0.0.0.0 --port 8000 --reload
```

## 3) Acessar no próprio computador

Abra no navegador:

`http://127.0.0.1:8000`

## 4) Acessar no celular (mesma rede Wi-Fi)

1. Descubra o IP do seu PC:

```powershell
ipconfig
```

2. Procure o IPv4 (exemplo: `192.168.0.25`)
3. No celular, abra:

`http://SEU_IP:8000`

Exemplo:

`http://192.168.0.25:8000`

## 5) Banco de dados e fotos

- Banco local: `social_igreja_web.db`
- Fotos de perfil: pasta `uploads/`

## Observações de teste

- O cadastro exige foto, Revisão de Vidas e batismo nas águas.
- Para acesso externo (fora da sua rede), será preciso liberar porta no roteador e configurar DNS/túnel.

## Recursos internos já implementados (modo teste)

- Senha com hash forte (`PBKDF2` com salt) e compatibilidade com hash antigo.
- Feed com curtidas e comentários.
- Exclusão da própria publicação.
- Busca de membros por nome, igreja, cidade e país.
- Edição de perfil (dados, nova senha e troca de foto).
- Papéis de usuário: `membro`, `lider`, `admin`.
- Painel de moderação para `lider/admin` com denúncias de post/comentário.
- Gestão de função de usuários para `admin`.
- Conexões bilaterais de `conhecidos` com solicitação, aceite e recusa.

## Regras de papéis (teste local)

- Primeiro usuário cadastrado recebe `admin` automaticamente.
- Demais usuários entram como `membro`.
- `lider/admin` podem remover conteúdo denunciado.
- `admin` pode alterar função de outros usuários.