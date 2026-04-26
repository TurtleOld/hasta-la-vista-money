# Начало работы
[![hasta-la-vista-money](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml/badge.svg)](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml)  

Добро пожаловать в документацию проекта **Hasta La Vista, Money**.

### Важно

Проект Hasta La Vista, Money находится в активной разработке, поэтому возможны ошибки и дальнейшие изменения.
___
Hasta La Vista, Money - это проект домашней бухгалтерии, предназначенный для удобного учета семейных доходов и расходов. Кроме того, приложение позволяет быстро вносить данные о покупках вручную.


Приложение разворачивается на собственной инфраструктуре с использованием [Docker](https://docs.docker.com/desktop/setup/install/linux/). Инструкция приведена ниже.

## Установка

Приложение разворачивается с использованием [Docker](https://docs.docker.com/desktop/setup/install/linux/). Развертывание возможно как на локальной машине, так и на сервере.
___

В каталоге, где будут размещены файлы проекта, создайте файл `.env` и заполните его следующими значениями:

`SECRET_KEY` - ключ для `settings.py`. Его можно сгенерировать командой:

```bash
base64 /dev/urandom | head -c50
```

> SECRET_KEY=

`DEBUG` - включает режим отладки. На production-сервере включать не следует.
Допустимые значения: `true`, `1`, `yes`.

> DEBUG=

`DATABASE_URL` - URL подключения к базе данных.

Пример:

`postgres://username:password@hostname-or-ip:port/database_name`

> DATABASE_URL=

`ALLOWED_HOSTS` - список разрешенных хостов.

Пример: `localhost,127.0.0.1`.

> ALLOWED_HOSTS=  

___

Скачайте файл [docker-compose.yaml](https://github.com/TurtleOld/hasta-la-vista-money/releases/download/v1.4.0/docker-compose.yaml) и поместите его в рабочий каталог. Этот файл является примером и служит базовым шаблоном для запуска приложения. При необходимости измените его под свою среду.

Для production-развертывания при самостоятельном размещении используйте отдельный чек-лист и руководство по минимальному набору переменных: [Self-hosted production](production_self_hosted.md).

После этого запустите приложение командой:
```bash
docker compose up -d
```
Приложение будет запущено в фоновом режиме. Если после выполнения команды ошибок нет, откройте браузер и перейдите по адресу `http://127.0.0.1:8090`.

При первом запуске сайта откроется страница регистрации для создания учетной записи администратора.
