import sys, os
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(PROJECT_ROOT)

# Remove accidental aztec_interiors path
sys.path = [p for p in sys.path if "aztec_interiors" not in p.lower()]

# Ensure correct backend root is first
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from dotenv import load_dotenv
from .db import Base, engine, SessionLocal
from sqlalchemy import inspect

load_dotenv()


def create_app():
    app = Flask(__name__)

    # ============================================
    # CONFIG
    # ============================================
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # ============================================
    # ⚙️ DATABASE INITIALIZATION
    # ============================================
    print("🔧 Initializing database schema...")
    try:
        from backend import models
        
        Base.metadata.create_all(bind=engine, checkfirst=True)
        
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"✅ Database schema initialized - {len(tables)} tables exist")
        
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        import traceback
        traceback.print_exc()

    # ============================================
    # CORS - Production Ready
    # ============================================
    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=False,
    )

    # ============================================
    # PREFLIGHT HANDLER
    # ============================================
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            resp = jsonify({"status": "ok"})
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "*"
            return resp, 200

    # ============================================
    # AFTER-REQUEST HEADERS
    # ============================================
    @app.after_request
    def add_cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    # ============================================
    # ❌ MOCK AUTH REMOVED - Using Real JWT Auth
    # ============================================
    # The @token_required decorator in auth_routes.py handles authentication

    # ============================================
    # BLUEPRINTS
    # ============================================
    from backend.routes import (
        auth_routes, db_routes,
        notification_routes, assignment_routes,
        customer_routes, file_routes, materials_routes, 
        job_routes, action_items_routes, manual_entry_routes, 
        analysis_routes
    )

    app.register_blueprint(auth_routes.auth_bp)
    app.register_blueprint(customer_routes.customer_bp)
    app.register_blueprint(db_routes.db_bp)
    app.register_blueprint(notification_routes.notification_bp)
    app.register_blueprint(assignment_routes.assignment_bp)
    app.register_blueprint(file_routes.file_bp)
    app.register_blueprint(materials_routes.materials_bp)
    app.register_blueprint(job_routes.job_bp)
    app.register_blueprint(action_items_routes.action_items_bp)
    app.register_blueprint(manual_entry_routes.manual_entry_bp)
    app.register_blueprint(analysis_routes.analysis_bp)
    

    # ============================================
    # HEALTH CHECK
    # ============================================
    @app.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "ok", "message": "Server is running"}), 200
    
    # ============================================
    # PUBLIC TEST ENDPOINT
    # ============================================
    @app.route("/api/test", methods=["GET"])
    def test_endpoint():
        return jsonify({
            "status": "ok",
            "message": "API is working",
            "auth": "JWT authentication enabled - use /auth/login"
        }), 200

    return app

# ============================================
# STANDALONE LAUNCH
# ============================================
if __name__ == "__main__":
    app = create_app()

    print("=" * 60)
    print("🔧 INITIALISING DATABASE...")
    print("=" * 60)

    from backend import models

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\n📋 {len(tables)} tables detected:")
    for t in tables:
        print(f"   ✓ {t}")

    print("\n✅ Database initialised successfully!\n")
    print("=" * 60)

    port = int(os.getenv("PORT", 5000))
    debug_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    
    print(f"🚀 Starting Flask on port {port}")
    print(f"🔐 JWT Authentication ENABLED")
    print(f"🔑 Login at: POST /auth/login")
    print(f"📝 Register at: POST /auth/register")
    print("=" * 60)
    
    app.run(debug=debug_mode, host="0.0.0.0", port=port, threaded=True)