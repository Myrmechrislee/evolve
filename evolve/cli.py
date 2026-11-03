import click

from .db import ensure_indexes, get_db
from .utils import is_frozen, utcnow


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
        result = get_db().users.update_one(
            {"sub": sub, "account.status": {"$ne": "deleted"}},
            {"$set": {"entitlements.manual_pro": enabled}},
        )
        if not result.matched_count:
            raise click.ClickException("User not found. Have the user sign in first.")
        click.echo(f"Manual Pro grant {'enabled' if enabled else 'disabled'} for {sub}.")
        if not enabled:
            click.echo(
                "An Auth0 Pro role, if assigned, remains independent. Remove that role and sign in again to revoke it."
            )
        click.echo("An admin dashboard membership override, if set, takes precedence over these grants.")

    @app.cli.command("set-admin")
    @click.option("--sub", required=True, help="Exact Auth0 subject, e.g. auth0|abc123.")
    @click.option("--enabled/--disabled", default=True)
    def set_admin(sub, enabled):
        """Bootstrap or manage an EVOLVE administrator after their first sign-in."""
        db = get_db()
        user = db.users.find_one({"sub": sub, "account.status": {"$ne": "deleted"}})
        if not user:
            raise click.ClickException("User not found. Have the user sign in first.")
        if not enabled and user.get("roles", {}).get("admin"):
            others = db.users.find({"sub": {"$ne": sub}, "roles.admin": True,
                                   "account.status": {"$ne": "deleted"}})
            if not any(not is_frozen(other) for other in others):
                raise click.ClickException("Appoint another active administrator before removing the last one.")
        db.users.update_one({"_id": user["_id"]}, {"$set": {"roles.admin": enabled}})
        db.admin_audit.insert_one({
            "actor": "CLI", "target": sub, "action": "change_admin", "details": {"admin": enabled},
            "created_at": utcnow(),
        })
        click.echo(f"Administrator access {'enabled' if enabled else 'disabled'} for {sub}.")
