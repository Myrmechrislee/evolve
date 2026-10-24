import click

from .db import ensure_indexes, get_db


def init_app(app):
    @app.cli.command("init-db")
    def init_db():
        """Check MongoDB and create required indexes before serving traffic."""
        get_db().command("ping")
        ensure_indexes()
        click.echo("MongoDB is connected. Required indexes are ready.")

    @app.cli.command("set-pro")
    @click.option("--sub", required=True, help="Exact Auth0 subject, e.g. auth0|abc123.")
    @click.option("--enabled/--disabled", default=True)
    def set_pro(sub, enabled):
        """Manage an independent server-side development Pro grant."""
        result = get_db().users.update_one({"sub": sub}, {"$set": {"entitlements.manual_pro": enabled}})
        if not result.matched_count:
            raise click.ClickException("User not found. Have the user sign in first.")
        click.echo(f"Manual Pro grant {'enabled' if enabled else 'disabled'} for {sub}.")
        if not enabled:
            click.echo(
                "An Auth0 Pro role, if assigned, remains independent. Remove that role and sign in again to revoke it."
            )
