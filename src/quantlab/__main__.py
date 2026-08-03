"""Ponto de entrada de ``python -m quantlab``.

Despacha para o app Typer definido em :mod:`quantlab.cli`.
"""

from quantlab.cli import app


def main() -> None:
    """Executa o CLI."""
    app()


if __name__ == "__main__":
    main()
