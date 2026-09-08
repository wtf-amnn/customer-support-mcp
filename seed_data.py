"""Seed the customer-support database with realistic test data.

Run from the project root:

    uv run seed_data.py            # add seed data (skips anything already there)
    uv run seed_data.py --reset    # wipe customers/tickets/comments first, then seed

Everything goes through the service layer rather than raw SQLAlchemy, so the
audit_logs table gets populated exactly as it would in real usage.
"""

from __future__ import annotations

import sys

from app.database import get_session
from app.models import AuditLog, Customer
from app.schemas import (
    CustomerCreate,
    CustomerUpdate,
    TicketCommentCreate,
    TicketCreate,
)
from app.services.customer_service import (
    DuplicateEmailError,
    create_customer,
    update_customer,
)
from app.services.ticket_service import (
    add_comment,
    assign_ticket,
    change_ticket_status,
    create_ticket,
)


# --------------------------------------------------------------------------
# Seed definitions
# --------------------------------------------------------------------------

CUSTOMERS = [
    {"name": "Rahul Mehta", "email": "rahul.mehta@example.com", "phone": "+91-9820011223"},
    {"name": "Priya Nair", "email": "priya.nair@example.com", "phone": "+91-9930044556"},
    {"name": "Arjun Desai", "email": "arjun.desai@example.com", "phone": None},
    {"name": "Sana Kapoor", "email": "sana.kapoor@example.com", "phone": "+91-9812233445"},
    {"name": "Vikram Rao", "email": "vikram.rao@example.com", "phone": "+91-9876501234"},
]

# Customers to mark inactive after creation (tests update_customer + status filter)
INACTIVE_EMAILS = {"vikram.rao@example.com"}

