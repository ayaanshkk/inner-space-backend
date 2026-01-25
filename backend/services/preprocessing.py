"""
Image Preprocessing
Prepare images for Claude API (resize, optimize, grayscale)
"""
import cv2
import numpy as np
from PIL import Image
import io
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """
    Preprocess images before sending to Claude API
    - Resize to save bandwidth/tokens
    - Optional grayscale conversion
    - Format optimization
    """
    
    def __init__(self, 
                 max_width: int = 2000,
                 max_height: int = 2000,
                 target_format: str = "JPEG",
                 quality: int = 85,
                 grayscale: bool = False):
        """
        Args:
            max_width: Maximum image width (px)
            max_height: Maximum image height (px)
            target_format: Output format (JPEG, PNG)
            quality: JPEG quality (1-100)
            grayscale: Convert to grayscale (saves tokens)
        """
        self.max_width = max_width
        self.max_height = max_height
        self.target_format = target_format
        self.quality = quality
        self.grayscale = grayscale
    
    def process(self, image_bytes: bytes) -> Tuple[bytes, dict]:
        """
        Main preprocessing pipeline
        
        Args:
            image_bytes: Raw image bytes
            
        Returns:
            Tuple of (processed_bytes, metadata)
        """
        logger.info("🔄 Preprocessing image...")
        
        # Load image
        image = self._load_image(image_bytes)
        original_size = image.shape[:2]
        
        # Resize if needed
        image, was_resized = self._resize_if_needed(image)
        
        # Convert to grayscale if requested
        if self.grayscale:
            image = self._to_grayscale(image)
        
        # Enhance contrast
        image = self._enhance_contrast(image)
        
        # Convert back to bytes
        processed_bytes = self._to_bytes(image)
        
        metadata = {
            'original_size': original_size,
            'processed_size': image.shape[:2],
            'was_resized': was_resized,
            'is_grayscale': self.grayscale,
            'format': self.target_format,
            'original_bytes': len(image_bytes),
            'processed_bytes': len(processed_bytes),
            'compression_ratio': len(image_bytes) / len(processed_bytes) if len(processed_bytes) > 0 else 1.0
        }
        
        logger.info(f"✅ Preprocessed: {metadata['original_size']} → {metadata['processed_size']}")
        logger.info(f"   Size: {metadata['original_bytes']:,} → {metadata['processed_bytes']:,} bytes "
                   f"({metadata['compression_ratio']:.2f}x)")
        
        return processed_bytes, metadata
    
    def _load_image(self, image_bytes: bytes) -> np.ndarray:
        """Load image from bytes using PIL then convert to OpenCV format"""
        try:
            # Use PIL to load (handles more formats)
            pil_image = Image.open(io.BytesIO(image_bytes))
            
            # Convert to RGB (remove alpha if present)
            if pil_image.mode == 'RGBA':
                # Create white background
                background = Image.new('RGB', pil_image.size, (255, 255, 255))
                background.paste(pil_image, mask=pil_image.split()[3])
                pil_image = background
            elif pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            
            # Convert to OpenCV format (BGR)
            image = np.array(pil_image)
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            
            return image
            
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            raise ValueError(f"Invalid image format: {e}")
    
    def _resize_if_needed(self, image: np.ndarray) -> Tuple[np.ndarray, bool]:
        """Resize if image exceeds max dimensions"""
        h, w = image.shape[:2]
        
        if w <= self.max_width and h <= self.max_height:
            return image, False
        
        # Calculate scaling factor
        scale = min(self.max_width / w, self.max_height / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        
        logger.info(f"📐 Resizing: {w}x{h} → {new_w}x{new_h}")
        
        # Use INTER_AREA for downscaling (best quality)
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        
        return resized, True
    
    def _to_grayscale(self, image: np.ndarray) -> np.ndarray:
        """Convert to grayscale to save tokens"""
        if len(image.shape) == 2:
            return image  # Already grayscale
        
        logger.info("🎨 Converting to grayscale")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Convert back to 3-channel for consistency
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    
    def _enhance_contrast(self, image: np.ndarray) -> np.ndarray:
        """
        Enhance contrast for better OCR/extraction
        Uses CLAHE (Contrast Limited Adaptive Histogram Equalization)
        """
        # Convert to LAB color space
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        # Apply CLAHE to L channel
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        
        # Merge back
        lab = cv2.merge([l, a, b])
        enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        
        return enhanced
    
    def _to_bytes(self, image: np.ndarray) -> bytes:
        """Convert OpenCV image back to bytes"""
        # Convert BGR to RGB for PIL
        if len(image.shape) == 3:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = image
        
        # Convert to PIL Image
        pil_image = Image.fromarray(image_rgb)
        
        # Save to bytes
        buffer = io.BytesIO()
        
        if self.target_format == "JPEG":
            pil_image.save(buffer, format="JPEG", quality=self.quality, optimize=True)
        elif self.target_format == "PNG":
            pil_image.save(buffer, format="PNG", optimize=True)
        else:
            pil_image.save(buffer, format=self.target_format)
        
        buffer.seek(0)
        return buffer.read()
    
    def estimate_tokens(self, image_bytes: bytes) -> int:
        """
        Estimate token cost for Claude API
        Claude charges ~1000 tokens per image regardless of size
        But larger images may cost more
        
        Args:
            image_bytes: Processed image bytes
            
        Returns:
            Estimated token count
        """
        # Load to get dimensions
        pil_image = Image.open(io.BytesIO(image_bytes))
        width, height = pil_image.size
        
        # Base cost
        base_tokens = 1000
        
        # Additional tokens for larger images
        pixels = width * height
        if pixels > 1_000_000:  # > 1MP
            base_tokens += 500
        if pixels > 4_000_000:  # > 4MP
            base_tokens += 1000
        
        return base_tokens


# Default preprocessor instance
default_preprocessor = ImagePreprocessor(
    max_width=2000,
    max_height=2000,
    target_format="JPEG",
    quality=85,
    grayscale=False  # Keep color for better recognition
)