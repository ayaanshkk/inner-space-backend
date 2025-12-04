from flask import Blueprint, request, jsonify
from datetime import datetime, date
import uuid
import traceback
from ..models import (
    Job, Customer, Team, Fitter, Salesperson, 
    JobDocument, JobFormLink, FormSubmission, 
    JobNote, Assignment
)
from ..db import SessionLocal
from .auth_helpers import token_required
from sqlalchemy import func

job_bp = Blueprint('jobs', __name__)

def generate_job_reference(session):
    """Generate sequential job reference like AZ-JOB001"""
    # Get the count of existing jobs
    job_count = session.query(Job).count()
    
    # Generate reference with zero-padded number
    reference_number = job_count + 1
    job_reference = f"AZ-JOB{reference_number:03d}"
    
    # Ensure uniqueness (in case of deletions)
    while session.query(Job).filter(Job.job_reference == job_reference).first():
        reference_number += 1
        job_reference = f"AZ-JOB{reference_number:03d}"
    
    return job_reference

def serialize_job(job):
    """Serialize job object to dictionary"""
    return {
        'id': job.id,
        'job_reference': job.job_reference,
        'job_name': job.job_name,
        'customer_id': job.customer_id,
        'customer_name': job.customer.name if job.customer else None,
        'job_type': job.job_type,
        'stage': job.stage,
        'priority': job.priority,
        'measure_date': job.measure_date.isoformat() if job.measure_date else None,
        'delivery_date': job.delivery_date.isoformat() if job.delivery_date else None,
        'completion_date': job.completion_date.isoformat() if job.completion_date else None,
        # 'quote_id': job.quote_id,
        # 'quote_price': float(job.quote_price) if job.quote_price else None,
        'agreed_price': float(job.agreed_price) if job.agreed_price else None,
        'deposit1': float(job.deposit1) if job.deposit1 else None,
        'deposit2': float(job.deposit2) if job.deposit2 else None,
        'deposit_due_date': job.deposit_due_date.isoformat() if job.deposit_due_date else None,
        'installation_address': job.installation_address,
        'assigned_team_id': job.assigned_team_id,
        'assigned_team_name': job.assigned_team_name or (job.assigned_team.name if job.assigned_team else None),
        'primary_fitter_id': job.primary_fitter_id,
        'primary_fitter_name': job.primary_fitter_name or (job.primary_fitter.name if job.primary_fitter else None),
        'salesperson_id': job.salesperson_id,
        'salesperson_name': job.salesperson_name or (job.salesperson.name if job.salesperson else None),
        'notes': job.notes,
        'has_counting_sheet': job.has_counting_sheet,
        'has_schedule': job.has_schedule,
        'has_invoice': job.has_invoice,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
    }

