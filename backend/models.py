import uuid
import enum
import secrets
from datetime import datetime, timedelta
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Enum, ForeignKey, Text, JSON, Numeric, Float, Time
)
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

from .db import Base, SessionLocal  # ✅ use declarative Base from db.py
# from db import Base, SessionLocal


# ----------------------------------
# Helpers / Enums
# ----------------------------------

JOB_STAGE_ENUM = Enum(
    'Lead', 'Quote', 'Consultation', 'Survey', 'Measure', 'Design', 'Quoted', 'Accepted',
    'Rejected', 'Ordered', 'Production', 'Delivery', 'Installation', 'Complete', 'Remedial', 'Cancelled',
    name='job_stage_enum'
)

JOB_TYPE_ENUM = Enum(
    'Kitchen', 'Bedroom', 'Wardrobe', 'Remedial', 'Other',
    name='job_type_enum'
)

CONTACT_MADE_ENUM = Enum('Yes', 'No', 'Unknown', name='contact_made_enum')
PREFERRED_CONTACT_ENUM = Enum('Phone', 'Email', 'WhatsApp', name='preferred_contact_enum')

CHECKLIST_TEMPLATE_ENUM = Enum(
    'BedroomChecklist', 'KitchenChecklist', 'PaymentTerms', 'CustomerSatisfaction',
    'RemedialAction', 'PromotionalOffer', name='checklist_template_enum'
)

DOCUMENT_TEMPLATE_TYPE_ENUM = Enum(
    'Invoice', 'Receipt', 'Quotation', 'Warranty', 'Terms', 'Other', name='document_template_type_enum'
)

# PAYMENT_METHOD_ENUM = Enum('BACS', 'Cash', 'Card', 'Other', name='payment_method_enum')
AUDIT_ACTION_ENUM = Enum('create', 'update', 'delete', name='audit_action_enum')
APPROVAL_STATUS_ENUM = Enum('pending', 'approved', 'rejected', name='approval_status_enum')
ASSIGNMENT_TYPE_ENUM = Enum('job', 'off', 'delivery', 'note', name='assignment_type_enum')

# ----------------------------------
# Auth & Security
# ----------------------------------

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    phone = Column(String(20))
    role = Column(String(20), default='user')
    department = Column(String(50))
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)
    reset_token = Column(String(100))
    reset_token_expires = Column(DateTime)
    verification_token = Column(String(100))
    is_invited = Column(Boolean, default=False, nullable=False)
    invitation_token = Column(String(100), unique=True, nullable=True, index=True)
    invited_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f'<User {self.email}>'

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:  # ✅ Check if password exists
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def generate_reset_token(self) -> str:
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        return self.reset_token

    def generate_verification_token(self) -> str:
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token

    def generate_jwt_token(self, secret_key: str) -> str:
        payload = {
            'user_id': self.id,
            'email': self.email,
            'role': self.role,
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow(),
        }
        return jwt.encode(payload, secret_key, algorithm='HS256')

    @staticmethod
    def verify_jwt_token(token: str, secret_key: str, session=None):
        try:
            payload = jwt.decode(token, secret_key, algorithms=['HS256'])
            
            # Use session if provided, otherwise manage a temporary session
            if session is None:
                local_session = SessionLocal()
            else:
                local_session = session
                
            # Lookup user using session.get (Correct Native SQLAlchemy)
            # session.get() is safe and modern
            user = local_session.get(User, payload['user_id'])
            
            # Only close session if it was locally created
            if session is None:
                local_session.close() 
                
            return user if user and user.is_active else None
        
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        except Exception:
            # Ensure the locally created session is closed on error
            if session is None and 'local_session' in locals():
                 local_session.close()
            return None

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.full_name,
            'phone': self.phone,
            'role': self.role,
            'department': self.department,
            'is_active': self.is_active,
            'is_invited': self.is_invited if hasattr(self, 'is_invited') else False,
            'invitation_token': self.invitation_token if hasattr(self, 'is_invited') and self.is_invited else None,
            'invited_at': self.invited_at.isoformat() if hasattr(self, 'invited_at') and self.invited_at else None,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'

    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False, index=True)
    ip_address = Column(String(45), nullable=False)
    success = Column(Boolean, default=False)
    attempted_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<LoginAttempt {self.email} - {"Success" if self.success else "Failed"}>'


class Session(Base):
    __tablename__ = 'user_sessions'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', backref='sessions')

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


# ----------------------------------
# Core CRM Entities
# ----------------------------------

