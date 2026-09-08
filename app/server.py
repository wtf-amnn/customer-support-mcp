from __future__ import annotations

import os
import sys
from pathlib import Path
import uvicorn
from starlette.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- every app.* import must come after the line above ---
from mcp.server import MCPServer

from app.context import set_current_actor
from app.database import get_session
from app.models import KnowledgeArticle
from app.schemas import (
    CustomerCreate,
    CustomerRead,
    TicketCommentCreate,
    TicketCreate,
    TicketRead,
)
from app.services.customer_service import (
    CustomerNotFoundError,
    DuplicateEmailError,
    create_customer,
    get_customer,
    list_customers,
)
from app.services.ticket_service import (
    InvalidStatusTransitionError,
    TicketNotFoundError,
    add_comment,
    assign_ticket,
    change_ticket_status,
    create_ticket,
    delete_ticket,
    get_ticket,
    list_tickets,
    resolve_ticket,
)

mcp = MCPServer("customer-support")


@mcp.tool()
def create_customer_tool(name: str, email: str, phone: str | None = None) -> dict:
    """Create a new customer record.

    Args:
        name: Full name of the customer.
        email: Customer's email address (must be unique).
        phone: Optional phone number.
    """
    try:
        data = CustomerCreate(name=name, email=email, phone=phone)
    except ValueError as exc:
        return {"error": f"Invalid input: {exc}"}

    with get_session() as session:
        try:
            customer = create_customer(session, data)
        except DuplicateEmailError as exc:
            return {"error": str(exc)}

        return CustomerRead.model_validate(customer).model_dump(mode="json")


@mcp.tool()
def get_customer_tool(customer_id: int) -> dict:
    """Fetch a customer by their id.

    Args:
        customer_id: The customer's numeric id.
    """
    with get_session() as session:
        try:
            customer = get_customer(session, customer_id)
        except CustomerNotFoundError as exc:
            return {"error": str(exc)}
        return CustomerRead.model_validate(customer).model_dump(mode="json")


@mcp.resource("customer://profile/{customer_id}")
def customer_profile_resource(customer_id: int) -> str:
    """Expose a customer's profile as a readable resource.

    Args:
        customer_id: The customer's numeric id.
    """
    with get_session() as session:
        try:
            customer = get_customer(session, customer_id)
        except CustomerNotFoundError as exc:
            return f"Error: {exc}"
        data = CustomerRead.model_validate(customer).model_dump(mode="json")
        return (
            f"Customer #{data['id']}\n"
            f"Name: {data['name']}\n"
            f"Email: {data['email']}\n"
            f"Phone: {data['phone'] or 'N/A'}\n"
            f"Status: {data['status']}\n"
        )



@mcp.resource("ticket://details/{ticket_id}")
def ticket_details_resource(ticket_id: int) -> str:
    """Full context for a ticket: details, customer, and comment history.

    Args:
        ticket_id: The ticket's numeric id.
    """
    with get_session() as session:
        try:
            ticket = get_ticket(session, ticket_id)
        except TicketNotFoundError as exc:
            return f"Error: {exc}"

        customer = ticket.customer          # relationship from models.py
        comments = ticket.comments          # relationship from models.py

        lines = [
            f"TICKET #{ticket.id}: {ticket.subject}",
            f"Status: {ticket.status} | Priority: {ticket.priority}",
            f"Assigned team: {ticket.assigned_team or 'unassigned'}",
            f"Opened: {ticket.created_at:%Y-%m-%d %H:%M} UTC",
            "",
            f"CUSTOMER: {customer.name} <{customer.email}>",
            f"Account status: {customer.status}",
            "",
            "DESCRIPTION:",
            ticket.description,
            "",
            f"COMMENTS ({len(comments)}):",
        ]

        if not comments:
            lines.append("  (none yet)")
        else:
            for c in comments:
                lines.append(f"  [{c.created_at:%Y-%m-%d %H:%M}] {c.author}: {c.body}")

        return "\n".join(lines)


@mcp.tool()
def get_ticket_details_tool(ticket_id: int) -> str:
    """Get full context for a ticket: details, customer info, and all comments.

    Use this instead of get_ticket_tool when you need the complete picture,
    including the customer and the comment history.

    Args:
        ticket_id: The ticket's numeric id.
    """
    return ticket_details_resource(ticket_id)



@mcp.resource("knowledge://articles/{category}")
def knowledge_articles_resource(category: str) -> str:
    """Support knowledge-base articles for a given category.

    Args:
        category: Article category, e.g. 'billing' or 'account'.
    """
    with get_session() as session:
        articles = (
            session.query(KnowledgeArticle)
            .filter(KnowledgeArticle.category == category)
            .order_by(KnowledgeArticle.title)
            .all()
        )

        if not articles:
            return f"No knowledge articles found in category '{category}'."

        sections = [f"KNOWLEDGE BASE — category: {category}", ""]
        for a in articles:
            sections.append(f"## {a.title}  (slug: {a.slug})")
            sections.append(a.body)
            sections.append("")

        return "\n".join(sections)


