#!/usr/bin/env python3
"""
Скрипт для проверки и диагностики проблем со статическими файлами в Django проекте.
"""

import os
import sys
import requests
from pathlib import Path
from urllib.parse import urljoin

def check_static_files_locally():
    """Проверяет статические файлы локально"""
    print("🔍 Проверка статических файлов локально...")
    
    static_dir = Path("static")
    if not static_dir.exists():
        print("❌ Директория static не найдена")
        return False
    
    # Проверяем основные файлы
    required_files = [
        "js/jquery-3.7.1.min.js",
        "js/script.js",
        "js/errors_form.js",
        "bootstrap/js/bootstrap.bundle.min.js",
        "css/styles.min.css"
    ]
    
    missing_files = []
    for file_path in required_files:
        full_path = static_dir / file_path
        if not full_path.exists():
            missing_files.append(file_path)
        else:
            print(f"✅ {file_path}")
    
    if missing_files:
        print(f"❌ Отсутствуют файлы: {missing_files}")
        return False
    
    return True

def check_static_files_production(base_url="http://localhost:8090"):
    """Проверяет статические файлы в продакшене"""
    print(f"\n🌐 Проверка статических файлов в продакшене ({base_url})...")
    
    static_files = [
        "/static/js/jquery-3.7.1.min.js",
        "/static/js/script.js", 
        "/static/js/errors_form.js",
        "/static/bootstrap/js/bootstrap.bundle.min.js",
        "/static/css/styles.min.css"
    ]
    
    issues = []
    
    for file_path in static_files:
        url = urljoin(base_url, file_path)
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '')
                if 'javascript' in content_type or 'css' in content_type:
                    print(f"✅ {file_path} - {content_type}")
                else:
                    print(f"⚠️  {file_path} - неправильный MIME тип: {content_type}")
                    issues.append(f"Неправильный MIME тип для {file_path}: {content_type}")
            else:
                print(f"❌ {file_path} - HTTP {response.status_code}")
                issues.append(f"HTTP {response.status_code} для {file_path}")
        except requests.RequestException as e:
            print(f"❌ {file_path} - ошибка: {e}")
            issues.append(f"Ошибка доступа к {file_path}: {e}")
    
    return issues

def check_csp_headers(base_url="http://localhost:8090"):
    """Проверяет CSP заголовки"""
    print(f"\n🛡️  Проверка CSP заголовков ({base_url})...")
    
    try:
        response = requests.get(base_url, timeout=10)
        csp_header = response.headers.get('content-security-policy', '')
        
        if csp_header:
            print(f"✅ CSP заголовок найден")
            if "'unsafe-hashes'" in csp_header:
                print("✅ unsafe-hashes разрешены в CSP")
            else:
                print("⚠️  unsafe-hashes не найдены в CSP")
        else:
            print("❌ CSP заголовок отсутствует")
            
    except requests.RequestException as e:
        print(f"❌ Ошибка при проверке CSP: {e}")

def main():
    print("🚀 Диагностика проблем со статическими файлами\n")
    
    # Локальная проверка
    local_ok = check_static_files_locally()
    
    # Проверка в продакшене
    production_issues = check_static_files_production()
    
    # Проверка CSP
    check_csp_headers()
    
    print("\n📋 Рекомендации:")
    
    if not local_ok:
        print("1. Запустите: make staticfiles")
    
    if production_issues:
        print("2. Проблемы в продакшене:")
        for issue in production_issues:
            print(f"   - {issue}")
        print("3. Перезапустите контейнеры: make docker-restart")
        print("4. Проверьте логи: make docker-logs")
    
    print("5. Убедитесь, что nginx правильно настроен для статических файлов")
    print("6. Проверьте, что WhiteNoise правильно настроен в Django")

if __name__ == "__main__":
    main()
