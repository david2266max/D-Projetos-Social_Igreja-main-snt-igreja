import hashlib
import hmac
import os
import secrets
import sqlite3
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from backup_sqlite import create_sqlite_backup, ensure_dir, prune_old_backups
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("DATA_DIR", BASE_DIR)
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "social_igreja_web.db"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(DATA_DIR, "uploads"))
CHAT_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "chat")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
SESSION_SECRET = os.getenv("SESSION_SECRET", "social-igreja-chave-local")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "5"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
BACKUP_DIR = os.getenv("BACKUP_DIR", os.path.join(DATA_DIR, "backups"))
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "15"))

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CHAT_UPLOAD_DIR, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            igreja TEXT NOT NULL,
            cidade TEXT NOT NULL,
            pais TEXT NOT NULL,
            telefone TEXT NOT NULL DEFAULT '',
            faixa_etaria TEXT NOT NULL,
            revisao_vidas INTEGER NOT NULL,
            batizado_aguas INTEGER NOT NULL,
            foto_url TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'membro',
            approved INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL
        )
        """
    )

    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row[1] for row in cursor.fetchall()]
    if "role" not in user_columns:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'membro'")
        except sqlite3.OperationalError:
            cursor.execute("PRAGMA table_info(users)")
            user_columns = [row[1] for row in cursor.fetchall()]
            if "role" not in user_columns:
                raise
    if "telefone" not in user_columns:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN telefone TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            cursor.execute("PRAGMA table_info(users)")
            user_columns = [row[1] for row in cursor.fetchall()]
            if "telefone" not in user_columns:
                raise
    if "approved" not in user_columns:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN approved INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError:
            cursor.execute("PRAGMA table_info(users)")
            user_columns = [row[1] for row in cursor.fetchall()]
            if "approved" not in user_columns:
                raise

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            conteudo TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS photo_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            caption TEXT,
            image_url TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS photo_post_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            criado_em TEXT NOT NULL,
            UNIQUE(photo_post_id, user_id),
            FOREIGN KEY (photo_post_id) REFERENCES photo_posts(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS photo_post_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            conteudo TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            FOREIGN KEY (photo_post_id) REFERENCES photo_posts(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            conteudo TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES posts(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS post_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            criado_em TEXT NOT NULL,
            UNIQUE(post_id, user_id),
            FOREIGN KEY (post_id) REFERENCES posts(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_user_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            motivo TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'aberto',
            criado_em TEXT NOT NULL,
            FOREIGN KEY (reporter_user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS known_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            known_user_id INTEGER NOT NULL,
            criado_em TEXT NOT NULL,
            UNIQUE(user_id, known_user_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (known_user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS connection_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_user_id INTEGER NOT NULL,
            receiver_user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendente',
            criado_em TEXT NOT NULL,
            UNIQUE(requester_user_id, receiver_user_id),
            FOREIGN KEY (requester_user_id) REFERENCES users(id),
            FOREIGN KEY (receiver_user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            name TEXT,
            created_by_user_id INTEGER NOT NULL,
            criado_em TEXT NOT NULL,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            criado_em TEXT NOT NULL,
            UNIQUE(conversation_id, user_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_user_id INTEGER NOT NULL,
            conteudo TEXT,
            file_url TEXT,
            file_name TEXT,
            criado_em TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (sender_user_id) REFERENCES users(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            last_read_message_id INTEGER NOT NULL DEFAULT 0,
            atualizado_em TEXT NOT NULL,
            UNIQUE(conversation_id, user_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )

    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 200000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations_str, salt, expected_hex = stored_hash.split("$", 3)
            iterations = int(iterations_str)
            test_hash = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
            ).hex()
            return hmac.compare_digest(test_hash, expected_hex)
        except ValueError:
            return False

    legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy, stored_hash)


def save_uploaded_photo(photo: UploadFile):
    if not photo.filename:
        return None, "Envie uma foto de perfil."

    extension = os.path.splitext(photo.filename)[1].lower()
    if extension not in [".jpg", ".jpeg", ".png", ".webp"]:
        return None, "Formato de foto inválido. Use JPG, PNG ou WEBP."

    file_name = f"{uuid.uuid4().hex}{extension}"
    file_path = os.path.join(UPLOAD_DIR, file_name)

    file_bytes = photo.file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return None, f"Foto muito grande. Limite de {MAX_UPLOAD_MB}MB."

    with open(file_path, "wb") as f:
        f.write(file_bytes)
    return f"/uploads/{file_name}", None


def save_gallery_photo(photo: UploadFile):
    if not photo or not photo.filename:
        return None, "Selecione uma imagem para publicar."

    extension = os.path.splitext(photo.filename)[1].lower()
    if extension not in [".jpg", ".jpeg", ".png", ".webp"]:
        return None, "Formato inválido. Use JPG, PNG ou WEBP."

    file_name = f"gallery_{uuid.uuid4().hex}{extension}"
    file_path = os.path.join(UPLOAD_DIR, file_name)

    file_bytes = photo.file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return None, f"Imagem muito grande. Limite de {MAX_UPLOAD_MB}MB."

    with open(file_path, "wb") as out:
        out.write(file_bytes)
    return f"/uploads/{file_name}", None


def save_chat_file(file: UploadFile):
    if not file or not file.filename:
        return None, None, None

    file_name = file.filename.strip()
    if not file_name:
        return None, None, "Arquivo inválido."

    extension = os.path.splitext(file_name)[1].lower()
    safe_name = f"{uuid.uuid4().hex}{extension}"
    file_path = os.path.join(CHAT_UPLOAD_DIR, safe_name)

    file_bytes = file.file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return None, None, f"Arquivo muito grande. Limite de {MAX_UPLOAD_MB}MB."

    with open(file_path, "wb") as out:
        out.write(file_bytes)

    return f"/uploads/chat/{safe_name}", file_name, None


def can_users_chat(cursor, user_a_id: int, user_b_id: int) -> bool:
    if user_a_id == user_b_id:
        return True
    cursor.execute(
        "SELECT 1 FROM known_contacts WHERE user_id = ? AND known_user_id = ?",
        (user_a_id, user_b_id),
    )
    return cursor.fetchone() is not None


def get_or_create_dm(cursor, user_a_id: int, user_b_id: int) -> int:
    first_id, second_id = sorted([user_a_id, user_b_id])
    cursor.execute(
        """
        SELECT c.id
        FROM conversations c
        INNER JOIN conversation_members cm1 ON cm1.conversation_id = c.id AND cm1.user_id = ?
        INNER JOIN conversation_members cm2 ON cm2.conversation_id = c.id AND cm2.user_id = ?
        WHERE c.type = 'dm'
        """,
        (first_id, second_id),
    )
    row = cursor.fetchone()
    if row:
        return row["id"]

    now = datetime.now().isoformat(timespec="seconds")
    cursor.execute(
        "INSERT INTO conversations (type, name, created_by_user_id, criado_em) VALUES ('dm', NULL, ?, ?)",
        (user_a_id, now),
    )
    conversation_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO conversation_members (conversation_id, user_id, criado_em) VALUES (?, ?, ?)",
        (conversation_id, first_id, now),
    )
    cursor.execute(
        "INSERT INTO conversation_members (conversation_id, user_id, criado_em) VALUES (?, ?, ?)",
        (conversation_id, second_id, now),
    )
    return conversation_id


def get_user_conversations(cursor, user_id: int):
    try:
        cursor.execute(
            """
            SELECT c.id,
                   c.type,
                   c.name,
                   c.criado_em,
                   (
                       SELECT m.conteudo
                       FROM messages m
                       WHERE m.conversation_id = c.id
                       ORDER BY m.id DESC
                       LIMIT 1
                   ) AS last_message,
                   (
                       SELECT m.criado_em
                       FROM messages m
                       WHERE m.conversation_id = c.id
                       ORDER BY m.id DESC
                       LIMIT 1
                   ) AS last_message_at,
                   (
                       SELECT GROUP_CONCAT(u.nome, ', ')
                       FROM conversation_members cmx
                       INNER JOIN users u ON u.id = cmx.user_id
                       WHERE cmx.conversation_id = c.id
                   ) AS participants_names,
                   (
                       SELECT u.nome
                       FROM conversation_members cmdm
                       INNER JOIN users u ON u.id = cmdm.user_id
                       WHERE cmdm.conversation_id = c.id AND cmdm.user_id != ?
                       LIMIT 1
                   ) AS dm_other_name,
                   (
                       SELECT COUNT(*)
                       FROM messages mu
                       WHERE mu.conversation_id = c.id
                         AND mu.sender_user_id != ?
                         AND mu.id > COALESCE(
                             (
                                 SELECT cr.last_read_message_id
                                 FROM conversation_reads cr
                                 WHERE cr.conversation_id = c.id AND cr.user_id = ?
                             ),
                             0
                         )
                   ) AS unread_count
            FROM conversations c
            INNER JOIN conversation_members cm ON cm.conversation_id = c.id
            WHERE cm.user_id = ?
            ORDER BY COALESCE(last_message_at, c.criado_em) DESC
            """,
            (user_id, user_id, user_id, user_id),
        )
        return cursor.fetchall()
    except sqlite3.OperationalError as err:
        if "conversation_reads" not in str(err):
            raise
        cursor.execute(
            """
            SELECT c.id,
                   c.type,
                   c.name,
                   c.criado_em,
                   (
                       SELECT m.conteudo
                       FROM messages m
                       WHERE m.conversation_id = c.id
                       ORDER BY m.id DESC
                       LIMIT 1
                   ) AS last_message,
                   (
                       SELECT m.criado_em
                       FROM messages m
                       WHERE m.conversation_id = c.id
                       ORDER BY m.id DESC
                       LIMIT 1
                   ) AS last_message_at,
                   (
                       SELECT GROUP_CONCAT(u.nome, ', ')
                       FROM conversation_members cmx
                       INNER JOIN users u ON u.id = cmx.user_id
                       WHERE cmx.conversation_id = c.id
                   ) AS participants_names,
                   (
                       SELECT u.nome
                       FROM conversation_members cmdm
                       INNER JOIN users u ON u.id = cmdm.user_id
                       WHERE cmdm.conversation_id = c.id AND cmdm.user_id != ?
                       LIMIT 1
                   ) AS dm_other_name,
                   0 AS unread_count
            FROM conversations c
            INNER JOIN conversation_members cm ON cm.conversation_id = c.id
            WHERE cm.user_id = ?
            ORDER BY COALESCE(last_message_at, c.criado_em) DESC
            """,
            (user_id, user_id),
        )
        return cursor.fetchall()


def get_conversation_if_member(cursor, conversation_id: int, user_id: int):
    cursor.execute(
        """
        SELECT c.id, c.type, c.name, c.created_by_user_id, c.criado_em
        FROM conversations c
        INNER JOIN conversation_members cm ON cm.conversation_id = c.id
        WHERE c.id = ? AND cm.user_id = ?
        """,
        (conversation_id, user_id),
    )
    return cursor.fetchone()


def normalize_phone(raw_phone: str) -> str:
    return "".join(ch for ch in (raw_phone or "") if ch.isdigit())


def whatsapp_link(raw_phone: str, sender_name: str) -> Optional[str]:
    phone = normalize_phone(raw_phone)
    if len(phone) < 10:
        return None
    message = quote(f"Paz! Aqui é {sender_name}. Vamos conversar na Rede Social SNT?")
    return f"https://wa.me/{phone}?text={message}"


def get_unread_chat_count(cursor, user_id: int) -> int:
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM conversations c
            INNER JOIN conversation_members cm ON cm.conversation_id = c.id
            WHERE cm.user_id = ?
              AND (
                  SELECT COUNT(*)
                  FROM messages m
                  WHERE m.conversation_id = c.id
                    AND m.sender_user_id != ?
                    AND m.id > COALESCE(
                        (
                            SELECT cr.last_read_message_id
                            FROM conversation_reads cr
                            WHERE cr.conversation_id = c.id AND cr.user_id = ?
                        ),
                        0
                    )
              ) > 0
            """,
            (user_id, user_id, user_id),
        )
        return cursor.fetchone()["total"]
    except sqlite3.OperationalError as err:
        if "conversation_reads" in str(err):
            return 0
        raise


