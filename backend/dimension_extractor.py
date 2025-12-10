"""
Dimension Extractor for Kitchen Layout Drawings
Extracts cabinet widths from dimension lines using Claude Sonnet 4
"""

import anthropic
import base64
import json
import logging
import os

logger = logging.getLogger('DimensionExtractor')

class DimensionExtractor:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            self.client = None
            logger.warning("Anthropic API key not found")
    
    def extract_dimensions_from_layout(self, image_bytes):
        """
        Extract cabinet dimensions from kitchen layout drawing
        Returns: List of cabinet widths in order
        """
        if not self.client:
            return {"error": "Anthropic client not initialized"}
        
        try:
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            prompt = """You are analyzing a kitchen layout drawing (top-down view).

TASK: Extract ALL cabinet widths from the main dimension line at the bottom of the drawing.

EXAMPLE:
If you see a dimension line showing: "2410" with segments "900  700  600  60  150"
You should extract: [900, 700, 600, 60, 150]

INSTRUCTIONS:
1. Look for the MAIN DIMENSION LINE at the bottom of the drawing
2. This line shows the total width (e.g., 2410mm, 2130mm)
3. Below it are INDIVIDUAL SEGMENTS showing each cabinet width
4. Extract EVERY number from left to right in ORDER
5. Include fillers (small widths like 60mm, 150mm)
6. Also note the DEPTH dimension (perpendicular line, usually 600mm or 900mm)

Return ONLY a JSON object:
{
    "total_width": 2410,
    "cabinet_widths": [900, 700, 600, 60, 150],
    "detected_depth": 600,
    "cabinet_count": 5,
    "notes": "Brief description of layout (L-shaped, straight, etc.)"
}

Be precise. Extract EVERY segment width in order from left to right."""

            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
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
                                "text": prompt
                            }
                        ]
                    }
                ]
            )
            
            content = message.content[0].text
            
            # Extract JSON
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)
                
                logger.info(f"Extracted {len(result.get('cabinet_widths', []))} cabinet dimensions")
                
                # Auto-assign cabinet types based on width
                cabinets = []
                for i, width in enumerate(result.get('cabinet_widths', [])):
                    cabinet_type = self._guess_cabinet_type(width)
                    cabinets.append({
                        'id': i + 1,
                        'width': width,
                        'type': cabinet_type,
                        'height': 720,  # Standard base unit height
                        'depth': result.get('detected_depth', 560)  # Standard or detected
                    })
                
                return {
                    'success': True,
                    'total_width': result.get('total_width'),
                    'cabinets': cabinets,
                    'layout_notes': result.get('notes', ''),
                    'raw_extraction': result
                }
            else:
                return {"error": "No valid JSON in response"}
                
        except Exception as e:
            logger.error(f"Extraction error: {str(e)}")
            return {"error": str(e)}
    
    def _guess_cabinet_type(self, width):
        """
        Guess cabinet type based on width
        These are common patterns but user can override
        """
        if width <= 100:
            return 'filler'
        elif width <= 300:
            return 'narrow'
        elif width <= 500:
            return 'drawer_base'
        elif 600 <= width <= 700:
            return 'sink_base'
        elif 700 <= width <= 1000:
            return 'standard_base'
        else:
            return 'wide_base'