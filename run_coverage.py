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


def run_coverage_run(timeout: int = 600) -> subprocess.CompletedProcess[bytes]:
    """Безопасно выполняет команду coverage run.

    Args:
        timeout: Максимальное время выполнения в секундах.

    Returns:
        CompletedProcess: Результат выполнения команды.

    Raises:
        SystemExit: При превышении времени выполнения, ошибке команды или отсутствии файла.
    """
    try:
        result = subprocess.run(
            ["python", "-m", "coverage", "run", "manage.py", "test"],
            check=True,
            timeout=timeout,
            cwd=Path.cwd(),
            capture_output=False,
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"Ошибка: команда превысила лимит времени выполнения ({timeout} секунд)")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при выполнении команды: {e}")
        sys.exit(e.returncode)
    except FileNotFoundError as e:
        print(f"Ошибка: Команда не найдена: {e}")
        sys.exit(1)


def run_coverage_xml(timeout: int = 60) -> subprocess.CompletedProcess[bytes]:
    """Безопасно выполняет команду coverage xml.

    Args:
        timeout: Максимальное время выполнения в секундах.

    Returns:
        CompletedProcess: Результат выполнения команды.

    Raises:
        SystemExit: При превышении времени выполнения, ошибке команды или отсутствии файла.
    """
    try:
        result = subprocess.run(
            ["python", "-m", "coverage", "xml"],
            check=True,
            timeout=timeout,
            cwd=Path.cwd(),
            capture_output=False,
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"Ошибка: команда превысила лимит времени выполнения ({timeout} секунд)")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при выполнении команды: {e}")
        sys.exit(e.returncode)
    except FileNotFoundError as e:
        print(f"Ошибка: Команда не найдена: {e}")
        sys.exit(1)


def run_coverage_report(timeout: int = 60) -> subprocess.CompletedProcess[bytes]:
    """Безопасно выполняет команду coverage report.

    Args:
        timeout: Максимальное время выполнения в секундах.

    Returns:
        CompletedProcess: Результат выполнения команды.

    Raises:
        SystemExit: При превышении времени выполнения, ошибке команды или отсутствии файла.
    """
    try:
        result = subprocess.run(
            ["python", "-m", "coverage", "report"],
            check=True,
            timeout=timeout,
            cwd=Path.cwd(),
            capture_output=False,
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"Ошибка: команда превысила лимит времени выполнения ({timeout} секунд)")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при выполнении команды: {e}")
        sys.exit(e.returncode)
    except FileNotFoundError as e:
        print(f"Ошибка: Команда не найдена: {e}")
        sys.exit(1)


def main() -> None:
    """Запускает тесты Django с coverage и генерирует отчёты.

    Валидирует окружение, устанавливает переменные окружения и выполняет
    команды coverage с ограничениями по времени и безопасности.
    """
    validate_environment()

    os.environ['DJANGO_SETTINGS_MODULE'] = 'config.django.base'

    run_coverage_run(timeout=600)
    run_coverage_xml(timeout=60)
    run_coverage_report(timeout=60)


if __name__ == '__main__':
    main()
