import sys
sys.path.insert(0, '.')

from backend.app import create_app
app = create_app()

print("\n=== ALL REGISTERED ROUTES ===")
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    print(f"{str(list(rule.methods)):<30} {rule.rule:<50} {rule.endpoint}")
