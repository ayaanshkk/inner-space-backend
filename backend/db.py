# db.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./local.db"
    print("⚠️ Using local SQLite database (DATABASE_URL not found in environment).")

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        future=True
    )
else:
    print("✅ Using hosted PostgreSQL database.")

    # Fix dialect prefix for SQLAlchemy 2.x
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        print("✅ Fixed database URL dialect (postgres -> postgresql)")

    # Strip pgbouncer hint — not a valid Postgres param
    for param in ('?pgbouncer=true', '&pgbouncer=true'):
        if param in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.replace(param, '')
            print("✅ Cleaned pgbouncer parameter from connection string")

    # ── Port correction ───────────────────────────────────────────────────────
    # Session mode (5432): holds one connection per client for the full session.
    # Transaction mode (6543): returns the connection to the pool after each
    # transaction, so far fewer physical connections are needed.
    # Supabase free tier caps session mode at 15 simultaneous clients, which a
    # Flask dev server with a few concurrent requests exhausts immediately.
    # Transaction mode has no such per-client cap — switch unconditionally.
    if ':5432' in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace(':5432', ':6543', 1)
        print("✅ Switched from port 5432 (session mode) → 6543 (transaction mode)")
    elif ':6543' in DATABASE_URL:
        print("✅ Using port 6543 (transaction mode / pgBouncer)")

    # ── Pool settings for transaction mode ───────────────────────────────────
    # In transaction mode each connection is shared, so a pool of 5+10 can
    # serve many more concurrent requests than session mode ever could.
    # pool_recycle keeps connections from going stale (Supabase closes idle
    # ones after ~5 min); pool_pre_ping verifies them before use.
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,          # permanent connections kept open
        max_overflow=10,      # burst connections (total cap = 15)
        pool_timeout=30,      # wait up to 30 s before raising an error
        pool_recycle=300,     # recycle after 5 min (matches Supabase idle timeout)
        pool_pre_ping=True,   # health-check before handing out a connection
        connect_args={
            "connect_timeout": 10,
        },
        future=True,
        echo=False,
    )

    print("✅ Connection pool configured: pool_size=5, max_overflow=10 (max total: 15)")

# ── Session factory ───────────────────────────────────────────────────────────
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
    expire_on_commit=False,
)

Base = declarative_base()


# ── Connection lifecycle hooks ────────────────────────────────────────────────
@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    pass

@event.listens_for(engine, "close")
def receive_close(dbapi_conn, connection_record):
    pass


# ── Public helpers ────────────────────────────────────────────────────────────

def get_db():
    """Dependency-style session generator."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection():
    """Quick liveness check — returns True on success."""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Database connection successful.")
        return True
    except SQLAlchemyError as e:
        print(f"❌ Database connection failed: {e}")
        return False


def get_db_connection():
    """Legacy wrapper for routes that expect a raw SQLAlchemy connection."""
    try:
        return engine.connect()
    except SQLAlchemyError as e:
        print(f"❌ Error creating database connection: {e}")
        raise


def init_db():
    """Create any missing tables without touching existing data."""
    from backend.models import (
        User, Customer, Project, Job, Assignment,
        CustomerFormData, DrawingDocument, FormDocument,
        MaterialOrder, ProductionNotification, Quotation, QuotationItem, Fitter
    )
    Base.metadata.create_all(bind=engine, checkfirst=True)
    print("✅ Database tables initialised")


def dispose_connections():
    """Release all pooled connections — called on shutdown."""
    engine.dispose()
    print("🧹 All database connections disposed")


import atexit
atexit.register(dispose_connections)