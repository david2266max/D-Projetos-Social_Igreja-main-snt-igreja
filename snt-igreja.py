import hashlib
import sqlite3
import sys
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
	QApplication,
	QCheckBox,
	QComboBox,
	QDialog,
	QFormLayout,
	QGroupBox,
	QHBoxLayout,
	QLabel,
	QLineEdit,
	QListWidget,
	QListWidgetItem,
	QMainWindow,
	QMessageBox,
	QPushButton,
	QTextEdit,
	QVBoxLayout,
	QWidget,
)


DB_NAME = "social_igreja.db"


class DatabaseManager:
	def __init__(self, db_name=DB_NAME):
		self.conn = sqlite3.connect(db_name)
		self.conn.row_factory = sqlite3.Row
		self.create_tables()

	def create_tables(self):
		cursor = self.conn.cursor()
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
				faixa_etaria TEXT NOT NULL,
				revisao_vidas INTEGER NOT NULL,
				batizado_aguas INTEGER NOT NULL,
				criado_em TEXT NOT NULL
			)
			"""
		)
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
		self.conn.commit()

	@staticmethod
	def hash_password(password):
		return hashlib.sha256(password.encode("utf-8")).hexdigest()

	def create_user(
		self,
		nome,
		email,
		senha,
		igreja,
		cidade,
		pais,
		faixa_etaria,
		revisao_vidas,
		batizado_aguas,
	):
		if not revisao_vidas or not batizado_aguas:
			return False, "Cadastro permitido apenas para membros com Revisão de Vidas e batismo nas águas."

		try:
			cursor = self.conn.cursor()
			cursor.execute(
				"""
				INSERT INTO users (
					nome, email, senha_hash, igreja, cidade, pais,
					faixa_etaria, revisao_vidas, batizado_aguas, criado_em
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				""",
				(
					nome.strip(),
					email.strip().lower(),
					self.hash_password(senha),
					igreja.strip(),
					cidade.strip(),
					pais.strip(),
					faixa_etaria,
					int(revisao_vidas),
					int(batizado_aguas),
					datetime.now().isoformat(timespec="seconds"),
				),
			)
			self.conn.commit()
			return True, "Usuário cadastrado com sucesso."
		except sqlite3.IntegrityError:
			return False, "Este e-mail já está cadastrado."

	def authenticate(self, email, senha):
		cursor = self.conn.cursor()
		cursor.execute(
			"SELECT * FROM users WHERE email = ? AND senha_hash = ?",
			(email.strip().lower(), self.hash_password(senha)),
		)
		return cursor.fetchone()

	def create_post(self, user_id, conteudo):
		cursor = self.conn.cursor()
		cursor.execute(
			"INSERT INTO posts (user_id, conteudo, criado_em) VALUES (?, ?, ?)",
			(user_id, conteudo.strip(), datetime.now().isoformat(timespec="seconds")),
		)
		self.conn.commit()

	def list_posts(self):
		cursor = self.conn.cursor()
		cursor.execute(
			"""
			SELECT p.id, p.conteudo, p.criado_em, u.nome, u.igreja, u.cidade, u.pais
			FROM posts p
			INNER JOIN users u ON u.id = p.user_id
			ORDER BY p.id DESC
			"""
		)
		return cursor.fetchall()

	def list_members(self, filtro=""):
		cursor = self.conn.cursor()
		if filtro.strip():
			like = f"%{filtro.strip().lower()}%"
			cursor.execute(
				"""
				SELECT nome, igreja, cidade, pais, faixa_etaria
				FROM users
				WHERE LOWER(nome) LIKE ? OR LOWER(igreja) LIKE ? OR LOWER(cidade) LIKE ? OR LOWER(pais) LIKE ?
				ORDER BY nome
				""",
				(like, like, like, like),
			)
		else:
			cursor.execute(
				"""
				SELECT nome, igreja, cidade, pais, faixa_etaria
				FROM users
				ORDER BY nome
				"""
			)
		return cursor.fetchall()


class RegisterDialog(QDialog):
	def __init__(self, db):
		super().__init__()
		self.db = db
		self.setWindowTitle("Cadastro de Membro")
		self.setMinimumWidth(420)
		self.setup_ui()

	def setup_ui(self):
		layout = QVBoxLayout()

		form = QFormLayout()
		self.nome_input = QLineEdit()
		self.email_input = QLineEdit()
		self.senha_input = QLineEdit()
		self.senha_input.setEchoMode(QLineEdit.Password)
		self.igreja_input = QLineEdit()
		self.cidade_input = QLineEdit()
		self.pais_input = QLineEdit("Brasil")

		self.faixa_input = QComboBox()
		self.faixa_input.addItems(["Jovem", "Adulto"])

		form.addRow("Nome:", self.nome_input)
		form.addRow("E-mail:", self.email_input)
		form.addRow("Senha:", self.senha_input)
		form.addRow("Igreja Sara Nossa Terra:", self.igreja_input)
		form.addRow("Cidade:", self.cidade_input)
		form.addRow("País:", self.pais_input)
		form.addRow("Faixa etária:", self.faixa_input)

		regras_box = QGroupBox("Critérios de participação")
		regras_layout = QVBoxLayout()
		self.revisao_check = QCheckBox("Já participou da Revisão de Vidas")
		self.batismo_check = QCheckBox("É batizado(a) nas águas")
		regras_layout.addWidget(self.revisao_check)
		regras_layout.addWidget(self.batismo_check)
		regras_box.setLayout(regras_layout)

		botoes = QHBoxLayout()
		salvar_btn = QPushButton("Cadastrar")
		cancelar_btn = QPushButton("Cancelar")
		salvar_btn.clicked.connect(self.handle_register)
		cancelar_btn.clicked.connect(self.reject)
		botoes.addWidget(salvar_btn)
		botoes.addWidget(cancelar_btn)

		layout.addLayout(form)
		layout.addWidget(regras_box)
		layout.addLayout(botoes)
		self.setLayout(layout)

	def handle_register(self):
		nome = self.nome_input.text()
		email = self.email_input.text()
		senha = self.senha_input.text()
		igreja = self.igreja_input.text()
		cidade = self.cidade_input.text()
		pais = self.pais_input.text()
		faixa = self.faixa_input.currentText()
		revisao = self.revisao_check.isChecked()
		batismo = self.batismo_check.isChecked()

		if not all([nome.strip(), email.strip(), senha.strip(), igreja.strip(), cidade.strip(), pais.strip()]):
			QMessageBox.warning(self, "Campos obrigatórios", "Preencha todos os campos.")
			return

		ok, msg = self.db.create_user(
			nome, email, senha, igreja, cidade, pais, faixa, revisao, batismo
		)
		if ok:
			QMessageBox.information(self, "Cadastro", msg)
			self.accept()
		else:
			QMessageBox.warning(self, "Cadastro", msg)


class MainWindow(QMainWindow):
	def __init__(self, db, user):
		super().__init__()
		self.db = db
		self.user = user
		self.setWindowTitle("Rede Social - Sara Nossa Terra")
		self.setMinimumSize(860, 580)
		self.setup_ui()
		self.load_posts()
		self.load_members()

	def setup_ui(self):
		central = QWidget()
		main_layout = QHBoxLayout()

		left_layout = QVBoxLayout()
		boas_vindas = QLabel(
			f"Bem-vindo(a), {self.user['nome']}\n{self.user['igreja']} - {self.user['cidade']}/{self.user['pais']}"
		)
		boas_vindas.setAlignment(Qt.AlignLeft)
		left_layout.addWidget(boas_vindas)

		self.post_input = QTextEdit()
		self.post_input.setPlaceholderText("Compartilhe um testemunho, aviso ou palavra de edificação...")
		self.post_input.setMaximumHeight(110)

		publicar_btn = QPushButton("Publicar")
		publicar_btn.clicked.connect(self.handle_create_post)

		self.feed_list = QListWidget()

		left_layout.addWidget(QLabel("Nova publicação:"))
		left_layout.addWidget(self.post_input)
		left_layout.addWidget(publicar_btn)
		left_layout.addWidget(QLabel("Feed da comunidade:"))
		left_layout.addWidget(self.feed_list)

		right_layout = QVBoxLayout()
		right_layout.addWidget(QLabel("Membros cadastrados"))

		self.search_member = QLineEdit()
		self.search_member.setPlaceholderText("Buscar por nome, igreja, cidade ou país")
		self.search_member.textChanged.connect(self.load_members)

		self.members_list = QListWidget()

		perfil_box = QGroupBox("Meu perfil")
		perfil_layout = QFormLayout()
		perfil_layout.addRow("Nome:", QLabel(self.user["nome"]))
		perfil_layout.addRow("E-mail:", QLabel(self.user["email"]))
		perfil_layout.addRow("Faixa etária:", QLabel(self.user["faixa_etaria"]))
		perfil_layout.addRow("Igreja:", QLabel(self.user["igreja"]))
		perfil_layout.addRow("Cidade:", QLabel(self.user["cidade"]))
		perfil_layout.addRow("País:", QLabel(self.user["pais"]))
		perfil_box.setLayout(perfil_layout)

		right_layout.addWidget(self.search_member)
		right_layout.addWidget(self.members_list)
		right_layout.addWidget(perfil_box)

		main_layout.addLayout(left_layout, 2)
		main_layout.addLayout(right_layout, 1)
		central.setLayout(main_layout)
		self.setCentralWidget(central)

	def handle_create_post(self):
		conteudo = self.post_input.toPlainText().strip()
		if not conteudo:
			QMessageBox.warning(self, "Publicação", "Escreva algo antes de publicar.")
			return
		self.db.create_post(self.user["id"], conteudo)
		self.post_input.clear()
		self.load_posts()

	def load_posts(self):
		self.feed_list.clear()
		posts = self.db.list_posts()
		if not posts:
			self.feed_list.addItem("Ainda não há publicações na comunidade.")
			return

		for post in posts:
			when = post["criado_em"].replace("T", " ")
			text = (
				f"{post['nome']} | {post['igreja']} ({post['cidade']}/{post['pais']})\n"
				f"{post['conteudo']}\n"
				f"{when}"
			)
			item = QListWidgetItem(text)
			self.feed_list.addItem(item)

	def load_members(self):
		self.members_list.clear()
		filtro = self.search_member.text()
		members = self.db.list_members(filtro)
		for member in members:
			self.members_list.addItem(
				f"{member['nome']} - {member['faixa_etaria']}\n"
				f"{member['igreja']} | {member['cidade']}/{member['pais']}"
			)


class LoginWindow(QWidget):
	def __init__(self):
		super().__init__()
		self.db = DatabaseManager()
		self.main_window = None
		self.setWindowTitle("Rede Social Igreja - Login")
		self.setMinimumSize(400, 250)
		self.setup_ui()

	def setup_ui(self):
		layout = QVBoxLayout()

		titulo = QLabel("Rede Social Sara Nossa Terra")
		titulo.setAlignment(Qt.AlignCenter)

		subtitulo = QLabel(
			"Para jovens e adultos das igrejas Sara Nossa Terra\n"
			"(Brasil e mundo), com Revisão de Vidas e batismo nas águas."
		)
		subtitulo.setAlignment(Qt.AlignCenter)

		form = QFormLayout()
		self.email_input = QLineEdit()
		self.senha_input = QLineEdit()
		self.senha_input.setEchoMode(QLineEdit.Password)
		form.addRow("E-mail:", self.email_input)
		form.addRow("Senha:", self.senha_input)

		buttons = QHBoxLayout()
		login_btn = QPushButton("Entrar")
		cadastrar_btn = QPushButton("Criar conta")
		login_btn.clicked.connect(self.handle_login)
		cadastrar_btn.clicked.connect(self.open_register)
		buttons.addWidget(login_btn)
		buttons.addWidget(cadastrar_btn)

		layout.addWidget(titulo)
		layout.addWidget(subtitulo)
		layout.addLayout(form)
		layout.addLayout(buttons)

		self.setLayout(layout)

	def open_register(self):
		dialog = RegisterDialog(self.db)
		dialog.exec_()

	def handle_login(self):
		email = self.email_input.text()
		senha = self.senha_input.text()

		if not email.strip() or not senha.strip():
			QMessageBox.warning(self, "Login", "Informe e-mail e senha.")
			return

		user = self.db.authenticate(email, senha)
		if user:
			self.main_window = MainWindow(self.db, user)
			self.main_window.show()
			self.close()
		else:
			QMessageBox.warning(self, "Login", "E-mail ou senha inválidos.")


def main():
	app = QApplication(sys.argv)
	window = LoginWindow()
	window.show()
	sys.exit(app.exec_())


if __name__ == "__main__":
	main()
