"""
OCR Dimension Extractor using Anthropic Claude API
Replaces EasyOCR/Tesseract with Claude's vision capabilities
"""
import anthropic
import base64
import os
import json
from typing import Dict, List, Optional
from PIL import Image
import io
import logging

logger = logging.getLogger(__name__)


class AnthropicExtractor:
    """
    Extract cabinet dimensions and details using Claude 3.5 Sonnet
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        """
        Initialize Anthropic API client
        
        Args:
            api_key: Anthropic API key (reads from ANTHROPIC_API_KEY env var if not provided)
            model: Claude model to use
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        
        if not self.api_key:
            raise ValueError(
                "Anthropic API key not found. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter"
            )
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model
        
        logger.info(f"✅ Anthropic API initialized with model: {model}")
    
    def extract_dimensions(self, image_bytes: bytes) -> Dict:
        """
        Extract cabinet dimensions from technical drawing
        
        Args:
            image_bytes: Image file bytes (JPEG, PNG, etc.)
            
        Returns:
            Dict with structure:
            {
                'success': bool,
                'method': 'anthropic_claude',
                'cabinets': [
                    {
                        'cabinet_id': str,
                        'width': int (mm),
                        'height': int (mm),
                        'depth': int (mm),
                        'type': str ('base', 'wall', 'tall', 'corner'),
                        'features': {
                            'shelves': int,
                            'drawers': int,
                            'doors': int,
                            'notes': str
                        }
                    }
                ],
                'confidence': float (0-1),
                'raw_response': str
            }
        """
        
        logger.info("🤖 Sending image to Claude API for extraction...")
        
        try:
            # Encode image to base64
            image_base64 = base64.standard_b64encode(image_bytes).decode('utf-8')
            
            # Determine media type
            media_type = self._detect_media_type(image_bytes)
            
            # Create the prompt
            prompt = self._create_extraction_prompt()
            
            # Call Claude API
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )
            
            # Extract response text
            response_text = message.content[0].text
            
            logger.info(f"✅ Claude API response received ({len(response_text)} chars)")
            logger.debug(f"Raw response: {response_text[:500]}...")
            
            # Parse JSON response
            result = self._parse_response(response_text)
            
            # Add metadata
            result['method'] = 'anthropic_claude'
            result['model'] = self.model
            result['raw_response'] = response_text
            
            # Calculate confidence
            if result.get('success'):
                result['confidence'] = self._calculate_confidence(result)
            
            logger.info(f"📊 Extracted {len(result.get('cabinets', []))} cabinets")
            
            return result
            
        except anthropic.APIError as e:
            logger.error(f"❌ Anthropic API error: {e}")
            return {
                'success': False,
                'method': 'anthropic_claude',
                'error': f"API error: {str(e)}",
                'cabinets': [],
                'confidence': 0.0
            }
        
        except Exception as e:
            logger.error(f"❌ Extraction failed: {e}", exc_info=True)
            return {
                'success': False,
                'method': 'anthropic_claude',
                'error': str(e),
                'cabinets': [],
                'confidence': 0.0
            }
    
    def _create_extraction_prompt(self) -> str:
        """Create the system prompt for Claude"""
        
        return """You are analyzing kitchen/wardrobe cabinet drawings. These can be FLOOR PLANS (top-down view) or ELEVATIONS (front/side view).

**STEP 1: IDENTIFY DRAWING TYPE**

**FLOOR PLAN** indicators:
- Top-down view showing room layout
- Dimension lines at top and bottom showing cabinet widths
- May show appliances (sink, stove, etc.)
- Example dimensions: "900 | 700 | 600" along bottom edge

**ELEVATION** indicators:
- Front or side view showing cabinet faces
- Shows actual heights and widths
- May show doors, drawers, handles
- Vertical dimension lines

**STEP 2: EXTRACT BASED ON TYPE**

## FOR FLOOR PLANS:

**Extract cabinet widths from dimension lines:**
- Look for dimension breakdowns along edges (e.g., "900", "700", "600")
- These numbers represent individual cabinet widths
- Add up segments to verify total width

**Apply KITCHEN STANDARD FORMULAS:**
- Height: **720mm** (standard base cabinet gable height)
- Depth: **560mm** (internal depth)
- Overall depth: 600mm (560 + 20mm door + 20mm overhang)

**Cabinet identification:**
- Each width segment = one cabinet
- Number cabinets left to right: CAB-1, CAB-2, CAB-3...
- Look for cabinet numbers if labeled (1, 2, 3, etc.)

**Example floor plan extraction:**
```
Bottom dimensions show: 900 | 700 | 600
Extract as:
- CAB-1: 900mm wide × 720mm high × 560mm deep
- CAB-2: 700mm wide × 720mm high × 560mm deep
- CAB-3: 600mm wide × 720mm high × 560mm deep
```

## FOR ELEVATIONS:

**Extract actual dimensions shown:**
- Width: From horizontal dimension lines
- Height: From vertical dimension lines
- Depth: May not be shown (use 560mm default for kitchens)

**Count visible features:**
- Doors: Rectangular outlines with handles
- Drawers: Horizontal divisions with handles
- Shelves: Internal horizontal lines

**STEP 3: DETERMINE FEATURES**

For ALL cabinets:
- **Shelves**: 1 (standard - one adjustable shelf)
- **Drawers**: Count if visible in drawing, else 0
- **Doors**: 
  - Cabinet width < 450mm: 1 door
  - Cabinet width >= 450mm: Assume 2 doors unless shown otherwise
  - If drawers visible, set doors = 0

**SPECIAL CASES:**
- L-corner cabinets: type = "corner", note in features
- Tall cabinets (height > 1500mm): type = "tall"
- Narrow panels (width < 200mm): type = "filler"
- Drawer units (3+ drawers): doors = 0, count drawers

**OUTPUT FORMAT:**
Return ONLY valid JSON (no markdown, no explanations):

```json
{
  "drawing_type": "floor_plan" or "elevation",
  "cabinets": [
    {
      "cabinet_id": "CAB-1",
      "width": 900,
      "height": 720,
      "depth": 560,
      "type": "base",
      "features": {
        "shelves": 1,
        "drawers": 0,
        "doors": 2,
        "notes": ""
      }
    }
  ],
  "drawing_notes": "Brief description of what you see",
  "extraction_confidence": "high" | "medium" | "low"
}
```

**CRITICAL RULES:**
- For floor plans: ALWAYS use height=720, depth=560
- Extract ALL cabinet widths from dimension lines
- Number cabinets sequentially (CAB-1, CAB-2, etc.)
- If you see numbered cabinets (1, 2, 3...), match those numbers
- Widths must match dimension breakdown exactly
- All dimensions in millimeters

**If extraction fails:**
```json
{
  "drawing_type": "unknown",
  "cabinets": [],
  "drawing_notes": "Reason for failure",
  "extraction_confidence": "failed"
}
```

Analyze the image and return ONLY the JSON."""
    
    def _detect_media_type(self, image_bytes: bytes) -> str:
        """Detect image format from bytes"""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            format_map = {
                'JPEG': 'image/jpeg',
                'PNG': 'image/png',
                'GIF': 'image/gif',
                'WEBP': 'image/webp'
            }
            return format_map.get(img.format, 'image/jpeg')
        except:
            return 'image/jpeg'  # Default
    
    def _parse_response(self, response_text: str) -> Dict:
        """
        Parse Claude's JSON response
        
        Args:
            response_text: Raw text response from Claude
            
        Returns:
            Parsed dict with cabinets
        """
        try:
            # Try to find JSON in the response
            # Sometimes Claude wraps it in ```json ... ```
            
            # Remove markdown code blocks if present
            text = response_text.strip()
            if text.startswith('```'):
                # Find the actual JSON
                lines = text.split('\n')
                json_lines = []
                in_json = False
                
                for line in lines:
                    if line.startswith('```'):
                        if in_json:
                            break
                        in_json = True
                        continue
                    if in_json:
                        json_lines.append(line)
                
                text = '\n'.join(json_lines)
            
            # Parse JSON
            data = json.loads(text)
            
            # Validate structure
            if 'cabinets' not in data:
                raise ValueError("Response missing 'cabinets' field")
            
            # Validate each cabinet
            for cab in data['cabinets']:
                required = ['cabinet_id', 'width', 'height', 'depth', 'type']
                for field in required:
                    if field not in cab:
                        raise ValueError(f"Cabinet missing required field: {field}")
            
            return {
                'success': True,
                'cabinets': data['cabinets'],
                'drawing_notes': data.get('drawing_notes', ''),
                'extraction_confidence': data.get('extraction_confidence', 'medium')
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Response text: {response_text}")
            
            # Try to extract dimensions from text as fallback
            return self._fallback_text_extraction(response_text)
        
        except Exception as e:
            logger.error(f"Response parsing error: {e}")
            return {
                'success': False,
                'error': f"Failed to parse response: {str(e)}",
                'cabinets': []
            }
    
    def _fallback_text_extraction(self, text: str) -> Dict:
        """
        Fallback: Try to extract dimensions from text if JSON parsing fails
        
        Args:
            text: Raw response text
            
        Returns:
            Dict with extracted cabinets (if any)
        """
        import re
        
        logger.warning("⚠️ JSON parsing failed, attempting text extraction...")
        
        # Look for dimension patterns
        # Example: "600mm × 720mm × 560mm" or "W:600 H:720 D:560"
        
        cabinets = []
        
        # Pattern 1: "600 × 720 × 560"
        pattern1 = r'(\d{3,4})\s*[×x]\s*(\d{3,4})\s*[×x]\s*(\d{3,4})'
        matches = re.findall(pattern1, text)
        
        for i, match in enumerate(matches):
            w, h, d = map(int, match)
            if 200 <= w <= 2000 and 300 <= h <= 3000 and 300 <= d <= 1000:
                cabinets.append({
                    'cabinet_id': f'CAB-{i+1}',
                    'width': w,
                    'height': h,
                    'depth': d,
                    'type': 'base' if h < 1000 else 'tall',
                    'features': {
                        'shelves': 1,
                        'drawers': 0,
                        'doors': 1,
                        'notes': 'Extracted from text'
                    }
                })
        
        if cabinets:
            logger.info(f"✅ Fallback extraction found {len(cabinets)} cabinets")
            return {
                'success': True,
                'cabinets': cabinets,
                'drawing_notes': 'Extracted using fallback text parsing',
                'extraction_confidence': 'low'
            }
        
        return {
            'success': False,
            'error': 'Could not extract dimensions from response',
            'cabinets': []
        }
    
    def _calculate_confidence(self, result: Dict) -> float:
        """
        Calculate overall confidence score
        
        Args:
            result: Extraction result dict
            
        Returns:
            Confidence score (0-1)
        """
        confidence_map = {
            'high': 0.9,
            'medium': 0.7,
            'low': 0.5,
            'failed': 0.0
        }
        
        extraction_conf = result.get('extraction_confidence', 'medium')
        base_confidence = confidence_map.get(extraction_conf, 0.7)
        
        # Adjust based on number of cabinets found
        num_cabinets = len(result.get('cabinets', []))
        if num_cabinets == 0:
            return 0.0
        elif num_cabinets > 5:
            base_confidence = min(1.0, base_confidence + 0.1)  # Bonus for complex drawings
        
        return base_confidence


# Deprecated/fallback OCR methods (kept for compatibility)
class LegacyOCRExtractor:
    """
    Legacy OCR extraction using EasyOCR/Tesseract
    DEPRECATED: Use AnthropicExtractor instead
    """
    
    def __init__(self):
        logger.warning("⚠️ LegacyOCRExtractor is deprecated. Use AnthropicExtractor instead.")
        self.available = False
    
    def extract_dimensions(self, image_bytes: bytes) -> Dict:
        """Legacy method - returns error"""
        return {
            'success': False,
            'method': 'legacy_ocr',
            'error': 'Legacy OCR is deprecated. Use Anthropic API.',
            'cabinets': [],
            'confidence': 0.0
        }