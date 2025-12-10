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
import anthropic  # NEW: Import Anthropic SDK

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger('DrawingAnalyzer')
logger.setLevel(logging.INFO)

# API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # NEW
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Keep as fallback
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
GOOGLE_CLOUD_CREDENTIALS = os.getenv("GOOGLE_CLOUD_CREDENTIALS")

class DrawingAnalyzer:
    def __init__(self):
        # Configurable offsets
        self.BACK_WIDTH_OFFSET = 36
        self.TOP_DEPTH_OFFSET = 30
        self.SHELF_DEPTH_OFFSET = 40  # FIXED: Was 70, now 40
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
        
        # NEW: Initialize Anthropic client
        if ANTHROPIC_API_KEY:
            self.anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            logger.info("Anthropic Claude client initialized")
        else:
            self.anthropic_client = None
            logger.warning("Anthropic API key not found, will use OpenAI as fallback")
    
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
    
    def analyze_with_claude(self, image_bytes, extracted_numbers_data):
        """NEW: Use Claude Sonnet 4 for analysis"""
        if not self.anthropic_client:
            logger.error("Anthropic client not initialized")
            return {"error": "Anthropic API key not configured"}
        
        try:
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
- Potential segmented widths: {extracted_numbers_data.get('potential_segmented_widths', [])}

IMPORTANT: If segments like 600+600 are detected, their sum (1200mm) is the cabinet width!
"""
            
            master_prompt = f"""You are an expert kitchen cabinet maker with 20+ years of experience.

CRITICAL INSTRUCTIONS:
======================
If you see TWO cabinets side by side in the drawing, analyze ONLY THE LEFT ONE.
Focus on the DRAWER/DOOR segments to determine cabinet width (e.g., 600+600 = 1200mm).

{numbers_summary}

TASK: Analyze this KITCHEN CABINET drawing for exactly ONE cabinet.

HEIGHT ADJUSTMENT (CRITICAL):
1. Find the TOTAL HEIGHT from drawing (usually 700-900mm)
2. SUBTRACT {self.LEG_HEIGHT_DEDUCTION}mm for legs
3. SUBTRACT {self.COUNTERTOP_DEDUCTION}mm for countertop
4. WORKING HEIGHT = Total - {self.LEG_HEIGHT_DEDUCTION} - {self.COUNTERTOP_DEDUCTION}

Example: 780mm total → 780 - {self.LEG_HEIGHT_DEDUCTION} - {self.COUNTERTOP_DEDUCTION} = {780 - self.LEG_HEIGHT_DEDUCTION - self.COUNTERTOP_DEDUCTION}mm working height

DIMENSION IDENTIFICATION:
- WIDTH (W): Look for DRAWER segments (e.g., 600+600 = 1200mm). DO NOT use 1350 or 1340 (those include frame).
- TOTAL HEIGHT (H_total): The full cabinet height (700-900mm typical)
- DEPTH (D): Front-to-back dimension (300-400mm typical)

COMPONENT FORMULAS (USE EXACT MATH):
====================================
Workshop Parameters:
- BACK_WIDTH_OFFSET = {self.BACK_WIDTH_OFFSET}mm
- TOP_DEPTH_OFFSET = {self.TOP_DEPTH_OFFSET}mm
- SHELF_DEPTH_OFFSET = {self.SHELF_DEPTH_OFFSET}mm

Calculate these components:

1. GABLES (Qty: 2): H_working × D
2. T/B PANELS (Qty: 2): (W - {self.BACK_WIDTH_OFFSET}) × (D - {self.TOP_DEPTH_OFFSET})
3. S/H HARDWARE (Qty: 1): (W - {self.BACK_WIDTH_OFFSET}) × (D - {self.SHELF_DEPTH_OFFSET})
4. BACK PANEL (Qty: 1): H_working × (W - {self.BACK_WIDTH_OFFSET})

JSON OUTPUT FORMAT:
{{
    "cabinet_modules": [
        {{
            "cabinet_width": [W_value],
            "cabinet_total_height": [H_total_value],
            "cabinet_working_height": [H_working_value],
            "cabinet_depth": [D_value],
            "calculated_components": {{
                "gables": {{
                    "height": [H_working],
                    "width": [D],
                    "quantity": 2
                }},
                "tb_panels": {{
                    "height": [(W-{self.BACK_WIDTH_OFFSET})],
                    "width": [(D-{self.TOP_DEPTH_OFFSET})],
                    "quantity": 2
                }},
                "sh_hardware": {{
                    "height": [(W-{self.BACK_WIDTH_OFFSET})],
                    "width": [(D-{self.SHELF_DEPTH_OFFSET})],
                    "quantity": 1
                }},
                "back": {{
                    "height": [H_working],
                    "width": [(W-{self.BACK_WIDTH_OFFSET})],
                    "quantity": 1
                }}
            }}
        }}
    ]
}}

CRITICAL REMINDERS:
- Use DRAWER WIDTH ONLY (600+600=1200), NOT frame width (1350)
- Apply height deductions ({self.LEG_HEIGHT_DEDUCTION} + {self.COUNTERTOP_DEDUCTION})
- Return ONLY valid JSON
- Do the actual math, show your work

Analyze the drawing and provide precise calculations."""
            
            logger.info("Analyzing with Claude Sonnet 4...")
            
            message = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                temperature=0.1,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": master_prompt
                            }
                        ]
                    }
                ]
            )
            
            content = message.content[0].text
            
            # Extract JSON from response
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                parsed_result = json.loads(json_str)
                logger.info("Claude analysis completed successfully")
                return parsed_result
            else:
                return {"error": "No valid JSON in Claude response", "raw_response": content}
                
        except Exception as e:
            logger.error(f"Claude analysis error: {str(e)}")
            return {"error": f"Claude request failed: {str(e)}"}
    
    def analyze_technical_drawing(self, image_bytes):
        logger.info("Starting kitchen cabinet analysis with Claude Sonnet 4")
        
        try:
            # Reset components
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
            
            # Extract numbers with Google Vision
            full_text, dimension_analysis = self.extract_numbers_with_google_vision(image_bytes)
            
            if not dimension_analysis or not dimension_analysis.get('all_numbers'):
                logger.error("Failed to extract numbers from image")
                return self.generate_empty_cutting_list()
            
            # Analyze with Claude Sonnet 4
            analysis_result = self.analyze_with_claude(image_bytes, dimension_analysis)
            
            if 'error' in analysis_result:
                logger.error(f"Analysis error: {analysis_result['error']}")
                return self.generate_empty_cutting_list()
            
            # Process results
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
        
        logger.info(f"Processing cabinet: {cabinet_width}W × {cabinet_total_height}H (working: {cabinet_working_height}H) × {cabinet_depth}D mm")
        
        calculated_components = module.get('calculated_components', {})
        
        component_mapping = {
            'gables': ('GABLE', 'Gables'),
            'tb_panels': ('T/B & FIX SHELVES', 'Top/Bottom'),
            'sh_hardware': ('S/H', 'Shelf/Hardware'),
            'back': ('BACKS', 'Back')
        }
        
        for comp_name, (category, description) in component_mapping.items():
            if comp_name not in calculated_components:
                logger.warning(f"Missing component: {comp_name}")
                continue
            
            comp_data = calculated_components[comp_name]
            height = safe_float_extract(comp_data, 'height')
            width = safe_float_extract(comp_data, 'width')
            quantity = safe_float_extract(comp_data, 'quantity', 1)
            
            if not self.validate_component_dimensions(height, width, comp_name):
                logger.warning(f"Invalid dimensions for {comp_name}: {height}×{width}")
                continue
            
            self.add_component(
                category, height, width, quantity,
                f"{description} - Cabinet {cabinet_width}×{cabinet_total_height}H×{cabinet_depth}D"
            )
            
            logger.info(f"Added {description}: {height}×{width}mm (Qty: {quantity})")
    
    def validate_cabinet_dimensions(self, width, height, depth):
        if width < 200 or width > 2000:
            return False
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
            
            title = f"CUTTING LIST - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            msp.add_text(title, dxfattribs={'height': 25, 'insert': (10, -30)})
            y_offset = -80
            
            current_row_max_h = 0
            
            for category, items in self.components.items():
                if not items:
                    continue
                
                if x_offset > 0:
                    x_offset = 0
                    y_offset -= current_row_max_h + margin
                
                msp.add_text(f"=== {category} ===", dxfattribs={'height': 20, 'insert': (x_offset, y_offset)})
                y_offset -= 40
                current_row_max_h = 0
                
                for item in items:
                    w = item['width']
                    h = item['height']
                    qty = item['quantity']
                    
                    for q in range(qty):
                        if x_offset + w + margin > 2000: 
                            x_offset = 0
                            y_offset -= current_row_max_h + margin
                            current_row_max_h = 0
                        
                        points = [
                            (x_offset, y_offset),
                            (x_offset + w, y_offset),
                            (x_offset + w, y_offset - h),
                            (x_offset, y_offset - h)
                        ]
                        
                        msp.add_lwpolyline(points, close=True)
                        
                        dim_text = f"{w}x{h}"
                        msp.add_text(dim_text, dxfattribs={'height': 12, 'insert': (x_offset + 5, y_offset - 15)})
                        
                        current_row_max_h = max(current_row_max_h, h)
                        
                        x_offset += w + margin
                
                x_offset = 0
                y_offset -= current_row_max_h + margin
                current_row_max_h = 0
            
            buffer = BytesIO()
            doc.saveas(buffer)
            dxf_string = buffer.getvalue().decode('utf-8', errors='ignore')
            return dxf_string
            
        except Exception as e:
            logger.error(f"Error generating DXF: {str(e)}")
            return None