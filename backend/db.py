# db.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

# Load DATABASE_URL from environment variable
DATABASE_URL = os.getenv("DATABASE_URL")

# Fallback to local SQLite database if DATABASE_URL not set
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./local.db"
    print("⚠️ Using local SQLite database (DATABASE_URL not found in environment).")
    
    # Create SQLAlchemy engine for SQLite
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        future=True
    )
else:
    print("✅ Using hosted PostgreSQL database.")
    
    # ✅ CRITICAL FIX: Remove the ?pgbouncer=true parameter
    # It's just a reminder for us - PostgreSQL doesn't understand it!
    if '?pgbouncer=true' in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace('?pgbouncer=true', '')
        print("✅ Cleaned pgbouncer parameter from connection string")
    elif '&pgbouncer=true' in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace('&pgbouncer=true', '')
        print("✅ Cleaned pgbouncer parameter from connection string")
    
    # Check which port is being used
    if ':5432' in DATABASE_URL:
        print("⚠️  WARNING: Using port 5432 (Session Mode)")
        print("   For better performance, consider switching to port 6543 (Transaction Mode)")
    elif ':6543' in DATABASE_URL:
        print("✅ Using port 6543 (Transaction Mode with pgBouncer)")
    
    # ✅ CRITICAL FIX: Optimized connection pool settings for Supabase
    engine = create_engine(
        DATABASE_URL,
        # Connection pool settings optimized for Supabase
        pool_size=2,              # ✅ Max 2 permanent connections (reduced from default 5)
        max_overflow=3,           # ✅ Allow 3 additional temporary connections (reduced from default 10)
        pool_timeout=30,          # ✅ Wait up to 30 seconds for a connection
        pool_recycle=300,         # ✅ Recycle connections after 5 minutes (Supabase closes idle connections)
        pool_pre_ping=True,       # ✅ Verify connection health before using
        
        # Connection parameters
        connect_args={
            "connect_timeout": 10,  # 10 second connection timeout
        },
        
        # Other settings
        future=True,
        echo=False  # Set to True for SQL debugging
    )
    
    print(f"✅ Connection pool configured: pool_size=2, max_overflow=3 (max total: 5 connections)")

# Create a configured "Session" class
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
    expire_on_commit=False  # ✅ Prevents attributes from expiring after commit
)

# Base class for declarative models
Base = declarative_base()


# ✅ Add event listeners for connection monitoring (optional but helpful)
@event.listens_for(engine, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Called when a new database connection is created"""
    # You can add connection setup here if needed
    pass

@event.listens_for(engine, "close")
def receive_close(dbapi_conn, connection_record):
    """Called when a database connection is closed"""
    # You can add connection cleanup here if needed
    pass


def get_db():
    """Dependency-style session generator"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_connection():
    """Optional: Check DB connection for diagnostics"""
    try:
        with engine.connect() as conn:
            # Test with a simple query
            from sqlalchemy import text
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
            print("✅ Database connection successful.")
            return True
    except SQLAlchemyError as e:
        print(f"❌ Database connection failed: {e}")
        return False


# 👇 Legacy compatibility function for routes still using get_db_connection()
def get_db_connection():
    """
    Legacy wrapper for backward compatibility with old code expecting
    a raw connection (like SQLite). Now returns an SQLAlchemy connection.
    """
    try:
        conn = engine.connect()
        return conn
    except SQLAlchemyError as e:
        print(f"❌ Error creating database connection: {e}")
        raise


def init_db():
    """Initialize database tables - only creates if they don't exist"""
    from backend.models import (
        User, Customer, Project, Job, Assignment, 
        CustomerFormData, DrawingDocument, FormDocument,
        MaterialOrder, ProductionNotification, Quotation, QuotationItem, Fitter
    )
    
    # ✅ CRITICAL: checkfirst=True ensures existing data is NOT dropped
    Base.metadata.create_all(bind=engine, checkfirst=True)
    print("✅ Database tables initialized")


def dispose_connections():
    """
    Dispose of all connections in the pool.
    Call this when shutting down the application.
    """
    engine.dispose()
    print("🧹 All database connections disposed")


# ✅ Add this for graceful shutdown
import atexit
atexit.register(dispose_connections)