@mcp.tool()
def get_knowledge_articles_tool(category: str) -> str:
    """Read support knowledge-base articles for a category.

    Use this to find relevant policy or troubleshooting guidance before
    advising on a ticket.

    Args:
        category: One of 'billing' or 'account'.
    """
    return knowledge_articles_resource(category)



@mcp.tool()
def list_customers_tool(status: str | None = None, limit: int = 50) -> list[dict]:
    """List customers, optionally filtered by status.

    Args:
        status: Filter by 'active' or 'inactive'. Omit for all customers.
        limit: Maximum number of customers to return.
    """
    with get_session() as session:
        customers = list_customers(session, status=status, limit=limit)
        return [
            CustomerRead.model_validate(c).model_dump(mode="json") for c in customers
        ]


@mcp.tool()
def create_ticket_tool(
    customer_id: int,
    subject: str,
    description: str,
    priority: str = "medium",
) -> dict:
    """Create a support ticket for an existing customer.

    Args:
        customer_id: Id of the customer raising the ticket.
        subject: Short summary of the issue.
        description: Full description of the issue.
        priority: One of 'low', 'medium', 'high', 'urgent'.
    """
    try:
        data = TicketCreate(
            customer_id=customer_id,
            subject=subject,
            description=description,
            priority=priority,
        )
    except ValueError as exc:
        return {"error": f"Invalid input: {exc}"}

    with get_session() as session:
        try:
            ticket = create_ticket(session, data)
        except CustomerNotFoundError as exc:
            return {"error": str(exc)}
        return TicketRead.model_validate(ticket).model_dump(mode="json")


VALID_TICKET_STATUSES = {"open", "in_progress", "resolved", "closed"}
VALID_TICKET_PRIORITIES = {"low", "medium", "high", "urgent"}


def _clean_filter(value: str | None) -> str | None:
    """Normalize a filter value: blank or whitespace-only becomes None."""
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


@mcp.tool()
def list_tickets_tool(
    status: str | None = None,
    priority: str | None = None,
    customer_id: int | None = None,
    limit: int = 50,
) -> list[dict] | dict:
    """List tickets with optional filters. Use this to find tickets matching criteria.

    Args:
        status: Filter by 'open', 'in_progress', 'resolved', or 'closed'. Omit for all.
        priority: Filter by 'low', 'medium', 'high', or 'urgent'. Omit for all.
        customer_id: Only tickets belonging to this customer.
        limit: Maximum number of tickets to return.
    """
    status = _clean_filter(status)
    priority = _clean_filter(priority)

    if status is not None and status not in VALID_TICKET_STATUSES:
        return {
            "error": f"Invalid status '{status}'. "
            f"Must be one of: {', '.join(sorted(VALID_TICKET_STATUSES))}."
        }

    if priority is not None and priority not in VALID_TICKET_PRIORITIES:
        return {
            "error": f"Invalid priority '{priority}'. "
            f"Must be one of: {', '.join(sorted(VALID_TICKET_PRIORITIES))}."
        }

    with get_session() as session:
        tickets = list_tickets(
            session,
            status=status,
            priority=priority,
            customer_id=customer_id,
            limit=limit,
        )
        return [TicketRead.model_validate(t).model_dump(mode="json") for t in tickets]


@mcp.tool()
def get_ticket_tool(ticket_id: int) -> dict:
    """Fetch a single ticket by id.

    Args:
        ticket_id: The ticket's numeric id.
    """
    with get_session() as session:
        try:
            ticket = get_ticket(session, ticket_id)
        except TicketNotFoundError as exc:
            return {"error": str(exc)}
        return TicketRead.model_validate(ticket).model_dump(mode="json")


@mcp.tool()
def assign_ticket_tool(ticket_id: int, team: str) -> dict:
    """Assign a ticket to a support team.

    Args:
        ticket_id: The ticket to assign.
        team: Name of the team, e.g. 'billing_team' or 'security_team'.
    """
    with get_session() as session:
        try:
            ticket = assign_ticket(session, ticket_id, team)
        except TicketNotFoundError as exc:
            return {"error": str(exc)}
        return TicketRead.model_validate(ticket).model_dump(mode="json")