class Customer(Base):
    __tablename__ = 'customers'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    date_of_measure = Column(Date)
    name = Column(String(200), nullable=False)
    address = Column(Text)
    postcode = Column(String(20))
    phone = Column(String(50))
    email = Column(String(200))
    contact_made = Column(CONTACT_MADE_ENUM, default='Unknown')
    preferred_contact_method = Column(PREFERRED_CONTACT_ENUM)
    marketing_opt_in = Column(Boolean, default=False)
    notes = Column(Text)
    
    # Stage field that can mirror project stages
    stage = Column(JOB_STAGE_ENUM, default='Lead')

    # Project types and salesperson
    project_types = Column(JSON)  # Can store ["Bedroom", "Kitchen"] etc.
    salesperson = Column(String(200))

    # Audit
    created_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(200))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Status flag
    status = Column(String(50), default='Active')

    # relationships
    # NEW: One-to-Many relationship with Projects
    projects = relationship('Project', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    
    jobs = relationship('Job', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    # quotations = relationship('Quotation', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    form_data = relationship('CustomerFormData', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    form_submissions = relationship('FormSubmission', back_populates='customer', lazy=True)

    def extract_postcode_from_address(self):
        if not self.address:
            return None
        import re
        pattern = r'\b[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}\b'
        match = re.search(pattern, self.address.upper())
        return match.group(0) if match else None

    def update_stage_from_job(self):
        """Update customer stage based on their primary job's stage"""
        primary_job = self.get_primary_job()
        if primary_job:
            self.stage = primary_job.stage
            session = SessionLocal()
            session.add(self)

    def get_primary_job(self):
        """Get the customer's primary (most recent or active) job"""
        from .models import Job
        return session.query(Job).filter(
            Job.customer_id == self.id,
            Job.stage != 'Cancelled'
        ).order_by(Job.created_at.desc()).first()

    def save(self):
        if not self.postcode and self.address:
            self.postcode = self.extract_postcode_from_address()
        session = SessionLocal()
        try:
            session.add(self)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

            
    def to_dict(self, include_projects=False, include_forms=False):
        """Convert customer to dictionary with optional project and form inclusion"""
        
        # ✅ Handle JSON column properly
        project_types_value = self.project_types
        if project_types_value is None:
            project_types_value = []
        elif isinstance(project_types_value, str):
            # If it's stored as a JSON string, parse it
            import json
            try:
                project_types_value = json.loads(project_types_value)
            except:
                project_types_value = []
        elif not isinstance(project_types_value, list):
            project_types_value = []
        
        data = {
            'id': self.id,
            'name': self.name,
            'phone': self.phone or '',
            'email': self.email or '',
            'address': self.address or '',
            'postcode': self.postcode or '',
            'salesperson': self.salesperson or '',
            'contact_made': self.contact_made or 'Unknown',
            'preferred_contact_method': self.preferred_contact_method or 'Phone',
            'marketing_opt_in': bool(self.marketing_opt_in),
            'notes': self.notes or '',
            'stage': self.stage or 'Lead',
            'status': self.status or 'Active',
            'project_types': project_types_value,
            'date_of_measure': self.date_of_measure.isoformat() if self.date_of_measure else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_by': self.created_by,
            'updated_by': self.updated_by,
            'project_count': len(self.projects) if self.projects else 0
        }
        
        if include_projects:
            data['projects'] = [project.to_dict(include_forms=False) for project in self.projects]
        
        # ✅ NEW: Include form submissions if requested
        if include_forms:
            import json
            data['form_submissions'] = [
                {
                    'id': form.id,
                    'submitted_at': form.submitted_at.isoformat() if form.submitted_at else None,
                    'form_data': json.loads(form.form_data) if isinstance(form.form_data, str) else form.form_data,
                    'token_used': form.token_used,
                    'project_id': form.project_id,
                    'created_by': form.created_by,
                    'approval_status': form.approval_status or 'approved',
                }
                for form in self.form_data  # ✅ Uses the 'form_data' relationship
            ]
        
        return data

    def __repr__(self):
        return f'<Customer {self.name}>'


# NEW MODEL: Project - Allows multiple projects per customer
class Project(Base):
    __tablename__ = 'projects'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # FOREIGN KEY: Links to Customer (many-to-one)
    customer_id = Column(String(36), ForeignKey('customers.id'), nullable=False)
    
    # Project details
    project_name = Column(String(200), nullable=False)
    project_type = Column(JOB_TYPE_ENUM, nullable=False)  # Kitchen, Bedroom, Wardrobe, etc.
    stage = Column(JOB_STAGE_ENUM, default='Lead', nullable=False)  # ✅ Added nullable=False
    date_of_measure = Column(Date)
    notes = Column(Text)
    
    # Audit
    created_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(200))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    customer = relationship('Customer', back_populates='projects')
    form_submissions = relationship('CustomerFormData', back_populates='project', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Project {self.id}: {self.project_name} for Customer {self.customer_id}>'

    def to_dict(self, include_forms=False):
        """Convert project to dictionary with optional form inclusion"""
        data = {
            'id': self.id,
            'customer_id': self.customer_id,
            'project_name': self.project_name,
            'project_type': self.project_type,
            'stage': self.stage or 'Lead',  # ✅ Fallback to 'Lead' if somehow None
            'date_of_measure': self.date_of_measure.isoformat() if self.date_of_measure else None,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_by': self.created_by,
            'updated_by': self.updated_by,
            'form_count': len(self.form_submissions) if self.form_submissions else 0
        }
        
        if include_forms:
            data['forms'] = [form.to_dict() for form in self.form_submissions]
        
        return data

class Team(Base):
    __tablename__ = 'teams'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    specialty = Column(String(100))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship('Fitter', back_populates='team', lazy=True)


class Fitter(Base):
    __tablename__ = 'fitters'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    team_id = Column(Integer, ForeignKey('teams.id'))
    skills = Column(Text)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    team = relationship('Team', back_populates='members')


class Salesperson(Base):
    __tablename__ = 'salespeople'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    email = Column(String(120))
    phone = Column(String(20))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Job(Base):
    __tablename__ = 'jobs'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))  # UUID
    customer_id = Column(String(36), ForeignKey('customers.id'), nullable=False)

    # Basic job info
    job_reference = Column(String(100), unique=True)
    job_name = Column(String(200))
    job_type = Column(JOB_TYPE_ENUM, nullable=False, default='Kitchen')
    stage = Column(JOB_STAGE_ENUM, nullable=False, default='Lead')
    priority = Column(String(20), default='Medium')

    # Pricing
    quote_price = Column(Numeric(10, 2))
    agreed_price = Column(Numeric(10, 2))
    sold_amount = Column(Numeric(10, 2))
    deposit1 = Column(Numeric(10, 2))
    deposit2 = Column(Numeric(10, 2))

    # Dates
    delivery_date = Column(DateTime)
    measure_date = Column(DateTime)
    completion_date = Column(DateTime)
    deposit_due_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Additional info
    installation_address = Column(Text)
    notes = Column(Text)

    # Team assignments
    salesperson_name = Column(String(100))
    assigned_team_name = Column(String(100))
    primary_fitter_name = Column(String(100))

    assigned_team_id = Column(Integer, ForeignKey('teams.id'))
    primary_fitter_id = Column(Integer, ForeignKey('fitters.id'))
    salesperson_id = Column(Integer, ForeignKey('salespeople.id'))

    # Links
    # quote_id = Column(Integer, ForeignKey('quotations.id'))
    quote_id = Column(Integer, nullable=True)

    # Boolean flags
    has_counting_sheet = Column(Boolean, default=False)
    has_schedule = Column(Boolean, default=False)
    # has_invoice = Column(Boolean, default=False)

    # relationships
    customer = relationship('Customer', back_populates='jobs')
    # quotation = relationship('Quotation', foreign_keys=[quote_id], back_populates='job', uselist=False)
    quotation = None
    assigned_team = relationship('Team', foreign_keys=[assigned_team_id])
    primary_fitter = relationship('Fitter', foreign_keys=[primary_fitter_id])
    salesperson = relationship('Salesperson', foreign_keys=[salesperson_id])

    documents = relationship('JobDocument', back_populates='job', lazy=True, cascade='all, delete-orphan')
    checklists = relationship('JobChecklist', back_populates='job', lazy=True, cascade='all, delete-orphan')
    schedule_items = relationship('ScheduleItem', back_populates='job', lazy=True, cascade='all, delete-orphan')
    rooms = relationship('Room', back_populates='job', lazy=True, cascade='all, delete-orphan')
    form_links = relationship('JobFormLink', back_populates='job', lazy=True, cascade='all, delete-orphan')
    job_notes = relationship('JobNote', back_populates='job', lazy=True, cascade='all, delete-orphan')
    # invoices = relationship('Invoice', back_populates='job', lazy=True, cascade='all, delete-orphan')
    counting_sheets = relationship('CountingSheet', back_populates='job', lazy=True, cascade='all, delete-orphan')
    remedials = relationship('RemedialAction', back_populates='job', lazy=True, cascade='all, delete-orphan')
    # payments = relationship('Payment', back_populates='job', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Job {self.job_reference or self.id}: {self.job_name or self.job_type}>'


