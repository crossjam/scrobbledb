"""
Allow scrobbledb to be executable through `python -m scrobbledb`.
"""
from .cli import cli

if __name__ == "__main__":
    cli()
