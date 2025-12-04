# import sys
# import os

# print("=" * 70)
# print("🔧 RENDER DATABASE INITIALIZATION")
# print("=" * 70)

# try:
#     from backend.app import create_app
#     from backend.db import SessionLocal, Base, engine
    
#     print("✅ Imports successful")
    
#     app = create_app()
    
#     with app.app_context():
#         # Import all models to register them
#         print("📦 Importing models...")
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
#         print("✅ All models imported")
        
#         # Create all tables
#         print("🔨 Creating database tables...")
        # Base.metadata.create_all(bind=engine)

#         print("✅ Tables created/verified")
        
#         # Verify tables were created
#         from sqlalchemy import inspect
#         inspector = inspect(db.engine)
#         tables = inspector.get_table_names()
#         print(f"✅ Database has {len(tables)} tables")
        
#         if 'users' not in tables:
#             print("❌ ERROR: users table was not created!")
#             sys.exit(1)
        
#         # Check/create default users
#         user_count = User.query.count()
        
#         if user_count == 0:
#             print("\n👤 Creating default users...")
            
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
            
#             # Manager user
#             manager = User(
#                 email='ayaan.ateeb@gmail.com',
#                 first_name='Ayaan',
#                 last_name='Ateeb',
#                 role='Manager',
#                 is_active=True,
#                 is_verified=True
#             )
#             manager.set_password('Ayaan#1804')
#             session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .add(manager)
            
#             # Employee user
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
            
#             session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .commit()
            
#             print("✅ Created 3 default users:")
#             print("   📧 admin@aztecinteriors.com / admin123 (Manager)")
#             print("   📧 ayaan.ateeb@gmail.com / Ayaan#1804 (Manager)")
#             print("   📧 employee@aztecinteriors.com / employee123 (Staff)")
#         else:
#             print(f"✅ Database ready with {user_count} users")
#             # Show existing users
#             for u in User.query.limit(5).all():
#                 print(f"   📧 {u.email} ({u.role})")
        
#         # Create test customer if needed
#         try:
#             customer_count = Customer.query.count()
#             if customer_count == 0:
#                 print("\n🏢 Creating test customer...")
#                 test_customer = Customer(
#                     name="Test Customer",
#                     address="123 Test Street",
#                     phone="01234567890",
#                     email="test@example.com",
#                     status="Active"
#                 )
#                 session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .add(test_customer)
#                 session = SessionLocal()
# # ...do stuff...
# session.add(...)
# session.commit()
# session.close()
# .commit()
#                 print("✅ Test customer created")
#         except Exception as e:
#             print(f"⚠️  Could not create test customer: {e}")
        
#     print("\n" + "=" * 70)
#     print("✅ INITIALIZATION COMPLETE")
#     print("=" * 70)
#     print("🚀 Starting Gunicorn...")
#     print("=" * 70)

# except Exception as e:
#     print(f"\n❌ INITIALIZATION FAILED: {e}")
#     import traceback
#     traceback.print_exc()
#     print("\n" + "=" * 70)
#     print("⚠️  Continuing anyway - Gunicorn will start")
#     print("=" * 70)
#     # Don't exit - let Gunicorn try to start anyway