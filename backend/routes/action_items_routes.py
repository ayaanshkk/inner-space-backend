from flask import Blueprint, request, jsonify
from datetime import datetime
import uuid
from ..models import ActionItem, Customer
from ..db import SessionLocal
from .auth_helpers import token_required

action_items_bp = Blueprint('action_items', __name__)

@action_items_bp.route('/action-items', methods=['GET'])
@token_required
def get_action_items():
    """Get all pending action items"""
    session = SessionLocal()
    try:
        # Get all incomplete action items
        action_items = session.query(ActionItem).filter(
            ActionItem.completed == False
        ).order_by(ActionItem.created_at.desc()).all()
        
        return jsonify([{
            'id': item.id,
            'customer_name': item.customer.name if item.customer else 'Unknown',
            'customer_id': item.customer_id,
            'stage': item.stage,
            'priority': item.priority,
            'created_at': item.created_at.isoformat(),
            'completed': item.completed
        } for item in action_items])
    except Exception as e:
        print(f"Error fetching action items: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@action_items_bp.route('/action-items/<string:action_id>/complete', methods=['PATCH'])
@token_required
def complete_action_item(action_id):
    """Mark an action item as completed"""
    session = SessionLocal()
    try:
        action_item = session.query(ActionItem).filter(ActionItem.id == action_id).first()
        if not action_item:
            return jsonify({'error': 'Action item not found'}), 404
        
        action_item.completed = True
        action_item.completed_at = datetime.utcnow()
        session.commit()
        
        return jsonify({'message': 'Action item marked as completed'})
    except Exception as e:
        print(f"Error completing action item: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@action_items_bp.route('/action-items', methods=['POST'])
def create_action_item():
    """Create a new action item (called automatically when customer moves to Accepted)"""
    session = SessionLocal()
    try:
        data = request.get_json()
        
        # Check if action item already exists for this customer
        existing = session.query(ActionItem).filter(
            ActionItem.customer_id == data['customer_id'],
            ActionItem.stage == 'Accepted',
            ActionItem.completed == False
        ).first()
        
        if existing:
            return jsonify({'message': 'Action item already exists'}), 200
        
        action_item = ActionItem(
            id=str(uuid.uuid4()),
            customer_id=data['customer_id'],
            stage='Accepted',
            priority='High',
            completed=False
        )
        
        session.add(action_item)
        session.commit()
        
        return jsonify({'message': 'Action item created successfully'}), 201
    except Exception as e:
        print(f"Error creating action item: {str(e)}")
        session.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()