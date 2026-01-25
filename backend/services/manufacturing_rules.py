"""
Manufacturing Rules for Cabinet Construction
Supports: Base Cabinets, Wall Cabinets, Tall Cabinets, Wardrobes
Based on client specifications and universal formulas
"""
from dataclasses import dataclass
from typing import Literal, Dict, List


@dataclass
class ConstructionStyle:
    """Construction style parameters"""
    
    # Material thicknesses
    material_thickness: int = 18  # Standard panel thickness (mm)
    back_thickness: int = 6  # Back panel thickness (mm)
    
    # Cabinet type
    cabinet_type: Literal["base", "wall", "tall", "wardrobe"] = "base"
    
    # Base cabinet specific
    toe_kick_height: int = 150  # Kitchen base cabinets
    
    # Wardrobe specific  
    wardrobe_toe_kick: int = 100  # Bedroom wardrobes
    
    # Gaps and clearances
    door_gap: int = 2  # Gap around doors (mm)
    back_construction_mode: Literal["overlay", "inset"] = "overlay"


class CabinetTypeDetector:
    """Detect cabinet type from dimensions"""
    
    @staticmethod
    def detect_type(width: int, height: int, depth: int) -> str:
        """
        Detect cabinet type from dimensions
        
        Args:
            width: Cabinet width (mm)
            height: Cabinet height (mm)
            depth: Cabinet depth (mm)
            
        Returns:
            Cabinet type: "base", "wall", "tall", "wardrobe"
        """
        
        # Tall cabinets (pantry, oven housing, floor-to-ceiling)
        if height > 1500:
            return "tall"
        
        # Wall cabinets (mounted on wall, above countertop)
        # Typically: 300-900mm height, 300-350mm depth
        if height <= 900 and depth <= 400:
            return "wall"
        
        # Wardrobes (bedroom fitted wardrobes)
        # Typically: very deep (560-600mm), variable height
        if depth >= 560 and height > 1500:
            return "wardrobe"
        
        # Base cabinets (default)
        # Typically: 720mm height, 560-600mm depth
        return "base"


