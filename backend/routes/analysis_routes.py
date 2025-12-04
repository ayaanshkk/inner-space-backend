from flask import Blueprint, request, jsonify, current_app, Response
from datetime import datetime
import base64
import os
import json
import logging

# Initialize logger first (before any imports that might fail)
logger = logging.getLogger('AnalysisRoutes')

# Import the core analysis logic
DrawingAnalyzer = None
analyzer = None

try:
    from ..drawing_analyzer_logic import DrawingAnalyzer as DA
    DrawingAnalyzer = DA
    logger.info("✅ DrawingAnalyzer imported successfully")
    
    # Try to create an instance
    try:
        analyzer = DrawingAnalyzer()
        logger.info("✅ DrawingAnalyzer instance created successfully")
    except Exception as init_error:
        logger.error(f"❌ Failed to initialize DrawingAnalyzer: {init_error}")
        analyzer = None
        
except ImportError as e:
    logger.error(f"❌ FATAL: Could not import DrawingAnalyzer logic. Missing dependencies? Error: {e}")
    import traceback
    traceback.print_exc()
    
    # Create a dummy analyzer class so the app doesn't crash
    class DummyAnalyzer:
        def __init__(self):
            self.BACK_WIDTH_OFFSET = 36
            self.TOP_DEPTH_OFFSET = 30
            self.SHELF_DEPTH_OFFSET = 70
            self.THICKNESS = 18
            self.LEG_HEIGHT_DEDUCTION = 100
            self.COUNTERTOP_DEDUCTION = 25
            self.vision_client = None
        
        def set_offsets(self, **kwargs):
            pass
        
        def analyze_technical_drawing(self, contents):
            raise NotImplementedError("DrawingAnalyzer not properly imported - check dependencies (ezdxf, google-cloud-vision, etc.)")
        
        def generate_dxf(self):
            return None
    
    DrawingAnalyzer = DummyAnalyzer
    analyzer = None

# Initialize the Blueprint
analysis_bp = Blueprint('analysis', __name__)


@analysis_bp.route('/analysis/health', methods=['GET'])
def health_check():
    """Health check for the analysis service and its dependencies"""
    return jsonify({
        "status": "healthy" if analyzer else "degraded",
        "timestamp": datetime.now().isoformat(),
        "analyzer_loaded": analyzer is not None,
        "api_status": {
            "google_vision": "configured" if (analyzer and hasattr(analyzer, 'vision_client') and analyzer.vision_client) else "not_configured",
            "openai": "configured" if os.getenv("OPENAI_API_KEY") else "not_configured"
        }
    }), 200 if analyzer else 503


@analysis_bp.route('/analysis/config', methods=['GET'])
def get_default_config():
    """Get default configuration values"""
    if not analyzer:
        return jsonify({
            "error": "DrawingAnalyzer not initialized",
            "message": "Check server logs for import errors. Required dependencies: ezdxf, google-cloud-vision, openai"
        }), 500
    
    return jsonify({
        "back_width_offset": analyzer.BACK_WIDTH_OFFSET,
        "top_depth_offset": analyzer.TOP_DEPTH_OFFSET,
        "shelf_depth_offset": analyzer.SHELF_DEPTH_OFFSET,
        "thickness": analyzer.THICKNESS,
        "leg_height_deduction": analyzer.LEG_HEIGHT_DEDUCTION,
        "countertop_deduction": analyzer.COUNTERTOP_DEDUCTION,
        "description": "Default kitchen cabinet configuration values"
    }), 200