# ----------------------------------
# Documents / Checklists / Rooms
# ----------------------------------

class JobDocument(Base):
    __tablename__ = 'job_documents'

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    mime_type = Column(String(100))
    category = Column(String(50))
    uploaded_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship('Job', back_populates='documents')


class JobChecklist(Base):
    __tablename__ = 'job_checklists'

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    template_type = Column(CHECKLIST_TEMPLATE_ENUM, nullable=True)
    template_version = Column(Integer, default=1)
    status = Column(String(20), default='Not Started')
    filled_by = Column(String(200))
    filled_at = Column(DateTime)
    fields = Column(JSON)  # JSON key/value for flexible templates
    signed = Column(Boolean, default=False)
    signature_path = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship('Job', back_populates='checklists')
    items = relationship('ChecklistItem', back_populates='checklist', lazy=True, cascade='all, delete-orphan')


class ChecklistItem(Base):
    __tablename__ = 'checklist_items'

    id = Column(Integer, primary_key=True)
    checklist_id = Column(Integer, ForeignKey('job_checklists.id'), nullable=False)
    text = Column(String(255), nullable=False)
    checked = Column(Boolean, default=False)
    order_index = Column(Integer, default=0)

    checklist = relationship('JobChecklist', back_populates='items')


class ScheduleItem(Base):
    __tablename__ = 'schedule_items'

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime)
    all_day = Column(Boolean, default=False)
    status = Column(String(20), default='Scheduled')
    assigned_team_id = Column(Integer, ForeignKey('teams.id'))
    assigned_fitter_id = Column(Integer, ForeignKey('fitters.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship('Job', back_populates='schedule_items')
    assigned_team = relationship('Team')
    assigned_fitter = relationship('Fitter')


class Room(Base):
    __tablename__ = 'rooms'

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
    name = Column(String(100), nullable=False)
    room_type = Column(String(50), nullable=False)
    measurements = Column(Text)  # could be JSON
    notes = Column(Text)
    order_index = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship('Job', back_populates='rooms')
    # appliances = relationship('RoomAppliance', back_populates='room', lazy=True, cascade='all, delete-orphan')

class JobFormLink(Base):
    __tablename__ = 'job_form_links'

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
    form_submission_id = Column(Integer, ForeignKey('form_submissions.id'), nullable=False)
    linked_at = Column(DateTime, default=datetime.utcnow)
    linked_by = Column(String(200))

    job = relationship('Job', back_populates='form_links')
    form_submission = relationship('FormSubmission', back_populates='job_links')


class JobNote(Base):
    __tablename__ = 'job_notes'

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
    content = Column(Text, nullable=False)
    note_type = Column(String(50), default='general')
    author = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship('Job', back_populates='job_notes')

# ----------------------------------
# Invoicing & Payments
# ----------------------------------

# class Invoice(Base):
#     __tablename__ = 'invoices'

#     id = Column(Integer, primary_key=True)
#     job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
#     invoice_number = Column(String(50), unique=True, nullable=False)
#     status = Column(String(20), default='Draft')
#     due_date = Column(Date)
#     paid_date = Column(Date)
#     created_at = Column(DateTime, default=datetime.utcnow)
#     updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

#     job = relationship('Job', back_populates='invoices')
#     line_items = relationship('InvoiceLineItem', back_populates='invoice', lazy=True, cascade='all, delete-orphan')
#     payments = relationship('Payment', back_populates='invoice', lazy=True)

#     @property
#     def amount_due(self):
#         total = sum([(li.quantity or 0) * (li.unit_price or 0) for li in self.line_items])
#         return total

#     @property
#     def amount_paid(self):
#         return sum([p.amount or 0 for p in self.payments if p.cleared])

#     @property
#     def balance(self):
#         return (self.amount_due or 0) - (self.amount_paid or 0)


# class InvoiceLineItem(Base):
#     __tablename__ = 'invoice_line_items'

#     id = Column(Integer, primary_key=True)
#     invoice_id = Column(Integer, ForeignKey('invoices.id'), nullable=False)
#     description = Column(String(255), nullable=False)
#     quantity = Column(Integer, default=1)
#     unit_price = Column(Numeric(10, 2), nullable=False)
#     vat_rate = Column(Numeric(5, 2), default=0)  # e.g. 20.00 for 20%

#     invoice = relationship('Invoice', back_populates='line_items')


# class Payment(Base):
#     __tablename__ = 'payments'

#     id = Column(Integer, primary_key=True)
#     job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
#     invoice_id = Column(Integer, ForeignKey('invoices.id'))  # optional link to invoice

#     date = Column(Date, default=datetime.utcnow)
#     amount = Column(Numeric(10, 2), nullable=False)
#     method = Column(PAYMENT_METHOD_ENUM, default='BACS')
#     reference = Column(String(120))
#     bank_details_used = Column(String(255))
#     notes = Column(Text)

#     cleared = Column(Boolean, default=True)

#     created_at = Column(DateTime, default=datetime.utcnow)

#     job = relationship('Job', back_populates='payments')
#     invoice = relationship('Invoice', back_populates='payments')


# ----------------------------------
# Counting Sheets
# ----------------------------------

class CountingSheet(Base):
    __tablename__ = 'counting_sheets'

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)
    room_id = Column(Integer, ForeignKey('rooms.id'))  # optional, per-room counting
    template_type = Column(Enum('KitchenCountingSheet', 'BedCountingSheet', name='counting_template_enum'), nullable=False)
    status = Column(Enum('Draft', 'Finalised', name='counting_status_enum'), default='Draft')

    created_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(200))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship('Job', back_populates='counting_sheets')
    room = relationship('Room')
    items = relationship('CountingItem', back_populates='sheet', lazy=True, cascade='all, delete-orphan')