class ComponentCalculator:
    """
    Calculate component dimensions for different cabinet types
    Uses universal formulas from client specifications
    """
    
    def __init__(self, style: ConstructionStyle = None):
        """
        Initialize calculator with construction style
        
        Args:
            style: ConstructionStyle parameters
        """
        self.style = style or ConstructionStyle()
        
    def calculate_base_cabinet(self, width: int) -> Dict:
        """
        Calculate BASE CABINET components (kitchen floor cabinets)
        
        Universal Formula from Client:
        - Height: 720mm (fixed)
        - Overall depth: 600mm
        - Internal depth: 560mm
        - Usable depth: 500mm (after 40mm back gap + 20mm backing)
        - Toe kick: 150mm
        
        Components:
        1. Gables: 720 × 560 (2 pcs)
        2. T/B: (W-36) × 500 (2 pcs)
        3. S/H: (W-36) × 500 (1 pc)
        4. Back: 720 × (W-36) (1 pc)
        5. Braces: (W-36) × 100 (1 pc, top only)
        
        Args:
            width: Cabinet width (mm)
            
        Returns:
            Dict with all component dimensions
        """
        
        # Fixed dimensions for base cabinets
        GABLE_HEIGHT = 720
        GABLE_DEPTH = 560
        PANEL_DEPTH = 500  # After 40mm+20mm gaps
        BRACE_HEIGHT = 100
        
        # Internal width (subtract 18mm each side)
        internal_width = width - (self.style.material_thickness * 2)  # W - 36
        
        return {
            "type": "base",
            "overall": {
                "width": width,
                "height": GABLE_HEIGHT,
                "depth": 600,  # Overall depth
                "internal_width": internal_width,
                "internal_depth": GABLE_DEPTH
            },
            "gables": {
                "width": GABLE_DEPTH,  # Depth becomes width when viewed from side
                "height": GABLE_HEIGHT,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "GABLE"
            },
            "top_bottom": {
                "width": internal_width,
                "depth": PANEL_DEPTH,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "T/B"
            },
            "shelves": {
                "width": internal_width,
                "depth": PANEL_DEPTH,
                "thickness": self.style.material_thickness,
                "quantity": 1,
                "component_type": "S/H"
            },
            "back": {
                "width": internal_width,
                "height": GABLE_HEIGHT,
                "thickness": self.style.back_thickness,
                "quantity": 1,
                "component_type": "BACKS"
            },
            "braces": {
                "width": internal_width,
                "height": BRACE_HEIGHT,
                "thickness": self.style.material_thickness,
                "quantity": 1,
                "component_type": "BRACES",
                "notes": "Top only - hollow basis"
            }
        }
    
    def calculate_wall_cabinet(self, width: int, height: int = 720) -> Dict:
        """
        Calculate WALL CABINET components (mounted on wall, above countertop)
        
        Typical Wall Cabinet:
        - Height: 600-900mm (variable, default 720mm)
        - Depth: 300-350mm (shallower than base)
        - No toe kick
        - Similar construction to base but shallower
        
        Components:
        1. Gables: H × 300 (2 pcs)
        2. T/B: (W-36) × 280 (2 pcs) - 20mm back gap
        3. S/H: (W-36) × 280 (1-2 pcs)
        4. Back: H × (W-36) (1 pc)
        5. Braces: (W-36) × 100 (2 pcs - top AND bottom for wall mounting)
        
        Args:
            width: Cabinet width (mm)
            height: Cabinet height (mm, default 720)
            
        Returns:
            Dict with all component dimensions
        """
        
        GABLE_DEPTH = 300  # Shallower than base
        PANEL_DEPTH = 280  # After 20mm back gap
        BRACE_HEIGHT = 100
        
        internal_width = width - (self.style.material_thickness * 2)
        
        # Number of shelves based on height
        shelf_count = 1 if height <= 700 else 2
        
        return {
            "type": "wall",
            "overall": {
                "width": width,
                "height": height,
                "depth": 320,  # Overall depth (300 + 20mm door)
                "internal_width": internal_width,
                "internal_depth": GABLE_DEPTH
            },
            "gables": {
                "width": GABLE_DEPTH,
                "height": height,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "GABLE"
            },
            "top_bottom": {
                "width": internal_width,
                "depth": PANEL_DEPTH,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "T/B"
            },
            "shelves": {
                "width": internal_width,
                "depth": PANEL_DEPTH,
                "thickness": self.style.material_thickness,
                "quantity": shelf_count,
                "component_type": "S/H"
            },
            "back": {
                "width": internal_width,
                "height": height,
                "thickness": self.style.back_thickness,
                "quantity": 1,
                "component_type": "BACKS"
            },
            "braces": {
                "width": internal_width,
                "height": BRACE_HEIGHT,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "BRACES",
                "notes": "Top and bottom for wall mounting"
            }
        }
    
    def calculate_tall_cabinet(self, width: int, height: int) -> Dict:
        """
        Calculate TALL CABINET components (pantry, oven housing, floor-to-ceiling)
        
        Tall Cabinet:
        - Height: 1800-2400mm (variable)
        - Depth: Same as base (560mm internal)
        - Has toe kick like base
        - More shelves based on height
        
        Components:
        1. Gables: H × 560 (2 pcs)
        2. T/B: (W-36) × 500 (2 pcs)
        3. S/H: (W-36) × 500 (variable based on height)
        4. Back: H × (W-36) (1 pc)
        5. Braces: (W-36) × 100 (2 pcs - top and bottom)
        
        Args:
            width: Cabinet width (mm)
            height: Cabinet height (mm)
            
        Returns:
            Dict with all component dimensions
        """
        
        GABLE_DEPTH = 560
        PANEL_DEPTH = 500
        BRACE_HEIGHT = 100
        
        internal_width = width - (self.style.material_thickness * 2)
        
        # Calculate shelves: approximately 1 per 400mm of height
        shelf_count = max(2, int((height - 200) / 400))
        
        return {
            "type": "tall",
            "overall": {
                "width": width,
                "height": height,
                "depth": 600,
                "internal_width": internal_width,
                "internal_depth": GABLE_DEPTH
            },
            "gables": {
                "width": GABLE_DEPTH,
                "height": height,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "GABLE"
            },
            "top_bottom": {
                "width": internal_width,
                "depth": PANEL_DEPTH,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "T/B"
            },
            "shelves": {
                "width": internal_width,
                "depth": PANEL_DEPTH,
                "thickness": self.style.material_thickness,
                "quantity": shelf_count,
                "component_type": "S/H"
            },
            "back": {
                "width": internal_width,
                "height": height,
                "thickness": self.style.back_thickness,
                "quantity": 1,
                "component_type": "BACKS"
            },
            "braces": {
                "width": internal_width,
                "height": BRACE_HEIGHT,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "BRACES",
                "notes": "Top and bottom"
            }
        }
    
    def calculate_wardrobe(self, width: int, height: int, depth: int = 560) -> Dict:
        """
        Calculate WARDROBE components (bedroom fitted wardrobes)
        
        Wardrobe Formula (from client):
        - Height: Variable (1800-2800mm)
        - Depth: 560mm (internal) typical
        - T/B: (W-36) × (D-30) - 30mm back gap
        - S/H: (W-36) × (D-40) - 40mm back gap
        - Toe kick: 100mm (bedroom)
        
        "In a wardrobe it's 40 minutes, because 20 mil is the gap 
        because we go tight into the wall. And 20 mils are back."
        
        Args:
            width: Cabinet width (mm)
            height: Cabinet height (mm)
            depth: Cabinet depth (mm, default 560)
            
        Returns:
            Dict with all component dimensions
        """
        
        internal_width = width - (self.style.material_thickness * 2)
        
        # Wardrobe-specific depth calculations
        tb_depth = depth - 30  # Top/bottom: D - 30mm
        shelf_depth = depth - 40  # Shelves: D - 40mm
        
        # Calculate shelves: approximately 1 per 500mm of height
        shelf_count = max(2, int((height - 200) / 500))
        
        return {
            "type": "wardrobe",
            "overall": {
                "width": width,
                "height": height,
                "depth": depth + 40,  # Overall with door
                "internal_width": internal_width,
                "internal_depth": depth
            },
            "gables": {
                "width": depth,
                "height": height,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "GABLE"
            },
            "top_bottom": {
                "width": internal_width,
                "depth": tb_depth,  # D - 30mm
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "T/B"
            },
            "shelves": {
                "width": internal_width,
                "depth": shelf_depth,  # D - 40mm
                "thickness": self.style.material_thickness,
                "quantity": shelf_count,
                "component_type": "S/H"
            },
            "back": {
                "width": internal_width,
                "height": height,
                "thickness": self.style.back_thickness,
                "quantity": 1,
                "component_type": "BACKS",
                "notes": "20mm from wall edge"
            },
            "braces": {
                "width": internal_width,
                "height": 100,
                "thickness": self.style.material_thickness,
                "quantity": 2,
                "component_type": "BRACES"
            }
        }
    
    def calculate_components(self, cabinet_data: Dict) -> Dict:
        """
        Calculate components based on cabinet type
        
        Args:
            cabinet_data: Dict with width, height, depth, type
            
        Returns:
            Dict with all component calculations
        """
        
        width = cabinet_data.get('width')
        height = cabinet_data.get('height', 720)
        depth = cabinet_data.get('depth', 560)
        cabinet_type = cabinet_data.get('type', 'base')
        
        # Auto-detect type if not specified
        if cabinet_type == 'auto':
            cabinet_type = CabinetTypeDetector.detect_type(width, height, depth)
        
        # Calculate based on type
        if cabinet_type == 'wall':
            return self.calculate_wall_cabinet(width, height)
        elif cabinet_type == 'tall':
            return self.calculate_tall_cabinet(width, height)
        elif cabinet_type == 'wardrobe':
            return self.calculate_wardrobe(width, height, depth)
        else:  # base (default)
            return self.calculate_base_cabinet(width)


# Default construction style for kitchens
DEFAULT_STYLE = ConstructionStyle(
    material_thickness=18,
    back_thickness=6,
    cabinet_type="base",
    toe_kick_height=150,
    back_construction_mode="overlay"
)