def resolve_photo_storage_path(foto_url: Optional[str]) -> Optional[str]:
    if not foto_url:
        return None
    if not foto_url.startswith("/uploads/"):
        return None
    relative_part = foto_url.replace("/uploads/", "", 1)
    relative_part = relative_part.replace("/", os.sep)
    return os.path.abspath(os.path.join(UPLOAD_DIR, relative_part))


def delete_user_account_data(cursor, target_user_id: int):
    cursor.execute("SELECT foto_url FROM users WHERE id = ?", (target_user_id,))
    user_row = cursor.fetchone()
    profile_photo_url = user_row["foto_url"] if user_row else None

    cursor.execute("SELECT id, image_url FROM photo_posts WHERE user_id = ?", (target_user_id,))
    photo_posts = cursor.fetchall()
    for post in photo_posts:
        cursor.execute("DELETE FROM photo_post_comments WHERE photo_post_id = ?", (post["id"],))
        cursor.execute("DELETE FROM photo_post_likes WHERE photo_post_id = ?", (post["id"],))

    cursor.execute("DELETE FROM photo_post_comments WHERE user_id = ?", (target_user_id,))
    cursor.execute("DELETE FROM photo_post_likes WHERE user_id = ?", (target_user_id,))
    cursor.execute("DELETE FROM photo_posts WHERE user_id = ?", (target_user_id,))

    cursor.execute("SELECT id FROM comments WHERE user_id = ?", (target_user_id,))
    own_comments = [row["id"] for row in cursor.fetchall()]
    for comment_id in own_comments:
        cursor.execute("DELETE FROM reports WHERE target_type = 'comment' AND target_id = ?", (comment_id,))
    cursor.execute("DELETE FROM comments WHERE user_id = ?", (target_user_id,))

    cursor.execute("SELECT id FROM posts WHERE user_id = ?", (target_user_id,))
    own_posts = [row["id"] for row in cursor.fetchall()]
    for post_id in own_posts:
        cursor.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        cursor.execute("DELETE FROM post_likes WHERE post_id = ?", (post_id,))
        cursor.execute("DELETE FROM reports WHERE target_type = 'post' AND target_id = ?", (post_id,))
    cursor.execute("DELETE FROM posts WHERE user_id = ?", (target_user_id,))

    cursor.execute("DELETE FROM post_likes WHERE user_id = ?", (target_user_id,))
    cursor.execute("DELETE FROM reports WHERE reporter_user_id = ?", (target_user_id,))
    cursor.execute("DELETE FROM known_contacts WHERE user_id = ? OR known_user_id = ?", (target_user_id, target_user_id))
    cursor.execute(
        "DELETE FROM connection_requests WHERE requester_user_id = ? OR receiver_user_id = ?",
        (target_user_id, target_user_id),
    )
    cursor.execute("DELETE FROM conversation_reads WHERE user_id = ?", (target_user_id,))
    cursor.execute("DELETE FROM messages WHERE sender_user_id = ?", (target_user_id,))
    cursor.execute("DELETE FROM conversation_members WHERE user_id = ?", (target_user_id,))
    cursor.execute(
        "DELETE FROM conversations WHERE id NOT IN (SELECT DISTINCT conversation_id FROM conversation_members)"
    )
    cursor.execute("DELETE FROM users WHERE id = ?", (target_user_id,))

    file_urls = []
    if profile_photo_url:
        file_urls.append(profile_photo_url)
    for post in photo_posts:
        file_urls.append(post["image_url"])
    return file_urls


