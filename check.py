#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, base64
from pathlib import Path

REQUIRED_HEADERS = [
    "//profile-title: base64:",
    "//profile-update-interval:",
    "//subscription-userinfo:",
    "//last update on:",
]

def validate_file(filepath: str) -> tuple[bool, list[str]]:
    errors = []
    path = Path(filepath)
    if not path.exists():
        return False, [f"File not found: {filepath}"]
    content = path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    for header in REQUIRED_HEADERS:
        if not any(line.startswith(header) for line in lines):
            errors.append(f"Missing header: {header}")
    title_line = [l for l in lines if l.startswith("//profile-title: base64:")]
    if title_line:
        try:
            encoded = title_line[0].split("base64:")[1].strip()
            decoded = base64.b64decode(encoded).decode('utf-8')
            if "GooseVPN" not in decoded:
                errors.append(f"Invalid title: {decoded}")
        except Exception as e:
            errors.append(f"Decode error: {e}")
    vless = sum(1 for l in lines if l.startswith('vless://'))
    warp = sum(1 for l in lines if l.startswith('warp://'))
    if vless + warp == 0:
        errors.append("No configs in file")
    for line in [l for l in lines if l.startswith(('vless://','warp://'))][:10]:
        if '#' not in line:
            errors.append(f"Config without name: {line[:50]}...")
            break
    for sec in ['wLTE', 'WiFi']:
        if not any(sec in line for line in lines):
            errors.append(f"Missing section: {sec}")
    return len(errors) == 0, errors

def main():
    files = ['configs/balanced.txt', 'configs/plus.txt']
    all_ok = True
    print("GooseVPN Validator")
    print("=" * 50)
    for fp in files:
        if not Path(fp).exists():
            print(f"Skipped: {fp}")
            continue
        ok, errs = validate_file(fp)
        if ok:
            content = Path(fp).read_text(encoding='utf-8')
            vless = sum(1 for l in content.split('\n') if l.startswith('vless://'))
            warp = sum(1 for l in content.split('\n') if l.startswith('warp://'))
            print(f"OK {fp}: {vless} VLESS + {warp} WARP = {vless+warp}")
        else:
            all_ok = False
            print(f"FAIL {fp}:")
            for e in errs:
                print(f"   {e}")
    print("=" * 50)
    if all_ok:
        print("All checks passed!")
        sys.exit(0)
    else:
        print("Errors found")
        sys.exit(1)

if __name__ == "__main__":
    main()
