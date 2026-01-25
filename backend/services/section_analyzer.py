"""
Section Analyzer
Transforms Claude API JSON output into format expected by CuttingListBuilder
"""
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class SectionAnalyzer:
    """
    Transform Claude's cabinet extraction into structured cabinet objects
    """
    
    def __init__(self):
        pass
    
    def transform_extraction(self, extraction_result: Dict) -> List[Dict]:
        """
        Transform Claude's extraction result into cabinet dictionaries
        
        Args:
            extraction_result: Dict from AnthropicExtractor with structure:
                {
                    'success': bool,
                    'cabinets': [
                        {
                            'cabinet_id': str,
                            'width': int,
                            'height': int,
                            'depth': int,
                            'type': str,
                            'features': {...}
                        }
                    ]
                }
        
        Returns:
            List of cabinet dicts ready for CuttingListBuilder:
            [
                {
                    'cabinet_id': str,
                    'width': int,
                    'height': int,
                    'depth': int,
                    'cabinet_type': str,
                    'shelves': int,
                    'drawers': int,
                    'doors': int,
                    'notes': str
                }
            ]
        """
        
        if not extraction_result.get('success'):
            logger.error("❌ Extraction failed, cannot transform")
            return []
        
        cabinets_raw = extraction_result.get('cabinets', [])
        
        if not cabinets_raw:
            logger.warning("⚠️ No cabinets found in extraction")
            return []
        
        logger.info(f"🔄 Transforming {len(cabinets_raw)} cabinets...")
        
        transformed = []
        
        for cab in cabinets_raw:
            try:
                transformed_cab = self._transform_single_cabinet(cab)
                transformed.append(transformed_cab)
                
                logger.debug(f"   ✓ {transformed_cab['cabinet_id']}: "
                           f"{transformed_cab['width']}×{transformed_cab['height']}×{transformed_cab['depth']}mm")
                
            except Exception as e:
                logger.error(f"Failed to transform cabinet {cab.get('cabinet_id', 'unknown')}: {e}")
                continue
        
        logger.info(f"✅ Transformed {len(transformed)} cabinets")
        
        return transformed
    
    def _transform_single_cabinet(self, cabinet: Dict) -> Dict:
        """
        Transform a single cabinet from Claude's format to CuttingListBuilder format
        
        Args:
            cabinet: Raw cabinet dict from Claude
            
        Returns:
            Transformed cabinet dict
        """
        
        # Extract features
        features = cabinet.get('features', {})
        
        # Map cabinet type
        cabinet_type = self._normalize_cabinet_type(cabinet.get('type', 'base'))
        
        # Validate dimensions
        width = int(cabinet['width'])
        height = int(cabinet['height'])
        depth = int(cabinet['depth'])
        
        if not self._validate_dimensions(width, height, depth, cabinet_type):
            logger.warning(f"⚠️ Unusual dimensions for {cabinet['cabinet_id']}: "
                         f"{width}×{height}×{depth}mm")
        
        return {
            'cabinet_id': cabinet['cabinet_id'],
            'width': width,
            'height': height,
            'depth': depth,
            'cabinet_type': cabinet_type,
            'shelves': int(features.get('shelves', 1)),
            'drawers': int(features.get('drawers', 0)),
            'doors': int(features.get('doors', 1)),
            'notes': features.get('notes', '')
        }
    
    def _normalize_cabinet_type(self, raw_type: str) -> str:
        """
        Normalize cabinet type to standard values
        
        Args:
            raw_type: Type from Claude (e.g., 'base', 'wall', 'tall')
            
        Returns:
            Normalized type
        """
        type_map = {
            'base': 'base',
            'wall': 'wall',
            'tall': 'tall',
            'pantry': 'tall',
            'corner': 'corner',
            'filler': 'filler',
            'drawer': 'drawer'
        }
        
        normalized = type_map.get(raw_type.lower(), 'base')
        
        if normalized != raw_type:
            logger.debug(f"Normalized type: {raw_type} → {normalized}")
        
        return normalized
    
    def _validate_dimensions(self, width: int, height: int, depth: int, 
                           cabinet_type: str) -> bool:
        """
        Validate cabinet dimensions are reasonable
        
        Args:
            width: Cabinet width (mm)
            height: Cabinet height (mm)
            depth: Cabinet depth (mm)
            cabinet_type: Type of cabinet
            
        Returns:
            True if dimensions seem valid
        """
        
        # Basic range checks
        if not (100 <= width <= 2000):
            return False
        if not (200 <= height <= 3000):
            return False
        if not (200 <= depth <= 1000):
            return False
        
        # Type-specific checks
        if cabinet_type == 'base':
            # Base cabinets: height 600-900mm, depth 500-650mm
            if not (600 <= height <= 900):
                logger.debug(f"Base cabinet height {height}mm outside typical range (600-900mm)")
            if not (500 <= depth <= 650):
                logger.debug(f"Base cabinet depth {depth}mm outside typical range (500-650mm)")
        
        elif cabinet_type == 'wall':
            # Wall cabinets: height 500-900mm, depth 300-400mm
            if not (500 <= height <= 900):
                logger.debug(f"Wall cabinet height {height}mm outside typical range (500-900mm)")
            if not (300 <= depth <= 400):
                logger.debug(f"Wall cabinet depth {depth}mm outside typical range (300-400mm)")
        
        elif cabinet_type == 'tall':
            # Tall cabinets: height 1500-2500mm
            if not (1500 <= height <= 2500):
                logger.debug(f"Tall cabinet height {height}mm outside typical range (1500-2500mm)")
        
        elif cabinet_type == 'filler':
            # Fillers: width < 200mm
            if width >= 200:
                logger.debug(f"Filler width {width}mm >= 200mm (not typical for filler)")
        
        return True
    
    def add_metadata(self, cabinets: List[Dict], extraction_result: Dict) -> List[Dict]:
        """
        Add extraction metadata to cabinet dictionaries
        
        Args:
            cabinets: Transformed cabinet dicts
            extraction_result: Original extraction result
            
        Returns:
            Cabinets with added metadata
        """
        
        metadata = {
            'extraction_method': extraction_result.get('method', 'unknown'),
            'extraction_confidence': extraction_result.get('confidence', 0.0),
            'drawing_notes': extraction_result.get('drawing_notes', '')
        }
        
        for cab in cabinets:
            cab['metadata'] = metadata.copy()
        
        return cabinets
    
    def validate_extraction(self, extraction_result: Dict) -> Dict:
        """
        Validate extraction result before transformation
        
        Args:
            extraction_result: Raw extraction from API
            
        Returns:
            Validation result dict:
            {
                'valid': bool,
                'errors': List[str],
                'warnings': List[str]
            }
        """
        
        errors = []
        warnings = []
        
        # Check success flag
        if not extraction_result.get('success'):
            errors.append("Extraction failed")
            return {'valid': False, 'errors': errors, 'warnings': warnings}
        
        # Check cabinets present
        cabinets = extraction_result.get('cabinets', [])
        if not cabinets:
            errors.append("No cabinets extracted")
            return {'valid': False, 'errors': errors, 'warnings': warnings}
        
        # Validate each cabinet
        for i, cab in enumerate(cabinets):
            cab_id = cab.get('cabinet_id', f'Cabinet-{i}')
            
            # Required fields
            required = ['cabinet_id', 'width', 'height', 'depth', 'type']
            for field in required:
                if field not in cab:
                    errors.append(f"{cab_id}: Missing required field '{field}'")
            
            # Dimension validation
            try:
                w = int(cab.get('width', 0))
                h = int(cab.get('height', 0))
                d = int(cab.get('depth', 0))
                
                if w <= 0 or h <= 0 or d <= 0:
                    errors.append(f"{cab_id}: Invalid dimensions ({w}×{h}×{d})")
                
                if w > 2000:
                    warnings.append(f"{cab_id}: Width {w}mm is unusually large")
                if h > 3000:
                    warnings.append(f"{cab_id}: Height {h}mm is unusually large")
                if d > 1000:
                    warnings.append(f"{cab_id}: Depth {d}mm is unusually large")
                
            except (ValueError, TypeError):
                errors.append(f"{cab_id}: Dimensions are not valid integers")
        
        # Check confidence
        confidence = extraction_result.get('confidence', 0)
        if confidence < 0.5:
            warnings.append(f"Low extraction confidence: {confidence:.1%}")
        
        is_valid = len(errors) == 0
        
        if warnings:
            logger.warning(f"⚠️ Validation warnings: {', '.join(warnings)}")
        
        if errors:
            logger.error(f"❌ Validation errors: {', '.join(errors)}")
        
        return {
            'valid': is_valid,
            'errors': errors,
            'warnings': warnings
        }