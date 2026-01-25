"""
Cutting List Builder
Pure calculation engine for generating cutting lists from cabinet specifications
"""
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
import pandas as pd
import logging

from backend.services.manufacturing_rules import ConstructionStyle, ComponentCalculator, DEFAULT_STYLE

logger = logging.getLogger(__name__)


@dataclass
class Cabinet:
    """
    Cabinet specification
    """
    cabinet_id: str
    width: int  # mm
    height: int  # mm
    depth: int  # mm
    cabinet_type: str  # 'base', 'wall', 'tall', 'corner', 'filler'
    shelves: int = 1
    drawers: int = 0
    doors: int = 1
    notes: str = ""
    
    def __post_init__(self):
        """Validate cabinet dimensions"""
        if self.width <= 0 or self.height <= 0 or self.depth <= 0:
            raise ValueError(f"Invalid dimensions for {self.cabinet_id}: "
                           f"{self.width}×{self.height}×{self.depth}")


class CuttingListBuilder:
    """
    Calculate cutting lists from cabinet specifications
    Pure math - no OCR/extraction logic here
    """
    
    def __init__(self, construction_style: ConstructionStyle = None):
        """
        Initialize builder
        
        Args:
            construction_style: Construction configuration (defaults to DEFAULT_STYLE)
        """
        self.style = construction_style or DEFAULT_STYLE
        self.calculator = ComponentCalculator(self.style)
        
        logger.info(f"🔧 CuttingListBuilder initialized")
        logger.info(f"   Mode: {self.style.back_construction_mode.upper()}")
    
    def build_cutting_list(self, cabinets: List[Dict]) -> Dict:
        """
        Main entry point: Generate cutting list from cabinet specs
        
        Args:
            cabinets: List of cabinet dicts with keys:
                - cabinet_id, width, height, depth, cabinet_type, shelves, drawers, doors
        
        Returns:
            Dict with:
                - components: List of component dicts
                - summary: Overall statistics
                - dataframe: Pandas DataFrame (optional)
        """
        
        logger.info(f"📊 Building cutting list for {len(cabinets)} cabinets...")
        
        if not cabinets:
            logger.warning("⚠️ No cabinets provided")
            return self._empty_result()
        
        all_components = []
        
        # Process each cabinet
        for cab_dict in cabinets:
            try:
                # Create Cabinet object
                cabinet = Cabinet(**cab_dict)
                
                # Calculate components
                components = self._calculate_cabinet_components(cabinet)
                
                # Add to list
                all_components.extend(components)
                
                logger.debug(f"   ✓ {cabinet.cabinet_id}: {len(components)} components")
                
            except Exception as e:
                logger.error(f"Failed to process cabinet {cab_dict.get('cabinet_id', 'unknown')}: {e}")
                continue
        
        if not all_components:
            logger.error("❌ No components generated")
            return self._empty_result()
        
        # Calculate summary
        summary = self._calculate_summary(all_components, len(cabinets))
        
        # Create DataFrame
        df = self._create_dataframe(all_components)
        
        logger.info(f"✅ Cutting list complete: {len(all_components)} components, "
                   f"{summary['total_pieces']} pieces")
        
        return {
            'components': all_components,
            'summary': summary,
            'dataframe': df,
            'construction_style': asdict(self.style)
        }
    
    def _calculate_cabinet_components(self, cabinet: Cabinet) -> List[Dict]:
        """
        Calculate all components for a single cabinet using new calculator
        
        Args:
            cabinet: Cabinet object
            
        Returns:
            List of component dicts
        """
        
        components = []
        
        # Route based on cabinet type
        if cabinet.cabinet_type == 'filler' and cabinet.width < 200:
            return self._calculate_filler_panel(cabinet)
        
        # Use new calculator that returns complete cabinet breakdown
        cabinet_data = {
            'width': cabinet.width,
            'height': cabinet.height,
            'depth': cabinet.depth,
            'type': cabinet.cabinet_type
        }
        
        # Get complete component breakdown from new calculator
        calc_result = self.calculator.calculate_components(cabinet_data)
        
        # Convert to component list format
        components = self._convert_calc_result_to_components(calc_result, cabinet)
        
        return components
    
    def _convert_calc_result_to_components(self, calc_result: Dict, cabinet: Cabinet) -> List[Dict]:
        """
        Convert new calculator result format to component list
        
        Args:
            calc_result: Result from ComponentCalculator.calculate_components()
            cabinet: Cabinet object
            
        Returns:
            List of component dicts in old format
        """
        components = []
        
        logger.debug(f"Converting calc_result keys: {calc_result.keys()}")
        
        # Extract each component type
        for comp_name in ['gables', 'top_bottom', 'shelves', 'back', 'braces']:
            if comp_name not in calc_result:
                logger.debug(f"Skipping {comp_name} - not in calc_result")
                continue
            
            comp_data = calc_result[comp_name]
            logger.debug(f"Processing {comp_name}: {comp_data.keys()}")
            
            try:
                # Handle gables
                if comp_name == 'gables':
                    components.append({
                        'component_type': 'GABLE',
                        'part_name': f'Gable ({cabinet.cabinet_id})',
                        'cabinet_id': cabinet.cabinet_id,
                        'overall_unit_width': comp_data.get('width', 0),
                        'component_width': comp_data.get('width', 0),
                        'width': comp_data.get('width', 0),
                        'height': comp_data.get('height', 0),
                        'depth': None,
                        'quantity': comp_data.get('quantity', 2),
                        'material_thickness': comp_data.get('thickness', 18),
                        'edge_banding_notes': 'Front edge',
                        'area_m2': (comp_data.get('width', 0) * comp_data.get('height', 0) * comp_data.get('quantity', 2)) / 1_000_000
                    })
                
                # Handle top/bottom
                elif comp_name == 'top_bottom':
                    # Top panel
                    components.append({
                        'component_type': 'T/B',
                        'part_name': f'Top Panel ({cabinet.cabinet_id})',
                        'cabinet_id': cabinet.cabinet_id,
                        'overall_unit_width': comp_data.get('width', 0),
                        'component_width': comp_data.get('width', 0),
                        'width': comp_data.get('width', 0),
                        'height': comp_data.get('depth', 0),
                        'depth': comp_data.get('depth', 0),
                        'quantity': 1,
                        'material_thickness': comp_data.get('thickness', 18),
                        'edge_banding_notes': 'Front edge',
                        'area_m2': (comp_data.get('width', 0) * comp_data.get('depth', 0)) / 1_000_000
                    })
                    
                    # Bottom panel
                    components.append({
                        'component_type': 'T/B',
                        'part_name': f'Bottom Panel ({cabinet.cabinet_id})',
                        'cabinet_id': cabinet.cabinet_id,
                        'overall_unit_width': comp_data.get('width', 0),
                        'component_width': comp_data.get('width', 0),
                        'width': comp_data.get('width', 0),
                        'height': comp_data.get('depth', 0),
                        'depth': comp_data.get('depth', 0),
                        'quantity': 1,
                        'material_thickness': comp_data.get('thickness', 18),
                        'edge_banding_notes': 'Front edge',
                        'area_m2': (comp_data.get('width', 0) * comp_data.get('depth', 0)) / 1_000_000
                    })
                
                # Handle shelves
                elif comp_name == 'shelves':
                    for i in range(comp_data.get('quantity', 1)):
                        shelf_num = i + 1
                        components.append({
                            'component_type': 'S/H',
                            'part_name': f'Shelf {shelf_num} ({cabinet.cabinet_id})',
                            'cabinet_id': cabinet.cabinet_id,
                            'overall_unit_width': comp_data.get('width', 0),
                            'component_width': comp_data.get('width', 0),
                            'width': comp_data.get('width', 0),
                            'height': comp_data.get('depth', 0),
                            'depth': comp_data.get('depth', 0),
                            'quantity': 1,
                            'material_thickness': comp_data.get('thickness', 18),
                            'edge_banding_notes': 'Front edge',
                            'area_m2': (comp_data.get('width', 0) * comp_data.get('depth', 0)) / 1_000_000
                        })
                
                # Handle back panel
                elif comp_name == 'back':
                    components.append({
                        'component_type': 'BACKS',
                        'part_name': f'Back Panel ({cabinet.cabinet_id})',
                        'cabinet_id': cabinet.cabinet_id,
                        'overall_unit_width': comp_data.get('width', 0),
                        'component_width': comp_data.get('width', 0),
                        'width': comp_data.get('width', 0),
                        'height': comp_data.get('height', 0),
                        'depth': None,
                        'quantity': comp_data.get('quantity', 1),
                        'material_thickness': comp_data.get('thickness', 18),
                        'edge_banding_notes': 'None',
                        'area_m2': (comp_data.get('width', 0) * comp_data.get('height', 0) * comp_data.get('quantity', 1)) / 1_000_000
                    })
                
                # Handle braces/rails
                elif comp_name == 'braces':
                    components.append({
                        'component_type': 'BRACES',
                        'part_name': f'Rail ({cabinet.cabinet_id})',
                        'cabinet_id': cabinet.cabinet_id,
                        'overall_unit_width': comp_data.get('width', 0),
                        'component_width': comp_data.get('width', 0),
                        'width': comp_data.get('width', 0),
                        'height': comp_data.get('height', 0),
                        'depth': None,
                        'quantity': comp_data.get('quantity', 1),
                        'material_thickness': comp_data.get('thickness', 18),
                        'edge_banding_notes': 'None',
                        'area_m2': (comp_data.get('width', 0) * comp_data.get('height', 0) * comp_data.get('quantity', 1)) / 1_000_000,
                        'notes': comp_data.get('notes', '')
                    })
                
            except KeyError as e:
                logger.error(f"Missing field {e} in {comp_name}: {comp_data}")
                raise ValueError(f"Missing required field {e} in component {comp_name}")
            except Exception as e:
                logger.error(f"Error processing {comp_name}: {e}")
                raise
        
        return components

    def _calculate_filler_panel(self, cabinet: Cabinet) -> List[Dict]:
        """Calculate components for narrow filler panel"""
        
        return [{
            'component_type': 'FILLER',
            'part_name': f'Filler Panel ({cabinet.cabinet_id})',
            'cabinet_id': cabinet.cabinet_id,
            'width': cabinet.depth,
            'height': cabinet.height,
            'depth': None,
            'quantity': 1,
            'thickness': self.style.material_thickness,
            'edge_banding': 'All visible edges',
            'formula': f'{cabinet.height} × {cabinet.depth}'
        }]
    
    def _calculate_drawer_components(self, cabinet_id: str, width: int, 
                                    height: int, depth: int, 
                                    num_drawers: int) -> List[Dict]:
        """
        Calculate drawer components
        
        Note: Simplified - full drawer calculation would include:
        - Drawer boxes (front, back, sides, bottom)
        - Drawer slides
        - Drawer fronts
        
        Args:
            cabinet_id: Cabinet identifier
            width: Cabinet width
            height: Cabinet height (available for drawers)
            depth: Cabinet depth
            num_drawers: Number of drawers
            
        Returns:
            List of drawer component dicts
        """
        
        components = []
        
        internal_width = width - (2 * self.style.material_thickness)
        
        # Calculate height per drawer (simplified)
        # Account for dividers between drawers
        divider_thickness = self.style.material_thickness
        available_height = height - self.style.toe_kick_height
        total_divider_height = (num_drawers - 1) * divider_thickness
        drawer_height = (available_height - total_divider_height) // num_drawers
        
        # Drawer fronts
        for i in range(num_drawers):
            door = self.calculator.calculate_door(
                width,
                drawer_height,
                num_doors=1
            )
            door['component_type'] = 'DRAWER_FRONT'
            door['part_name'] = f'Drawer Front {i+1} ({cabinet_id})'
            door['cabinet_id'] = cabinet_id
            components.append(door)
        
        # Drawer dividers (horizontal shelves between drawers)
        if num_drawers > 1:
            for i in range(num_drawers - 1):
                divider = self.calculator.calculate_shelf(width, depth)
                divider['component_type'] = 'DRAWER_DIVIDER'
                divider['part_name'] = f'Drawer Divider {i+1} ({cabinet_id})'
                divider['cabinet_id'] = cabinet_id
                components.append(divider)
        
        return components
    
    def _calculate_summary(self, components: List[Dict], num_cabinets: int) -> Dict:
        """
        Calculate summary statistics
        
        Args:
            components: List of all components
            num_cabinets: Number of cabinets
            
        Returns:
            Summary dict
        """
        
        total_pieces = sum(comp['quantity'] for comp in components)
        
        # Calculate total area (m²)
        total_area = 0.0
        for comp in components:
            w = comp.get('width')
            h = comp.get('height')
            d = comp.get('depth')
            qty = comp.get('quantity', 1)
            
            if w and h:
                total_area += (w * h * qty) / 1_000_000
            elif w and d:
                total_area += (w * d * qty) / 1_000_000
        
        # Component type breakdown
        type_counts = {}
        for comp in components:
            comp_type = comp['component_type']
            if comp_type not in type_counts:
                type_counts[comp_type] = 0
            type_counts[comp_type] += comp['quantity']
        
        return {
            'total_cabinets': num_cabinets,
            'total_components': len(components),
            'total_pieces': total_pieces,
            'total_area_m2': round(total_area, 2),
            'component_breakdown': type_counts
        }
    
    def _create_dataframe(self, components: List[Dict]) -> pd.DataFrame:
        """
        Create pandas DataFrame from components
        
        Args:
            components: List of component dicts
            
        Returns:
            DataFrame with cutting list
        """
        
        # Prepare rows for DataFrame
        rows = []
        
        for comp in components:
            row = {
                'Cabinet ID': comp.get('cabinet_id', ''),
                'Component Type': comp['component_type'],
                'Part Name': comp['part_name'],
                'Width (mm)': comp.get('width', ''),
                'Height (mm)': comp.get('height', ''),
                'Depth (mm)': comp.get('depth', ''),
                'Quantity': comp['quantity'],
                'Thickness (mm)': comp.get('material_thickness', 18),  # Fixed field name
                'Edge Banding': comp.get('edge_banding_notes', 'None'),  # Fixed field name
                'Formula': comp.get('formula', '')
            }
            rows.append(row)
        
        df = pd.DataFrame(rows)
        
        # Reorder columns
        column_order = [
            'Cabinet ID', 'Component Type', 'Part Name',
            'Width (mm)', 'Height (mm)', 'Depth (mm)', 'Quantity',
            'Thickness (mm)', 'Edge Banding', 'Formula'
        ]
        
        df = df[column_order]
        
        return df
    
    def _empty_result(self) -> Dict:
        """Return empty result structure"""
        return {
            'components': [],
            'summary': {
                'total_cabinets': 0,
                'total_components': 0,
                'total_pieces': 0,
                'total_area_m2': 0.0,
                'component_breakdown': {}
            },
            'dataframe': pd.DataFrame(),
            'construction_style': asdict(self.style)
        }
    
    def export_to_csv(self, components: List[Dict], filepath: str):
        """
        Export cutting list to CSV file
        
        Args:
            components: List of component dicts
            filepath: Output CSV file path
        """
        df = self._create_dataframe(components)
        df.to_csv(filepath, index=False)
        logger.info(f"📁 Exported to CSV: {filepath}")
    
    def export_to_excel(self, components: List[Dict], filepath: str):
        """
        Export cutting list to Excel file
        
        Args:
            components: List of component dicts
            filepath: Output Excel file path
        """
        df = self._create_dataframe(components)
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Cutting List', index=False)
            
            # Auto-adjust column widths
            worksheet = writer.sheets['Cutting List']
            for idx, col in enumerate(df.columns):
                max_length = max(
                    df[col].astype(str).apply(len).max(),
                    len(col)
                ) + 2
                worksheet.column_dimensions[chr(65 + idx)].width = min(max_length, 50)
        
        logger.info(f"📁 Exported to Excel: {filepath}")