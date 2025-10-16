#!/usr/bin/env python3
"""
Кроссплатформенный скрипт для запуска coverage тестов Django.
"""
import os
import subprocess
import sys
from pathlib import Path


def validate_environment():
    """Проверяем, что мы находимся в правильной директории проекта."""
    current_dir = Path.cwd()
    manage_py = current_dir / 'manage.py'
    
    if not manage_py.exists():
        print('Ошибка: manage.py не найден. Убедитесь, что вы находитесь в корневой директории проекта.')
        sys.exit(1)
    
    # Проверяем, что manage.py - это файл, а не символическая ссылка
    if not manage_py.is_file():
        print('Ошибка: manage.py должен быть обычным файлом.')
        sys.exit(1)
    
    return manage_py


def run_coverage_command(cmd, description, timeout=600):
    """Безопасно выполняет команду coverage."""
    try:
        print(f'{description}...')
        result = subprocess.run(
            cmd,
            check=True,
            timeout=timeout,
            cwd=Path.cwd(),
            capture_output=False,
        )
        return result
    except subprocess.TimeoutExpired:
        print(f'Ошибка: {description} превысил лимит времени выполнения ({timeout} секунд)')
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f'Ошибка при выполнении {description}: {e}')
        sys.exit(e.returncode)
    except FileNotFoundError as e:
        print(f'Ошибка: Команда не найдена: {e}')
        sys.exit(1)


def main():
    # Валидируем окружение
    manage_py = validate_environment()
    
    # Устанавливаем переменную окружения
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.django.base'
    
    # Безопасные команды с валидацией
    coverage_run_cmd = [sys.executable, '-m', 'coverage', 'run', str(manage_py), 'test']
    coverage_xml_cmd = [sys.executable, '-m', 'coverage', 'xml']
    coverage_report_cmd = [sys.executable, '-m', 'coverage', 'report']
    
    # Выполняем команды с ограничениями безопасности
    run_coverage_command(coverage_run_cmd, 'Запуск тестов с coverage', timeout=600)
    run_coverage_command(coverage_xml_cmd, 'Генерация XML отчёта', timeout=60)
    run_coverage_command(coverage_report_cmd, 'Генерация текстового отчёта', timeout=60)


if __name__ == '__main__':
    main()