class CountingItem(Base):
    __tablename__ = 'counting_items'

    id = Column(Integer, primary_key=True)
    sheet_id = Column(Integer, ForeignKey('counting_sheets.id'), nullable=False)

    description = Column(String(255), nullable=False)   # ITEM
    quantity_requested = Column(Integer, default=0)     # ORDERED
    quantity_ordered = Column(Integer, default=0)
    quantity_counted = Column(Integer, default=0)       # COUNTED
    unit = Column(String(50))
    supplier = Column(String(120))
    customer_supplied = Column(Boolean, default=False)
    notes = Column(Text)

    sheet = relationship('CountingSheet', back_populates='items')


# ----------------------------------
# Remedial Actions
# ----------------------------------

class RemedialAction(Base):
    __tablename__ = 'remedial_actions'

    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=False)

    date = Column(Date, default=datetime.utcnow)
    assigned_to = Column(String(200))  # could be fitter/team/user
    status = Column(Enum('Submitted', 'Reviewed', 'Actioned', name='remedial_status_enum'), default='Submitted')
    notes = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship('Job', back_populates='remedials')
    items = relationship('RemedialItem', back_populates='remedial', lazy=True, cascade='all, delete-orphan')


class RemedialItem(Base):
    __tablename__ = 'remedial_items'

    id = Column(Integer, primary_key=True)
    remedial_id = Column(Integer, ForeignKey('remedial_actions.id'), nullable=False)

    number = Column(Integer)  # No
    item = Column(String(120))
    remedial_action = Column(String(255))
    colour = Column(String(50))
    size = Column(String(50))
    quantity = Column(Integer, default=1)
    status = Column(String(50), default='Pending')

    remedial = relationship('RemedialAction', back_populates='items')


