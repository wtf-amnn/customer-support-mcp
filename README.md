Customer Support Operations MCP — best overall

Build an MCP server through which Claude manages customers and support tickets.

Database tables:

customers
tickets
ticket_comments
knowledge_articles
audit_logs

Tools:

create_customer
create_ticket
list_tickets
get_ticket
assign_ticket
add_comment
change_ticket_status
resolve_ticket
delete_ticket

Resources:

customer://profile/{customer_id}
ticket://details/{ticket_id}
knowledge://articles/{category}

Reusable prompt:

/triage-ticket

Claude could handle requests such as:

Find urgent unresolved tickets, summarize each one, and suggest the correct support team.
Create a ticket for Rahul's payment issue and attach the refund-policy article.

Why this is a proper MCP project:

Tools perform controlled database actions.
Resources provide customer and knowledge-base context.
Prompts define repeatable support workflows.
Claude can chain several tools together.
Destructive actions can require approval.
Every action can be written to an audit log.

This project demonstrates all three primary MCP server capabilities: tools, resources and prompts. MCP server concepts

Suggested stack:

Python
MCP Python SDK
SQLite initially
SQLAlchemy
Pydantic
pytest
Claude Desktop

Resume bullet:

Built a Python MCP server integrating Claude with a relational customer-support system, exposing validated CRUD tools, contextual resources, ticket-triage workflows and audit logging.


Step 1 — Create the project

Open PowerShell:

cd C:\Users\Dell\Desktop\amnnn

mkdir customer-support-mcp
cd customer-support-mcp

uv init
uv add "mcp[cli]" sqlalchemy pydantic
uv add --dev pytest

Create the project structure:

mkdir app
mkdir app\services
mkdir tests

New-Item app\__init__.py
New-Item app\database.py
New-Item app\models.py
New-Item app\schemas.py
New-Item app\server.py

New-Item app\services\__init__.py
New-Item app\services\customer_service.py
New-Item app\services\ticket_service.py
New-Item app\services\audit_service.py

New-Item tests\__init__.py
New-Item tests\test_customers.py
New-Item tests\test_tickets.py

Your structure should be:

customer-support-mcp/
├── app/
│   ├── services/
│   │   ├── __init__.py
│   │   ├── audit_service.py
│   │   ├── customer_service.py
│   │   └── ticket_service.py
│   ├── __init__.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   └── server.py
├── tests/
│   ├── __init__.py
│   ├── test_customers.py
│   └── test_tickets.py
├── pyproject.toml
└── uv.lock

Verify the dependencies:

uv run python -c "import mcp; import sqlalchemy; import pydantic; print('Dependencies installed successfully')"


Step 2 — Create the SQLite database and models
1. Add the database configuration

Open app\database.py and paste:

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_PATH = Path(__file__).resolve().parent.parent / "customer_support.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(
    dbapi_connection,
    connection_record,
) -> None:
    """Enable foreign-key enforcement for every SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a database session with rollback on failure."""
    session = SessionLocal()

    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all database tables."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
2. Add the database models

Open app\models.py and paste:

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="customer_status_check",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    phone: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    tickets: Mapped[list[Ticket]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
    )


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="ticket_priority_check",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="ticket_status_check",
        ),
        Index("ticket_status_priority_index", "status", "priority"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="open",
        nullable=False,
    )
    assigned_team: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    customer: Mapped[Customer] = relationship(back_populates="tickets")
    comments: Mapped[list[TicketComment]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
    )


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    ticket: Mapped[Ticket] = relationship(back_populates="comments")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(index=True)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


Create the tables

Run from the project root:

uv run python -c "from app.database import init_db; init_db(); print('Database initialized successfully')"

Expected output:

Database initialized successfully

A new file should appear:

customer_support.db
4. Confirm the tables

Run:

uv run python -c "from sqlalchemy import inspect; from app.database import engine; print(inspect(engine).get_table_names())"

Expected result:

['audit_logs', 'customers', 'ticket_comments', 'tickets']