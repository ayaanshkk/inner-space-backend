"""
Quick script to reset password for uwais.innerspace user
Run this from the backend directory:
    python reset_password.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from werkzeug.security import generate_password_hash
from backend.db import SessionLocal
from sqlalchemy import text

def reset_password(username, new_password):
    """Reset password for a user"""
    session = SessionLocal()
    try:
        # Generate password hash
        password_hash = generate_password_hash(new_password)
        
        # Update password in database
        query = text("""
            UPDATE "StreemLyne_MT"."User_Master"
            SET password = :password_hash,
                updated_at = NOW()
            WHERE user_name = :username
            RETURNING user_id, employee_id
        """)
        
        result = session.execute(query, {
            'password_hash': password_hash,
            'username': username
        })
        
        updated_user = result.fetchone()
        session.commit()
        
        if updated_user:
            print(f"✅ Password reset successful for user: {username}")
            print(f"   User ID: {updated_user.user_id}")
            print(f"   Employee ID: {updated_user.employee_id}")
            print(f"   New password: {new_password}")
            return True
        else:
            print(f"❌ User not found: {username}")
            return False
            
    except Exception as e:
        session.rollback()
        print(f"❌ Error resetting password: {e}")
        return False
    finally:
        session.close()

if __name__ == "__main__":
    # Reset password for uwais.innerspace
    username = "uwais.innerspace"
    new_password = "InnerSpace123!"
    
    print(f"Resetting password for: {username}")
    print(f"New password will be: {new_password}")
    print("-" * 50)
    
    success = reset_password(username, new_password)
    
    if success:
        print("\n" + "=" * 50)
        print("✅ PASSWORD RESET COMPLETE!")
        print("=" * 50)
        print(f"\nYou can now login with:")
        print(f"  Username: {username}")
        print(f"  Password: {new_password}")
        print("=" * 50)
    else:
        print("\n❌ Password reset failed")