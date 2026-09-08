from app.database import get_session
from app.models import KnowledgeArticle

ARTICLES = [
    {
        "slug": "refund-policy",
        "title": "Refund Policy",
        "category": "billing",
        "body": (
            "Refunds are available within 30 days of purchase. "
            "Customers on annual plans may request a prorated refund at any time. "
            "Refunds are processed to the original payment method within 5-7 business days. "
            "Escalate to the billing team for amounts over $500."
        ),
    },
    {
        "slug": "failed-payments",
        "title": "Troubleshooting Failed Payments",
        "category": "billing",
        "body": (
            "Common causes: expired card, insufficient funds, bank fraud hold, "
            "or a mismatched billing address. Ask the customer to confirm the card "
            "details, then retry. If it fails three times, escalate to billing."
        ),
    },
    {
        "slug": "password-reset",
        "title": "Password Reset Procedure",
        "category": "account",
        "body": (
            "Direct customers to the 'Forgot password' link. Reset emails expire "
            "after 60 minutes. If the email never arrives, check spam, then verify "
            "the account email is correct. Never reset a password on the customer's behalf."
        ),
    },
    {
        "slug": "login-issues",
        "title": "Login Troubleshooting",
        "category": "account",
        "body": (
            "Check whether the account is active (inactive accounts cannot log in). "
            "Clear cookies, try an incognito window, and confirm the correct email. "
            "For repeated lockouts, escalate to the security team."
        ),
    },
]


def seed() -> None:
    with get_session() as session:
        for article in ARTICLES:
            exists = (
                session.query(KnowledgeArticle)
                .filter(KnowledgeArticle.slug == article["slug"])
                .first()
            )
            if exists is None:
                session.add(KnowledgeArticle(**article))
                print(f"added: {article['slug']}")
            else:
                print(f"skipped (exists): {article['slug']}")







if __name__ == "__main__":
    seed()