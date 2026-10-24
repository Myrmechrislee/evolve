"""Flask CLI entry point: flask --app app run --debug --port 9000."""

from evolve import create_app

app = create_app()
