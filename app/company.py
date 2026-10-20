"""
CompanyOS
=========
"""

from pathlib import Path

from agno.company import Product, Source

from app.sandbox import REPOSITORY

products = [
    Product(
        id="this-agentos",
        name="AgentOS",
        purpose="Turn ideas into agents that do useful work.",
        sources=[
            Source(type="website", reference="https://github.com/agno-agi/agno/releases"),
            Source(type="git", reference=str(Path(__file__).resolve().parents[1])),
            Source(type="git", reference=REPOSITORY.url),
        ],
    ),
]