# Each ticket references a customer by email so ids don't have to be hardcoded.
# "transitions" are applied in order via change_ticket_status, so they must
# follow the VALID_TRANSITIONS graph in ticket_service.py.
TICKETS = [
    {
        "customer_email": "rahul.mehta@example.com",
        "subject": "Payment failed three times",
        "description": (
            "Tried paying for the annual plan with my HDFC credit card. "
            "It was declined three times but I can see a hold on my statement. "
            "Need this refunded and the subscription activated."
        ),
        "priority": "urgent",
        "team": None,
        "transitions": [],
        "comments": [],
    },
    {
        "customer_email": "priya.nair@example.com",
        "subject": "Cannot log in after password reset",
        "description": (
            "I reset my password yesterday but the new one is not accepted. "
            "The reset email arrived twice and I used the most recent link."
        ),
        "priority": "high",
        "team": "account_team",
        "transitions": ["in_progress"],
        "comments": [
            ("support_agent", "Confirmed the account is active. Sent a fresh reset link."),
            ("priya.nair", "Still getting 'invalid credentials' on the new password."),
        ],
    },
    {
        "customer_email": "arjun.desai@example.com",
        "subject": "Refund not received after 10 days",
        "description": (
            "Cancelled the annual plan on the 3rd and was told the prorated refund "
            "would arrive in 5-7 business days. Nothing has come through yet."
        ),
        "priority": "urgent",
        "team": "billing_team",
        "transitions": ["in_progress"],
        "comments": [
            ("billing_agent", "Located the refund; it failed due to a closed card. Reissuing to UPI."),
        ],
    },
    {
        "customer_email": "sana.kapoor@example.com",
        "subject": "Invoice shows wrong GST number",
        "description": (
            "The GST number on my last two invoices belongs to my old company. "
            "I need corrected invoices for filing."
        ),
        "priority": "medium",
        "team": "billing_team",
        "transitions": ["in_progress", "resolved"],
        "comments": [
            ("billing_agent", "Updated the billing profile and reissued both invoices."),
            ("sana.kapoor", "Received, both look correct now. Thank you."),
        ],
    },
    {
        "customer_email": "rahul.mehta@example.com",
        "subject": "Feature request: export tickets to CSV",
        "description": (
            "It would help a lot if the reporting page had a CSV export option "
            "instead of copy-pasting from the table."
        ),
        "priority": "low",
        "team": "product_team",
        "transitions": [],
        "comments": [
            ("support_agent", "Logged with the product team for the next planning cycle."),
        ],
    },
    {
        "customer_email": "priya.nair@example.com",
        "subject": "Repeated account lockouts",
        "description": (
            "My account locks out roughly every second day even with the correct "
            "password. Happening across two different devices."
        ),
        "priority": "high",
        "team": "security_team",
        "transitions": ["in_progress", "resolved", "closed"],
        "comments": [
            ("security_agent", "Found a stale session token triggering the lockout rule. Cleared it."),
            ("priya.nair", "No lockouts for a week now."),
        ],
    },
    {
        "customer_email": "vikram.rao@example.com",
        "subject": "Downgrade request before renewal",
        "description": (
            "I want to move from the Business plan to Starter before the renewal "
            "date so I am not charged the higher amount."
        ),
        "priority": "medium",
        "team": None,
        "transitions": [],
        "comments": [],
    },
    {
        "customer_email": "arjun.desai@example.com",
        "subject": "API returning 500 on bulk ticket creation",
        "description": (
            "Posting more than 50 tickets in one batch returns a 500. "
            "Batches of 20 work fine. Blocking our migration."
        ),
        "priority": "urgent",
        "team": "engineering_team",
        "transitions": ["in_progress"],
        "comments": [
            ("eng_oncall", "Reproduced. Batch handler times out past ~40 records. Fix in review."),
        ],
    },
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def reset_database() -> None:
    """Delete all customers (tickets and comments cascade) plus audit logs."""
    with get_session() as session:
        customers = session.query(Customer).all()
        for customer in customers:
            session.delete(customer)
        deleted_logs = session.query(AuditLog).delete()
        print(f"reset: removed {len(customers)} customers and {deleted_logs} audit logs")


def seed_customers() -> dict[str, int]:
    """Create customers. Returns a mapping of email -> customer id."""
    email_to_id: dict[str, int] = {}

    for spec in CUSTOMERS:
        with get_session() as session:
            existing = (
                session.query(Customer)
                .filter(Customer.email == spec["email"])
                .first()
            )
            if existing is not None:
                email_to_id[spec["email"]] = existing.id
                print(f"customer exists, skipping: {spec['email']}")
                continue

            try:
                customer = create_customer(session, CustomerCreate(**spec))
            except DuplicateEmailError as exc:
                print(f"  ! {exc}")
                continue

            email_to_id[spec["email"]] = customer.id
            print(f"created customer {customer.id}: {customer.name}")

    for email in INACTIVE_EMAILS:
        customer_id = email_to_id.get(email)
        if customer_id is None:
            continue
        with get_session() as session:
            update_customer(session, customer_id, CustomerUpdate(status="inactive"))
            print(f"marked inactive: {email}")

    return email_to_id


def seed_tickets(email_to_id: dict[str, int]) -> None:
    """Create tickets, assign teams, add comments, and apply status transitions."""
    for spec in TICKETS:
        customer_id = email_to_id.get(spec["customer_email"])
        if customer_id is None:
            print(f"  ! no customer for {spec['customer_email']}, skipping ticket")
            continue

        with get_session() as session:
            ticket = create_ticket(
                session,
                TicketCreate(
                    customer_id=customer_id,
                    subject=spec["subject"],
                    description=spec["description"],
                    priority=spec["priority"],
                ),
            )
            ticket_id = ticket.id
            print(f"created ticket {ticket_id}: {spec['subject'][:45]}")

        if spec["team"]:
            with get_session() as session:
                assign_ticket(session, ticket_id, spec["team"])
                print(f"  assigned to {spec['team']}")

        for author, body in spec["comments"]:
            with get_session() as session:
                add_comment(
                    session,
                    ticket_id,
                    TicketCommentCreate(author=author, body=body),
                )
            print(f"  comment by {author}")

        for new_status in spec["transitions"]:
            with get_session() as session:
                change_ticket_status(session, ticket_id, new_status)
            print(f"  status -> {new_status}")


def print_summary() -> None:
    """Show what the seeded database now contains."""
    from app.models import Ticket, TicketComment

    with get_session() as session:
        customer_count = session.query(Customer).count()
        ticket_count = session.query(Ticket).count()
        comment_count = session.query(TicketComment).count()
        audit_count = session.query(AuditLog).count()

        print("\n--- summary ---")
        print(f"customers:      {customer_count}")
        print(f"tickets:        {ticket_count}")
        print(f"comments:       {comment_count}")
        print(f"audit log rows: {audit_count}")

        print("\ntickets by status:")
        for status in ("open", "in_progress", "resolved", "closed"):
            count = session.query(Ticket).filter(Ticket.status == status).count()
            print(f"  {status:<13} {count}")

        print("\ntickets by priority:")
        for priority in ("low", "medium", "high", "urgent"):
            count = session.query(Ticket).filter(Ticket.priority == priority).count()
            print(f"  {priority:<13} {count}")


def main() -> None:
    if "--reset" in sys.argv:
        reset_database()

    email_to_id = seed_customers()
    seed_tickets(email_to_id)
    print_summary()


if __name__ == "__main__":
    main()
