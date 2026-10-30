#!/usr/bin/env python3
"""
CLI entry point for Sin'X Manual Poster.

Commands:
  run-web       Start the Web Dashboard and background scheduler
  create-user   Create a new user (Admin or Karyawan)
  list-users    List all registered users
  status        Display queue statistics
  reset-stuck   Reset posts stuck in 'uploading' status
  info          Display environment, hardware, and directory info
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.table import Table

from poster.config import get_config
from poster.db.models import init_db
from poster.utils.hardware import get_system_info
from poster.utils.logger import setup_logging

console = Console()


def _ensure_env():
    cfg = get_config()
    cfg.ensure_directories()
    init_db(cfg.DB_PATH)


def cmd_run_web(args):
    """Start the FastAPI server with uvicorn."""
    _ensure_env()
    setup_logging(level="INFO")

    cfg = get_config()
    host = args.host or cfg.HOST
    port = args.port or cfg.PORT

    console.print(f"[bold cyan]🚀 Menjalankan Sin'X Manual Poster di http://{host}:{port}...[/bold cyan]")
    import uvicorn
    uvicorn.run("web.server:app", host=host, port=port, reload=args.reload)


def cmd_create_user(args):
    """Create a new user."""
    _ensure_env()
    import poster.auth as auth_module
    from poster.db.queue import create_account, list_accounts

    cfg = get_config()
    username = args.username or input("Username: ").strip()
    if not username:
        console.print("[red]Username tidak boleh kosong.[/red]")
        return

    password = args.password
    if not password:
        import getpass
        password = getpass.getpass("Password: ")
    if len(password) < 6:
        console.print("[red]Password minimal 6 karakter.[/red]")
        return

    account_name = args.account or username
    is_admin = bool(args.admin)

    existing = {a["name"].lower(): a for a in list_accounts(cfg.DB_PATH)}
    if account_name.lower() in existing:
        acc = existing[account_name.lower()]
    else:
        acc = create_account(account_name, cfg.DB_PATH)

    try:
        user = auth_module.create_user(
            db_path=cfg.DB_PATH,
            username=username,
            password=password,
            account_id=acc["id"],
            is_admin=is_admin,
        )
        console.print(f"\n[bold green]✓ Berhasil membuat user '{username}' (Role: {'Admin' if is_admin else 'Karyawan'})![/bold green]")
    except Exception as e:
        console.print(f"[red]Gagal membuat user:[/red] {e}")


def cmd_list_users(args):
    """List registered users."""
    _ensure_env()
    import poster.auth as auth_module

    cfg = get_config()
    users = auth_module.list_users(cfg.DB_PATH)
    if not users:
        console.print("[yellow]Belum ada user terdaftar.[/yellow]")
        return

    table = Table(title="Daftar Pengguna Sin'X Manual Poster", show_header=True, header_style="bold magenta")
    table.add_column("ID", width=6)
    table.add_column("Username", style="bold cyan")
    table.add_column("Profil Akun", style="green")
    table.add_column("Role", style="yellow")
    table.add_column("Dibuat Pada", style="dim")

    for u in users:
        table.add_row(
            str(u["id"]),
            u["username"],
            u.get("account_name", "-"),
            "Admin" if u.get("is_admin") else "Karyawan",
            str(u.get("created_at", "-"))[:19],
        )
    console.print(table)


def cmd_status(args):
    """Show database queue statistics."""
    _ensure_env()
    from poster.db.queue import get_stats

    cfg = get_config()
    stats = get_stats(db_path=cfg.DB_PATH)

    table = Table(title="Statistik Sin'X Manual Poster", show_header=True, header_style="bold cyan")
    table.add_column("Metrik", style="bold")
    table.add_column("Jumlah", style="green", justify="right")

    table.add_row("Total Postingan", str(stats.get("total_posts", 0)))
    table.add_row("Dijadwalkan (Scheduled)", str(stats.get("scheduled", 0)))
    table.add_row("Sedang Diupload", str(stats.get("uploading", 0)))
    table.add_row("Berhasil (Done)", str(stats.get("done", 0)))
    table.add_row("Gagal (Failed)", str(stats.get("failed", 0)))

    console.print(table)


def cmd_reset_stuck(args):
    """Reset posts stuck in uploading status."""
    _ensure_env()
    from poster.db.models import db_session

    cfg = get_config()
    with db_session(cfg.DB_PATH) as conn:
        cur = conn.execute(
            """
            UPDATE posts
            SET status = 'failed', updated_at = CURRENT_TIMESTAMP
            WHERE status = 'uploading'
            """
        )
        conn.execute(
            """
            UPDATE post_platforms
            SET status = 'failed', error_msg = 'Reset stuck', updated_at = CURRENT_TIMESTAMP
            WHERE status = 'uploading'
            """
        )
        count = cur.rowcount
    console.print(f"[bold green]✓ Mereset {count} pekerjaan yang terhenti.[/bold green]")


def cmd_info(args):
    """Display system info."""
    _ensure_env()
    cfg = get_config()
    info = get_system_info()

    table = Table(title="Informasi Lingkungan & Sistem", show_header=True, header_style="bold blue")
    table.add_column("Komponen", style="bold")
    table.add_column("Nilai", style="cyan")

    table.add_row("OS", f"{info.get('os')} ({info.get('arch')})")
    table.add_row("Python Version", info.get("python_version", "-"))
    table.add_row("GPU", info.get("gpu_name") or "None (CPU Mode)")
    table.add_row("Database Path", cfg.DB_PATH)
    table.add_row("Uploads Directory", str(cfg.UPLOADS_DIR.resolve()))
    table.add_row("Profiles Directory", str(cfg.PROFILES_DIR.resolve()))
    table.add_row("Default Port", str(cfg.PORT))

    console.print(table)


def main():
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="Sin'X Manual Poster Management CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run-web
    p_web = sub.add_parser("run-web", help="Start web dashboard & background scheduler")
    p_web.add_argument("--host", default=None)
    p_web.add_argument("--port", type=int, default=None)
    p_web.add_argument("--reload", action="store_true")
    p_web.set_defaults(func=cmd_run_web)

    # create-user
    p_user = sub.add_parser("create-user", help="Create a user account")
    p_user.add_argument("--username", "-u")
    p_user.add_argument("--password", "-p")
    p_user.add_argument("--account", "-a")
    p_user.add_argument("--admin", action="store_true")
    p_user.set_defaults(func=cmd_create_user)

    # list-users
    p_list = sub.add_parser("list-users", help="List registered users")
    p_list.set_defaults(func=cmd_list_users)

    # status
    p_stat = sub.add_parser("status", help="Show database queue statistics")
    p_stat.set_defaults(func=cmd_status)

    # reset-stuck
    p_rst = sub.add_parser("reset-stuck", help="Reset stuck uploading jobs")
    p_rst.set_defaults(func=cmd_reset_stuck)

    # info
    p_inf = sub.add_parser("info", help="Display system & environment info")
    p_inf.set_defaults(func=cmd_info)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
