#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, re, base64
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
        return False, [f"❌ Файл не найден: {filepath}"]
    
    content = path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    
    for header in REQUIRED_HEADERS:
        if not any(line.startswith(header) for line in lines):
            errors.append(f"❌ Отсутствует заголовок: {header}")
    
    title_line = [l for l in lines if l.startswith("//profile-title: base64:")]
    if title_line:
        try:
            encoded = title_line[0].split("base64:")[1].strip()
            decoded = base64.b64decode(encoded).decode('utf-8')
            if "GooseVPN" not in decoded:
                errors.append(f"❌ Неверный title: {decoded}")
        except Exception as e:
            errors.append(f"❌ Ошибка декодирования title: {e}")
    
    vless_count = sum(1 for line in lines if line.startswith('vless://'))
    warp_count = sum(1 for line in lines if line.startswith('warp://'))
    total = vless_count + warp_count
    
    if total == 0:
        errors.append("❌ Нет ни одного конфига в файле")
    
    config_lines = [l for l in lines if l.startswith(('vless://', 'warp://'))]
    for line in config_lines[:10]:
        if '#' not in line:
            errors.append(f"❌ Конфиг без имени: {line[:50]}...")
            break
    
    sections = ['wLTE', 'WiFi', 'Резерв']
    for sec in sections:
        if not any(sec in line for line in lines):
            if sec != 'Резерв':
                errors.append(f"⚠️ Отсутствует секция: {sec}")
    
    is_valid = len(errors) == 0
    return is_valid, errors

def main():
    files = ['balanced.txt', 'plus.txt']
    all_ok = True
    
    print("🔍 Валидация конфигов")
    print("=" * 50)
    
    for filepath in files:
        if not Path(filepath).exists():
            print(f"⏭️ Пропущен: {filepath} (не найден)")
            continue
        
        is_valid, errors = validate_file(filepath)
        if is_valid:
            content = Path(filepath).read_text(encoding='utf-8')
            vless = sum(1 for l in content.split('\n') if l.startswith('vless://'))
            warp = sum(1 for l in content.split('\n') if l.startswith('warp://'))
            print(f"✅ {filepath}: {vless} VLESS + {warp} WARP = {vless+warp} конфигов")
        else:
            all_ok = False
            print(f"❌ {filepath}:")
            for err in errors:
                print(f"   {err}")
    
    print("=" * 50)
    if all_ok:
        print("🎉 Все проверки пройдены!")
        sys.exit(0)
    else:
        print("⚠️ Есть ошибки. Проверьте вывод выше.")
        sys.exit(1)

if __name__ == "__main__":
    main()