@analysis_bp.route('/analysis/analyze', methods=['POST', 'OPTIONS'])
def analyze_drawing():
    """
    Analyze a kitchen cabinet technical drawing and generate cutting list
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    try:
        # Check if analyzer is available
        if not analyzer:
            return jsonify({
                "success": False, 
                "error": "DrawingAnalyzer not initialized. Check server logs for import errors.",
                "message": "Required dependencies may be missing: ezdxf, google-cloud-vision, openai"
            }), 500

        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file part in the request"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "error": "No file selected for upload"}), 400
        
        # Check file type
        if not file.content_type.startswith('image/') and file.content_type not in ['application/pdf']:
             return jsonify({"success": False, "error": "File must be an image or PDF"}), 400
        
        # Read file contents
        contents = file.read()
        
        if len(contents) == 0:
            return jsonify({"success": False, "error": "Empty file uploaded"}), 400
        
        # Get optional parameters from form data, converting to int
        data = request.form
        
        # Helper to safely get and convert form data to int
        def safe_get_int(key, default_value):
            try:
                return int(data.get(key, default_value))
            except ValueError:
                return default_value

        back_width_offset = safe_get_int('back_width_offset', analyzer.BACK_WIDTH_OFFSET)
        top_depth_offset = safe_get_int('top_depth_offset', analyzer.TOP_DEPTH_OFFSET)
        shelf_depth_offset = safe_get_int('shelf_depth_offset', analyzer.SHELF_DEPTH_OFFSET)
        thickness = safe_get_int('thickness', analyzer.THICKNESS)
        leg_height_deduction = safe_get_int('leg_height_deduction', analyzer.LEG_HEIGHT_DEDUCTION)
        countertop_deduction = safe_get_int('countertop_deduction', analyzer.COUNTERTOP_DEDUCTION)

        # Configure analyzer with custom offsets
        analyzer.set_offsets(
            back_width_offset=back_width_offset,
            top_depth_offset=top_depth_offset,
            shelf_depth_offset=shelf_depth_offset,
            thickness=thickness,
            leg_height_deduction=leg_height_deduction,
            countertop_deduction=countertop_deduction
        )
        
        current_app.logger.info(f"Starting analysis for file: {file.filename}")
        
        # Run the analysis
        results = analyzer.analyze_technical_drawing(contents)
        
        if not results or sum(cat.get('total_pieces', 0) for cat in results.values()) == 0:
             # Check if analysis failed completely
             raise Exception("Unable to extract measurements from the drawing. Please ensure the image is clear, contains visible dimensions, and is a technical drawing of a kitchen cabinet.")
        
        # Generate DXF file
        dxf_content = analyzer.generate_dxf()
        
        # Calculate summary statistics
        total_pieces = sum(cat.get('total_pieces', 0) for cat in results.values())
        total_area = sum(cat.get('total_area', 0) for cat in results.values())
        categories_with_items = len([c for c in results.values() if c.get('total_pieces', 0) > 0])
        
        # Convert DXF to base64 for transmission
        dxf_base64 = base64.b64encode(dxf_content.encode('utf-8')).decode('utf-8') if dxf_content else None
        
        # Prepare response
        response_data = {
            "success": True,
            "filename": file.filename,
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_pieces": total_pieces,
                "total_area": round(total_area, 2),
                "categories": categories_with_items
            },
            "results": results,
            "dxf_content": dxf_base64,
            "configuration": {
                "back_width_offset": back_width_offset,
                "top_depth_offset": top_depth_offset,
                "shelf_depth_offset": shelf_depth_offset,
                "thickness": thickness,
                "leg_height_deduction": leg_height_deduction,
                "countertop_deduction": countertop_deduction,
                "total_height_deduction": leg_height_deduction + countertop_deduction
            }
        }
        
        current_app.logger.info(f"Analysis completed successfully for {file.filename}: {total_pieces} pieces generated")
        return jsonify(response_data), 200
        
    except Exception as e:
        current_app.logger.error(f"Analysis failed for {getattr(file, 'filename', 'unknown file')}: {str(e)}", exc_info=True)
        
        # Provide more helpful error messages based on the exception
        error_message = str(e)
        user_message = "Analysis failed. Please try again."
        
        # Check for specific error patterns
        if 'timeout' in error_message.lower() or 'timed out' in error_message.lower():
            user_message = "Analysis timed out. The AI service took too long to respond. Please try again with a clearer image or check your internet connection."
        elif 'api key' in error_message.lower() or 'authentication' in error_message.lower():
            user_message = "API keys are not configured properly. Please contact the administrator to set up Google Cloud Vision and OpenAI API keys."
        elif 'unable to extract' in error_message.lower() or 'no valid cutting list' in error_message.lower():
            user_message = error_message  # Use the detailed message we created
        elif 'connection' in error_message.lower():
            user_message = "Failed to connect to AI services. Please check your internet connection and try again."
        
        return jsonify(
            {
                "success": False,
                "error": error_message,
                "message": user_message,
                "timestamp": datetime.now().isoformat()
            }
        ), 500