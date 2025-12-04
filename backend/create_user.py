import os
import sys
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()

from backend.db import SessionLocal
from backend.models import User
from werkzeug.security import generate_password_hash
from datetime import datetime

def create_admin_user():
    """Create the initial admin user for Inner Space"""
    
    session = SessionLocal()
    
    try:
        # Check if any users exist
        existing_users = session.query(User).count()
        
        if existing_users > 0:
            print(f"⚠️  Database already has {existing_users} user(s)")
            response = input("Do you want to create another user anyway? (y/n): ")
            if response.lower() != 'y':
                print("❌ Cancelled")
                return
        
        print("\n" + "="*60)
        print("🔧 CREATE INITIAL ADMIN USER FOR INNER SPACE")
        print("="*60 + "\n")
        
        # Get user details
        email = input("Enter email (e.g., admin@innerspace.com): ").strip()
        if not email:
            print("❌ Email is required")
            return
        
        # Check if email already exists
        existing = session.query(User).filter_by(email=email).first()
        if existing:
            print(f"❌ User with email {email} already exists!")
            return
        
        password = input("Enter password (min 8 characters): ").strip()
        if len(password) < 8:
            print("❌ Password must be at least 8 characters")
            return
        
        first_name = input("Enter first name: ").strip()
        last_name = input("Enter last name: ").strip()
        
        print("\nAvailable roles:")
        print("  1. Manager (full access)")
        print("  2. HR")
        print("  3. Sales")
        print("  4. Production")
        print("  5. Staff")
        
        role_choice = input("Select role (1-5): ").strip()
        role_map = {
            '1': 'Manager',
            '2': 'HR',
            '3': 'Sales',
            '4': 'Production',
            '5': 'Staff'
        }
        
        role = role_map.get(role_choice, 'Manager')
        
        # Hash the password
        password_hash = generate_password_hash(password)
        
        # ✅ DON'T specify ID - let the database auto-generate it
        new_user = User(
            # ❌ NO ID - Database will auto-generate
            email=email,
            password_hash=password_hash,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        session.add(new_user)
        session.commit()
        session.refresh(new_user)  # Get the auto-generated ID
        
        print("\n" + "="*60)
        print("✅ USER CREATED SUCCESSFULLY!")
        print("="*60)
        print(f"\nEmail: {email}")
        print(f"Password: {password}")
        print(f"Name: {first_name} {last_name}")
        print(f"Role: {role}")
        print(f"ID: {new_user.id}")  # This will be the auto-generated integer
        print("\n🎉 You can now login to Inner Space with these credentials!")
        print("\n" + "="*60)
        print("NEXT STEPS:")
        print("="*60)
        print("\n1. Clear browser localStorage:")
        print("   - Press F12 to open DevTools")
        print("   - Go to Console tab")
        print("   - Type: localStorage.clear()")
        print("   - Press Enter")
        print("   - Type: location.reload()")
        print("   - Press Enter")
        print("\n2. Login with:")
        print(f"   Email: {email}")
        print(f"   Password: {password}")
        print("\n3. Create your first customer!")
        
    except Exception as e:
        session.rollback()
        print(f"\n❌ Error creating user: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    create_admin_user()