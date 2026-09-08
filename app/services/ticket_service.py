from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Ticket
from app.schemas import TicketCreate
from app.services.audit_service import log_action
from app.services.customer_service import CustomerNotFoundError, get_customer


class TicketNotFoundError(Exception):
    """Raised when a ticket_id doesn't exist."""


def create_ticket(session: Session, data: TicketCreate) -> Ticket:
    """Create a new ticket for an existing customer."""
    # Validate the customer exists BEFORE creating the ticket —
    # gives a clear CustomerNotFoundError instead of a raw FK constraint error.
    get_customer(session, data.customer_id)

    ticket = Ticket(
        customer_id=data.customer_id,
        subject=data.subject,
        description=data.description,
        priority=data.priority,
    )
    session.add(ticket)
    session.flush()

    log_action(
        session,
        action="create_ticket",
        entity_type="ticket",
        entity_id=ticket.id,
        details={"subject": ticket.subject, "priority": ticket.priority},
    )
    return ticket


def get_ticket(session: Session, ticket_id: int) -> Ticket:
    """Fetch a single ticket by id, or raise if not found."""
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(f"No ticket with id={ticket_id}")
    return ticket


# Valid status transitions: keys are current status, values are allowed next statuses
VALID_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress", "closed"},
    "in_progress": {"resolved", "open", "closed"},
    "resolved": {"closed", "in_progress"},  # reopened if the fix didn't work
    "closed": set(),  # terminal state — no transitions out
}


class InvalidStatusTransitionError(Exception):
    """Raised when a status change isn't allowed from the current status."""


def change_ticket_status(session: Session, ticket_id: int, new_status: str) -> Ticket:
    """Change a ticket's status, enforcing the allowed transition graph."""
    ticket = get_ticket(session, ticket_id)

    allowed = VALID_TRANSITIONS.get(ticket.status, set())
    if new_status not in allowed:
        raise InvalidStatusTransitionError(
            f"Cannot move ticket {ticket_id} from '{ticket.status}' to '{new_status}'"
        )

    old_status = ticket.status
    ticket.status = new_status
    session.flush()

    log_action(
        session,
        action="change_ticket_status",
        entity_type="ticket",
        entity_id=ticket.id,
        details={"from": old_status, "to": new_status},
    )
    return ticket


def resolve_ticket(session: Session, ticket_id: int) -> Ticket:
    """Convenience wrapper: mark a ticket resolved via the same validated path."""
    return change_ticket_status(session, ticket_id, "resolved")


def list_tickets(
    session: Session,
    status: str | None = None,
    priority: str | None = None,
    customer_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Ticket]:
    """List tickets with optional filters, newest first."""
    query = session.query(Ticket)
    if status is not None:
        query = query.filter(Ticket.status == status)
    if priority is not None:
        query = query.filter(Ticket.priority == priority)
    if customer_id is not None:
        query = query.filter(Ticket.customer_id == customer_id)
    return query.order_by(Ticket.id.desc()).offset(offset).limit(limit).all()


from app.models import TicketComment  # add to your existing models import
from app.schemas import TicketCommentCreate  # add to your existing schemas import


def assign_ticket(session: Session, ticket_id: int, team: str) -> Ticket:
    """Assign a ticket to a support team."""
    ticket = get_ticket(session, ticket_id)

    old_team = ticket.assigned_team
    ticket.assigned_team = team
    session.flush()

    log_action(
        session,
        action="assign_ticket",
        entity_type="ticket",
        entity_id=ticket.id,
        details={"from_team": old_team, "to_team": team},
    )
    return ticket


def add_comment(
    session: Session, ticket_id: int, data: TicketCommentCreate
) -> TicketComment:
    """Add a comment to a ticket."""
    get_ticket(session, ticket_id)  # raises TicketNotFoundError if missing

    comment = TicketComment(
        ticket_id=ticket_id,
        author=data.author,
        body=data.body,
    )
    session.add(comment)
    session.flush()

    log_action(
        session,
        action="add_comment",
        entity_type="ticket_comment",
        entity_id=comment.id,
        details={"ticket_id": ticket_id, "author": data.author},
    )
    return comment


def delete_ticket(session: Session, ticket_id: int) -> None:
    """Delete a ticket and its comments (cascade)."""
    ticket = get_ticket(session, ticket_id)

    log_action(
        session,
        action="delete_ticket",
        entity_type="ticket",
        entity_id=ticket.id,
        details={"subject": ticket.subject, "status": ticket.status},
    )
    session.delete(ticket)
    session.flush()