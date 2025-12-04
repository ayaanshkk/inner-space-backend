# import sys
# import os

# # Get current directory
# current_dir = os.path.abspath(os.getcwd())

# print("=" * 70)
# print("🚨 EMERGENCY DATABASE SETUP")
# print("=" * 70)
# print(f"📁 Working from: {current_dir}")

# # Make sure we're in the right place
# if not os.path.exists('backend'):
#     print("\n❌ ERROR: 'backend' folder not found!")
#     print("   Please run this script from the project root directory:")
#     print("   cd aztec_interiors")
#     print("   python setup_database.py")
#     sys.exit(1)

# # Import from backend
# from backend.app import create_app
# from backend.db import SessionLocal, Base, engine

# print("✅ App imported successfully")

# app = create_app()

# with app.app_context():
#     print("\n📦 Importing all models...")
    
#     # Import ALL models
#     try:
#         from backend.models import (
#             User, LoginAttempt, Session, Customer, Project, Team, Fitter, 
#             Salesperson, Job, JobDocument, JobChecklist, ChecklistItem,
#             ScheduleItem, Room, RoomAppliance, JobFormLink, JobNote,
#             ApplianceCategory, Brand, Product, Quotation, QuotationItem,
#             ProductQuoteItem, Invoice, InvoiceLineItem, Payment, CountingSheet,
#             CountingItem, RemedialAction, RemedialItem, DocumentTemplate,
#             AuditLog, VersionedSnapshot, ProductionNotification, FormSubmission,
#             CustomerFormData, ApprovalNotification, DataImport, DrawingDocument,
#             Assignment
#         )
#         print("✅ All models imported successfully")
#     except ImportError as e:
#         print(f"❌ Error importing models: {e}")
#         import traceback
#         traceback.print_exc()
#         sys.exit(1)
    
#     # Drop all existing tables
#     print("\n⚠️  Dropping existing tables...")
#     try:
#         Base.metadata.drop_all(bind=engine)
# ()
#         print("✅ Old tables dropped")
#     except Exception as e:
#         print(f"⚠️  Warning dropping tables: {e}")
    
#     # Create all tables fresh
#     print("\n🔨 Creating all tables...")
#     Base.metadata.create_all(bind=engine)

    
#     # Verify tables
#     from sqlalchemy import inspect
#     inspector = inspect(db.engine)
#     tables = inspector.get_table_names()
    
#     print(f"\n✅ Created {len(tables)} tables:")
    
#     # Show important tables first
#     important_tables = ['users', 'customers', 'projects', 'jobs', 'assignments']
#     for table in important_tables:
#         if table in tables:
#             print(f"   ✓ {table}")
    
#     # Show count of remaining tables
#     other_tables = [t for t in tables if t not in important_tables]
#     if other_tables:
#         print(f"   ✓ ... and {len(other_tables)} more tables")
    
#     if 'users' not in tables:
#         print("\n❌ ERROR: users table was not created!")
#         print("   There may be an issue with your models.py")
#         sys.exit(1)
    
#     # Create default users
#     print("\n👤 Creating default users...")
    
#     try:
#         # Check if users already exist
#         existing_count = User.query.count()
#         if existing_count > 0:
#             print(f"⚠️  Found {existing_count} existing users:")
#             for u in User.query.all():
#                 print(f"   - {u.email} ({u.role})")
#             print("\n   Skipping user creation")
#         else:
#             # Admin user
#             admin = User(
#                 email='admin@aztecinteriors.com',
#                 first_name='Admin',
#                 last_name='User',
#                 role='Manager',
#                 is_active=True,
#                 is_verified=True
#             )
#             admin.set_password('admin123')
#             session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .add(admin)
            
#             # Your user
#             user = User(
#                 email='ayaan.ateeb@gmail.com',
#                 first_name='Ayaan',
#                 last_name='Ateeb',
#                 role='Manager',
#                 is_active=True,
#                 is_verified=True
#             )
#             user.set_password('Ayaan#1804')
#             session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .add(user)
            
#             # Employee
#             employee = User(
#                 email='employee@aztecinteriors.com',
#                 first_name='Test',
#                 last_name='Employee',
#                 role='Staff',
#                 is_active=True,
#                 is_verified=True
#             )
#             employee.set_password('employee123')
#             session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .add(employee)
            
#             # Commit users
#             session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .commit()
            
#             print("✅ Default users created:")
#             print("   📧 admin@aztecinteriors.com / admin123 (Manager)")
#             print("   📧 ayaan.ateeb@gmail.com / Ayaan#1804 (Manager)")
#             print("   📧 employee@aztecinteriors.com / employee123 (Staff)")
            
#     except Exception as e:
#         print(f"❌ Error with users: {e}")
#         import traceback
#         traceback.print_exc()
#         session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .rollback()
    
#     # Create test customer
#     print("\n🏢 Creating test customer...")
#     try:
#         existing_customers = Customer.query.count()
#         if existing_customers > 0:
#             print(f"⚠️  Found {existing_customers} existing customers, skipping")
#         else:
#             test_customer = Customer(
#                 name="Test Customer",
#                 address="123 Test Street",
#                 phone="01234567890",
#                 email="test@example.com",
#                 status="Active"
#             )
#             session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .add(test_customer)
#             session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .commit()
#             print("✅ Test customer created")
#     except Exception as e:
#         print(f"⚠️  Warning creating customer: {e}")
#         session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .rollback()
    
#     # Final verification
#     print("\n📊 Database Summary:")
#     try:
#         user_count = User.query.count()
#         customer_count = Customer.query.count()
#         print(f"   Users: {user_count}")
#         print(f"   Customers: {customer_count}")
#         print(f"   Total Tables: {len(tables)}")
        
#         if user_count > 0:
#             print("\n✅ Ready to login with:")
#             for u in User.query.all():
#                 print(f"      {u.email}")
                
#     except Exception as e:
#         print(f"   Unable to query: {e}")
    
#     print("\n" + "=" * 70)
#     print("✅ DATABASE SETUP COMPLETE!")
#     print("=" * 70)
#     print("\n🚀 Start the server:")
#     print("   cd backend")
#     print("   python app.py")
#     print("\n📝 Login credentials:")
#     print("   Email: ayaan.ateeb@gmail.com")
#     print("   Password: Ayaan#1804")
#     print("\n🌐 Or deploy to Render with these files!")
#     print("=" * 70)