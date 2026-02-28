import argparse
import glob
import os
import sqlite3
from datetime import datetime


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def create_sqlite_backup(db_path: str, backup_dir: str, prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_name = f"{prefix}_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_name)

    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    return backup_path


def prune_old_backups(backup_dir: str, prefix: str, keep: int) -> list[str]:
    pattern = os.path.join(backup_dir, f"{prefix}_*.db")
    backups = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    to_remove = backups[keep:]
    removed = []
    for file_path in to_remove:
        os.remove(file_path)
        removed.append(file_path)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cria backup do SQLite e mantém apenas os mais recentes."
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("DB_PATH", "/var/data/social_igreja_web.db"),
        help="Caminho do arquivo SQLite.",
    )
    parser.add_argument(
        "--backup-dir",
        default=os.getenv("BACKUP_DIR", "/var/data/backups"),
        help="Pasta onde os backups serão gravados.",
    )
    parser.add_argument(
        "--prefix",
        default="social_igreja_web",
        help="Prefixo do nome dos arquivos de backup.",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=15,
        help="Quantidade de backups mais recentes para manter.",
    )
    args = parser.parse_args()

    if args.keep < 1:
        raise ValueError("--keep deve ser >= 1")

    if not os.path.exists(args.db_path):
        raise FileNotFoundError(f"Banco não encontrado: {args.db_path}")

    ensure_dir(args.backup_dir)

    backup_path = create_sqlite_backup(args.db_path, args.backup_dir, args.prefix)
    removed = prune_old_backups(args.backup_dir, args.prefix, args.keep)

    print(f"Backup criado: {backup_path}")
    print(f"Backups removidos: {len(removed)}")
    print(f"Retenção aplicada: últimos {args.keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
