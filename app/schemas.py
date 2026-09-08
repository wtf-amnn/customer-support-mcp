from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CustomerCreate(BaseModel):
    """Fields required to create a new customer."""

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)


class CustomerUpdate(BaseModel):
    """Fields that can be updated on an existing customer. All optional."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class CustomerRead(BaseModel):
    """Shape of a customer returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    phone: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class TicketCreate(BaseModel):
    """Fields required to create a new ticket."""

    customer_id: int
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    priority: str = Field(default="medium", pattern="^(low|medium|high|urgent)$")


class TicketUpdate(BaseModel):
    """Fields that can be updated on an existing ticket. All optional."""

    subject: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    priority: str | None = Field(default=None, pattern="^(low|medium|high|urgent)$")
    status: str | None = Field(
        default=None, pattern="^(open|in_progress|resolved|closed)$"
    )
    assigned_team: str | None = Field(default=None, max_length=100)


class TicketRead(BaseModel):
    """Shape of a ticket returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    subject: str
    description: str
    priority: str
    status: str
    assigned_team: str | None
    created_at: datetime
    updated_at: datetime


class TicketCommentCreate(BaseModel):
    """Fields required to add a comment to a ticket."""

    author: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1)


class TicketCommentRead(BaseModel):
    """Shape of a ticket comment returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    author: str
    body: str
    created_at: datetime