#!/usr/bin/env python3
"""
Кроссплатформенный скрипт для запуска тестов Django.
"""
import os
import subprocess
import sys


def main():
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.django.base'
    
    cmd = ['uv', 'run', 'python', 'manage.py', 'test', '-v', '2']
    
    try:
        result = subprocess.run(cmd, check=True)
        sys.exit(result.returncode)
    except subprocess.CalledProcessError as e:
        print(f'Тесты завершились с ошибкой: {e}')
        sys.exit(e.returncode)
    except FileNotFoundError:
        print('Ошибка: manage.py не найден. Убедитесь, что вы находитесь в корневой директории проекта.')
        sys.exit(1)


if __name__ == '__main__':
    main()