# ----------------------------------
# Templates Library
# ----------------------------------

class DocumentTemplate(Base):
    __tablename__ = 'document_templates'

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    template_type = Column(DOCUMENT_TEMPLATE_TYPE_ENUM, nullable=False)
    file_path = Column(String(500), nullable=False)  # points to uploaded file
    merge_fields = Column(JSON)  # list/structure of exposed merge fields
    uploaded_by = Column(String(200))
    uploaded_at = Column(DateTime, default=datetime.utcnow)


# ----------------------------------
# Audit & Versioning
# ----------------------------------

class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(120), nullable=False)
    entity_id = Column(String(120), nullable=False)
    action = Column(AUDIT_ACTION_ENUM, nullable=False)
    changed_by = Column(String(200))
    changed_at = Column(DateTime, default=datetime.utcnow)
    change_summary = Column(JSON)  # JSON diff summary
    previous_snapshot = Column(JSON)
    new_snapshot = Column(JSON)


class VersionedSnapshot(Base):
    __tablename__ = 'versioned_snapshots'

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(120), nullable=False)
    entity_id = Column(String(120), nullable=False)
    version_number = Column(Integer, nullable=False)
    reason = Column(String(255))
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(200))


# ----------------------------------
# Notifications
# ----------------------------------

class ProductionNotification(Base):
    __tablename__ = 'production_notifications'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=True)
    customer_id = Column(String(36), ForeignKey('customers.id'), nullable=True)
    checklist_id = Column(String(50), nullable=True)
    form_submission_id = Column(Integer, nullable=True)
    form_type = Column(String(50), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    read = Column(Boolean, default=False)
    dismissed = Column(Boolean, default=False)
    moved_by = Column(String(255), nullable=True)
    
    # relationships
    user = relationship('User', backref='notifications')
    job = relationship('Job', backref='notifications')
    customer = relationship('Customer', backref='notifications')


# ----------------------------------
# Forms / Submissions / Imports
# ----------------------------------

class FormSubmission(Base):
    __tablename__ = 'form_submissions'

    id = Column(Integer, primary_key=True)
    customer_id = Column(String(36), ForeignKey('customers.id'))
    form_data = Column(Text, nullable=False)
    source = Column(String(100))
    submitted_at = Column(DateTime, default=datetime.utcnow)
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime)

    customer = relationship('Customer', back_populates='form_submissions')
    job_links = relationship('JobFormLink', back_populates='form_submission', lazy=True, cascade='all, delete-orphan')


