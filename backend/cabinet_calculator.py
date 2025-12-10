"""
Kitchen Cabinet Calculator
Calculates ALL components for each cabinet based on type and dimensions
Supports: GABLES, T/B, S/H, BACKS, DOORS, END PANELS, BRACES
"""

import logging

logger = logging.getLogger('CabinetCalculator')

class CabinetCalculator:
    def __init__(self):
        # Standard offsets and parameters
        self.BACK_WIDTH_OFFSET = 36
        self.TOP_BOTTOM_DEPTH_OFFSET = 60  # D - 60 for T/B
        self.SHELF_DEPTH_OFFSET = 130  # D - 130 for shelves
        self.THICKNESS = 18
        self.DOOR_HEIGHT_TOLERANCE = 5  # Door is H - 5mm
        self.BRACE_HEIGHT = 100
        
    def calculate_complete_kitchen(self, cabinets_list):
        """
        Calculate ALL components for all cabinets
        
        Input format:
        [
            {
                'id': 1,
                'width': 900,
                'type': 'standard_base',
                'height': 720,
                'depth': 560
            },
            ...
        ]
        
        Output: Complete cutting list with all categories
        """
        all_components = {
            'GABLE': [],
            'T/B & FIX SHELVES': [],
            'BACKS': [],
            'S/H': [],
            'DOORS & DRAW FACES': [],
            'END PANELS & INFILLS': [],
            'BRACES': []
        }
        
        for cabinet in cabinets_list:
            cab_type = cabinet.get('type', 'standard_base')
            width = cabinet.get('width', 0)
            height = cabinet.get('height', 720)
            depth = cabinet.get('depth', 560)
            cab_id = cabinet.get('id', 0)
            
            # Calculate components based on type
            if cab_type == 'filler':
                components = self._calculate_filler(cab_id, width, height, depth)
            elif cab_type == 'narrow':
                components = self._calculate_narrow(cab_id, width, height, depth)
            elif cab_type == 'sink_base':
                components = self._calculate_sink_base(cab_id, width, height, depth)
            elif cab_type == 'drawer_base':
                components = self._calculate_drawer_base(cab_id, width, height, depth)
            elif cab_type == 'corner_l':
                components = self._calculate_corner_l(cab_id, width, height, depth)
            else:  # standard_base, wide_base
                components = self._calculate_standard_base(cab_id, width, height, depth)
            
            # Merge into all_components
            for category, items in components.items():
                all_components[category].extend(items)
        
        return all_components
    
    def _calculate_standard_base(self, cab_id, W, H, D):
        """
        Standard base cabinet
        - 2 Gables
        - 2 T/B panels
        - 1 Shelf
        - 1 Back
        - 2 Doors
        - 1 Brace
        """
        components = {
            'GABLE': [],
            'T/B & FIX SHELVES': [],
            'BACKS': [],
            'S/H': [],
            'DOORS & DRAW FACES': [],
            'END PANELS & INFILLS': [],
            'BRACES': []
        }
        
        # GABLES: H × D (Qty: 2)
        components['GABLE'].append({
            'dimensions': f"{H}x{D}",
            'height': H,
            'width': D,
            'quantity': 2,
            'notes': f"Cabinet #{cab_id} - Gables"
        })
        
        # T/B: (W-36) × (D-60) (Qty: 2)
        tb_width = W - self.BACK_WIDTH_OFFSET
        tb_depth = D - self.TOP_BOTTOM_DEPTH_OFFSET
        components['T/B & FIX SHELVES'].append({
            'dimensions': f"{tb_width}x{tb_depth}",
            'height': tb_width,
            'width': tb_depth,
            'quantity': 2,
            'notes': f"Cabinet #{cab_id} - Top/Bottom"
        })
        
        # S/H: (W-36) × (D-130) (Qty: 1)
        shelf_width = W - self.BACK_WIDTH_OFFSET
        shelf_depth = D - self.SHELF_DEPTH_OFFSET
        components['S/H'].append({
            'dimensions': f"{shelf_width}x{shelf_depth}",
            'height': shelf_width,
            'width': shelf_depth,
            'quantity': 1,
            'notes': f"Cabinet #{cab_id} - Shelf"
        })
        
        # BACK: H × (W-36) (Qty: 1)
        back_width = W - self.BACK_WIDTH_OFFSET
        components['BACKS'].append({
            'dimensions': f"{H}x{back_width}",
            'height': H,
            'width': back_width,
            'quantity': 1,
            'notes': f"Cabinet #{cab_id} - Back"
        })
        
        # DOORS: (H-5) × ((W-36)/2) (Qty: 2)
        door_height = H - self.DOOR_HEIGHT_TOLERANCE
        door_width = (W - self.BACK_WIDTH_OFFSET) // 2
        components['DOORS & DRAW FACES'].append({
            'dimensions': f"{door_height}x{door_width}",
            'height': door_height,
            'width': door_width,
            'quantity': 2,
            'notes': f"Cabinet #{cab_id} - Doors"
        })
        
        # BRACE: (W-36) × 100 (Qty: 1)
        brace_width = W - self.BACK_WIDTH_OFFSET
        components['BRACES'].append({
            'dimensions': f"{brace_width}x{self.BRACE_HEIGHT}",
            'height': brace_width,
            'width': self.BRACE_HEIGHT,
            'quantity': 1,
            'notes': f"Cabinet #{cab_id} - Brace"
        })
        
        return components
    
    def _calculate_sink_base(self, cab_id, W, H, D):
        """
        Sink base - similar to standard but:
        - Only 1 T/B (top only)
        - No shelf (sink opening)
        - Lower back (for plumbing)
        """
        components = {
            'GABLE': [],
            'T/B & FIX SHELVES': [],
            'BACKS': [],
            'S/H': [],
            'DOORS & DRAW FACES': [],
            'END PANELS & INFILLS': [],
            'BRACES': []
        }
        
        # GABLES: H × D (Qty: 2)
        components['GABLE'].append({
            'dimensions': f"{H}x{D}",
            'height': H,
            'width': D,
            'quantity': 2,
            'notes': f"Cabinet #{cab_id} - Gables (Sink)"
        })
        
        # T/B: (W-36) × (D-60) (Qty: 1 - top only)
        tb_width = W - self.BACK_WIDTH_OFFSET
        tb_depth = D - self.TOP_BOTTOM_DEPTH_OFFSET
        components['T/B & FIX SHELVES'].append({
            'dimensions': f"{tb_width}x{tb_depth}",
            'height': tb_width,
            'width': tb_depth,
            'quantity': 1,
            'notes': f"Cabinet #{cab_id} - Top (Sink)"
        })
        
        # No shelf for sink base
        
        # BACK: Lower back for plumbing - 550 × (W-36)
        back_height = 550  # Standard sink back height
        back_width = W - self.BACK_WIDTH_OFFSET
        components['BACKS'].append({
            'dimensions': f"{back_height}x{back_width}",
            'height': back_height,
            'width': back_width,
            'quantity': 1,
            'notes': f"Cabinet #{cab_id} - Back (Sink - Lower)"
        })
        
        # DOORS: (H-5) × ((W-36)/2) (Qty: 2)
        door_height = H - self.DOOR_HEIGHT_TOLERANCE
        door_width = (W - self.BACK_WIDTH_OFFSET) // 2
        components['DOORS & DRAW FACES'].append({
            'dimensions': f"{door_height}x{door_width}",
            'height': door_height,
            'width': door_width,
            'quantity': 2,
            'notes': f"Cabinet #{cab_id} - Doors (Sink)"
        })
        
        # BRACE
        brace_width = W - self.BACK_WIDTH_OFFSET
        components['BRACES'].append({
            'dimensions': f"{brace_width}x{self.BRACE_HEIGHT}",
            'height': brace_width,
            'width': self.BRACE_HEIGHT,
            'quantity': 1,
            'notes': f"Cabinet #{cab_id} - Brace (Sink)"
        })
        
        return components
    
    def _calculate_drawer_base(self, cab_id, W, H, D):
        """
        Drawer base cabinet - multiple drawers
        """
        # Similar to standard but with multiple drawer fronts
        components = self._calculate_standard_base(cab_id, W, H, D)
        
        # Override doors with drawer fronts
        # Typically 3-4 drawer fronts stacked
        door_height = H - self.DOOR_HEIGHT_TOLERANCE
        drawer_width = W - self.BACK_WIDTH_OFFSET
        
        # 3 equal drawers
        drawer_height = door_height // 3
        
        components['DOORS & DRAW FACES'] = [{
            'dimensions': f"{drawer_height}x{drawer_width}",
            'height': drawer_height,
            'width': drawer_width,
            'quantity': 3,
            'notes': f"Cabinet #{cab_id} - Drawer Fronts"
        }]
        
        return components
    
    def _calculate_filler(self, cab_id, W, H, D):
        """
        Filler panel - narrow vertical piece
        """
        components = {
            'GABLE': [],
            'T/B & FIX SHELVES': [],
            'BACKS': [],
            'S/H': [],
            'DOORS & DRAW FACES': [],
            'END PANELS & INFILLS': [],
            'BRACES': []
        }
        
        # Just an end panel
        # Standard height with legs: 900mm (720 + 150 legs + 30 worktop)
        total_height = 900
        
        components['END PANELS & INFILLS'].append({
            'dimensions': f"{total_height}x{W}",
            'height': total_height,
            'width': W,
            'quantity': 1,
            'notes': f"Filler #{cab_id} - {W}mm"
        })
        
        return components
    
    def _calculate_narrow(self, cab_id, W, H, D):
        """
        Narrow cabinet (200-300mm) - typically for spices/bottles
        """
        components = self._calculate_standard_base(cab_id, W, H, D)
        
        # Override doors - single door for narrow units
        door_height = H - self.DOOR_HEIGHT_TOLERANCE
        door_width = W - self.BACK_WIDTH_OFFSET
        
        components['DOORS & DRAW FACES'] = [{
            'dimensions': f"{door_height}x{door_width}",
            'height': door_height,
            'width': door_width,
            'quantity': 1,
            'notes': f"Cabinet #{cab_id} - Door (Narrow)"
        }]
        
        return components
    
    def _calculate_corner_l(self, cab_id, W, H, D):
        """
        L-shaped corner cabinet
        TODO: Implement specific L-corner formulas
        For now, use standard as placeholder
        """
        logger.warning(f"L-corner cabinet calculation not yet implemented for cabinet #{cab_id}")
        components = self._calculate_standard_base(cab_id, W, H, D)
        
        # Add note that this needs review
        for category in components:
            for item in components[category]:
                item['notes'] += " [L-CORNER - NEEDS REVIEW]"
        
        return components
    
    def format_for_frontend(self, components):
        """
        Format components for frontend display
        """
        summary = {}
        
        for category, items in components.items():
            if items:
                total_pieces = sum(item['quantity'] for item in items)
                
                # Convert to frontend format
                formatted_items = []
                for idx, item in enumerate(items, 1):
                    formatted_items.append({
                        'part_id': f"{self._get_category_code(category)}-{idx:02d}",
                        'dimensions': item['dimensions'],
                        'height': item['height'],
                        'width': item['width'],
                        'quantity': item['quantity'],
                        'material_type': self._get_material_type(category),
                        'notes': item['notes'],
                        'raw_text': item['notes']
                    })
                
                summary[category] = {
                    'items': formatted_items,
                    'total_pieces': total_pieces,
                    'unique_sizes': len(set(item['dimensions'] for item in items)),
                    'total_area': self._calculate_area(items)
                }
            else:
                summary[category] = {
                    'items': [],
                    'total_pieces': 0,
                    'unique_sizes': 0,
                    'total_area': 0.0
                }
        
        return summary
    
    def _get_category_code(self, category):
        codes = {
            'GABLE': 'GABLE',
            'T/B & FIX SHELVES': 'SHELF',
            'BACKS': 'BACK',
            'S/H': 'HARDWARE',
            'DOORS & DRAW FACES': 'DOOR',
            'END PANELS & INFILLS': 'PANEL',
            'BRACES': 'BRACE'
        }
        return codes.get(category, 'COMP')
    
    def _get_material_type(self, category):
        materials = {
            'GABLE': '18mm MFC',
            'T/B & FIX SHELVES': '18mm MFC',
            'BACKS': '6mm MDF',
            'S/H': '18mm MFC',
            'DOORS & DRAW FACES': '18mm MFC',
            'END PANELS & INFILLS': '18mm MFC',
            'BRACES': '18mm MFC'
        }
        return materials.get(category, '18mm MFC')
    
    def _calculate_area(self, items):
        """Calculate total area in m²"""
        total_area = 0
        for item in items:
            width = item.get('width', 0)
            height = item.get('height', 0)
            quantity = item.get('quantity', 1)
            total_area += (width * height * quantity) / 1000000
        return round(total_area, 2)