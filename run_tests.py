#!/usr/bin/env python3
"""
Кроссплатформенный скрипт для запуска тестов Django.
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


def main():
    # Валидируем окружение
    manage_py = validate_environment()
    
    # Устанавливаем переменную окружения
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.django.base'
    
    # Безопасная команда с валидацией
    cmd = ['uv', 'run', 'python', str(manage_py), 'test', '-v', '2']
    
    try:
        # Запускаем с ограничениями безопасности
        result = subprocess.run(
            cmd,
            check=True,
            timeout=300,  # 5 минут timeout
            cwd=Path.cwd(),  # Явно указываем рабочую директорию
            capture_output=False,  # Не захватываем вывод для безопасности
        )
        sys.exit(result.returncode)
    except subprocess.TimeoutExpired:
        print('Ошибка: Тесты превысили лимит времени выполнения (5 минут)')
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f'Тесты завершились с ошибкой: {e}')
        sys.exit(e.returncode)
    except FileNotFoundError as e:
        print(f'Ошибка: Команда не найдена: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
