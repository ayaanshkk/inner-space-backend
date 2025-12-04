from db import SessionLocal
from models import DrawingDocument, FormDocument
import requests

def check_file_urls():
    """Check all file URLs and report any issues"""
    session = SessionLocal()
    
    try:
        # Get all drawings
        drawings = session.query(DrawingDocument).all()
        forms = session.query(FormDocument).all()
        
        print(f"Checking {len(drawings)} drawings...")
        print(f"Checking {len(forms)} form documents...")
        print()
        
        issues = []
        
        # Check drawings
        for drawing in drawings:
            print(f"\nDrawing: {drawing.file_name}")
            print(f"  file_url: {drawing.file_url}")
            print(f"  storage_path: {drawing.storage_path}")
            
            # Check if storage_path is a valid URL
            if not drawing.storage_path:
                issues.append(f"Drawing {drawing.id}: storage_path is empty")
                print(f"  ❌ storage_path is empty!")
            elif not drawing.storage_path.startswith('http'):
                issues.append(f"Drawing {drawing.id}: storage_path is not a URL: {drawing.storage_path}")
                print(f"  ❌ storage_path is not a URL!")
            elif 'cloudinary' not in drawing.storage_path:
                issues.append(f"Drawing {drawing.id}: storage_path is not a Cloudinary URL")
                print(f"  ❌ storage_path is not a Cloudinary URL!")
            else:
                # Try to fetch the file
                try:
                    response = requests.head(drawing.storage_path, timeout=5)
                    if response.status_code == 200:
                        print(f"  ✅ File accessible at Cloudinary")
                    else:
                        issues.append(f"Drawing {drawing.id}: Cloudinary returns {response.status_code}")
                        print(f"  ❌ Cloudinary returns {response.status_code}")
                except Exception as e:
                    issues.append(f"Drawing {drawing.id}: Cannot reach Cloudinary - {str(e)}")
                    print(f"  ❌ Cannot reach Cloudinary: {e}")
        
        # Check forms
        for form in forms:
            print(f"\nForm: {form.file_name}")
            print(f"  file_url: {form.file_url}")
            print(f"  storage_path: {form.storage_path}")
            
            # Check if storage_path is a valid URL
            if not form.storage_path:
                issues.append(f"Form {form.id}: storage_path is empty")
                print(f"  ❌ storage_path is empty!")
            elif not form.storage_path.startswith('http'):
                issues.append(f"Form {form.id}: storage_path is not a URL: {form.storage_path}")
                print(f"  ❌ storage_path is not a URL!")
            elif 'cloudinary' not in form.storage_path:
                issues.append(f"Form {form.id}: storage_path is not a Cloudinary URL")
                print(f"  ❌ storage_path is not a Cloudinary URL!")
            else:
                # Try to fetch the file
                try:
                    response = requests.head(form.storage_path, timeout=5)
                    if response.status_code == 200:
                        print(f"  ✅ File accessible at Cloudinary")
                    else:
                        issues.append(f"Form {form.id}: Cloudinary returns {response.status_code}")
                        print(f"  ❌ Cloudinary returns {response.status_code}")
                except Exception as e:
                    issues.append(f"Form {form.id}: Cannot reach Cloudinary - {str(e)}")
                    print(f"  ❌ Cannot reach Cloudinary: {e}")
        
        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        
        if issues:
            print(f"\n❌ Found {len(issues)} issues:")
            for issue in issues:
                print(f"  - {issue}")
            print("\nRecommendation: Re-upload files with issues or fix their storage_path values.")
        else:
            print("\n✅ All files look good!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    print("=" * 70)
    print("FILE URL DIAGNOSTIC")
    print("=" * 70)
    print()
    check_file_urls()