"""One-off migration: add the `actor` column to audit_logs."""

from sqlalchemy import inspect, text

from app.database import engine


def migrate() -> None:
    columns = {col["name"] for col in inspect(engine).get_columns("audit_logs")}

    if "actor" in columns:
        print("column 'actor' already exists, nothing to do")
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE audit_logs "
                "ADD COLUMN actor VARCHAR(100) NOT NULL DEFAULT 'system'"
            )
        )
    print("added 'actor' column to audit_logs")


if __name__ == "__main__":
    migrate()