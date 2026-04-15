from __future__ import annotations
import click


@click.group()
def main() -> None:
    """Mastodon is My Blog — personal Mastodon reader and blog tool."""


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8000, show_default=True, type=int, help="Bind port.")
@click.option("--reload", "reload_", is_flag=True, default=False, help="Enable auto-reload (dev).")
@click.option("--workers", default=1, show_default=True, type=int, help="Number of worker processes.")
def start(host: str, port: int, reload_: bool, workers: int) -> None:
    """Start the web server."""
    import uvicorn
    click.echo(f"Starting mastodon_is_my_blog on http://{host}:{port}")
    uvicorn.run(
        "mastodon_is_my_blog.main:app",
        host=host,
        port=port,
        reload=reload_,
        workers=workers if not reload_ else 1,
    )


@main.command("db-info")
def db_info() -> None:
    """Show the resolved database path."""
    from mastodon_is_my_blog.db_path import get_default_db_url
    url = get_default_db_url()
    click.echo(f"DB_URL: {url}")


@main.command()
def version() -> None:
    """Show the installed package version."""
    from importlib.metadata import version as pkg_version
    click.echo(pkg_version("mastodon_is_my_blog"))


if __name__ == "__main__":
    main()
