from flask import Blueprint, request, jsonify
from datetime import datetime
from ..models import User, Assignment, Job, Customer
from .auth_routes import token_required
from ..db import SessionLocal

assignment_bp = Blueprint('assignments', __name__)

@assignment_bp.route('/assignments', methods=['GET', 'POST'])
@token_required
def handle_assignments():
    current_user = request.current_user
    
    if request.method == 'POST':
        data = request.json
        session = SessionLocal()
        
        try:
            # Parse date
            assignment_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            
            # Parse times if provided
            start_time = None
            end_time = None
            if data.get('start_time'):
                start_time = datetime.strptime(data['start_time'], '%H:%M').time()
            if data.get('end_time'):
                end_time = datetime.strptime(data['end_time'], '%H:%M').time()
            
            # Calculate hours
            estimated_hours = data.get('estimated_hours')
            if isinstance(estimated_hours, str):
                estimated_hours = float(estimated_hours) if estimated_hours else None

            user_id = data.get('user_id')
            team_member_name = None
            if user_id:
                assigned_user = session.get(User, user_id) 
                if assigned_user:
                    team_member_name = assigned_user.full_name
                
            # Create assignment
            assignment = Assignment(
                type=data.get('type', 'job'),
                title=data.get('title', ''),
                date=assignment_date,
                user_id=data.get('user_id'),
                team_member=team_member_name,
                created_by=current_user.id,
                job_id=data.get('job_id'),
                customer_id=data.get('customer_id'),
                start_time=start_time,
                end_time=end_time,
                estimated_hours=estimated_hours,
                notes=data.get('notes', ''),
                priority=data.get('priority', 'Medium'),
                status=data.get('status', 'Scheduled'),
                job_type=data.get('job_type')  # ✅ ADD THIS LINE
            )
            
            session.add(assignment)
            session.commit()

            return jsonify({
                'message': 'Assignment created successfully',
                'assignment': assignment.to_dict()
            }), 201

        except Exception as e:
            session.rollback()
            return jsonify({'error': str(e)}), 400
        finally:
            session.close()
    
    # GET
    if request.method == 'GET':
        session = SessionLocal()
        try:
            current_user_id = request.current_user.id
            
            query = session.query(Assignment)

            if current_user.role != 'Manager':
                query = query.filter(Assignment.user_id == current_user_id)
            
            assignments = query.order_by(Assignment.date.desc()).all()

            return jsonify([a.to_dict() for a in assignments])
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()


@assignment_bp.route('/assignments/<string:assignment_id>', methods=['GET', 'PUT', 'DELETE'])
@token_required
def handle_single_assignment(assignment_id):
    current_user = request.current_user
    
    session = SessionLocal()
    assignment = None
    try:
        assignment = session.get(Assignment, assignment_id) 
        
        if not assignment:
            return jsonify({'error': 'Assignment not found'}), 404
        
        # Authorization Check
        if request.method in ['PUT', 'DELETE', 'GET']:
            is_manager = current_user.role == 'Manager'
            is_assigned_user = assignment.user_id == current_user.id
            
            if not is_manager and not is_assigned_user:
                if request.method == 'PUT' and list(request.json.keys()) == ['status']:
                    pass 
                else:
                    return jsonify({'error': 'Unauthorized access to assignment'}), 403
        
        # GET
        if request.method == 'GET':
            return jsonify(assignment.to_dict())
        
        # PUT
        elif request.method == 'PUT':
            data = request.json
            
            if 'type' in data:
                assignment.type = data['type']
            if 'title' in data:
                assignment.title = data['title']
            if 'date' in data:
                assignment.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
            if 'start_time' in data:
                assignment.start_time = datetime.strptime(data['start_time'], '%H:%M').time() if data['start_time'] else None
            if 'end_time' in data:
                assignment.end_time = datetime.strptime(data['end_time'], '%H:%M').time() if data['end_time'] else None
            if 'estimated_hours' in data:
                estimated_hours = data['estimated_hours']
                assignment.estimated_hours = float(estimated_hours) if isinstance(estimated_hours, str) else estimated_hours
            if 'notes' in data:
                assignment.notes = data['notes']
            if 'priority' in data:
                assignment.priority = data['priority']
            if 'status' in data:
                assignment.status = data['status']
            if 'job_type' in data:  # ✅ ADD THIS
                assignment.job_type = data['job_type']
            if 'user_id' in data:
                assignment.user_id = data['user_id']
                new_user = session.get(User, data['user_id'])
                if new_user:
                    assignment.team_member = new_user.full_name
                
            assignment.updated_by = current_user.id
            assignment.updated_at = datetime.utcnow()
            
            session.commit()
            
            return jsonify({
                'message': 'Assignment updated successfully',
                'assignment': assignment.to_dict()
            })
            
        # DELETE
        elif request.method == 'DELETE':
            session.delete(assignment)
            session.commit()
            
            return jsonify({'message': 'Assignment deleted successfully'})
        
    except Exception as e:
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@assignment_bp.route('/assignments/by-date-range', methods=['GET'])
@token_required 
def get_assignments_by_date_range():
    """Get assignments within a date range"""
    current_user = request.current_user
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date or not end_date:
        return jsonify({'error': 'start_date and end_date are required'}), 400
    
    session = SessionLocal()
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        query = session.query(Assignment).filter(
            Assignment.date >= start,
            Assignment.date <= end
        )
        
        if current_user.role != 'Manager':
            query = query.filter(Assignment.user_id == current_user.id)
            
        assignments = query.order_by(Assignment.date).all()
        
        return jsonify([a.to_dict() for a in assignments])
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    finally:
        session.close()


@assignment_bp.route('/jobs/available', methods=['GET'])
@token_required 
def get_available_jobs():
    """Get jobs that are ready to be scheduled"""
    session = SessionLocal()
    try:
        jobs = session.query(Job).filter(
            Job.stage.in_(['ready', 'in_progress', 'confirmed', 'Accepted', 'Production'])
        ).order_by(Job.created_at.desc()).all()
        
        return jsonify([{
            'id': j.id,
            'job_reference': j.job_reference,
            'customer_name': j.customer.name if j.customer else 'Unknown', 
            'customer_id': j.customer_id,
            'job_type': j.job_type or 'Interior Design',
            'stage': j.stage
        } for j in jobs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@assignment_bp.route('/customers/active', methods=['GET'])
@token_required 
def get_active_customers():
    """Get active customers"""
    session = SessionLocal()
    try:
        customers = session.query(Customer).filter(
            Customer.status == 'Active'
        ).order_by(Customer.name).all()
        
        return jsonify([{
            'id': c.id,
            'name': c.name,
            'address': c.address,
            'phone': c.phone,
            'stage': c.stage
        } for c in customers])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()