@job_bp.route('/jobs', methods=['GET', 'OPTIONS'])
@token_required
def get_jobs():
    """Get all jobs with optional filtering"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        customer_id = request.args.get('customer_id')
        stage = request.args.get('stage')
        job_type = request.args.get('type')
        
        query = session.query(Job)
        
        if customer_id:
            query = query.filter(Job.customer_id == customer_id)
        if stage:
            query = query.filter(Job.stage == stage)
        if job_type:
            query = query.filter(Job.job_type == job_type)
        
        jobs = query.order_by(Job.created_at.desc()).all()
        
        return jsonify([serialize_job(job) for job in jobs])
    except Exception as e:
        print(f"Error fetching jobs: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_job(job_id):
    """Get a specific job by ID"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        return jsonify(serialize_job(job))
    except Exception as e:
        print(f"Error fetching job {job_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs', methods=['POST'])
@token_required
def create_job():
    """Create a new job"""
    session = SessionLocal()
    try:
        data = request.get_json()
        print("Received data:", data)
        
        # Validate required fields
        required_fields = ['customer_id', 'job_type', 'measure_date', 'completion_date']
        missing_fields = []
        
        for field in required_fields:
            if not data.get(field):
                missing_fields.append(field)
        
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            print("Validation error:", error_msg)
            return jsonify({'error': error_msg}), 400
        
        # Validate customer exists
        customer = session.query(Customer).filter(Customer.id == data['customer_id']).first()
        if not customer:
            return jsonify({'error': 'Customer not found'}), 400
        
        # Generate sequential job reference
        job_reference = generate_job_reference(session)
        print(f"Generated job reference: {job_reference}")
        
        # Parse dates safely
        def parse_date(date_str):
            if date_str:
                try:
                    return datetime.strptime(date_str.split('T')[0], '%Y-%m-%d')
                except ValueError:
                    print(f"Invalid date format: {date_str}")
                    return None
            return None
        
        # Use customer's address as installation address if not provided
        installation_address = data.get('installation_address') or customer.address
        
        # Default priority to Medium if not provided
        priority = data.get('priority', 'Medium')
        
        # Default stage to Lead
        stage = data.get('stage', 'Lead')
        
        job = Job(
            id=str(uuid.uuid4()),
            job_reference=job_reference,
            job_name=data.get('job_name'),
            customer_id=data['customer_id'],
            job_type=data['job_type'],
            stage=stage,
            priority=priority,
            measure_date=parse_date(data.get('measure_date')),
            delivery_date=parse_date(data.get('delivery_date')),
            completion_date=parse_date(data.get('completion_date')),
            # quote_id=data.get('quote_id') if data.get('quote_id') else None,
            # quote_price=data.get('quote_price'),
            agreed_price=data.get('agreed_price'),
            deposit1=data.get('deposit1'),
            deposit2=data.get('deposit2'),
            deposit_due_date=parse_date(data.get('deposit_due_date')),
            installation_address=installation_address,
            assigned_team_id=data.get('assigned_team') if data.get('assigned_team') else None,
            primary_fitter_id=data.get('primary_fitter') if data.get('primary_fitter') else None,
            salesperson_id=data.get('salesperson') if data.get('salesperson') else None,
            assigned_team_name=data.get('team_member'),
            salesperson_name=data.get('salesperson_name') or customer.salesperson,
            notes=data.get('notes', ''),
            has_counting_sheet=data.get('create_counting_sheet', False),
            has_schedule=data.get('create_schedule', False),
            has_invoice=data.get('generate_invoice', False)
        )
        
        session.add(job)
        session.flush()
        
        print(f"✅ Created job with ID: {job.id}, Reference: {job_reference}")
        
        # Create notification
        try:
            from backend.routes.notification_routes import create_activity_notification
            
            user_name = data.get('created_by', 'System')
            job_name_display = data.get('job_name') or f"{data['job_type']} Job"
            
            create_activity_notification(
                session=session,
                message=f"💼 New job created for customer '{customer.name}': {job_name_display} ({data['job_type']}) - Ref: {job_reference}",
                job_id=job.id,
                customer_id=customer.id,
                moved_by=user_name
            )
            
            print(f"✅ Notification created for job {job.id}")
        except ImportError:
            print("⚠️ Warning: Notification function not found.")
        except Exception as notif_error:
            print(f"⚠️ Failed to create notification: {notif_error}")
        
        # Link attached forms
        attached_forms = data.get('attached_forms', [])
        for form_id in attached_forms:
            try:
                form_link = JobFormLink(
                    job_id=job.id,
                    form_submission_id=form_id,
                    linked_by=data.get('created_by', 'System')
                )
                session.add(form_link)
            except Exception as e:
                print(f"Error linking form {form_id}: {e}")
        
        # Create initial note
        if data.get('notes'):
            try:
                initial_note = JobNote(
                    job_id=job.id,
                    content=data['notes'],
                    note_type='general',
                    author=data.get('created_by', 'System')
                )
                session.add(initial_note)
            except Exception as e:
                print(f"Error creating initial note: {e}")
        
        session.commit()
        
        return jsonify(serialize_job(job)), 201
        
    except Exception as e:
        print(f"❌ Error creating job: {str(e)}")
        traceback.print_exc()
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_job(job_id):
    """Update an existing job"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        data = request.get_json()
        
        def parse_date(date_str):
            if date_str:
                try:
                    return datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    return None
            return None
        
        updateable_fields = [
            'job_name', 'job_type', 'stage', 'priority',
            'agreed_price', 'deposit1', 'deposit2', 'installation_address',
            'assigned_team_id', 'primary_fitter_id', 'salesperson_id', 
            'assigned_team_name', 'primary_fitter_name', 'salesperson_name', 'notes'
        ]
        
        for field in updateable_fields:
            if field in data:
                setattr(job, field, data[field])
        
        date_fields = ['measure_date', 'delivery_date', 'completion_date', 'deposit_due_date']
        for field in date_fields:
            if field in data:
                setattr(job, field, parse_date(data[field]))
        
        job.updated_at = datetime.utcnow()
        
        session.commit()
        
        return jsonify(serialize_job(job))
    except Exception as e:
        print(f"Error updating job {job_id}: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_job(job_id):
    """Delete a job and its dependent records"""
    if request.method == 'OPTIONS':
        return jsonify({}), 200
        
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        print(f"Attempting to delete job {job_id} and its dependencies.")

        # Delete dependent records
        session.query(JobNote).filter(JobNote.job_id == job_id).delete(synchronize_session='fetch')
        session.query(JobDocument).filter(JobDocument.job_id == job_id).delete(synchronize_session='fetch')
        session.query(JobFormLink).filter(JobFormLink.job_id == job_id).delete(synchronize_session='fetch')
        session.query(Assignment).filter(Assignment.job_id == job_id).delete(synchronize_session='fetch')

        session.flush()
        
        session.delete(job)
        session.commit()
        
        print(f"✅ Successfully deleted job {job_id}.")
        return jsonify({'message': 'Job deleted successfully'})
        
    except Exception as e:
        traceback.print_exc()
        print(f"❌ Error deleting job {job_id}: {str(e)}")
        session.rollback()
        return jsonify({'error': f"Failed to delete job"}), 500
    finally:
        session.close()

# Keep all other endpoints the same...
@job_bp.route('/jobs/<string:job_id>/notes', methods=['GET'])
def get_job_notes(job_id):
    """Get all notes for a job"""
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        notes = session.query(JobNote).filter(JobNote.job_id == job_id).order_by(JobNote.created_at.desc()).all()
        
        return jsonify([{
            'id': note.id,
            'content': note.content,
            'note_type': note.note_type,
            'author': note.author,
            'created_at': note.created_at.isoformat()
        } for note in notes])
    except Exception as e:
        print(f"Error fetching notes for job {job_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>/notes', methods=['POST'])
def add_job_note(job_id):
    """Add a note to a job"""
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        data = request.get_json()
        
        if not data.get('content'):
            return jsonify({'error': 'Note content is required'}), 400
        
        note = JobNote(
            job_id=job_id,
            content=data['content'],
            note_type=data.get('note_type', 'general'),
            author=data.get('author', 'System')
        )
        
        session.add(note)
        session.commit()
        
        return jsonify({
            'id': note.id,
            'content': note.content,
            'note_type': note.note_type,
            'author': note.author,
            'created_at': note.created_at.isoformat()
        }), 201
    except Exception as e:
        print(f"Error adding note to job {job_id}: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>/documents', methods=['GET'])
def get_job_documents(job_id):
    """Get all documents for a job"""
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        documents = session.query(JobDocument).filter(JobDocument.job_id == job_id).order_by(JobDocument.created_at.desc()).all()
        
        return jsonify([{
            'id': doc.id,
            'filename': doc.filename,
            'original_filename': doc.original_filename,
            'file_size': doc.file_size,
            'mime_type': doc.mime_type,
            'category': doc.category,
            'uploaded_by': doc.uploaded_by,
            'created_at': doc.created_at.isoformat()
        } for doc in documents])
    except Exception as e:
        print(f"Error fetching documents for job {job_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/<string:job_id>/stage', methods=['PATCH'])
def update_job_stage(job_id):
    """Update job stage"""
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            return jsonify({'error': 'Job not found'}), 404
            
        data = request.get_json()
        
        if not data.get('stage'):
            return jsonify({'error': 'Stage is required'}), 400
        
        old_stage = job.stage
        job.stage = data['stage']
        job.updated_at = datetime.utcnow()
        
        stage_note = JobNote(
            job_id=job_id,
            content=f'Stage changed from "{old_stage}" to "{data["stage"]}"',
            note_type='system',
            author=data.get('updated_by', 'System')
        )
        session.add(stage_note)
        
        session.commit()
        
        return jsonify(serialize_job(job))
    except Exception as e:
        print(f"Error updating stage for job {job_id}: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/teams', methods=['GET'])
def get_teams():
    """Get all active teams"""
    session = SessionLocal()
    try:
        teams = session.query(Team).filter(Team.active == True).order_by(Team.name).all()
        return jsonify([{
            'id': team.id,
            'name': team.name,
            'specialty': team.specialty
        } for team in teams])
    except Exception as e:
        print(f"Error fetching teams: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/fitters', methods=['GET'])
def get_fitters():
    """Get all active fitters"""
    session = SessionLocal()
    try:
        fitters = session.query(Fitter).filter(Fitter.active == True).order_by(Fitter.name).all()
        return jsonify([{
            'id': fitter.id,
            'name': fitter.name,
            'team_id': fitter.team_id,
            'team_name': fitter.team.name if fitter.team else None
        } for fitter in fitters])
    except Exception as e:
        print(f"Error fetching fitters: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/salespeople', methods=['GET'])
def get_salespeople():
    """Get all active salespeople"""
    session = SessionLocal()
    try:
        salespeople = session.query(Salesperson).filter(Salesperson.active == True).order_by(Salesperson.name).all()
        return jsonify([{
            'id': person.id,
            'name': person.name,
            'email': person.email
        } for person in salespeople])
    except Exception as e:
        print(f"Error fetching salespeople: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/forms/unlinked', methods=['GET'])
def get_unlinked_forms():
    """Get form submissions not linked to any job"""
    session = SessionLocal()
    try:
        customer_id = request.args.get('customer_id')
        
        linked_form_ids = session.query(JobFormLink.form_submission_id).subquery()
        
        query = session.query(FormSubmission).filter(
            ~FormSubmission.id.in_(linked_form_ids)
        )
        
        if customer_id:
            query = query.filter(FormSubmission.customer_id == customer_id)
        
        forms = query.order_by(FormSubmission.submitted_at.desc()).all()
        
        return jsonify([{
            'id': form.id,
            'customer_id': form.customer_id,
            'submitted_at': form.submitted_at.isoformat(),
            'processed': form.processed,
            'source': form.source
        } for form in forms])
    except Exception as e:
        print(f"Error fetching unlinked forms: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@job_bp.route('/jobs/stats', methods=['GET'])
def get_job_stats():
    """Get job statistics"""
    session = SessionLocal()
    try:
        stats = {
            'total_jobs': session.query(Job).count(),
            'by_stage': {},
            'by_type': {},
            'by_priority': {}
        }
        
        stage_counts = session.query(
            Job.stage, 
            func.count(Job.id)
        ).group_by(Job.stage).all()
        
        for stage, count in stage_counts:
            stats['by_stage'][stage] = count
        
        type_counts = session.query(
            Job.job_type, 
            func.count(Job.id)
        ).group_by(Job.job_type).all()
        
        for job_type, count in type_counts:
            stats['by_type'][job_type] = count
        
        priority_counts = session.query(
            Job.priority, 
            func.count(Job.id)
        ).group_by(Job.priority).all()
        
        for priority, count in priority_counts:
            stats['by_priority'][priority] = count
        
        return jsonify(stats)
    except Exception as e:
        print(f"Error fetching job stats: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()