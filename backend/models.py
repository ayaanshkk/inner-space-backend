"""
Complete Models File - InnerSpace Interiors CRM
Contains both legacy auth models (User) and StreemLyne_MT schema models
"""

import uuid
import secrets
from datetime import datetime, timedelta
from sqlalchemy import (
    Column, Integer, SmallInteger, String, Boolean, DateTime, Date, 
    ForeignKey, Text, Float, Numeric
)
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash

from backend.db import Base

# ==========================================
# LEGACY AUTH MODELS
# ==========================================

class User(Base):
    """Legacy local auth user model"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(50), nullable=True)
    role = Column(String(50), nullable=False, default='Staff')
    department = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    reset_token = Column(String(255), nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    verification_token = Column(String(255), nullable=True)
    is_invited = Column(Boolean, default=False)
    invitation_token = Column(String(255), nullable=True)
    invited_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f'<User {self.email}>'

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
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
            'is_invited': self.is_invited,
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


# ==========================================
# CRM AUTH MODEL
# ==========================================

class UserMaster(Base):
    """CRM User Master (StreemLyne_MT.User_Master)"""
    __tablename__ = 'User_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    user_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    employee_id = Column(SmallInteger, nullable=True, index=True)
    user_name = Column(String(255), nullable=True)
    password = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<UserMaster {self.user_id} {self.user_name}>"

    @property
    def is_active(self) -> bool:
        return True

    @property
    def id(self):
        return self.employee_id

    def check_password(self, password: str) -> bool:
        return self.password == password if self.password else False

    @property
    def roles(self):
        return []

    def to_dict(self) -> dict:
        return {
            'user_id': self.user_id,
            'employee_id': self.employee_id,
            'user_name': self.user_name,
            'role': getattr(self, 'role', None),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active,
        }


# ==========================================
# CRM MODELS (StreemLyne_MT Schema)
# ==========================================

SCHEMA = 'StreemLyne_MT'


class Tenant_Master(Base):
    __tablename__ = 'Tenant_Master'
    __table_args__ = {'schema': SCHEMA}
    
    tenant_id = Column('tenant_id', SmallInteger, primary_key=True, autoincrement=True)
    tenant_company_name = Column(String(255))
    tenant_contact_name = Column(String(255))
    onboarding_Date = Column('onboarding_Date', Date)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class Employee_Master(Base):
    __tablename__ = 'Employee_Master'
    __table_args__ = {'schema': SCHEMA}
    
    employee_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)
    employee_name = Column(String(255))
    employee_designation_id = Column(SmallInteger)
    phone = Column(String(50))
    email = Column(String(255))
    date_of_birth = Column(Date)
    date_of_joining = Column(Date)
    id_type = Column(String(50))
    id_number = Column(String(100))
    role_ids = Column(String(255))
    created_on = Column(DateTime)
    updated_on = Column(DateTime)
    commission_percentage = Column(Float)


class Client_Master(Base):
    __tablename__ = 'Client_Master'
    __table_args__ = {'schema': SCHEMA}    
    
    client_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_client_id = Column(SmallInteger, nullable=True)
    tenant_id = Column(SmallInteger, nullable=True)
    display_id = Column(Integer, nullable=True)
    assigned_employee_id = Column(SmallInteger, nullable=True)
    client_company_name = Column(String(255))
    client_contact_name = Column(String(255))
    address = Column(String(500))
    country_id = Column(SmallInteger)
    post_code = Column(String(20))
    client_phone = Column(String(50))
    client_mobile = Column(String(50), nullable=True)
    client_email = Column(String(255))
    client_website = Column(String(255))
    default_currency_id = Column(SmallInteger)
    created_at = Column(DateTime)
    position = Column(String(100))
    company_number = Column(String(50))
    date_of_birth = Column(Date)
    charity_ltd_company_number = Column(String(50))
    partner_details = Column(Text)
    bank_name = Column(String(255))
    account_number = Column(String(50))
    sort_code = Column(String(20))
    home_door_number = Column(String(20))
    home_street = Column(String(255))
    partner_dob = Column(Date)
    credit_score = Column(Integer)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_reason = Column(String(100), nullable=True)
    is_archived = Column(Boolean, default=False)
    archived_at = Column(DateTime)
    archived_reason = Column(String(255))
    display_order = Column(Integer, nullable=True)
    is_allocated = Column(Boolean, default=False, nullable=True)


class Opportunity_Details(Base):
    """
    Opportunity/Job tracking for InnerSpace Interiors
    Maps to kitchen/bedroom installation projects
    """
    __tablename__ = 'Opportunity_Details'
    __table_args__ = {'schema': SCHEMA}
    
    # Core fields
    opportunity_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(SmallInteger, nullable=True)
    client_id = Column(SmallInteger, nullable=True)
    opportunity_title = Column(String(255))
    opportunity_description = Column(Text)
    opportunity_date = Column(Date)
    opportunity_owner_employee_id = Column(SmallInteger, nullable=True)
    stage_id = Column(SmallInteger, nullable=True)
    opportunity_value = Column(Numeric(10, 2))
    currency_id = Column(SmallInteger)
    created_at = Column(DateTime)
    
    # Project details
    project_type = Column(String(50), nullable=True)  # 'Kitchen', 'Bedroom', 'Wardrobe'
    installation_address = Column(String(500), nullable=True)
    postcode = Column(String(20), nullable=True)
    
    # Dates
    measure_date = Column(Date, nullable=True)
    delivery_date = Column(Date, nullable=True)
    installation_date = Column(Date, nullable=True)
    completion_date = Column(Date, nullable=True)
    
    # Pricing
    quote_price = Column(Numeric(10, 2), nullable=True)
    agreed_price = Column(Numeric(10, 2), nullable=True)
    deposit_amount = Column(Numeric(10, 2), nullable=True)
    
    # Team assignments
    assigned_employee_id = Column(SmallInteger, nullable=True)
    fitter_team = Column(String(255), nullable=True)
    
    # Status tracking
    is_allocated = Column(Boolean, default=False, nullable=True)
    notes = Column(Text, nullable=True)
    deleted_at = Column(DateTime, nullable=True)


class Client_Interactions(Base):
    __tablename__ = 'Client_Interactions'
    __table_args__ = {'schema': SCHEMA}
    
    interaction_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    client_id = Column(SmallInteger, nullable=True)
    contact_date = Column(Date)
    contact_method = Column(SmallInteger)
    notes = Column(String(1000))
    next_steps = Column(String(500))
    reminder_date = Column(Date)
    created_at = Column(DateTime)


class Stage_Master(Base):
    __tablename__ = 'Stage_Master'
    __table_args__ = {'schema': SCHEMA}
    
    stage_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    stage_name = Column(String(100))
    stage_description = Column(String(255))
    preceding_stage_id = Column(SmallInteger)
    stage_type = Column(SmallInteger)


class Role_Master(Base):
    __tablename__ = 'Role_Master'
    __table_args__ = {'schema': SCHEMA}
    
    role_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    role_name = Column(String(100))
    role_description = Column(String(255))
    is_system = Column(Boolean)
    created_at = Column(DateTime)


class User_Role_Mapping(Base):
    __tablename__ = 'User_Role_Mapping'
    __table_args__ = {'schema': SCHEMA}
    
    user_role_mapping_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    user_id = Column(SmallInteger)
    role_id = Column(SmallInteger)


class Currency_Master(Base):
    __tablename__ = 'Currency_Master'
    __table_args__ = {'schema': SCHEMA}
    
    currency_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    currency_name = Column(String(100))
    currency_code = Column(String(10))
    created_at = Column(DateTime)


class Country_Master(Base):
    __tablename__ = 'Country_Master'
    __table_args__ = {'schema': SCHEMA}
    
    country_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    country_name = Column(String(100))
    country_isd_code = Column(String(10))
    created_at = Column(DateTime)


class Notification_Master(Base):
    """
    Notification system for InnerSpace Interiors
    Tracks activity notifications, tasks, and alerts
    """
    __tablename__ = 'Notification_Master'
    __table_args__ = {'schema': SCHEMA}
    
    notification_id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=False)
    employee_id = Column(Integer, nullable=True)
    client_id = Column(Integer, nullable=True)
    contract_id = Column(Integer, nullable=True)  # Maps to opportunity_id
    property_id = Column(Integer, nullable=True)
    
    notification_type = Column(String(50), nullable=False)  # 'activity', 'task', 'alert'
    priority = Column(String(20), nullable=False, default='medium')  # 'high', 'medium', 'low'
    message = Column(Text, nullable=False)
    
    read = Column(Boolean, default=False, nullable=False)
    dismissed = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)


class Customer_Documents(Base):
    """
    Document storage for customer files
    Includes drawings, forms, contracts, etc.
    """
    __tablename__ = 'Customer_Documents'
    __table_args__ = {'schema': SCHEMA}
    
    document_id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=False)
    client_id = Column(Integer, nullable=True)
    contract_id = Column(Integer, nullable=True)  # opportunity_id
    
    document_name = Column(String(255), nullable=False)
    document_type = Column(String(50), nullable=True)  # 'drawing', 'form', 'contract', 'invoice'
    file_path = Column(String(500), nullable=False)
    file_url = Column(String(500), nullable=True)
    mime_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    
    uploaded_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Drawing_Cutting_List(Base):
    """
    Cutting list items extracted from drawings
    For kitchen/bedroom cabinet manufacturing
    """
    __tablename__ = 'Drawing_Cutting_List'
    __table_args__ = {'schema': SCHEMA}
    
    cutting_list_id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey('StreemLyne_MT.Customer_Documents.document_id'), nullable=True)
    tenant_id = Column(Integer, nullable=False)
    client_id = Column(Integer, nullable=True)
    
    # Component details
    component_type = Column(String(100), nullable=False)  # 'GABLE', 'T/B', 'SHELF', 'DOOR'
    part_name = Column(String(200), nullable=False)
    cabinet_id = Column(String(100), nullable=True)
    
    # Dimensions (mm)
    overall_unit_width = Column(Integer, nullable=True)
    component_width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    depth = Column(Integer, nullable=True)
    quantity = Column(Integer, default=1)
    material_thickness = Column(Integer, default=18)
    
    # Additional info
    edge_banding_notes = Column(String(255), nullable=True)
    area_m2 = Column(Numeric(10, 4), nullable=True)
    section_index = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


# ==========================================
# LEGACY CUSTOMER MODEL (for backwards compatibility)
# ==========================================

class Customer(Base):
    """Legacy customer model - kept for backwards compatibility"""
    __tablename__ = 'customers'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    phone = Column(String(50))
    email = Column(String(200))
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'address': self.address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }