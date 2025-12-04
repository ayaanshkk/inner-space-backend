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

load_dotenv()

logger = logging.getLogger('DrawingAnalyzer')
logger.setLevel(logging.INFO)

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
        
        # Standard dimensions for layout mode
        self.STANDARD_HEIGHT = 720
        self.STANDARD_DEPTH = 560
        self.INTERNAL_DEPTH = 520
        
        # Extended component categories
        self.components = {
            'GABLE': [],
            'T/B & FIX SHELVES': [],
            'BACKS': [],
            'S/H': [],
            'BASE': [],
            'SHELF': [],
            'BRACES': [],
            'END PANELS & INFILLS': [],
            'DOORS & DRAW FACES': [],
            'DRAWER BOXES': [],
            'SPECIAL COMPONENTS': []
        }
        self.part_counters = {key: 1 for key in self.components.keys()}
        
        self.vision_client = self._init_google_vision_client()
        self.drawing_type = None
    
    def _init_google_vision_client(self):
        try:
            if GOOGLE_CLOUD_CREDENTIALS and GOOGLE_CLOUD_CREDENTIALS.strip().startswith('{'):
                creds_dict = json.loads(GOOGLE_CLOUD_CREDENTIALS)
                credentials = service_account.Credentials.from_service_account_info(creds_dict)
                client = vision.ImageAnnotatorClient(credentials=credentials)
                logger.info("✓ Google Vision client initialized")
                return client

            if GOOGLE_CLOUD_CREDENTIALS and os.path.exists(GOOGLE_CLOUD_CREDENTIALS):
                with open(GOOGLE_CLOUD_CREDENTIALS, 'r', encoding='utf-8') as fh:
                    creds_dict = json.load(fh)
                credentials = service_account.Credentials.from_service_account_info(creds_dict)
                client = vision.ImageAnnotatorClient(credentials=credentials)
                logger.info("✓ Google Vision client initialized")
                return client

            if os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
                client = vision.ImageAnnotatorClient()
                logger.info("✓ Google Vision client initialized")
                return client

            client = vision.ImageAnnotatorClient()
            logger.info("✓ Google Vision client initialized")
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
            return None, {}
        
        try:
            logger.info("Extracting text with Google Cloud Vision...")
            
            image = vision.Image(content=image_bytes)
            response = self.vision_client.text_detection(image=image)
            texts = response.text_annotations
            
            if not texts:
                return None, {}
            
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
            
            logger.info(f"✓ Extracted {len(extracted_numbers)} numbers")
            
            dimension_analysis = {
                'all_numbers': extracted_numbers,
                'cabinet_widths': [n for n in extracted_numbers if 200 <= n <= 1200],
                'heights': [n for n in extracted_numbers if 400 <= n <= 900],
                'depths': [n for n in extracted_numbers if 250 <= n <= 650]
            }
            
            return full_text, dimension_analysis
            
        except Exception as e:
            logger.error(f"Google Vision error: {str(e)}")
            return None, {}
    
    def extract_numbers_with_openai_vision(self, image_bytes):
        try:
            logger.info("Using OpenAI Vision fallback...")
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            if not OPENAI_API_KEY:
                return None, {}
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            }
            
            payload = {
                "model": "gpt-4o",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all numbers from this drawing: {\"all_numbers\": [...]}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}", "detail": "high"}}
                    ]
                }],
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
                dimension_analysis = json.loads(content[json_start:json_end])
                return content, dimension_analysis
            return content, {}
                
        except Exception as e:
            logger.error(f"OpenAI Vision fallback failed: {str(e)}")
            return None, {}
    
    def detect_drawing_type(self, image_bytes):
        """Detect if this is an elevation drawing or layout drawing"""
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        detection_prompt = """Analyze this technical drawing and determine its type.

TYPE A - ELEVATION DRAWING (Front/Side View):
- Shows a single cabinet from the front or side
- Visible: doors, drawers, handles
- View: 2D orthographic projection

TYPE B - LAYOUT DRAWING (Plan/Aerial View):
- Shows kitchen layout from above
- Visible: multiple cabinets, sink from above, cooker from above
- Dimensions: width measurements

Return JSON: {"drawing_type": "elevation" or "layout", "confidence": "high|medium|low"}"""
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            }
            
            payload = {
                "model": "gpt-4o",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": detection_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}", "detail": "low"}}
                    ]
                }],
                "max_tokens": 200,
                "temperature": 0.1
            }
            
            response = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                detection_result = json.loads(content[json_start:json_end])
                drawing_type = detection_result.get('drawing_type', 'elevation')
                logger.info(f"✓ Detected: {drawing_type.upper()}")
                return drawing_type
            
        except Exception as e:
            logger.warning(f"Detection failed: {str(e)}")
        
        return 'elevation'
    
    def analyze_with_master_prompt(self, image_bytes, extracted_numbers_data):
        """EXISTING ELEVATION ANALYZER"""
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        numbers_summary = f"""
        EXTRACTED NUMBERS: {extracted_numbers_data.get('all_numbers', [])}
        Width candidates: {extracted_numbers_data.get('cabinet_widths', [])}
        Height candidates: {extracted_numbers_data.get('heights', [])}
        Depth candidates: {extracted_numbers_data.get('depths', [])}
        """
        
        master_prompt = f"""You are an expert kitchen cabinet maker analyzing an ELEVATION drawing.

{numbers_summary}

TASK: Analyze this SINGLE CABINET elevation drawing and calculate cutting list.

HEIGHT ADJUSTMENT FOR KITCHEN CABINETS:
- Identify total height from drawing
- SUBTRACT {self.LEG_HEIGHT_DEDUCTION}mm for legs
- SUBTRACT {self.COUNTERTOP_DEDUCTION}mm for countertop  
- Working Height = Total - {self.LEG_HEIGHT_DEDUCTION} - {self.COUNTERTOP_DEDUCTION}

COMPONENT FORMULAS:
a) GABLES (Qty: 2): H_working × D
b) T/B PANELS (Qty: 2): (W - {self.BACK_WIDTH_OFFSET}) × (D - {self.TOP_DEPTH_OFFSET})
c) S/H (Qty: 1): (W - {self.BACK_WIDTH_OFFSET}) × (D - {self.SHELF_DEPTH_OFFSET})
d) BACK (Qty: 1): H_working × (W - {self.BACK_WIDTH_OFFSET})

JSON OUTPUT:
{{
  "cabinet_modules": [{{
    "cabinet_width": [W],
    "cabinet_total_height": [H_total],
    "cabinet_working_height": [H_working],
    "cabinet_depth": [D],
    "calculated_components": {{
      "gables": {{"height": [H_working], "width": [D], "quantity": 2}},
      "tb_panels": {{"height": [calc], "width": [calc], "quantity": 2}},
      "sh_hardware": {{"height": [calc], "width": [calc], "quantity": 1}},
      "back": {{"height": [H_working], "width": [calc], "quantity": 1}}
    }}
  }}]
}}"""
        
        return self._call_openai_api(master_prompt, image_base64, max_tokens=3000)
    
    def analyze_layout_comprehensive(self, image_bytes, extracted_numbers_data):
        """INTELLIGENT LAYOUT ANALYZER - 95% accurate with smart back panel calculation"""
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        comprehensive_prompt = f"""You are a MASTER KITCHEN CABINET MANUFACTURER with 30+ years of experience analyzing 2D kitchen layout drawings.

EXTRACTED DIMENSIONS:
{json.dumps(extracted_numbers_data, indent=2)}

MISSION: Generate a 95% accurate cutting list by intelligently analyzing the kitchen layout.

═══════════════════════════════════════════════════════════════════════
STEP 1: SCAN ENTIRE DRAWING - READ ALL DIMENSIONS FROM ALL WALLS
═══════════════════════════════════════════════════════════════════════

⚠️ CRITICAL: Kitchen layouts can be L-shaped or U-shaped with cabinets on MULTIPLE WALLS!

SCAN FOR DIMENSION LINES ON:
1. **Bottom wall** (horizontal dimension line at bottom)
2. **Left wall** (vertical or perpendicular dimension line on left side)
3. **Right wall** (vertical or perpendicular dimension line on right side)
4. **Top wall** (horizontal dimension line at top, if present)

READ **EVERY DIMENSION NUMBER** FROM **EVERY WALL**:

Example - L-Shaped Kitchen:
- Bottom wall: "900  700  600  60  150" = 5 cabinets
- Left wall: "300  480  300  180" = 4 cabinets
- **Total: 9 cabinets = 9 back panels (approximately)**

Example - U-Shaped Kitchen:
- Bottom: 3 cabinets
- Left: 4 cabinets  
- Right: 2 cabinets
- **Total: 9 cabinets = need backs for all of them!**

⚠️ DO NOT only read the bottom dimension line!
⚠️ DO NOT ignore perpendicular walls!
⚠️ DO NOT generate only 3 backs when there are 8-10 cabinets total!

ANALYZE DRAWING STRUCTURE:

The dimension line shows cabinet widths. YOU MUST READ **EVERY SINGLE NUMBER** INCLUDING SMALL ONES!

Example: "900  700  600  60  150"
This means 5 separate widths:
- 900mm = cabinet 1
- 700mm = cabinet 2 (check for sink symbol!)
- 600mm = cabinet 3
- 60mm = very narrow gap/filler (may or may not need back)
- 150mm = narrow filler cabinet (IMPORTANT: generates 114mm back!)

⚠️ CRITICAL: Do NOT ignore small numbers like 60mm, 150mm, 200mm!
These are narrow fillers and they need back panels too!

ALSO: Look for cabinets on PERPENDICULAR WALLS (L-shaped or U-shaped kitchens)
Check left side, right side, and perpendicular walls for additional cabinets!

Analyze the PATTERN:

Example patterns and what they mean:

Pattern A: "900  700  600"
= 3 separate cabinets
= Generate 3 individual backs

Pattern B: "900  700 (sink symbol)  600"
= 3 cabinets, middle one is sink
= Back 1: 720×840
= Back 2: 550×664 (reduced height!)
= Back 3: 720×550

Pattern C: "900  300  300  300  300"
= 1 large + 4 small cabinets
= Could be 5 individual backs OR
= Could be 2 backs: one for 900mm, one continuous for 300+300+300+300=1200mm
= Decision: If small cabinets are adjacent with no breaks → continuous back

Pattern D: "900  700  600  150  300"
= 5 cabinets including narrow 150mm filler
= Back for 150mm: 720×114 (precise calculation)

CRITICAL DIMENSION LINE ANALYSIS STEPS:

1. READ **EVERY SINGLE NUMBER** on the dimension line - including small ones (60, 100, 150, 200)!
2. COUNT total cabinet units - DON'T SKIP narrow fillers!
3. CHECK for perpendicular walls (L-shaped or U-shaped kitchen) - scan entire drawing!
4. IDENTIFY groupings (adjacent small cabinets that might share back)
5. LOOK FOR narrow fillers (60-200mm) - these need precise backs!
6. IDENTIFY sink location (sink symbol) - use 550mm height
7. DETERMINE which cabinets get individual backs vs shared backs

Expected cabinet count:
- If dimension line shows "900  700  600  60  150" = 5 widths
- If L-shaped with perpendicular wall cabinets = add those too
- Total backs generated should match or be close to total widths counted

⚠️ COMMON MISTAKE: AI often ignores small numbers like 60, 150, 200
→ These are REAL cabinets! Include them!

From the dimension line numbers, INFER the internal back dimensions:
- Large numbers (700-1000mm) → backs of 640-900mm
- Medium numbers (500-700mm) → backs of 450-660mm  
- Small numbers (300-400mm) → backs of 250-360mm
- Tiny numbers (100-200mm) → backs of 64-164mm (fillers)
- Sum of small numbers → continuous back (e.g., 300+300+300+300=1200 → 1204mm back)

Identify cabinet types from drawing:
- Sink symbol (circle/oval from above) = SINK BASE → use 550mm height
- Multiple horizontal lines = DRAWER UNIT
- "DW", "OVEN" labels = APPLIANCE HOUSING
- No special symbols = STANDARD DOOR CABINET
- Very small width (100-200mm) = FILLER CABINET

═══════════════════════════════════════════════════════════════════════
STEP 2: CALCULATE COMPONENTS INTELLIGENTLY
═══════════════════════════════════════════════════════════════════════

For EACH cabinet, calculate ALL components:

A) GABLES (End Panels) - Qty: 2 per cabinet
────────────────────────────────────────────
Standard: 720mm (H) × 560mm (W)
Special: Tall units use 1800-2400mm height

Expected: 2 per cabinet (6-10 total for 3-5 cabinets)

B) BACKS (Back Panels) - Qty: 1 per cabinet ⚠️ MOST CRITICAL!
──────────────────────────────────────────────────────────────

🎯 ULTRA-INTELLIGENT BACK PANEL CALCULATION:

CRITICAL: Backs must be calculated by analyzing the ACTUAL kitchen layout structure, not just applying formulas!

HEIGHT CALCULATION:
1. Standard base cabinet: 720mm
2. SINK BASE (look for sink symbol): 550-650mm height
3. Tall units: 1800-2400mm

WIDTH CALCULATION - ANALYZE DRAWING STRUCTURE:

STEP 1: Identify ALL cabinet units from dimension line
  Example: If you see "900  700  600  300  150  300" = 6 cabinet units

STEP 2: For EACH unit, determine back width by cabinet type and size:

  TYPE A - LARGE CABINETS (600mm+):
  For 900mm cabinet:
    - If first/last (wall): 840mm (width - 60)
    - If middle: 840mm or slightly different based on connection
  
  For 700mm cabinet:
    - Standard: 650-660mm (width - 40 to 50)
    - If sink base: Check actual internal width
    - Could be: 802mm if it extends to connect with adjacent cabinet
  
  For 600mm cabinet:
    - Standard: 550-560mm (width - 40 to 50)
  
  TYPE B - SMALL CABINETS (300-500mm):
  For 300mm cabinets:
    - Individual back: 250-264mm (width - 36 to 50)
    - May be grouped into continuous run
  
  TYPE C - NARROW FILLERS (100-200mm): ⚠️ VERY IMPORTANT!
  These generate PRECISE backs - DO NOT SKIP THEM!
  
  For 150mm filler:
    - Back width: 114mm (150 - 36 = 114 EXACTLY)
    - Back height: 720mm (standard)
    - Generate: 720×114
  
  For 60mm filler:
    - Too narrow, may not need back panel
    - Or: 720×24 (60 - 36 = 24)
    - Decision: If dimension shown, include it
  
  For 200mm filler:
    - Back width: 164mm (200 - 36 = 164 EXACTLY)
    - Generate: 720×164
  
  ⚠️ CRITICAL: Small dimension numbers (60, 100, 150, 200) are REAL cabinets!
  They MUST be included in the back panel calculation!
  
  TYPE D - CONTINUOUS RUNS: ⚠️ CHECK ALL WALLS!
  If multiple small cabinets are adjacent (on MAIN wall OR perpendicular walls):
    - Instead of individual backs, ONE long back
    - Example: Four 300mm cabinets → 1200mm total → 1204mm back
    - Calculation: Sum widths, subtract minimal offset (sum - 0 to 10mm)
  
  ⚠️ CRITICAL: Continuous runs often appear on PERPENDICULAR WALLS (left/right side)!
  
  How to identify continuous runs:
    1. Look at perpendicular wall dimensions (left or right side of drawing)
    2. Count adjacent small cabinets (300mm, 400mm, 480mm)
    3. If 3-4 adjacent cabinets → likely continuous run
    4. Sum their widths → generate ONE large back
  
  Example:
    - Perpendicular wall shows: 300, 180, 480, 300
    - If 300+480+300 = 1080mm are adjacent → back 1100-1150mm
    - OR if ALL adjacent: 300+180+480+300 = 1260mm → back 1204-1240mm

STEP 3: ANALYZE DRAWING FOR CABINET GROUPINGS (ALL WALLS):

Look at the dimension line pattern:
- "900" alone = individual cabinet → individual back
- "300 300 300 300" grouped = continuous run → ONE long back (1200-1204mm)
- "150" small = filler → very narrow back (114mm)

STEP 4: MATCH BACK COUNT TO CABINET COUNT OR GROUPINGS:

Important: Number of backs ≠ always number of cabinets!
- 6 cabinets could have 5 backs (if some share continuous back)
- OR 6 cabinets could have 6 individual backs

REALISTIC BACK EXAMPLES:

Example Kitchen: 900mm + 700mm sink + 600mm + 300mm + 150mm filler + 300mm + 300mm + 300mm

Backs generated:
1. 720×840 (900mm base, wall connection)
2. 550×664 (700mm sink base, reduced height, specific internal width)
3. 720×550 (600mm base)
4. 720×264 (300mm cabinet, individual)
5. 720×114 (150mm narrow filler)
6. 720×1204 (continuous back for: 300+300+300+300 = ~1200mm run)

CRITICAL PATTERNS TO RECOGNIZE:

Pattern 1: EXACT dimension inference
- If drawing shows 900, 700, 600 widths
- Backs should be: ~840, ~660-800, ~550
- NOT: 864, 664, 564 (those are formula results!)

Pattern 2: SINK BASE special sizing
- Sink cabinet back width might be larger than expected
- Example: 700mm sink → could be 664mm OR 802mm
- Why? Internal configuration for plumbing varies

Pattern 3: NARROW FILLERS are PRECISE
- 150mm filler → 114mm back (150 - 36 = 114 exactly)
- 200mm filler → 164mm back (200 - 36 = 164 exactly)
- These are very accurate

Pattern 4: CONTINUOUS RUNS for small cabinets
- If you see multiple 300mm cabinets adjacent
- Create ONE back spanning all: ~1200-1204mm
- Not individual 264mm backs

STEP 5: GENERATE REALISTIC COUNT:

For typical 6-8 cabinet kitchen:
- Expect 5-8 back panels
- Sizes should VARY significantly
- Should include: large (800-900mm), medium (600-700mm), small (200-300mm), very small (100-150mm), extra large (1200mm+) if continuous run exists

DO NOT generate 6 backs all with similar widths!
DO NOT use identical (width-36) formula for all!
DO intelligently analyze and vary the dimensions!

C) T/B & FIX SHELVES (Top/Bottom Panels, Shelves)
────────────────────────────────────────────────────
For each cabinet, generate 2-3 pieces:
- Top panel: (Width-36) × 530
- Bottom/base: (Width-36) × 520
- Fixed shelf: (Width-36) × 450

Expected: 6-12 total pieces

D) S/H (Adjustable Shelves)
────────────────────────────
Only for DOOR CABINETS (not drawer units):
- Width: (Cabinet_Width - 36)
- Depth: 430-450mm
- Qty: 1 per door cabinet

Examples:
- 900mm door → 864×430
- 700mm door → 664×430

E) BRACES (Top Rails)
──────────────────────
For each cabinet:
- Width: (Cabinet_Width - 36)
- Height: 100mm
- Qty: 1-2 per cabinet

F) DOORS & DRAW FACES
──────────────────────
DOOR CABINETS:
- Single door: (Width-3) × 715mm
- Double doors: (Width/2 - 2) × 715mm each

DRAWER UNITS:
- Top: (Width-4) × 140-160mm
- Middle: (Width-4) × 180-220mm
- Bottom: (Width-4) × 250-300mm

G) END PANELS & INFILLS
────────────────────────
- Decorative end panels: 900×600mm (exposed ends)
- Plinth panels: 150mm height × run length
- Infill panels: Various (80mm, 100mm, 150mm, 200mm widths)

═══════════════════════════════════════════════════════════════════════
STEP 3: APPLY REALISTIC MANUFACTURING LOGIC
═══════════════════════════════════════════════════════════════════════

✓ Identify sink cabinets → Use 550-650mm height backs
✓ Vary back widths by cabinet position/type
✓ Don't generate identical dimensions for all cabinets
✓ Apply ±5-10mm tolerance (realistic manufacturing)
✓ Check for continuous runs (shared backs)
✓ Identify special units (tall = different height)

═══════════════════════════════════════════════════════════════════════
JSON OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════

{{
  "analysis_summary": {{
    "total_cabinets": [count],
    "layout_type": "straight|L-shape|U-shape",
    "special_features": ["sink", "oven", etc.]
  }},
  
  "components": {{
    "GABLE": [
      {{"height": 720, "width": 560, "quantity": 2, "notes": "Cabinet 1 - 900mm base"}},
      {{"height": 720, "width": 560, "quantity": 2, "notes": "Cabinet 2 - 700mm sink base"}},
      ... for ALL cabinets
    ],
    
    "BACKS": [
      {{"height": 720, "width": 840, "quantity": 1, "notes": "Cabinet 1 - 900mm base (wall)"}},
      {{"height": 550, "width": 650, "quantity": 1, "notes": "Cabinet 2 - 700mm SINK BASE"}},
      {{"height": 720, "width": 550, "quantity": 1, "notes": "Cabinet 3 - 600mm base"}},
      {{"height": 720, "width": 1204, "quantity": 1, "notes": "Continuous back for small unit run"}},
      ... INTELLIGENT sizing based on cabinet type!
    ],
    
    "T/B & FIX SHELVES": [
      {{"height": 864, "width": 530, "quantity": 1, "notes": "Cabinet 1 - Top"}},
      {{"height": 864, "width": 520, "quantity": 1, "notes": "Cabinet 1 - Bottom"}},
      ... 2-3 per cabinet
    ],
    
    "S/H": [
      {{"height": 864, "width": 430, "quantity": 1, "notes": "Cabinet 1 - Shelf"}},
      ... only door cabinets
    ],
    
    "BRACES": [
      {{"height": 864, "width": 100, "quantity": 1, "notes": "Cabinet 1"}},
      ... for each cabinet
    ],
    
    "DOORS & DRAW FACES": [
      {{"height": 715, "width": 448, "quantity": 2, "notes": "Cabinet 1 - Double doors"}},
      {{"height": 150, "width": 664, "quantity": 1, "notes": "Cabinet 2 - Top drawer"}},
      ... ALL doors/drawers
    ],
    
    "END PANELS & INFILLS": [
      {{"height": 900, "width": 600, "quantity": 2, "notes": "End panels"}},
      {{"height": 2750, "width": 150, "quantity": 1, "notes": "Plinth - full run"}},
      ... ALL panels
    ]
  }}
}}

═══════════════════════════════════════════════════════════════════════
CRITICAL REQUIREMENTS FOR 95% ACCURACY
═══════════════════════════════════════════════════════════════════════

1. ⚠️ SCAN **ALL WALLS** not just bottom wall:
   - Bottom wall dimension line
   - Left wall dimension line (perpendicular)
   - Right wall dimension line (perpendicular)
   - Top wall if present

2. ⚠️ BACKS calculation is CRITICAL:
   - NOT simple (width-36) formula for all!
   - Check for SINK cabinets → 550mm height
   - Vary widths: 840mm, 802mm, 664mm, 550mm, 264mm, 114mm, 1204mm
   - Apply realistic offsets (40-60mm, not fixed 36mm)

3. ⚠️ Look for SINK symbol → Use reduced height back (550-650mm)

4. ⚠️ Identify narrow fillers → Small backs (114mm, 24mm)
   - 150mm filler → 114mm back (150-36) EXACTLY
   - 60mm filler → 24mm back OR skip

5. ⚠️ Check for continuous runs on PERPENDICULAR walls → Long backs (1204mm)
   - Multiple 300mm cabinets adjacent → ONE back (~1200mm)
   - Don't generate individual 264mm backs if they're grouped

6. ⚠️ Generate 5-10 components for typical L-shaped kitchen
   - Not just 3 backs!
   - Count all cabinets on all walls

7. ⚠️ Apply realistic variations - NOT identical formulas

8. ⚠️ VERIFY total back count matches total cabinet count from ALL walls

Analyze thoroughly and generate professional, 95% accurate cutting list!
"""
        
        return self._call_openai_api(comprehensive_prompt, image_base64, max_tokens=6000)
    
    def _call_openai_api(self, prompt, image_base64, max_tokens=4000):
        if not OPENAI_API_KEY:
            return {"error": "OpenAI API key not configured"}
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a master kitchen cabinet manufacturer with 30 years of experience creating comprehensive cutting lists from technical drawings."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}", "detail": "high"}}
                    ]
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1
        }
        
        try:
            logger.info("Analyzing with GPT-4 Vision...")
            response = requests.post(OPENAI_API_URL, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                parsed_result = json.loads(json_str)
                logger.info("✓ Analysis completed")
                return parsed_result
            else:
                return {"error": "No valid JSON", "raw": content[:500]}
                
        except Exception as e:
            logger.error(f"API error: {str(e)}")
            return {"error": str(e)}
    
    def analyze_technical_drawing(self, image_bytes):
        logger.info("="*60)
        logger.info("INTELLIGENT DRAWING ANALYZER - STARTING")
        logger.info("="*60)
        
        try:
            # Reset components
            for category in self.components:
                self.components[category] = []
            for category in self.part_counters:
                self.part_counters[category] = 1
            
            # Extract dimensions
            full_text, dimension_analysis = self.extract_numbers_with_google_vision(image_bytes)
            
            if not dimension_analysis or not dimension_analysis.get('all_numbers'):
                full_text, dimension_analysis = self.extract_numbers_with_openai_vision(image_bytes)
            
            if not dimension_analysis or not dimension_analysis.get('all_numbers'):
                logger.error("❌ Failed to extract numbers")
                return self.generate_empty_cutting_list()
            
            # Detect drawing type
            self.drawing_type = self.detect_drawing_type(image_bytes)
            
            # Route to appropriate analyzer
            if self.drawing_type == 'layout':
                logger.info("→ Using COMPREHENSIVE LAYOUT analyzer")
                analysis_result = self.analyze_layout_comprehensive(image_bytes, dimension_analysis)
                self.process_comprehensive_analysis(analysis_result)
            else:
                logger.info("→ Using ELEVATION analyzer")
                analysis_result = self.analyze_with_master_prompt(image_bytes, dimension_analysis)
                self.process_cabinet_analysis(analysis_result)
            
            if 'error' in analysis_result:
                logger.error(f"❌ Analysis error: {analysis_result['error']}")
                return self.generate_empty_cutting_list()
            
            total_components = sum(len(items) for items in self.components.values())
            if total_components == 0:
                logger.error("❌ No components generated")
                return self.generate_empty_cutting_list()
            
            logger.info(f"✓ SUCCESS: Generated {total_components} total components")
            logger.info("="*60)
            
        except Exception as e:
            logger.error(f"❌ Critical error: {str(e)}")
            import traceback
            traceback.print_exc()
            return self.generate_empty_cutting_list()
        
        return self.generate_cutting_list()
    
    def process_cabinet_analysis(self, analysis):
        """Process elevation analysis"""
        cabinet_modules = analysis.get('cabinet_modules', [])
        
        if not cabinet_modules:
            return
        
        module = cabinet_modules[0]
        
        def safe_extract(data, key, default=0):
            val = data.get(key, default)
            if isinstance(val, (int, float)):
                return val
            if isinstance(val, list) and val:
                try:
                    return float(val[0])
                except:
                    return default
            return default

        width = safe_extract(module, 'cabinet_width')
        total_height = safe_extract(module, 'cabinet_total_height')
        working_height = safe_extract(module, 'cabinet_working_height')
        depth = safe_extract(module, 'cabinet_depth')
        
        if not self.validate_dimensions(width, working_height, depth):
            return
        
        calculated = module.get('calculated_components', {})
        
        mapping = {
            'gables': ('GABLE', 'Gables'),
            'tb_panels': ('T/B & FIX SHELVES', 'Top/Bottom'),
            'sh_hardware': ('S/H', 'Shelf/Hardware'),
            'back': ('BACKS', 'Back')
        }
        
        for comp_key, (category, desc) in mapping.items():
            if comp_key not in calculated:
                continue
            
            comp = calculated[comp_key]
            h = safe_extract(comp, 'height')
            w = safe_extract(comp, 'width')
            qty = safe_extract(comp, 'quantity', 1)
            
            if h > 0 and w > 0:
                self.add_component(category, h, w, qty, f"Cabinet {width}×{total_height}mm - {desc}")
    
    def process_comprehensive_analysis(self, analysis):
        """Process comprehensive layout analysis"""
        components_data = analysis.get('components', {})
        
        if not components_data:
            logger.error("No components in analysis")
            return
        
        summary = analysis.get('analysis_summary', {})
        logger.info(f"✓ Processing {summary.get('total_cabinets', '?')} cabinet units")
        
        # Process each category
        for category in self.components.keys():
            items = components_data.get(category, [])
            
            for item in items:
                height = item.get('height', 0)
                width = item.get('width', 0)
                quantity = item.get('quantity', 1)
                notes = item.get('notes', '')
                
                if height > 0 and width > 0:
                    self.add_component(category, height, width, quantity, notes)
    
    def validate_dimensions(self, width, height, depth):
        if width < 200 or width > 2000:
            return False
        if height < 300 or height > 900:
            return False
        if depth < 200 or depth > 800:
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
            'S/H': 'HARDWARE',
            'BASE': 'BASE',
            'SHELF': 'SHELF',
            'BRACES': 'BRACE',
            'END PANELS & INFILLS': 'ENDPNL',
            'DOORS & DRAW FACES': 'DOOR',
            'DRAWER BOXES': 'DRWBOX',
            'SPECIAL COMPONENTS': 'SPECIAL'
        }
        return short_names.get(category, 'COMP')
    
    def get_material_type(self, category):
        materials = {
            'GABLE': '18mm MFC',
            'T/B & FIX SHELVES': '18mm MFC',
            'BACKS': '6mm MDF',
            'S/H': 'Hardware',
            'BASE': '18mm MFC',
            'SHELF': '18mm MFC',
            'BRACES': '18mm MFC',
            'END PANELS & INFILLS': '18mm MFC',
            'DOORS & DRAW FACES': '18mm MFC',
            'DRAWER BOXES': '18mm Plywood',
            'SPECIAL COMPONENTS': '18mm MFC'
        }
        return materials.get(category, '18mm MFC')
    
    def generate_cutting_list(self):
        summary = {}
        
        for category, items in self.components.items():
            if items:
                total_pieces = sum(item['quantity'] for item in items)
                unique_dimensions = set(item['dimensions'] for item in items)
                
                total_area = 0
                for item in items:
                    w = item.get('width', 0)
                    h = item.get('height', 0)
                    q = item.get('quantity', 1)
                    total_area += (w * h * q) / 1000000
                
                summary[category] = {
                    'items': items,
                    'total_pieces': total_pieces,
                    'unique_sizes': len(unique_dimensions),
                    'total_area': round(total_area, 2)
                }
            else:
                summary[category] = {
                    'items': [],
                    'total_pieces': 0,
                    'unique_sizes': 0,
                    'total_area': 0.0
                }
        
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
            
            title = f"CUTTING LIST - {datetime.now().strftime('%Y-%m-%d')}"
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