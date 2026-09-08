from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Customer
from app.schemas import CustomerCreate
from app.services.audit_service import log_action

from app.schemas import CustomerUpdate

class CustomerNotFoundError(Exception):
    """Raised when a customer_id doesn't exist."""


class DuplicateEmailError(Exception):
    """Raised when a customer email already exists."""


def create_customer(session: Session, data: CustomerCreate) -> Customer:
    """Create a new customer and record it in the audit log."""
    customer = Customer(
        name=data.name,
        email=data.email,
        phone=data.phone,
    )
    session.add(customer)

    try:
        session.flush()  # triggers the unique-email constraint now, not later
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateEmailError(f"Email already exists: {data.email}") from exc

    log_action(
        session,
        action="create_customer",
        entity_type="customer",
        entity_id=customer.id,
        details={"name": customer.name, "email": customer.email},
    )
    return customer


def get_customer(session: Session, customer_id: int) -> Customer:
    """Fetch a single customer by id, or raise if not found."""
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise CustomerNotFoundError(f"No customer with id={customer_id}")
    return customer


def list_customers(
    session: Session,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Customer]:
    """List customers, optionally filtered by status, with pagination."""
    query = session.query(Customer)
    if status is not None:
        query = query.filter(Customer.status == status)
    return query.order_by(Customer.id).offset(offset).limit(limit).all()


def update_customer(
    session: Session, customer_id: int, data: CustomerUpdate
) -> Customer:
    """Update fields on an existing customer. Only sets fields that were provided."""
    customer = get_customer(session, customer_id)

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(customer, field, value)

    session.flush()

    log_action(
        session,
        action="update_customer",
        entity_type="customer",
        entity_id=customer.id,
        details=updates,
    )
    return customer


def delete_customer(session: Session, customer_id: int) -> None:
    """Delete a customer and all their tickets (cascade)."""
    customer = get_customer(session, customer_id)

    log_action(
        session,
        action="delete_customer",
        entity_type="customer",
        entity_id=customer.id,
        details={"name": customer.name, "email": customer.email},
    )
    session.delete(customer)
    session.flush()

