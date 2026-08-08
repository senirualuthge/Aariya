import os
import re

def rebuild():
    """
    Parses TECHNICAL_ANALYSIS.md to extract and reconstruct the source code.
    """
    if not os.path.exists('TECHNICAL_ANALYSIS.md'):
        print("Error: TECHNICAL_ANALYSIS.md not found in current directory.")
        return

    with open('TECHNICAL_ANALYSIS.md', 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern to match: <!-- FILE: path -->\n```language\ncode\n```
    pattern = r'<!-- FILE: (.*?) -->\s*?\n```.*?\n([\s\S]*?)\n```'
    matches = re.finditer(pattern, content)

    extracted_count = 0
    for match in matches:
        path = match.group(1).strip()
        code = match.group(2)
        
        print(f"Reconstructing: {path}")
        
        # Create directory structure
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        # Write file
        with open(path, 'w', encoding='utf-8') as f:
            f.write(code)
        
        extracted_count += 1

    print(f"\n✅ Rebuild complete. {extracted_count} files reconstructed.")
    print("\nNext steps:")
    print("1. cd server && pip install -r requirements.txt && python3 main.py")
    print("2. npm install && npm run dev")
    print("3. cd mobile && flutter pub get && flutter run")

if __name__ == "__main__":
    rebuild()