def set_flash(request: Request, message: str):
    request.session["flash_msg"] = message


def pop_flash(request: Request):
    msg = request.session.get("flash_msg")
    if msg:
        request.session.pop("flash_msg", None)
    return msg


def is_moderator(user_row):
    return user_row and user_row["role"] in ("lider", "admin")


def is_admin(user_row):
    return user_row and user_row["role"] == "admin"


def list_backups():
    ensure_dir(BACKUP_DIR)
    backups = []
    for name in os.listdir(BACKUP_DIR):
        if not name.startswith("social_igreja_web_") or not name.endswith(".db"):
            continue
        file_path = os.path.join(BACKUP_DIR, name)
        if not os.path.isfile(file_path):
            continue
        stats = os.stat(file_path)
        backups.append(
            {
                "name": name,
                "size_kb": max(1, int(stats.st_size / 1024)),
                "modified": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    backups.sort(key=lambda item: item["name"], reverse=True)
    return backups


app = FastAPI(title="Rede Social Sara Nossa Terra")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/health")
def healthcheck():
    try:
        conn = get_conn()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok", "db": "ok"}
    except sqlite3.Error:
        return {"status": "degraded", "db": "error"}


@app.get("/")
def home(request: Request):
    user_id = request.session.get("user_id")
    if user_id:
        return RedirectResponse(url="/feed", status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None, "cadastro_msg": pop_flash(request)},
    )


@app.get("/register")
def register_page(request: Request):
    user_id = request.session.get("user_id")
    if user_id:
        return RedirectResponse(url="/feed", status_code=302)
    return templates.TemplateResponse(
        "register.html",
        {"request": request, "cadastro_msg": pop_flash(request)},
    )


@app.post("/register")
async def register(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(...),
    confirmar_senha: str = Form(...),
    igreja: str = Form(...),
    cidade: str = Form(...),
    pais: str = Form(...),
    telefone: str = Form(""),
    faixa_etaria: str = Form(...),
    revisao_vidas: str = Form("off"),
    batizado_aguas: str = Form("off"),
    foto: UploadFile = File(...),
):
    senha = senha.strip()
    confirmar_senha = confirmar_senha.strip()
    if len(senha) < 8:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "cadastro_msg": "A senha precisa ter pelo menos 8 caracteres.",
            },
        )

    if senha != confirmar_senha:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "cadastro_msg": "Senha e confirmação de senha não conferem.",
            },
        )

    if revisao_vidas != "on" or batizado_aguas != "on":
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "cadastro_msg": "Cadastro permitido apenas para membros com Revisão de Vidas e batismo nas águas.",
            },
        )

    foto_url, foto_error = save_uploaded_photo(foto)
    if foto_error:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "cadastro_msg": foto_error,
            },
        )

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM users")
    total_users = cursor.fetchone()["total"]
    default_role = "admin" if total_users == 0 else "membro"
    approved = 1 if total_users == 0 else 0
    try:
        cursor.execute(
            """
            INSERT INTO users (
                nome, email, senha_hash, igreja, cidade, pais,
                telefone, faixa_etaria, revisao_vidas, batizado_aguas, foto_url, role, approved, criado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nome.strip(),
                email.strip().lower(),
                hash_password(senha),
                igreja.strip(),
                cidade.strip(),
                pais.strip(),
                normalize_phone(telefone),
                faixa_etaria,
                1,
                1,
                foto_url,
                default_role,
                approved,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "cadastro_msg": "Este e-mail já está cadastrado.",
            },
        )

    conn.close()
    if approved:
        set_flash(request, "Cadastro realizado com sucesso. Agora faça login.")
    else:
        set_flash(request, "Solicitação enviada. Aguarde aprovação de um admin para entrar.")
    return RedirectResponse(url="/", status_code=302)


@app.post("/login")
def login(request: Request, email: str = Form(...), senha: str = Form(...)):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, senha_hash, approved FROM users WHERE email = ?",
        (email.strip().lower(),),
    )
    user = cursor.fetchone()

    if not user or not verify_password(senha, user["senha_hash"]):
        conn.close()
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "E-mail ou senha inválidos.", "cadastro_msg": None},
        )

    if not user["approved"]:
        conn.close()
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Cadastro pendente de aprovação do admin.", "cadastro_msg": None},
        )

    if not user["senha_hash"].startswith("pbkdf2_sha256$"):
        cursor.execute(
            "UPDATE users SET senha_hash = ? WHERE id = ?",
            (hash_password(senha), user["id"]),
        )
        conn.commit()
    conn.close()

    request.session["user_id"] = user["id"]
    return RedirectResponse(url="/feed", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


@app.get("/feed")
def feed(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    current_user = cursor.fetchone()

    busca = request.query_params.get("q", "").strip().lower()

    cursor.execute(
        """
        SELECT p.id, p.user_id, p.conteudo, p.criado_em, u.nome, u.igreja, u.cidade, u.pais, u.foto_url,
               (SELECT COUNT(*) FROM post_likes pl WHERE pl.post_id = p.id) AS likes_count,
               EXISTS(
                   SELECT 1 FROM post_likes mpl
                   WHERE mpl.post_id = p.id AND mpl.user_id = ?
               ) AS liked_by_me
        FROM posts p
        INNER JOIN users u ON u.id = p.user_id
        ORDER BY p.id DESC
        """,
        (user_id,),
    )
    posts = cursor.fetchall()

    cursor.execute(
        """
        SELECT c.id, c.post_id, c.conteudo, c.criado_em, u.nome
        FROM comments c
        INNER JOIN users u ON u.id = c.user_id
        ORDER BY c.id ASC
        """
    )
    comments_rows = cursor.fetchall()
    comments_by_post = {}
    for row in comments_rows:
        comments_by_post.setdefault(row["post_id"], []).append(row)

    cursor.execute(
        """
        SELECT r.id, r.target_type, r.target_id, r.motivo, r.status, r.criado_em,
               ru.nome AS reporter_nome
        FROM reports r
        INNER JOIN users ru ON ru.id = r.reporter_user_id
        WHERE r.status = 'aberto'
        ORDER BY r.id DESC
        """
    )
    reports = cursor.fetchall()

    if busca:
        like = f"%{busca}%"
        cursor.execute(
            """
            SELECT id, nome, igreja, cidade, pais, telefone, faixa_etaria, foto_url, role
            FROM users
            WHERE approved = 1
              AND (lower(nome) LIKE ? OR lower(igreja) LIKE ? OR lower(cidade) LIKE ? OR lower(pais) LIKE ?)
            ORDER BY nome
            """,
            (like, like, like, like),
        )
    else:
        cursor.execute(
            "SELECT id, nome, igreja, cidade, pais, telefone, faixa_etaria, foto_url, role FROM users WHERE approved = 1 ORDER BY nome"
        )
    members = []
    for row in cursor.fetchall():
        member = dict(row)
        member["whatsapp_link"] = whatsapp_link(member.get("telefone", ""), current_user["nome"])
        members.append(member)

    cursor.execute(
        "SELECT known_user_id FROM known_contacts WHERE user_id = ?",
        (user_id,),
    )
    known_ids = {row["known_user_id"] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT receiver_user_id
        FROM connection_requests
        WHERE requester_user_id = ? AND status = 'pendente'
        """,
        (user_id,),
    )
    pending_sent_ids = {row["receiver_user_id"] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT cr.id, cr.requester_user_id, u.nome, u.igreja, u.cidade, u.pais, u.foto_url, cr.criado_em
        FROM connection_requests cr
        INNER JOIN users u ON u.id = cr.requester_user_id
        WHERE cr.receiver_user_id = ? AND cr.status = 'pendente'
        ORDER BY cr.id DESC
        """,
        (user_id,),
    )
    pending_received = cursor.fetchall()
    pending_received_count = len(pending_received)
    pending_sent_count = len(pending_sent_ids)

    unread_chat_count = get_unread_chat_count(cursor, user_id)

    pending_registrations = []
    backup_files = []
    if is_admin(current_user):
        cursor.execute(
            """
            SELECT id, nome, email, igreja, cidade, pais, criado_em
            FROM users
            WHERE approved = 0
            ORDER BY id DESC
            """
        )
        pending_registrations = cursor.fetchall()
        backup_files = list_backups()

    cursor.execute(
        """
        SELECT u.id, u.nome, u.igreja, u.cidade, u.pais, u.foto_url, u.telefone
        FROM known_contacts kc
        INNER JOIN users u ON u.id = kc.known_user_id
        WHERE kc.user_id = ?
        ORDER BY u.nome
        """,
        (user_id,),
    )
    known_contacts = []
    for row in cursor.fetchall():
        known = dict(row)
        known["whatsapp_link"] = whatsapp_link(known.get("telefone", ""), current_user["nome"])
        known_contacts.append(known)

    cursor.execute("SELECT COUNT(*) AS total FROM posts WHERE user_id = ?", (user_id,))
    my_posts_count = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM comments WHERE user_id = ?", (user_id,))
    my_comments_count = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM known_contacts WHERE user_id = ?", (user_id,))
    my_known_count = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM post_likes pl
        INNER JOIN posts p ON p.id = pl.post_id
        WHERE p.user_id = ?
        """,
        (user_id,),
    )
    my_likes_received = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM users")
    total_members = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM posts")
    total_posts = cursor.fetchone()["total"]

    profile_stats = {
        "my_posts": my_posts_count,
        "my_comments": my_comments_count,
        "my_known": my_known_count,
        "my_likes_received": my_likes_received,
    }
    community_stats = {
        "total_members": total_members,
        "total_posts": total_posts,
    }
    conn.close()

    return templates.TemplateResponse(
        "feed.html",
        {
            "request": request,
            "user": current_user,
            "posts": posts,
            "comments_by_post": comments_by_post,
            "members": members,
            "busca": busca,
            "flash": pop_flash(request),
            "reports": reports,
            "is_moderator": is_moderator(current_user),
            "is_admin": is_admin(current_user),
            "known_ids": known_ids,
            "known_contacts": known_contacts,
            "pending_sent_ids": pending_sent_ids,
            "pending_sent_count": pending_sent_count,
            "pending_received": pending_received,
            "pending_received_count": pending_received_count,
            "unread_chat_count": unread_chat_count,
            "pending_registrations": pending_registrations,
            "backup_files": backup_files,
            "profile_stats": profile_stats,
            "community_stats": community_stats,
        },
    )