# UPDATED: CustomerFormData now requires project_id
class CustomerFormData(Base):
    __tablename__ = 'customer_form_data'

    id = Column(Integer, primary_key=True)
    
    # FOREIGN KEYS: Links to both Customer and Project
    customer_id = Column(String(36), ForeignKey('customers.id'), nullable=False)
    project_id = Column(String(36), ForeignKey('projects.id'), nullable=True)  # Changed to nullable=True
    
    form_data = Column(Text, nullable=False)
    token_used = Column(String(64), nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # ADD THIS LINE

    # Approval fields
    approval_status = Column(String(20), default='pending')
    approved_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    approval_date = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    
    # User who created the submission
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)

    # relationshipS
    customer = relationship('Customer', back_populates='form_data')
    project = relationship('Project', back_populates='form_submissions')
    
    # NEW RELATIONSHIPS ADDED FOR CLARITY:
    approved_by_user = relationship('User', foreign_keys=[approved_by], backref='approved_forms')
    creator = relationship('User', foreign_keys=[created_by], backref='created_forms')

    # Notifications relationship with cascade delete
    notifications = relationship(
        'ApprovalNotification',
        backref='document',
        cascade='all, delete-orphan',
        foreign_keys='ApprovalNotification.document_id'
    )

    def __repr__(self):
        return f'<CustomerFormData {self.id} for Customer {self.customer_id}>'

    def to_dict(self):
        import json
        try:
            parsed_data = json.loads(self.form_data)
        except:
            parsed_data = {"raw": self.form_data}
        
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'project_id': self.project_id,
            'form_data': parsed_data,
            'token_used': self.token_used,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,  # ADD THIS LINE
            'approval_status': self.approval_status,
            'approved_by': self.approved_by,
            'approval_date': self.approval_date.isoformat() if self.approval_date else None,
            'rejection_reason': self.rejection_reason,
            'created_by': self.created_by
        }


class ApprovalNotification(Base):
    __tablename__ = 'approval_notifications'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    document_type = Column(String(50), nullable=False)
    
    # Foreign key with cascade delete
    document_id = Column(
        Integer, 
        ForeignKey('customer_form_data.id', ondelete='CASCADE'),
        nullable=False
    )
    
    status = Column(String(20), default='pending')
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)
    
    # relationships
    user = relationship('User', backref='approval_notifications') 
    
    def __repr__(self):
        return f'<ApprovalNotification {self.id} for User {self.user_id}>'


class DataImport(Base):
    __tablename__ = 'data_imports'

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)
    import_type = Column(String(50), nullable=False)  # 'appliance_matrix', 'kbb_pricelist'
    status = Column(String(20), default='processing')  # processing, completed, failed
    records_processed = Column(Integer, default=0)
    records_failed = Column(Integer, default=0)
    error_log = Column(Text)
    imported_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    def __repr__(self):
        return f'<DataImport {self.filename} ({self.status})>'

