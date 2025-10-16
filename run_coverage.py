#!/usr/bin/env python3
"""
Кроссплатформенный скрипт для запуска coverage тестов Django.
"""
import os
import subprocess
import sys
from pathlib import Path


def validate_environment() -> Path:
    """Проверяет, что мы находимся в правильной директории проекта.

    Returns:
        Path: Путь к файлу manage.py.

    Raises:
        SystemExit: Если manage.py не найден или является символической ссылкой.
    """
    current_dir = Path.cwd()
    manage_py = current_dir / 'manage.py'

    if not manage_py.exists():
        print('Ошибка: manage.py не найден. Убедитесь, что вы находитесь в корневой директории проекта.')
        sys.exit(1)

    if not manage_py.is_file():
        print('Ошибка: manage.py должен быть обычным файлом.')
        sys.exit(1)

    return manage_py


def run_coverage_command(
    cmd: list[str], description: str, timeout: int = 600
) -> subprocess.CompletedProcess[bytes]:
    """Безопасно выполняет команду coverage.

    Args:
        cmd: Команда для выполнения.
        description: Описание команды для вывода.
        timeout: Максимальное время выполнения в секундах.

    Returns:
        CompletedProcess: Результат выполнения команды.

    Raises:
        SystemExit: При превышении времени выполнения, ошибке команды или отсутствии файла.
    """
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


def main() -> None:
    """Запускает тесты Django с coverage и генерирует отчёты.

    Валидирует окружение, устанавливает переменные окружения и выполняет
    команды coverage с ограничениями по времени и безопасности.
    """
    manage_py = validate_environment()

    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.django.base'

    coverage_run_cmd = [sys.executable, '-m', 'coverage', 'run', str(manage_py), 'test']
    coverage_xml_cmd = [sys.executable, '-m', 'coverage', 'xml']
    coverage_report_cmd = [sys.executable, '-m', 'coverage', 'report']

    run_coverage_command(coverage_run_cmd, 'Запуск тестов с coverage', timeout=600)
    run_coverage_command(coverage_xml_cmd, 'Генерация XML отчёта', timeout=60)
    run_coverage_command(coverage_report_cmd, 'Генерация текстового отчёта', timeout=60)


if __name__ == '__main__':
    main()
