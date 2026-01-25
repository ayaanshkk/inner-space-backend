# backend/migrate_drawings_add_confidence.py

"""
Migration: Add confidence column to drawings table
"""

from backend.db import engine
from sqlalchemy import text

def migrate_add_confidence():
    """Add confidence column to drawings table"""
    
    with engine.connect() as conn:
        print("🔧 Adding confidence column to drawings table...")
        
        try:
            # Check if column exists
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='drawings' AND column_name='confidence'
            """))
            
            if result.fetchone():
                print("⚠️ Column 'confidence' already exists, skipping")
                return
            
            # Add the column
            conn.execute(text("""
                ALTER TABLE drawings 
                ADD COLUMN confidence NUMERIC(5, 4)
            """))
            
            conn.commit()
            print("✅ Successfully added confidence column")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            conn.rollback()
            raise

if __name__ == "__main__":
    migrate_add_confidence()