class DrawingDocument(Base):
    __tablename__ = 'drawing_documents'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # FOREIGN KEYS: Links to Customer and Project
    customer_id = Column(String(36), ForeignKey('customers.id', ondelete='CASCADE'), nullable=False) # ADDED ondelete='CASCADE'
    project_id = Column(String(36), ForeignKey('projects.id', ondelete='CASCADE'), nullable=True) # ADDED ondelete='CASCADE'
    
    # File details
    file_name = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False) # Path on disk or S3/Cloud Storage key
    file_url = Column(String(500), nullable=False)     # URL to download/view the file
    mime_type = Column(String(100))
    category = Column(String(50), default='Drawing')   # e.g., 'Drawing', 'Layout', 'Photo'
    
    # Audit
    uploaded_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    # relationshipS (passive_deletes=True can also help, but ondelete='CASCADE' is stronger)
    customer = relationship('Customer', backref='drawing_documents')
    project = relationship('Project', backref='drawing_documents')
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'project_id': self.project_id,
            'filename': self.file_name,
            'url': self.file_url,
            'type': self.category, # Using category for the frontend's 'type' field
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'uploaded_by': self.uploaded_by
        }


class Assignment(Base):
    __tablename__ = 'assignments'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    type = Column(ASSIGNMENT_TYPE_ENUM, nullable=False, default='job')
    title = Column(String(255), nullable=False)
    date = Column(Date, nullable=False)  # Keep for backward compatibility
    
    # ✅ NEW FIELDS: Add start_date and end_date for task date ranges
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    customer_name = Column(String(200), nullable=True)
    
    user_id = Column(Integer, ForeignKey('users.id'))
    team_member = Column(String(200))
    
    created_by = Column(Integer, ForeignKey('users.id'))
    updated_by = Column(Integer, ForeignKey('users.id'))
    
    job_id = Column(String(36), ForeignKey('jobs.id'))
    customer_id = Column(String(36), ForeignKey('customers.id'))
    job_type = Column(String(100))
    
    start_time = Column(Time)
    end_time = Column(Time)
    estimated_hours = Column(Float)
    
    notes = Column(Text)
    priority = Column(String(20), default='Medium')
    status = Column(String(20), default='Scheduled')
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # ✅ RELATIONSHIPS (keep existing)
    job = relationship('Job', backref='assignments')
    customer = relationship('Customer', backref='assignments')
    
    user = relationship(
        'User', 
        foreign_keys=[user_id], 
        backref='assigned_assignments',
        overlaps="created_by_user,updated_by_user"
    )
    
    created_by_user = relationship(
        'User', 
        foreign_keys=[created_by], 
        backref='created_assignments',
        overlaps="user,updated_by_user"
    )
    
    updated_by_user = relationship(
        'User', 
        foreign_keys=[updated_by], 
        backref='updated_assignments',
        overlaps="user,created_by_user"
    )
    
    def to_dict(self):
        """Convert assignment to dictionary with safe attribute access"""
        try:
            created_by_name = None
            try:
                if self.created_by_user:
                    created_by_name = self.created_by_user.full_name
            except Exception as e:
                print(f"Error getting created_by_user: {e}")
            
            updated_by_name = None
            try:
                if self.updated_by_user:
                    updated_by_name = self.updated_by_user.full_name
            except Exception as e:
                print(f"Error getting updated_by_user: {e}")
            
            job_reference = None
            try:
                if self.job:
                    job_reference = self.job.job_reference
            except Exception as e:
                print(f"Error getting job reference: {e}")
            
            customer_name = None
            try:
                if self.customer:
                    customer_name = self.customer.name
            except Exception as e:
                print(f"Error getting customer name: {e}")
            
            return {
                'id': self.id,
                'type': self.type,
                'title': self.title,
                'date': self.date.isoformat() if self.date else None,
                # ✅ NEW FIELDS IN RESPONSE
                'start_date': self.start_date.isoformat() if self.start_date else None,
                'end_date': self.end_date.isoformat() if self.end_date else None,
                'customer_name': self.customer_name or customer_name,
                'user_id': self.user_id,
                'team_member': self.team_member,
                'job_id': self.job_id,
                'customer_id': self.customer_id,
                'job_type': self.job_type,
                'start_time': self.start_time.strftime('%H:%M') if self.start_time else None,
                'end_time': self.end_time.strftime('%H:%M') if self.end_time else None,
                'estimated_hours': self.estimated_hours,
                'notes': self.notes,
                'priority': self.priority,
                'status': self.status,
                'created_at': self.created_at.isoformat() if self.created_at else None,
                'updated_at': self.updated_at.isoformat() if self.updated_at else None,
                'created_by': self.created_by,
                'created_by_name': created_by_name,
                'updated_by': self.updated_by,
                'updated_by_name': updated_by_name,
                'job_reference': job_reference,
            }
        except Exception as e:
            print(f"Error in Assignment.to_dict(): {e}")
            import traceback
            traceback.print_exc()
            return {
                'id': self.id,
                'type': self.type,
                'title': self.title,
                'date': self.date.isoformat() if self.date else None,
                'error': 'Error loading full assignment data'
            }

