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
        return False, [f"❌ Файл не найден: {filepath}"]
    content = path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    
    for header in REQUIRED_HEADERS:
        if not any(line.startswith(header) for line in lines):
            errors.append(f"❌ Отсутствует: {header}")
    
    title_line = [l for l in lines if l.startswith("//profile-title: base64:")]
    if title_line:
        try:
            encoded = title_line[0].split("base64:")[1].strip()
            decoded = base64.b64decode(encoded).decode('utf-8')
            if "GooseVPN" not in decoded:
                errors.append(f"❌ Неверный title: {decoded}")
        except Exception as e:
            errors.append(f"❌ Ошибка декодирования: {e}")
    
    vless = sum(1 for l in lines if l.startswith('vless://'))
    warp = sum(1 for l in lines if l.startswith('warp://'))
    if vless + warp == 0:
        errors.append("❌ Нет конфигов в файле")
    
    for line in [l for l in lines if l.startswith(('vless://','warp://'))][:10]:
        if '#' not in line:
            errors.append(f"❌ Конфиг без имени: {line[:50]}...")
            break
    
    for sec in ['wLTE', 'WiFi']:
        if not any(sec in line for line in lines):
            errors.append(f"⚠️ Отсутствует секция: {sec}")
    
    return len(errors) == 0, errors

def main():
    files = ['configs/balanced.txt', 'configs/plus.txt']
    all_ok = True
    print("🔍 Валидация подписки")
    print("=" * 50)
    for fp in files:
        if not Path(fp).exists():
            print(f"⏭️ Пропущен: {fp}")
            continue
        ok, errs = validate_file(fp)
        if ok:
            content = Path(fp).read_text(encoding='utf-8')
            vless = sum(1 for l in content.split('\n') if l.startswith('vless://'))
            warp = sum(1 for l in content.split('\n') if l.startswith('warp://'))
            print(f"✅ {fp}: {vless} VLESS + {warp} WARP = {vless+warp}")
        else:
            all_ok = False
            print(f"❌ {fp}:")
            for e in errs: print(f"   {e}")
    print("=" * 50)
    if all_ok:
        print("🎉 Все проверки пройдены!")
        sys.exit(0)
    else:
        print("⚠️ Есть ошибки")
        sys.exit(1)

if __name__ == "__main__":
    main()
