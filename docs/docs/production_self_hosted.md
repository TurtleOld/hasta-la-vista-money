# Self-hosted production-развертывание

Это руководство описывает минимально необходимое окружение и проверки для
production-развертывания при самостоятельном размещении.

## Политика работы с секретами

Не храните production-секреты в репозитории.

Не создавайте вручную и не редактируйте на сервере неуправляемый файл `.env`.

Вместо этого используйте один из контролируемых способов:

1. CI/CD secrets формируют runtime-файл `.env` во время деплоя.
2. Менеджер секретов, например Vault, 1Password Secrets Automation, Doppler
   или Infisical, формирует runtime-файл `.env` во время деплоя.
3. Инструмент управления конфигурацией, например Ansible, записывает
   runtime-файл `.env` из зашифрованных переменных.

Если `docker-compose.prod.yaml` читает `.env`, рассматривайте этот файл как
сгенерированный runtime-артефакт, а не как вручную поддерживаемый источник
истинных значений.

## Обязательные переменные окружения

Эти переменные должны быть заданы для каждого production-развертывания при
самостоятельном размещении:

| Переменная | Обязательность | Примечание |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | Да | Используйте `config.django.prod`. |
| `SECRET_KEY` | Да | Генерируйте отдельное стойкое значение для каждого развертывания. |
| `DEBUG` | Да | Должно быть `false`. |
| `ALLOWED_HOSTS` | Да | Список публичных хостов через запятую, например `money.example.com`. |
| `BASE_URL` | Да | Публичный HTTPS-адрес с завершающим `/`, например `https://money.example.com/`. |
| `CSRF_TRUSTED_ORIGINS` | Да | Список доверенных HTTPS origins через запятую, например `https://money.example.com`. |
| `DATABASE_URL` | Условно | Требуется при использовании внешнего экземпляра PostgreSQL вместо встроенного сервиса `db`. |
| `REDIS_LOCATION` | Да | URL Redis, используемый в production для кеша, сессий, Celery, rate limiting и axes. |
| `SESSION_COOKIE_SECURE` | Да | В production сохраняйте значение `true`. |
| `SESSION_COOKIE_HTTPONLY` | Да | В production сохраняйте значение `true`. |
| `SESSION_COOKIE_SAMESITE` | Да | Значение по умолчанию `Lax` подходит для текущего приложения. |
| `CSRF_COOKIE_SECURE` | Да | В production сохраняйте значение `true`. |
| `SECURE_SSL_REDIRECT` | Да | Сохраняйте `true`, если только TLS не завершается до приложения и это корректно не настроено. |
| `SECURE_CONTENT_TYPE_NOSNIFF` | Да | Сохраняйте `true`. |
| `SECURE_HSTS_SECONDS` | Да | Значение по умолчанию `31536000`. Уменьшайте только при осторожном поэтапном включении HSTS. |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | Да | Сохраняйте `true`, если все поддомены готовы к работе только по HTTPS. |
| `SECURE_HSTS_PRELOAD` | Да | Сохраняйте `true` только если вы намерены выполнить требования preload-списка. |
| `ERROR_TRACKING_DSN` | Рекомендуется | Sentry-compatible DSN. Настоятельно рекомендуется для диагностики production-сбоев. |
| `ERROR_TRACKING_ENVIRONMENT` | Рекомендуется | Обычно `production`. |

Следующие переменные обязательны при использовании встроенного Postgres-сервиса
из `docker-compose.prod.yaml`. В этом режиме `docker compose` автоматически
формирует `DATABASE_URL` для приложения, поэтому одни и те же учетные данные
не нужно дублировать одновременно в `DATABASE_URL` и `POSTGRES_*`.

| Переменная | Обязательность | Примечание |
|---|---|---|
| `POSTGRES_DB` | Да | Имя базы данных для контейнера Postgres. |
| `POSTGRES_USER` | Да | Имя пользователя базы данных для контейнера Postgres. |
| `POSTGRES_PASSWORD` | Да | Пароль базы данных для контейнера Postgres. Секрет. |

## Минимальный пример

```env
DJANGO_SETTINGS_MODULE=config.django.prod
SECRET_KEY=replace-with-generated-secret-key
DEBUG=false
ALLOWED_HOSTS=money.example.com
BASE_URL=https://money.example.com/
CSRF_TRUSTED_ORIGINS=https://money.example.com
REDIS_LOCATION=redis://redis:6379/0
POSTGRES_DB=hlvm
POSTGRES_USER=hlvm
POSTGRES_PASSWORD=replace-with-db-password
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_HTTPONLY=true
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SECURE=true
SECURE_SSL_REDIRECT=true
SECURE_CONTENT_TYPE_NOSNIFF=true
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=true
SECURE_HSTS_PRELOAD=true
ERROR_TRACKING_DSN=
ERROR_TRACKING_ENVIRONMENT=production
```

Для внешнего экземпляра PostgreSQL используйте:

```env
DATABASE_URL=postgresql://hlvm:replace-with-db-password@db.example.com:5432/hlvm
```

## Чек-лист production-развертывания

1. Сгенерируйте `SECRET_KEY` вне репозитория и храните его в CI secrets или в менеджере секретов.
2. Храните `POSTGRES_PASSWORD`, `DATABASE_URL` при его использовании и прочие секреты в CI secrets или в менеджере секретов.
3. Формируйте runtime-файл `.env` из управляемых секретов во время деплоя.
4. Убедитесь, что runtime-файл `.env` не закоммичен и имеет ограниченные права доступа на хосте.
5. Установите `DJANGO_SETTINGS_MODULE=config.django.prod`.
6. Установите `DEBUG=false`.
7. Установите `ALLOWED_HOSTS` в список реальных публичных хостов.
8. Установите `BASE_URL` и `CSRF_TRUSTED_ORIGINS` в соответствии с реальным публичным HTTPS-адресом.
9. Если используется встроенный сервис Postgres, задайте `POSTGRES_DB`, `POSTGRES_USER` и `POSTGRES_PASSWORD`.
10. Если используется внешний PostgreSQL, задайте `DATABASE_URL`.
11. Установите `REDIS_LOCATION` на доступный экземпляр Redis.
12. Сохраняйте `SESSION_COOKIE_SECURE=true` и `CSRF_COOKIE_SECURE=true`.
13. Сохраняйте `SESSION_COOKIE_HTTPONLY=true` и отдельно проверьте `SESSION_COOKIE_SAMESITE`, прежде чем менять его.
14. Сохраняйте `SECURE_SSL_REDIRECT=true`, если только TLS не завершается выше по цепочке и это не проверено отдельно.
15. Проверьте `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS` и `SECURE_HSTS_PRELOAD` перед публичным запуском.
16. Настройте `ERROR_TRACKING_DSN` и `ERROR_TRACKING_ENVIRONMENT` для наблюдаемости production-окружения.
17. Запустите стек командой `docker compose -f docker-compose.prod.yaml up -d`.
18. Убедитесь, что контейнеры находятся в состоянии health, командой `docker compose -f docker-compose.prod.yaml ps`.
19. Убедитесь, что приложение доступно по HTTPS, а cookies помечены флагом `Secure`.
20. Проверьте вход в систему, сохранение сессий, Redis-зависимые операции и подключение к базе данных.
21. До ввода в эксплуатацию проверьте процедуры резервного копирования и восстановления PostgreSQL и пользовательских файлов.
