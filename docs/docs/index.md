# Getting started
[![hasta-la-vista-money](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml/badge.svg)](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml)  

Welcome to the documentation page of the project **Hasta La Vista, Money**!

### Disclaimer:
The Hasta La Vista, Money project is currently under active development, so be aware of potential bugs and future changes.
___
Hasta La Vista, Money is a home accounting project designed to efficiently manage family expenses and income. Additionally, the app provides an easy way to enter purchase data manually.


The application is deployed on your own hosting using [Docker](https://docs.docker.com/desktop/setup/install/linux/), instructions below.

## Installation  

The application is deployed using [Docker](https://docs.docker.com/desktop/setup/install/linux/). You can deploy it on your local machine or a server.
___

In the directory where the project files will reside, create a _.env_ file and populate it with the following details:

SECRET_KEY - Key for the settings.py file. You can generate the key using the command - ```base64 /dev/urandom | head -c50```

> SECRET_KEY=

DEBUG - Debugging activation. Do not enable on a production server.
Set one of the following values: true, 1, yes.

> DEBUG=

DATABASE_URL - Database connection URL  
postgres://username:password@name or IP server:port/name_database

> DATABASE_URL=

ALLOWED_HOSTS - List of allowed hosts. Example 'localhost',
'127.0.0.1'. By default, hosts - localhost, 127.0.0.1

> ALLOWED_HOSTS=  

___

Download the [docker-compose.yaml](https://github.com/TurtleOld/hasta-la-vista-money/releases/download/v1.4.0/docker-compose.yaml) file and place it in your directory. This file is a sample and serves as a basic template for launching the application. Feel free to modify it as you see fit.

Next, start the application using the command below:
```commandline
docker compose up -d
```
The application will launch in the background. If there are no errors after running the command, open your browser and go to http://127.0.0.1:8090.  
Upon the first launch of the website, a registration page will open for creating an administrator account.