class FormDocument(Base):
    __tablename__ = 'form_documents'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # FOREIGN KEY: Links to Customer
    customer_id = Column(String(36), ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    
    # File details
    file_name = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=False)
    mime_type = Column(String(100))
    category = Column(String(50), default='form')  # 'excel', 'pdf', 'form'
    
    # Audit
    uploaded_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)

    # relationship
    customer = relationship('Customer', backref='form_documents')
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'filename': self.file_name,
            'url': self.file_url,
            'type': self.category,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'uploaded_by': self.uploaded_by
        }

class MaterialStatus(enum.Enum):
    """Material order status options"""
    NOT_ORDERED = "not_ordered"
    ORDERED = "ordered"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    DELAYED = "delayed"

# Add this MaterialOrder model class
class MaterialOrder(Base):
    """
    Tracks material orders for customer projects
    Links to Customer, Project/Job, and User (who ordered)
    """
    __tablename__ = 'material_orders'
    
    # Primary Key
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Foreign Keys - Link to existing tables
    customer_id = Column(String(36), ForeignKey('customers.id'), nullable=False)
    job_id = Column(String(36), ForeignKey('jobs.id'), nullable=True)
    
    # CRITICAL FIX: Changed from Column(Integer...) to Column(String(36)...) 
    # to match the expected type of projects.id (which is typically a UUID/String).
    project_id = Column(String(36), ForeignKey('projects.id'), nullable=True) 
    
    ordered_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    
    # Material Details
    material_description = Column(Text, nullable=False)
    supplier_name = Column(String(255), nullable=True)
    supplier_reference = Column(String(100), nullable=True)
    
    # Status & Dates
    status = Column(String(20), default='not_ordered', nullable=False)
    order_date = Column(DateTime, nullable=True)
    expected_delivery_date = Column(DateTime, nullable=True)
    actual_delivery_date = Column(DateTime, nullable=True)
    
    # Cost Information
    estimated_cost = Column(Numeric(10, 2), nullable=True)
    actual_cost = Column(Numeric(10, 2), nullable=True)
    
    # Additional Info
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    customer = relationship('Customer', backref='material_orders')
    ordered_by = relationship('User', backref='material_orders_placed', foreign_keys=[ordered_by_user_id])
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'customer_name': self.customer.name if self.customer else None,
            'job_id': self.job_id,
            'project_id': self.project_id,
            'material_description': self.material_description,
            'supplier_name': self.supplier_name,
            'supplier_reference': self.supplier_reference,
            # ✅ CRITICAL FIX: Handle both string and enum cases
            'status': self.status if isinstance(self.status, str) else self.status.value,
            'order_date': self.order_date.isoformat() if self.order_date else None,
            'expected_delivery_date': self.expected_delivery_date.isoformat() if self.expected_delivery_date else None,
            'actual_delivery_date': self.actual_delivery_date.isoformat() if self.actual_delivery_date else None,
            'estimated_cost': float(self.estimated_cost) if self.estimated_cost else None,
            'actual_cost': float(self.actual_cost) if self.actual_cost else None,
            'ordered_by': self.ordered_by.full_name if self.ordered_by else None,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    @property
    def is_modification_safe(self):
        """Returns True if materials haven't been ordered yet"""
        return self.status == MaterialStatus.NOT_ORDERED

# Add this MaterialChangeLog model class
class MaterialChangeLog(Base):
    """
    Audit trail for material order changes
    Tracks who made changes and when
    """
    __tablename__ = 'material_change_logs'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    material_order_id = Column(String(36), ForeignKey('material_orders.id'), nullable=False)
    changed_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    
    change_type = Column(String(50), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    change_description = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    material_order = relationship('MaterialOrder', backref='change_logs')
    changed_by = relationship('User', backref='material_changes_made')
    
    def to_dict(self):
        return {
            'id': self.id,
            'material_order_id': self.material_order_id,
            'changed_by': self.changed_by.username if self.changed_by else None,
            'change_type': self.change_type,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'change_description': self.change_description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class ActionItem(Base):
    __tablename__ = 'action_items'
    
    id = Column(String, primary_key=True)
    customer_id = Column(String, ForeignKey('customers.id'), nullable=False)
    stage = Column(String, nullable=False)  # The stage that triggered this action
    priority = Column(String, default='High')  # High, Medium, Low
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    customer = relationship("Customer", backref="action_items")