@app.post("/posts")
def create_post(request: Request, conteudo: str = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conteudo = conteudo.strip()
    if not conteudo:
        return RedirectResponse(url="/feed", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO posts (user_id, conteudo, criado_em) VALUES (?, ?, ?)",
        (user_id, conteudo, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url="/feed", status_code=302)


@app.get("/photos")
def photos_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    current_user = cursor.fetchone()

    cursor.execute(
        """
        SELECT pp.id, pp.user_id, pp.caption, pp.image_url, pp.criado_em,
               u.nome, u.igreja, u.cidade, u.pais, u.foto_url,
               (SELECT COUNT(*) FROM photo_post_likes ppl WHERE ppl.photo_post_id = pp.id) AS likes_count,
               EXISTS(
                   SELECT 1 FROM photo_post_likes mpl
                   WHERE mpl.photo_post_id = pp.id AND mpl.user_id = ?
               ) AS liked_by_me
        FROM photo_posts pp
        INNER JOIN users u ON u.id = pp.user_id
        ORDER BY pp.id DESC
        """,
        (user_id,),
    )
    photo_posts = cursor.fetchall()

    cursor.execute(
        """
        SELECT c.id, c.photo_post_id, c.conteudo, c.criado_em, u.nome
        FROM photo_post_comments c
        INNER JOIN users u ON u.id = c.user_id
        ORDER BY c.id ASC
        """
    )
    comments_rows = cursor.fetchall()
    comments_by_photo = {}
    for row in comments_rows:
        comments_by_photo.setdefault(row["photo_post_id"], []).append(row)
    conn.close()

    return templates.TemplateResponse(
        "photos.html",
        {
            "request": request,
            "user": current_user,
            "photo_posts": photo_posts,
            "comments_by_photo": comments_by_photo,
            "flash": pop_flash(request),
        },
    )


@app.post("/photos")
async def create_photo_post(
    request: Request,
    caption: str = Form(""),
    image: UploadFile = File(...),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    image_url, image_error = save_gallery_photo(image)
    if image_error:
        set_flash(request, image_error)
        return RedirectResponse(url="/photos", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO photo_posts (user_id, caption, image_url, criado_em)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            caption.strip() or None,
            image_url,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()
    set_flash(request, "Foto publicada com sucesso.")
    return RedirectResponse(url="/photos", status_code=302)


@app.post("/photos/{photo_post_id}/like")
def toggle_photo_like(photo_post_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM photo_post_likes WHERE photo_post_id = ? AND user_id = ?",
        (photo_post_id, user_id),
    )
    like = cursor.fetchone()
    if like:
        cursor.execute("DELETE FROM photo_post_likes WHERE id = ?", (like["id"],))
    else:
        cursor.execute(
            "INSERT INTO photo_post_likes (photo_post_id, user_id, criado_em) VALUES (?, ?, ?)",
            (photo_post_id, user_id, datetime.now().isoformat(timespec="seconds")),
        )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/photos", status_code=302)


@app.post("/photos/{photo_post_id}/comments")
def create_photo_comment(photo_post_id: int, request: Request, conteudo: str = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    texto = conteudo.strip()
    if not texto:
        return RedirectResponse(url="/photos", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO photo_post_comments (photo_post_id, user_id, conteudo, criado_em) VALUES (?, ?, ?, ?)",
        (photo_post_id, user_id, texto, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/photos", status_code=302)


@app.post("/photos/{photo_post_id}/delete")
def delete_photo_post(photo_post_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, image_url FROM photo_posts WHERE id = ?", (photo_post_id,))
    photo_post = cursor.fetchone()
    if not photo_post:
        conn.close()
        set_flash(request, "Foto não encontrada.")
        return RedirectResponse(url="/photos", status_code=302)

    if photo_post["user_id"] != user_id:
        conn.close()
        set_flash(request, "Você só pode excluir suas próprias fotos.")
        return RedirectResponse(url="/photos", status_code=302)

    cursor.execute("DELETE FROM photo_post_comments WHERE photo_post_id = ?", (photo_post_id,))
    cursor.execute("DELETE FROM photo_post_likes WHERE photo_post_id = ?", (photo_post_id,))
    cursor.execute("DELETE FROM photo_posts WHERE id = ?", (photo_post_id,))
    conn.commit()
    conn.close()

    image_path = resolve_photo_storage_path(photo_post["image_url"])
    if image_path and os.path.exists(image_path):
        try:
            os.remove(image_path)
        except OSError:
            pass

    set_flash(request, "Foto removida com sucesso.")
    return RedirectResponse(url="/photos", status_code=302)


@app.post("/posts/{post_id}/like")
def toggle_like(post_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM post_likes WHERE post_id = ? AND user_id = ?",
        (post_id, user_id),
    )
    like = cursor.fetchone()
    if like:
        cursor.execute("DELETE FROM post_likes WHERE id = ?", (like["id"],))
    else:
        cursor.execute(
            "INSERT INTO post_likes (post_id, user_id, criado_em) VALUES (?, ?, ?)",
            (post_id, user_id, datetime.now().isoformat(timespec="seconds")),
        )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/posts/{post_id}/comments")
def create_comment(post_id: int, request: Request, conteudo: str = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    texto = conteudo.strip()
    if not texto:
        return RedirectResponse(url="/feed", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO comments (post_id, user_id, conteudo, criado_em) VALUES (?, ?, ?, ?)",
        (post_id, user_id, texto, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/posts/{post_id}/delete")
def delete_post(post_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    acting_user = cursor.fetchone()
    cursor.execute("SELECT user_id FROM posts WHERE id = ?", (post_id,))
    post = cursor.fetchone()
    can_delete = post and (post["user_id"] == user_id or (acting_user and acting_user["role"] in ("lider", "admin")))
    if can_delete:
        cursor.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        cursor.execute("DELETE FROM post_likes WHERE post_id = ?", (post_id,))
        cursor.execute("DELETE FROM reports WHERE target_type = 'post' AND target_id = ?", (post_id,))
        cursor.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        conn.commit()
        set_flash(request, "Publicação removida com sucesso.")
    conn.close()
    return RedirectResponse(url="/feed", status_code=302)


@app.get("/profile/edit")
def profile_edit_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    current_user = cursor.fetchone()

    admin_candidates = []
    if current_user and current_user["role"] == "admin":
        cursor.execute(
            """
            SELECT id, nome, email
            FROM users
            WHERE id != ? AND approved = 1
            ORDER BY nome
            """,
            (user_id,),
        )
        admin_candidates = cursor.fetchall()
    conn.close()

    return templates.TemplateResponse(
        "profile_edit.html",
        {
            "request": request,
            "user": current_user,
            "flash": pop_flash(request),
            "admin_candidates": admin_candidates,
        },
    )


@app.get("/users/{target_user_id}")
def user_profile_page(target_user_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (target_user_id,))
    target_user = cursor.fetchone()
    if not target_user:
        conn.close()
        set_flash(request, "Usuário não encontrado.")
        return RedirectResponse(url="/feed", status_code=302)

    can_view = user_id == target_user_id
    if not can_view:
        cursor.execute(
            "SELECT 1 FROM known_contacts WHERE user_id = ? AND known_user_id = ?",
            (user_id, target_user_id),
        )
        relation = cursor.fetchone()
        can_view = relation is not None

    if not can_view:
        conn.close()
        set_flash(request, "Perfil disponível apenas para conhecidos aceitos.")
        return RedirectResponse(url="/feed", status_code=302)

    cursor.execute(
        """
        SELECT p.id, p.conteudo, p.criado_em,
               (SELECT COUNT(*) FROM post_likes pl WHERE pl.post_id = p.id) AS likes_count
        FROM posts p
        WHERE p.user_id = ?
        ORDER BY p.id DESC
        """,
        (target_user_id,),
    )
    user_posts = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS total FROM posts WHERE user_id = ?", (target_user_id,))
    posts_count = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM known_contacts WHERE user_id = ?", (target_user_id,))
    known_count = cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM post_likes pl
        INNER JOIN posts p ON p.id = pl.post_id
        WHERE p.user_id = ?
        """,
        (target_user_id,),
    )
    likes_received = cursor.fetchone()["total"]
    conn.close()

    return templates.TemplateResponse(
        "user_profile.html",
        {
            "request": request,
            "user": target_user,
            "user_posts": user_posts,
            "posts_count": posts_count,
            "known_count": known_count,
            "likes_received": likes_received,
        },
    )


@app.post("/profile")
async def update_profile(
    request: Request,
    nome: str = Form(...),
    igreja: str = Form(...),
    cidade: str = Form(...),
    pais: str = Form(...),
    telefone: str = Form(""),
    faixa_etaria: str = Form(...),
    nova_senha: str = Form(""),
    foto: UploadFile = File(None),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    updates = [
        "nome = ?",
        "igreja = ?",
        "cidade = ?",
        "pais = ?",
        "telefone = ?",
        "faixa_etaria = ?",
    ]
    values = [
        nome.strip(),
        igreja.strip(),
        cidade.strip(),
        pais.strip(),
        normalize_phone(telefone),
        faixa_etaria,
    ]

    senha_limpa = nova_senha.strip()
    if senha_limpa:
        if len(senha_limpa) < 8:
            conn.close()
            set_flash(request, "A nova senha precisa ter pelo menos 8 caracteres.")
            return RedirectResponse(url="/profile/edit", status_code=302)
        updates.append("senha_hash = ?")
        values.append(hash_password(senha_limpa))

    if foto and foto.filename:
        foto_url, foto_error = save_uploaded_photo(foto)
        if foto_error:
            conn.close()
            set_flash(request, foto_error)
            return RedirectResponse(url="/profile/edit", status_code=302)
        updates.append("foto_url = ?")
        values.append(foto_url)

    values.append(user_id)
    cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", values)
    conn.commit()
    conn.close()
    set_flash(request, "Perfil atualizado com sucesso.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/profile/delete")
def delete_profile(
    request: Request,
    replacement_admin_id: str = Form(""),
    confirm_delete_text: str = Form(""),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, role FROM users WHERE id = ?", (user_id,))
    current_user = cursor.fetchone()
    if not current_user:
        conn.close()
        request.session.clear()
        return RedirectResponse(url="/", status_code=302)

    if confirm_delete_text.strip().upper() != "EXCLUIR":
        conn.close()
        set_flash(request, "Para excluir o perfil, digite EXCLUIR no campo de confirmação.")
        return RedirectResponse(url="/profile/edit", status_code=302)

    if current_user["role"] == "admin":
        replacement_admin_id = replacement_admin_id.strip()
        if not replacement_admin_id.isdigit() or int(replacement_admin_id) == user_id:
            conn.close()
            set_flash(request, "Como admin, selecione outro usuário para assumir admin antes de excluir seu perfil.")
            return RedirectResponse(url="/profile/edit", status_code=302)
        new_admin_id = int(replacement_admin_id)
        cursor.execute("SELECT id FROM users WHERE id = ? AND approved = 1", (new_admin_id,))
        if not cursor.fetchone():
            conn.close()
            set_flash(request, "Usuário escolhido para admin não é válido.")
            return RedirectResponse(url="/profile/edit", status_code=302)
        cursor.execute("UPDATE users SET role = 'admin' WHERE id = ?", (new_admin_id,))

    file_urls = delete_user_account_data(cursor, user_id)
    conn.commit()
    conn.close()

    for file_url in file_urls:
        file_path = resolve_photo_storage_path(file_url)
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

    request.session.clear()
    return RedirectResponse(url="/", status_code=302)


@app.post("/posts/{post_id}/report")
def report_post(post_id: int, request: Request, motivo: str = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    texto = motivo.strip()
    if not texto:
        set_flash(request, "Informe o motivo da denúncia.")
        return RedirectResponse(url="/feed", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reports (reporter_user_id, target_type, target_id, motivo, criado_em) VALUES (?, 'post', ?, ?, ?)",
        (user_id, post_id, texto, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    set_flash(request, "Denúncia enviada para moderação.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/comments/{comment_id}/report")
def report_comment(comment_id: int, request: Request, motivo: str = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    texto = motivo.strip()
    if not texto:
        set_flash(request, "Informe o motivo da denúncia.")
        return RedirectResponse(url="/feed", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO reports (reporter_user_id, target_type, target_id, motivo, criado_em) VALUES (?, 'comment', ?, ?, ?)",
        (user_id, comment_id, texto, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    set_flash(request, "Denúncia enviada para moderação.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/moderation/reports/{report_id}/resolve")
def resolve_report(report_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if not is_moderator(user):
        conn.close()
        return RedirectResponse(url="/feed", status_code=302)

    cursor.execute("UPDATE reports SET status = 'resolvido' WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    set_flash(request, "Denúncia marcada como resolvida.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/moderation/reports/{report_id}/remove-target")
def remove_report_target(report_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if not is_moderator(user):
        conn.close()
        return RedirectResponse(url="/feed", status_code=302)

    cursor.execute("SELECT target_type, target_id FROM reports WHERE id = ?", (report_id,))
    report = cursor.fetchone()
    if not report:
        conn.close()
        return RedirectResponse(url="/feed", status_code=302)

    if report["target_type"] == "post":
        post_id = report["target_id"]
        cursor.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        cursor.execute("DELETE FROM post_likes WHERE post_id = ?", (post_id,))
        cursor.execute("DELETE FROM reports WHERE target_type = 'post' AND target_id = ?", (post_id,))
        cursor.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    elif report["target_type"] == "comment":
        comment_id = report["target_id"]
        cursor.execute("DELETE FROM reports WHERE target_type = 'comment' AND target_id = ?", (comment_id,))
        cursor.execute("DELETE FROM comments WHERE id = ?", (comment_id,))

    cursor.execute("UPDATE reports SET status = 'resolvido' WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    set_flash(request, "Conteúdo removido e denúncia resolvida.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/admin/users/{target_user_id}/role")
def update_user_role(target_user_id: int, request: Request, new_role: str = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    if new_role not in ("membro", "lider", "admin"):
        set_flash(request, "Função inválida.")
        return RedirectResponse(url="/feed", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    acting_user = cursor.fetchone()
    if not is_admin(acting_user):
        conn.close()
        return RedirectResponse(url="/feed", status_code=302)

    if target_user_id == user_id and new_role != "admin":
        conn.close()
        set_flash(request, "Você não pode remover seu próprio perfil de admin.")
        return RedirectResponse(url="/feed", status_code=302)

    cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, target_user_id))
    conn.commit()
    conn.close()
    set_flash(request, "Função do usuário atualizada.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/admin/users/{target_user_id}/approve")
def approve_user_registration(target_user_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    acting_user = cursor.fetchone()
    if not is_admin(acting_user):
        conn.close()
        return RedirectResponse(url="/feed", status_code=302)

    cursor.execute("UPDATE users SET approved = 1 WHERE id = ?", (target_user_id,))
    conn.commit()
    conn.close()
    set_flash(request, "Cadastro aprovado com sucesso.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/admin/users/{target_user_id}/reject")
def reject_user_registration(target_user_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    acting_user = cursor.fetchone()
    if not is_admin(acting_user):
        conn.close()
        return RedirectResponse(url="/feed", status_code=302)

    file_urls = delete_user_account_data(cursor, target_user_id)
    conn.commit()
    conn.close()

    for file_url in file_urls:
        file_path = resolve_photo_storage_path(file_url)
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

    set_flash(request, "Solicitação de cadastro recusada e usuário removido.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/admin/backups/create")
def create_backup_now(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    acting_user = cursor.fetchone()
    conn.close()

    if not is_admin(acting_user):
        return RedirectResponse(url="/feed", status_code=302)

    try:
        ensure_dir(BACKUP_DIR)
        backup_path = create_sqlite_backup(DB_PATH, BACKUP_DIR, "social_igreja_web")
        removed = prune_old_backups(BACKUP_DIR, "social_igreja_web", max(1, BACKUP_KEEP))
        set_flash(
            request,
            f"Backup criado: {os.path.basename(backup_path)}. Removidos {len(removed)} arquivo(s) antigos.",
        )
    except Exception as err:
        set_flash(request, f"Falha ao criar backup: {err}")

    return RedirectResponse(url="/feed", status_code=302)


@app.get("/admin/backups/{backup_name}/download")
def download_backup(backup_name: str, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    acting_user = cursor.fetchone()
    conn.close()

    if not is_admin(acting_user):
        return RedirectResponse(url="/feed", status_code=302)

    safe_name = os.path.basename(backup_name)
    if safe_name != backup_name:
        set_flash(request, "Arquivo de backup inválido.")
        return RedirectResponse(url="/feed", status_code=302)

    ensure_dir(BACKUP_DIR)
    backup_path = os.path.abspath(os.path.join(BACKUP_DIR, safe_name))
    backup_dir_abs = os.path.abspath(BACKUP_DIR)
    if os.path.commonpath([backup_path, backup_dir_abs]) != backup_dir_abs or not os.path.exists(backup_path):
        set_flash(request, "Backup não encontrado.")
        return RedirectResponse(url="/feed", status_code=302)

    return FileResponse(
        path=backup_path,
        filename=safe_name,
        media_type="application/octet-stream",
    )


@app.post("/connections/{target_user_id}/request")
def send_connection_request(target_user_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    if target_user_id == user_id:
        set_flash(request, "Você não pode enviar solicitação para si mesmo.")
        return RedirectResponse(url="/feed", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE id = ?", (target_user_id,))
    target_exists = cursor.fetchone()
    if not target_exists:
        conn.close()
        set_flash(request, "Usuário não encontrado.")
        return RedirectResponse(url="/feed", status_code=302)

    cursor.execute(
        "SELECT id FROM known_contacts WHERE user_id = ? AND known_user_id = ?",
        (user_id, target_user_id),
    )
    existing_connection = cursor.fetchone()
    if existing_connection:
        conn.close()
        set_flash(request, "Esse membro já é seu conhecido.")
        return RedirectResponse(url="/feed", status_code=302)

    cursor.execute(
        """
        SELECT id FROM connection_requests
        WHERE requester_user_id = ? AND receiver_user_id = ? AND status = 'pendente'
        """,
        (user_id, target_user_id),
    )
    same_direction_pending = cursor.fetchone()
    if same_direction_pending:
        conn.close()
        set_flash(request, "Solicitação já enviada e pendente.")
        return RedirectResponse(url="/feed", status_code=302)

    cursor.execute(
        """
        SELECT id FROM connection_requests
        WHERE requester_user_id = ? AND receiver_user_id = ? AND status = 'pendente'
        """,
        (target_user_id, user_id),
    )
    opposite_pending = cursor.fetchone()
    if opposite_pending:
        cursor.execute(
            "UPDATE connection_requests SET status = 'aceita' WHERE id = ?",
            (opposite_pending["id"],),
        )
        cursor.execute(
            "INSERT INTO known_contacts (user_id, known_user_id, criado_em) VALUES (?, ?, ?)",
            (user_id, target_user_id, datetime.now().isoformat(timespec="seconds")),
        )
        cursor.execute(
            "INSERT INTO known_contacts (user_id, known_user_id, criado_em) VALUES (?, ?, ?)",
            (target_user_id, user_id, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        conn.close()
        set_flash(request, "Conexão aceita automaticamente: vocês agora são conhecidos.")
        return RedirectResponse(url="/feed", status_code=302)

    cursor.execute(
        """
        INSERT INTO connection_requests (requester_user_id, receiver_user_id, status, criado_em)
        VALUES (?, ?, 'pendente', ?)
        """,
        (user_id, target_user_id, datetime.now().isoformat(timespec="seconds")),
    )
    set_flash(request, "Solicitação de conhecido enviada.")

    conn.commit()
    conn.close()
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/connections/requests/{request_id}/accept")
def accept_connection_request(request_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT requester_user_id, receiver_user_id, status
        FROM connection_requests
        WHERE id = ?
        """,
        (request_id,),
    )
    req = cursor.fetchone()
    if not req or req["receiver_user_id"] != user_id or req["status"] != "pendente":
        conn.close()
        set_flash(request, "Solicitação inválida ou já processada.")
        return RedirectResponse(url="/feed", status_code=302)

    requester_id = req["requester_user_id"]
    cursor.execute("UPDATE connection_requests SET status = 'aceita' WHERE id = ?", (request_id,))
    cursor.execute(
        "INSERT OR IGNORE INTO known_contacts (user_id, known_user_id, criado_em) VALUES (?, ?, ?)",
        (user_id, requester_id, datetime.now().isoformat(timespec="seconds")),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO known_contacts (user_id, known_user_id, criado_em) VALUES (?, ?, ?)",
        (requester_id, user_id, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    set_flash(request, "Solicitação aceita. Vocês agora são conhecidos.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/connections/requests/{request_id}/reject")
def reject_connection_request(request_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE connection_requests
        SET status = 'recusada'
        WHERE id = ? AND receiver_user_id = ? AND status = 'pendente'
        """,
        (request_id, user_id),
    )
    changed = cursor.rowcount
    conn.commit()
    conn.close()
    if changed:
        set_flash(request, "Solicitação recusada.")
    else:
        set_flash(request, "Solicitação inválida ou já processada.")
    return RedirectResponse(url="/feed", status_code=302)


@app.post("/connections/{target_user_id}/remove")
def remove_connection(target_user_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM known_contacts WHERE user_id = ? AND known_user_id = ?",
        (user_id, target_user_id),
    )
    cursor.execute(
        "DELETE FROM known_contacts WHERE user_id = ? AND known_user_id = ?",
        (target_user_id, user_id),
    )
    conn.commit()
    conn.close()
    set_flash(request, "Conexão removida.")

    return RedirectResponse(url="/feed", status_code=302)


@app.get("/chat")
def chat_page(request: Request, conversation_id: Optional[int] = None):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    current_user = cursor.fetchone()

    cursor.execute(
        """
        SELECT u.id, u.nome, u.igreja, u.cidade, u.pais, u.foto_url
        FROM known_contacts kc
        INNER JOIN users u ON u.id = kc.known_user_id
        WHERE kc.user_id = ?
        ORDER BY u.nome
        """,
        (user_id,),
    )
    known_contacts = cursor.fetchall()

    conversations = get_user_conversations(cursor, user_id)

    selected = None
    selected_id = conversation_id
    if selected_id is None and conversations:
        selected_id = conversations[0]["id"]

    if selected_id is not None:
        selected = get_conversation_if_member(cursor, selected_id, user_id)
        if not selected:
            set_flash(request, "Conversa não encontrada.")
            selected_id = None

    conversation_messages = []
    conversation_members = []
    if selected:
        cursor.execute(
            """
            SELECT m.id, m.conteudo, m.file_url, m.file_name, m.criado_em,
                   u.id AS sender_id, u.nome AS sender_nome, u.foto_url AS sender_foto
            FROM messages m
            INNER JOIN users u ON u.id = m.sender_user_id
            WHERE m.conversation_id = ?
            ORDER BY m.id ASC
            """,
            (selected["id"],),
        )
        conversation_messages = cursor.fetchall()

        last_message_id = conversation_messages[-1]["id"] if conversation_messages else 0
        cursor.execute(
            """
            INSERT INTO conversation_reads (conversation_id, user_id, last_read_message_id, atualizado_em)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation_id, user_id)
            DO UPDATE SET
                last_read_message_id = excluded.last_read_message_id,
                atualizado_em = excluded.atualizado_em
            """,
            (selected["id"], user_id, last_message_id, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()

        cursor.execute(
            """
            SELECT u.id, u.nome, u.foto_url
            FROM conversation_members cm
            INNER JOIN users u ON u.id = cm.user_id
            WHERE cm.conversation_id = ?
            ORDER BY u.nome
            """,
            (selected["id"],),
        )
        conversation_members = cursor.fetchall()

    conversation_items = []
    for conv in conversations:
        if conv["type"] == "dm":
            display_name = conv["dm_other_name"] or "Conversa"
        else:
            display_name = conv["name"] or "Grupo"
        conversation_items.append(
            {
                "id": conv["id"],
                "type": conv["type"],
                "display_name": display_name,
                "last_message": conv["last_message"],
                "last_message_at": conv["last_message_at"],
                "unread_count": conv["unread_count"],
            }
        )

    selected_title = None
    if selected:
        if selected["type"] == "group":
            selected_title = selected["name"] or "Grupo"
        else:
            selected_title = "Conversa"
            for member in conversation_members:
                if member["id"] != user_id:
                    selected_title = member["nome"]
                    break

    conn.close()

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "user": current_user,
            "flash": pop_flash(request),
            "known_contacts": known_contacts,
            "conversations": conversation_items,
            "selected_conversation": selected,
            "selected_title": selected_title,
            "conversation_messages": conversation_messages,
            "conversation_members": conversation_members,
            "selected_conversation_id": selected_id,
        },
    )


@app.post("/chat/dm/{target_user_id}")
def create_or_open_dm(target_user_id: int, request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    if target_user_id == user_id:
        set_flash(request, "Selecione outro usuário para conversar.")
        return RedirectResponse(url="/chat", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE id = ?", (target_user_id,))
    target_user = cursor.fetchone()
    if not target_user:
        conn.close()
        set_flash(request, "Usuário não encontrado.")
        return RedirectResponse(url="/chat", status_code=302)

    if not can_users_chat(cursor, user_id, target_user_id):
        conn.close()
        set_flash(request, "Você só pode iniciar chat com conhecidos aceitos.")
        return RedirectResponse(url="/chat", status_code=302)

    conversation_id = get_or_create_dm(cursor, user_id, target_user_id)
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/chat?conversation_id={conversation_id}", status_code=302)


@app.post("/chat/groups")
def create_group_chat(
    request: Request,
    name: str = Form(...),
    member_ids: list[int] = Form([]),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    group_name = name.strip()
    if len(group_name) < 3:
        set_flash(request, "O nome do grupo deve ter pelo menos 3 caracteres.")
        return RedirectResponse(url="/chat", status_code=302)

    unique_members = sorted({int(member_id) for member_id in member_ids if int(member_id) != user_id})
    participants = [user_id] + unique_members
    if len(participants) < 3:
        set_flash(request, "Selecione pelo menos 2 membros para criar um grupo.")
        return RedirectResponse(url="/chat", status_code=302)

    conn = get_conn()
    cursor = conn.cursor()

    for member_id in unique_members:
        cursor.execute("SELECT id FROM users WHERE id = ?", (member_id,))
        if not cursor.fetchone():
            conn.close()
            set_flash(request, "Um dos membros selecionados não existe.")
            return RedirectResponse(url="/chat", status_code=302)
        if not can_users_chat(cursor, user_id, member_id):
            conn.close()
            set_flash(request, "Grupo permitido somente com conhecidos aceitos.")
            return RedirectResponse(url="/chat", status_code=302)

    now = datetime.now().isoformat(timespec="seconds")
    cursor.execute(
        "INSERT INTO conversations (type, name, created_by_user_id, criado_em) VALUES ('group', ?, ?, ?)",
        (group_name, user_id, now),
    )
    conversation_id = cursor.lastrowid

    for participant_id in participants:
        cursor.execute(
            "INSERT INTO conversation_members (conversation_id, user_id, criado_em) VALUES (?, ?, ?)",
            (conversation_id, participant_id, now),
        )

    conn.commit()
    conn.close()
    set_flash(request, "Grupo criado com sucesso.")
    return RedirectResponse(url=f"/chat?conversation_id={conversation_id}", status_code=302)


@app.post("/chat/{conversation_id}/messages")
async def send_chat_message(
    conversation_id: int,
    request: Request,
    conteudo: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    texto = conteudo.strip()

    conn = get_conn()
    cursor = conn.cursor()
    conversation = get_conversation_if_member(cursor, conversation_id, user_id)
    if not conversation:
        conn.close()
        set_flash(request, "Conversa inválida.")
        return RedirectResponse(url="/chat", status_code=302)

    file_url = None
    file_name = None
    if file and file.filename:
        file_url, file_name, file_error = save_chat_file(file)
        if file_error:
            conn.close()
            set_flash(request, file_error)
            return RedirectResponse(url=f"/chat?conversation_id={conversation_id}", status_code=302)

    if not texto and not file_url:
        conn.close()
        set_flash(request, "Envie uma mensagem ou anexe um arquivo.")
        return RedirectResponse(url=f"/chat?conversation_id={conversation_id}", status_code=302)

    cursor.execute(
        """
        INSERT INTO messages (conversation_id, sender_user_id, conteudo, file_url, file_name, criado_em)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (conversation_id, user_id, texto or None, file_url, file_name, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/chat?conversation_id={conversation_id}", status_code=302)
