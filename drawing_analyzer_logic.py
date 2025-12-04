import os
import ezdxf
import json
import requests
import logging
import re
from datetime import datetime
from io import StringIO, BytesIO
from google.cloud import vision
from google.oauth2 import service_account
from google.protobuf.json_format import MessageToDict
from dotenv import load_dotenv
import base64

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger('DrawingAnalyzer')
logger.setLevel(logging.INFO) # Set to INFO by default

# API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
GOOGLE_CLOUD_CREDENTIALS = os.getenv("GOOGLE_CLOUD_CREDENTIALS")

class DrawingAnalyzer:
    def __init__(self):
        # Configurable offsets
        self.BACK_WIDTH_OFFSET = 36
        self.TOP_DEPTH_OFFSET = 30
        self.SHELF_DEPTH_OFFSET = 70
        self.THICKNESS = 18
        self.LEG_HEIGHT_DEDUCTION = 100
        self.COUNTERTOP_DEDUCTION = 25
        
        self.components = {
            'GABLE': [],
            'T/B & FIX SHELVES': [],
            'BACKS': [],
            'S/H': []
        }
        self.part_counters = {
            'GABLE': 1,
            'T/B & FIX SHELVES': 1,
            'BACKS': 1,
            'S/H': 1
        }
        
        self.vision_client = self._init_google_vision_client()
    
    def _init_google_vision_client(self):
        try:
            if GOOGLE_CLOUD_CREDENTIALS and GOOGLE_CLOUD_CREDENTIALS.strip().startswith('{'):
                logger.debug("Initializing Google Vision client from inline JSON credentials.")
                creds_dict = json.loads(GOOGLE_CLOUD_CREDENTIALS)
                credentials = service_account.Credentials.from_service_account_info(creds_dict)
                client = vision.ImageAnnotatorClient(credentials=credentials)
                logger.info("Google Vision client initialized from inline JSON credentials.")
                return client

            if GOOGLE_CLOUD_CREDENTIALS and os.path.exists(GOOGLE_CLOUD_CREDENTIALS):
                logger.debug("Initializing Google Vision client from credentials file path.")
                with open(GOOGLE_CLOUD_CREDENTIALS, 'r', encoding='utf-8') as fh:
                    creds_dict = json.load(fh)
                credentials = service_account.Credentials.from_service_account_info(creds_dict)
                client = vision.ImageAnnotatorClient(credentials=credentials)
                logger.info("Google Vision client initialized from JSON file.")
                return client

            if os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
                logger.debug("GOOGLE_APPLICATION_CREDENTIALS detected.")
                client = vision.ImageAnnotatorClient()
                logger.info("Google Vision client initialized using GOOGLE_APPLICATION_CREDENTIALS path.")
                return client

            logger.debug("Attempting to initialize Vision client using default credentials (ADC).")
            client = vision.ImageAnnotatorClient()
            logger.info("Google Vision client initialized using default credentials (ADC).")
            return client

        except Exception as e:
            logger.warning(f"Could not initialize Google Cloud Vision client: {e}")
            return None
    
    def set_offsets(self, back_width_offset, top_depth_offset, shelf_depth_offset, 
                    thickness, leg_height_deduction, countertop_deduction):
        self.BACK_WIDTH_OFFSET = back_width_offset
        self.TOP_DEPTH_OFFSET = top_depth_offset
        self.SHELF_DEPTH_OFFSET = shelf_depth_offset
        self.THICKNESS = thickness
        self.LEG_HEIGHT_DEDUCTION = leg_height_deduction
        self.COUNTERTOP_DEDUCTION = countertop_deduction
    
    def generate_empty_cutting_list(self):
        summary = {}
        for category in self.components:
            summary[category] = {
                'items': [],
                'total_pieces': 0,
                'unique_sizes': 0,
                'total_area': 0.0
            }
        return summary
    
    def extract_numbers_with_google_vision(self, image_bytes):
        if not self.vision_client:
            logger.error("Google Cloud Vision client not initialized")
            return None, []
        
        try:
            logger.info("Extracting text with Google Cloud Vision...")
            
            image = vision.Image(content=image_bytes)
            response = self.vision_client.text_detection(image=image)
            
            try:
                raw_resp = MessageToDict(response._pb)
            except:
                raw_resp = {"error": "failed to convert protobuf to dict"}
            
            logger.debug(f"Raw Google Vision response (truncated): {json.dumps(raw_resp, indent=2)[:2000]}")
            
            texts = response.text_annotations
            
            if not texts:
                logger.warning("No text detected in the image")
                return None, []
            
            full_text = texts[0].description if texts else ""
            
            number_pattern = r'\b\d+(?:\.\d+)?\b'
            all_numbers = re.findall(number_pattern, full_text)
            
            extracted_numbers = []
            for num_str in all_numbers:
                try:
                    num = float(num_str) if '.' in num_str else int(num_str)
                    extracted_numbers.append(num)
                except ValueError:
                    continue
            
            logger.info(f"Extracted {len(extracted_numbers)} numbers from image")
            
            dimension_analysis = {
                'width_candidates': [n for n in extracted_numbers if 800 <= n <= 2000],
                'height_candidates': [n for n in extracted_numbers if 400 <= n <= 900],
                'depth_candidates': [n for n in extracted_numbers if 250 <= n <= 500],
                'large_numbers': [n for n in extracted_numbers if n > 2500],
                'small_numbers': [n for n in extracted_numbers if n < 200],
                'segment_candidates': [n for n in extracted_numbers if 400 <= n <= 800],
                'all_numbers': extracted_numbers
            }
            
            segments = dimension_analysis['segment_candidates']
            potential_widths = []
            
            for i, seg1 in enumerate(segments):
                for j, seg2 in enumerate(segments[i+1:], i+1):
                    if abs(seg1 - seg2) <= 50:
                        total_width = seg1 + seg2
                        if 900 <= total_width <= 1800:
                            potential_widths.append({
                                'segments': [seg1, seg2],
                                'total': total_width,
                                'description': f"{seg1}+{seg2}={total_width}"
                            })
            
            dimension_analysis['potential_segmented_widths'] = potential_widths
            
            return full_text, dimension_analysis
            
        except Exception as e:
            logger.error(f"Error in Google Cloud Vision extraction: {str(e)}")
            return None, []
    
    def extract_numbers_with_openai_vision(self, image_bytes):
        """Fallback method: Extract numbers directly using OpenAI Vision"""
        try:
            logger.info("Using OpenAI Vision as fallback for text extraction...")
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            if not OPENAI_API_KEY:
                logger.error("OpenAI API key not configured")
                return None, {}
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            }
            
            # The prompt is simplified here but remains effective for number extraction
            payload = {
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """Analyze this image of a kitchen cabinet technical drawing and extract ALL visible numbers/dimensions.
                                Return them as a JSON object with this structure:
                                {
                                    "all_numbers": [list of all numbers found],
                                    "width_candidates": [numbers that look like widths 800-2000mm],
                                    "height_candidates": [numbers that look like heights 400-900mm],
                                    "depth_candidates": [numbers that look like depths 250-500mm],
                                    "segment_candidates": [numbers 400-800mm that could be cabinet segments],
                                    "large_numbers": [numbers >2500mm, likely room dimensions],
                                    "small_numbers": [numbers <200mm, likely details],
                                    "potential_segmented_widths": []
                                }"""
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 1000,
                "temperature": 0.1
            }
            
            response = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                dimension_analysis = json.loads(json_str)
                logger.info(f"OpenAI Vision extraction succeeded: {len(dimension_analysis.get('all_numbers', []))} numbers found")
                return content, dimension_analysis
            else:
                logger.warning("No JSON found in OpenAI Vision response")
                return content, {}
                
        except Exception as e:
            logger.error(f"OpenAI Vision fallback failed: {str(e)}")
            return None, {}
    
    def analyze_with_master_prompt(self, image_bytes, extracted_numbers_data):
        # NOTE: This complex prompt is based on the provided code, designed for GPT-4 to perform calculations.
        # It relies on accurate OCR/Vision results and the model's ability to follow complex mathematical instructions.
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        numbers_summary = f"""
        VISION EXTRACTION RESULTS:
        =====================================
        All extracted numbers: {extracted_numbers_data.get('all_numbers', [])}
        
        CATEGORIZED BY TYPICAL CABINET DIMENSIONS:
        - Width candidates (800-2000mm): {extracted_numbers_data.get('width_candidates', [])}
        - Height candidates (400-900mm): {extracted_numbers_data.get('height_candidates', [])}
        - Depth candidates (250-500mm): {extracted_numbers_data.get('depth_candidates', [])}
        - Segment candidates (400-800mm): {extracted_numbers_data.get('segment_candidates', [])}
        - Large numbers (>2500mm, likely room dimensions): {extracted_numbers_data.get('large_numbers', [])}
        - Small numbers (<200mm, likely details/hardware): {extracted_numbers_data.get('small_numbers', [])}
        
        POTENTIAL SEGMENTED WIDTHS DETECTED:
        {extracted_numbers_data.get('potential_segmented_widths', [])}
        
        IMPORTANT: If segments like 600+600 are detected, PRIORITIZE their sum as the cabinet width!
        """
        
        master_prompt = f"""
        You are an expert kitchen cabinet maker and technical drawing analyzer with 20+ years of experience.
        Your task is to analyze a KITCHEN CABINET technical drawing and create a precise cutting list for exactly ONE cabinet.
        
        {numbers_summary}
        
        ================================================================================
        CRITICAL KITCHEN CABINET ANALYSIS - READ CAREFULLY
        ================================================================================
        
        IMPORTANT: This is a KITCHEN CABINET drawing. Kitchen cabinets have legs underneath and need countertop clearance.
        
        KITCHEN CABINET HEIGHT ADJUSTMENT PROTOCOL:
        ==========================================
        1. Identify the TOTAL HEIGHT from the drawing (usually 700-900mm for kitchen cabinets)
        2. SUBTRACT {self.LEG_HEIGHT_DEDUCTION}mm for legs underneath the cabinet
        3. SUBTRACT {self.COUNTERTOP_DEDUCTION}mm for countertop accommodation
        4. The WORKING HEIGHT = Total Height - {self.LEG_HEIGHT_DEDUCTION} - {self.COUNTERTOP_DEDUCTION}
        
        Example: If drawing shows 780mm total height:
        Working Height = 780 - {self.LEG_HEIGHT_DEDUCTION} - {self.COUNTERTOP_DEDUCTION} = {780 - self.LEG_HEIGHT_DEDUCTION - self.COUNTERTOP_DEDUCTION}mm
        
        Your analysis MUST follow this exact process:
        
        1. DIMENSION IDENTIFICATION PROTOCOL
        ====================================
        a) Cross-reference the extracted numbers with what you see in the image
        b) Identify the PRIMARY KITCHEN CABINET in the drawing (ignore secondary elements)
        c) Determine the THREE key dimensions with SPECIAL ATTENTION TO WIDTH:
        
        *WIDTH IDENTIFICATION PRIORITY (CRITICAL):*
        - Look for segmented widths that add up (e.g., 600+600=1200mm)
        - NEVER use overall room dimensions (>2500mm) or spacing dimensions
        - Common kitchen cabinet widths: 900, 1000, 1200, 1500mm
        - The TRUE CABINET WIDTH is usually shown as door/drawer segments
        
        DIMENSION REQUIREMENTS:
            - WIDTH (W): The actual cabinet width (sum of segments if shown), typically 800-2000mm
            - TOTAL HEIGHT (H_total): The full height shown in drawing, typically 700-900mm for kitchen cabinets
            - DEPTH (D): Usually the front-to-back dimension, typically 300-400mm for kitchen cabinets
        
        d) CALCULATE WORKING HEIGHT:
            H_working = H_total - {self.LEG_HEIGHT_DEDUCTION} - {self.COUNTERTOP_DEDUCTION}
        
        2. MATHEMATICAL PRECISION REQUIREMENTS
        =======================================
        Once you identify W, H_working (adjusted height), and D, you MUST apply these EXACT formulas:
        
        CONFIGURED WORKSHOP PARAMETERS:
        - BACK_WIDTH_OFFSET = {self.BACK_WIDTH_OFFSET}mm
        - TOP_DEPTH_OFFSET = {self.TOP_DEPTH_OFFSET}mm
        - SHELF_DEPTH_OFFSET = {self.SHELF_DEPTH_OFFSET}mm
        - BOARD_THICKNESS = {self.THICKNESS}mm
        - LEG_HEIGHT_DEDUCTION = {self.LEG_HEIGHT_DEDUCTION}mm
        - COUNTERTOP_DEDUCTION = {self.COUNTERTOP_DEDUCTION}mm
        
        COMPONENT CALCULATIONS (DO THE ACTUAL MATH):
        
        a) GABLES (End Panels) - Quantity: 2
            Formula: H_working × D
            
        b) T/B PANELS (Top/Bottom) - Quantity: 2
            Formula: (W - {self.BACK_WIDTH_OFFSET}) × (D - {self.TOP_DEPTH_OFFSET})
            
        c) S/H HARDWARE (Shelf) - Quantity: 1
            Formula: (W - {self.BACK_WIDTH_OFFSET}) × (D - {self.SHELF_DEPTH_OFFSET})
            
        d) BACK PANEL - Quantity: 1
            Formula: H_working × (W - {self.BACK_WIDTH_OFFSET})
        
        ================================================================================
        JSON OUTPUT FORMAT (USE EXACT STRUCTURE)
        ================================================================================
        
        {{
            "analysis_confidence": "high|medium|low",
            "dimension_detection": {{
                "width_detected": [actual_number],
                "width_calculation_method": "Explain if this is a single dimension or sum of segments",
                "segments_found": [list any segments that were added],
                "total_height_detected": [actual_number_from_drawing],
                "working_height_calculated": [total_height - {self.LEG_HEIGHT_DEDUCTION} - {self.COUNTERTOP_DEDUCTION}],
                "depth_detected": [actual_number],
                "height_adjustment_applied": "Deducted {self.LEG_HEIGHT_DEDUCTION}mm for legs and {self.COUNTERTOP_DEDUCTION}mm for countertop"
            }},
            "cabinet_modules": [
                {{
                    "module_id": 1,
                    "cabinet_width": [detected_W_value],
                    "cabinet_total_height": [detected_H_total_value],
                    "cabinet_working_height": [calculated_H_working_value],
                    "cabinet_depth": [detected_D_value],
                    "calculated_components": {{
                        "gables": {{
                            "formula": "H_working × D",
                            "calculation": "[H_working] × [D] = [result]",
                            "height": [H_working_value],
                            "width": [D_value],
                            "quantity": 2
                        }},
                        "tb_panels": {{
                            "formula": "(W - {self.BACK_WIDTH_OFFSET}) × (D - {self.TOP_DEPTH_OFFSET})",
                            "calculation": "([W] - {self.BACK_WIDTH_OFFSET}) × ([D] - {self.TOP_DEPTH_OFFSET}) = [result]",
                            "height": [calculated_value],
                            "width": [calculated_value],
                            "quantity": 2
                        }},
                        "sh_hardware": {{
                            "formula": "(W - {self.BACK_WIDTH_OFFSET}) × (D - {self.SHELF_DEPTH_OFFSET})",
                            "calculation": "([W] - {self.BACK_WIDTH_OFFSET}) × ([D] - {self.SHELF_DEPTH_OFFSET}) = [result]",
                            "height": [calculated_value],
                            "width": [calculated_value],
                            "quantity": 1
                        }},
                        "back": {{
                            "formula": "H_working × (W - {self.BACK_WIDTH_OFFSET})",
                            "calculation": "[H_working] × ([W] - {self.BACK_WIDTH_OFFSET}) = [result]",
                            "height": [H_working_value],
                            "width": [calculated_value],
                            "quantity": 1
                        }}
                    }}
                }}
            ]
        }}
        
        Analyze the KITCHEN CABINET drawing carefully. Use the extracted numbers as your 
        primary source. Apply the height adjustments for legs and countertop. Use WORKING HEIGHT for all 
        calculations. Perform all calculations step by step. Double-check your math. Deliver precise results.
        """
        
        if not OPENAI_API_KEY:
            return {"error": "OpenAI API key not configured"}
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        
        payload = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert kitchen cabinet maker and technical drawing analyzer. You must provide precise, mathematically accurate cutting lists based on kitchen cabinet technical drawings. Always apply height adjustments for legs and countertops. Always verify your calculations."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": master_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 3000,
            "temperature": 0.1
        }
        
        try:
            logger.info("Analyzing with OpenAI GPT-4 Vision...")
            response = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                parsed_result = json.loads(json_str)
                
                logger.info("OpenAI analysis completed successfully")
                return parsed_result
            else:
                return {"error": "No valid JSON in OpenAI response", "raw_response": content}
                
        except Exception as e:
            logger.error(f"OpenAI analysis error: {str(e)}")
            return {"error": f"OpenAI request failed: {str(e)}"}
    
    def analyze_technical_drawing(self, image_bytes):
        logger.info("Starting kitchen cabinet technical drawing analysis with Google Cloud Vision + OpenAI")
        
        try:
            # Reset components for new analysis
            self.components = {
                'GABLE': [],
                'T/B & FIX SHELVES': [],
                'BACKS': [],
                'S/H': []
            }
            self.part_counters = {
                'GABLE': 1,
                'T/B & FIX SHELVES': 1,
                'BACKS': 1,
                'S/H': 1
            }
            
            # Try Google Cloud Vision first, fall back to OpenAI Vision
            full_text, dimension_analysis = self.extract_numbers_with_google_vision(image_bytes)
            
            if not dimension_analysis or not dimension_analysis.get('all_numbers'):
                logger.warning("Google Cloud Vision extraction failed or returned no data, using OpenAI Vision fallback")
                full_text, dimension_analysis = self.extract_numbers_with_openai_vision(image_bytes)
            
            if not dimension_analysis or not dimension_analysis.get('all_numbers'):
                logger.error("Failed to extract numbers from image using both methods")
                return self.generate_empty_cutting_list()
            
            analysis_result = self.analyze_with_master_prompt(image_bytes, dimension_analysis)
            
            if 'error' in analysis_result:
                logger.error(f"Analysis error: {analysis_result['error']}")
                return self.generate_empty_cutting_list()
            
            self.process_cabinet_analysis(analysis_result)
            
            total_components = sum(len(items) for items in self.components.values())
            if total_components == 0:
                logger.error("No valid components generated")
                return self.generate_empty_cutting_list()
            
            logger.info(f"Analysis complete: Generated {total_components} components")
            
        except Exception as e:
            logger.error(f"Error in analysis: {str(e)}")
            return self.generate_empty_cutting_list()
        
        return self.generate_cutting_list()
    
    def process_cabinet_analysis(self, analysis):
        cabinet_modules = analysis.get('cabinet_modules', [])
        
        if not cabinet_modules:
            logger.error("No cabinet modules identified")
            return
        
        module = cabinet_modules[0]
        
        # Safely extract and convert dimensions
        def safe_float_extract(data, key, default=0):
            val = data.get(key, default)
            if isinstance(val, (int, float)):
                return val
            if isinstance(val, list) and val:
                try:
                    return float(val[0])
                except (ValueError, TypeError):
                    return default
            return default

        cabinet_width = safe_float_extract(module, 'cabinet_width')
        cabinet_total_height = safe_float_extract(module, 'cabinet_total_height')
        cabinet_working_height = safe_float_extract(module, 'cabinet_working_height')
        cabinet_depth = safe_float_extract(module, 'cabinet_depth')
        
        if not self.validate_cabinet_dimensions(cabinet_width, cabinet_working_height, cabinet_depth):
            logger.error(f"Invalid cabinet dimensions: {cabinet_width}×{cabinet_working_height}×{cabinet_depth}")
            return
        
        logger.info(f"Processing kitchen cabinet: {cabinet_width}W × {cabinet_total_height}H (working: {cabinet_working_height}H) × {cabinet_depth}D mm")
        
        calculated_components = module.get('calculated_components', {})
        
        component_mapping = {
            'gables': ('GABLE', 'Gables (End Panels)'),
            'tb_panels': ('T/B & FIX SHELVES', 'Top/Bottom Panels'),
            'sh_hardware': ('S/H', 'Shelf/Hardware'),
            'back': ('BACKS', 'Back Panel')
        }
        
        for comp_name, (category, description) in component_mapping.items():
            if comp_name not in calculated_components:
                logger.warning(f"Missing component: {comp_name}")
                continue
            
            comp_data = calculated_components[comp_name]
            height = safe_float_extract(comp_data, 'height')
            width = safe_float_extract(comp_data, 'width')
            quantity = safe_float_extract(comp_data, 'quantity', 1)
            calculation = comp_data.get('calculation', '')
            
            if not self.validate_component_dimensions(height, width, comp_name):
                logger.warning(f"Invalid dimensions for {comp_name}: {height}×{width}")
                continue
            
            self.add_component(
                category, height, width, quantity,
                f"Kitchen Cabinet {cabinet_width}×{cabinet_total_height}H(→{cabinet_working_height})×{cabinet_depth}D - {description} | Calc: {calculation}"
            )
            
            logger.info(f"Added {description}: {height}×{width}mm (Qty: {quantity})")
    
    def validate_cabinet_dimensions(self, width, height, depth):
        if width < 200 or width > 2000:
            return False
        # Working height check - adjusted height is expected to be smaller
        if height < 300 or height > 800:
            return False 
        if depth < 200 or depth > 800:
            return False
        return True
    
    def validate_component_dimensions(self, height, width, component_type):
        if height <= 0 or width <= 0:
            return False
        if height > 3000 or width > 3000:
            return False
        return True
    
    def add_component(self, category, height, width, quantity, description):
        try:
            height = max(10, int(round(height)))
            width = max(10, int(round(width)))
            quantity = max(1, int(quantity))
            
            if category not in self.components:
                return
            
            part_id = f"{self.get_category_short_name(category)}-{self.part_counters[category]:02d}"
            material_type = self.get_material_type(category)
            
            component_data = {
                'part_id': part_id,
                'dimensions': f"{height}x{width}",
                'height': height,
                'width': width,
                'quantity': quantity,
                'material_type': material_type,
                'notes': description,
                'raw_text': description
            }
            
            self.components[category].append(component_data)
            self.part_counters[category] += 1
            
        except Exception as e:
            logger.error(f"Error adding component: {str(e)}")
    
    def get_category_short_name(self, category):
        short_names = {
            'GABLE': 'GABLE',
            'T/B & FIX SHELVES': 'SHELF',
            'BACKS': 'BACK',
            'S/H': 'HARDWARE'
        }
        return short_names.get(category, 'COMP')
    
    def get_material_type(self, category):
        materials = {
            'GABLE': '18mm MFC',
            'T/B & FIX SHELVES': '18mm MFC',
            'BACKS': '6mm MDF',
            'S/H': 'Hardware'
        }
        return materials.get(category, '18mm MFC')
    
    def generate_cutting_list(self):
        summary = {}
        total_items = 0
        
        for category, items in self.components.items():
            if items:
                total_pieces = sum(item['quantity'] for item in items)
                unique_dimensions = set(item['dimensions'] for item in items)
                
                total_area = 0
                for item in items:
                    width = item.get('width', 0)
                    height = item.get('height', 0)
                    quantity = item.get('quantity', 1)
                    # Convert mm^2 to m^2: divide by 1,000,000
                    total_area += (width * height * quantity) / 1000000 
                
                summary[category] = {
                    'items': items,
                    'total_pieces': total_pieces,
                    'unique_sizes': len(unique_dimensions),
                    'total_area': round(total_area, 2)
                }
                total_items += total_pieces
            else:
                summary[category] = {
                    'items': [],
                    'total_pieces': 0,
                    'unique_sizes': 0,
                    'total_area': 0.0
                }
        
        logger.info(f"Generated {total_items} total components")
        return summary
    
    def generate_dxf(self):
        """Generate DXF file"""
        try:
            doc = ezdxf.new(dxfversion='R2010')
            doc.units = ezdxf.units.MM
            msp = doc.modelspace()
            
            x_offset = 0
            y_offset = 0
            margin = 50
            
            title = f"KITCHEN CABINET CUTTING LIST - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            msp.add_text(title, dxfattribs={'height': 25, 'insert': (10, -30)})
            y_offset = -80
            
            # Temporary storage for the height of the current row to calculate the next starting point
            current_row_max_h = 0
            
            for category, items in self.components.items():
                if not items:
                    continue
                
                if x_offset > 0:
                    x_offset = 0
                    y_offset -= current_row_max_h + margin # Move down by max height in current row + margin
                
                msp.add_text(f"=== {category} ===", dxfattribs={'height': 20, 'insert': (x_offset, y_offset)})
                y_offset -= 40
                current_row_max_h = 0 # Reset max height for the new row
                
                for item in items:
                    w = item['width']
                    h = item['height']
                    qty = item['quantity']
                    
                    for q in range(qty):
                        # Start a new row if width exceeds limit (e.g., 2000)
                        if x_offset + w + margin > 2000: 
                            x_offset = 0
                            y_offset -= current_row_max_h + margin # Move down to the next row
                            current_row_max_h = 0 # Reset max height for the new row
                        
                        points = [
                            (x_offset, y_offset),
                            (x_offset + w, y_offset),
                            (x_offset + w, y_offset - h),
                            (x_offset, y_offset - h)
                        ]
                        
                        # Add rectangle
                        msp.add_lwpolyline(points, close=True)
                        
                        # Add dimensions text
                        dim_text = f"{w}x{h}"
                        msp.add_text(dim_text, dxfattribs={'height': 12, 'insert': (x_offset + 5, y_offset - 15)})
                        
                        # Update max height for the current row
                        current_row_max_h = max(current_row_max_h, h)
                        
                        # Move insertion point for next piece
                        x_offset += w + margin
                
                # Reset x_offset and move down for next category
                x_offset = 0
                y_offset -= current_row_max_h + margin # Move down by the max height of the last row + margin
                current_row_max_h = 0 # Reset max height for the new category block
            
            # Save to BytesIO buffer
            buffer = BytesIO()
            doc.saveas(buffer)
            dxf_string = buffer.getvalue().decode('utf-8', errors='ignore')
            return dxf_string
            
        except Exception as e:
            logger.error(f"Error generating DXF: {str(e)}")
            return None