#!/usr/bin/env python3
"""
Кроссплатформенный скрипт для запуска coverage тестов Django.
"""
import os
import subprocess
import sys


def main():
    # Устанавливаем переменную окружения
    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.django.base'
    
    try:
        # Запускаем coverage
        print('Запуск тестов с coverage...')
        subprocess.run([sys.executable, '-m', 'coverage', 'run', 'manage.py', 'test'], check=True)
        
        print('Генерация XML отчёта...')
        subprocess.run([sys.executable, '-m', 'coverage', 'xml'], check=True)
        
        print('Генерация текстового отчёта...')
        subprocess.run([sys.executable, '-m', 'coverage', 'report'], check=True)
        
    except subprocess.CalledProcessError as e:
        print(f'Coverage завершился с ошибкой: {e}')
        sys.exit(e.returncode)
    except FileNotFoundError:
        print('Ошибка: manage.py не найден. Убедитесь, что вы находитесь в корневой директории проекта.')
        sys.exit(1)


if __name__ == '__main__':
    main()