@mcp.tool()
def add_comment_tool(ticket_id: int, author: str, body: str) -> dict:
    """Add a comment to a ticket.

    Args:
        ticket_id: The ticket to comment on.
        author: Who is writing the comment.
        body: The comment text.
    """
    try:
        data = TicketCommentCreate(author=author, body=body)
    except ValueError as exc:
        return {"error": f"Invalid input: {exc}"}

    with get_session() as session:
        try:
            comment = add_comment(session, ticket_id, data)
        except TicketNotFoundError as exc:
            return {"error": str(exc)}
        return {
            "id": comment.id,
            "ticket_id": comment.ticket_id,
            "author": comment.author,
            "body": comment.body,
        }


@mcp.tool()
def change_ticket_status_tool(ticket_id: int, new_status: str) -> dict:
    """Change a ticket's status. Only valid transitions are allowed.

    Valid transitions: open -> in_progress/closed; in_progress -> resolved/open/closed;
    resolved -> closed/in_progress; closed is terminal.

    Args:
        ticket_id: The ticket to update.
        new_status: One of 'open', 'in_progress', 'resolved', 'closed'.
    """
    with get_session() as session:
        try:
            ticket = change_ticket_status(session, ticket_id, new_status)
        except (TicketNotFoundError, InvalidStatusTransitionError) as exc:
            return {"error": str(exc)}
        return TicketRead.model_validate(ticket).model_dump(mode="json")


@mcp.tool()
def resolve_ticket_tool(ticket_id: int) -> dict:
    """Mark a ticket as resolved.

    Args:
        ticket_id: The ticket to resolve.
    """
    with get_session() as session:
        try:
            ticket = resolve_ticket(session, ticket_id)
        except (TicketNotFoundError, InvalidStatusTransitionError) as exc:
            return {"error": str(exc)}
        return TicketRead.model_validate(ticket).model_dump(mode="json")


@mcp.tool()
def delete_ticket_tool(ticket_id: int, confirm: bool = False) -> dict:
    """Permanently delete a ticket and all its comments. Destructive and irreversible.

    Args:
        ticket_id: The ticket to delete.
        confirm: Must be explicitly set to true to proceed with deletion.
    """
    if not confirm:
        return {
            "error": (
                f"Deletion not confirmed. Ticket {ticket_id} was NOT deleted. "
                "Confirm with the user, then call again with confirm=true."
            )
        }

    with get_session() as session:
        try:
            delete_ticket(session, ticket_id)
        except TicketNotFoundError as exc:
            return {"error": str(exc)}
        return {"deleted": True, "ticket_id": ticket_id}



@mcp.prompt()
def triage_ticket(ticket_id: int) -> str:
    """Triage a support ticket: assess, categorize, and recommend next steps.

    Args:
        ticket_id: The ticket to triage.
    """
    return f"""Triage support ticket #{ticket_id}.

Work through these steps:

1. Read the full ticket context from the resource `ticket://details/{ticket_id}`.
   This includes the ticket, the customer, and the full comment history.

2. Check the customer's other tickets using `list_tickets_tool` with their
   customer_id, to see whether this is a recurring or escalating problem.

3. Use `get_knowledge_articles_tool` to read the relevant category — 'billing'
   for payment, refund, or invoice issues, and 'account' for login, password,
   or access issues.

4. Then report back with:
   - A two-sentence summary of the issue
   - Whether the current priority ({{priority}}) looks correct, and why
   - Which team should own it (billing_team, account_team, security_team,
     engineering_team, or product_team)
   - Any knowledge base article that applies, referenced by its slug
   - The recommended next action

Do not change the ticket's status or assignment yet — present your
recommendation first and wait for my confirmation."""

@mcp.prompt()
def daily_queue_review() -> str:
    """Review the open ticket queue and produce a prioritized action list."""
    return """Review the current support queue and give me a prioritized plan for today.

1. Use `get_ticket_details_tool` with ticket_id={ticket_id} to read the full
   ticket context, including the customer and the complete comment history.

2. For any ticket marked 'urgent' or 'high', read `ticket://details/{ticket_id}`
   to get the customer and comment history.

3. Flag anything that looks like it needs attention:
   - Urgent tickets that are still unassigned
   - Tickets where the customer has commented more recently than the support team
   - Customers with more than one open ticket (possible escalation)

4. Give me:
   - A ranked list of what to work on first, with a one-line reason for each
   - Any ticket that should be reassigned, and to which team
   - Anything that looks stalled

Report only — do not change any ticket."""

if __name__ == "__main__":
    set_current_actor(os.environ.get("MCP_ACTOR", "local"))

    if os.environ.get("MCP_TRANSPORT") == "http":
        app = mcp.streamable_http_app()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
            allow_headers=["*"],
            expose_headers=["Mcp-Session-Id"],
        )
        uvicorn.run(app, host="127.0.0.1", port=3001)
    else:
        mcp.run()