#!/usr/bin/env python3
"""
Test which Claude models are available with your API key
"""
import os

# Common Claude model names to test
MODELS_TO_TEST = [
    "claude-3-5-sonnet-20241022",  # Latest Sonnet 3.5 (Oct 2024)
    "claude-3-5-sonnet-20240620",  # Earlier Sonnet 3.5 (June 2024)
    "claude-3-sonnet-20240229",    # Sonnet 3 (Feb 2024)
    "claude-3-opus-20240229",      # Opus 3 (Feb 2024)
    "claude-3-haiku-20240307",     # Haiku 3 (Mar 2024)
    "claude-sonnet-4-20250514",    # Sonnet 4 (if available)
]

print("=" * 60)
print("TESTING CLAUDE API MODELS")
print("=" * 60)

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    print("❌ ANTHROPIC_API_KEY not set in environment")
    print("\nSet it with:")
    print('  export ANTHROPIC_API_KEY="your-key-here"')
    exit(1)

print(f"✅ API Key found: {api_key[:20]}...")
print()

try:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    
    for model in MODELS_TO_TEST:
        print(f"Testing: {model}")
        try:
            # Try a simple message with minimal tokens
            response = client.messages.create(
                model=model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )
            print(f"  ✅ WORKS - Response: {response.content[0].text}")
        except anthropic.NotFoundError:
            print(f"  ❌ NOT FOUND - Model not available")
        except Exception as e:
            print(f"  ⚠️  ERROR: {e}")
        print()
    
    print("=" * 60)
    print("RECOMMENDATION:")
    print("Use the first model that shows ✅ WORKS")
    print("=" * 60)
    
except ImportError:
    print("❌ anthropic package not installed")
    print("\nInstall with:")
    print("  pip install anthropic")
except Exception as e:
    print(f"❌ Error: {e}")