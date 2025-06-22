# Contribute

This section is dedicated to helping you join our project. Whether you're an experienced developer or just starting out, we value your enthusiasm and willingness to contribute. Here you'll find resources and guides that will help you get started contributing to our project.

If you have any questions or need assistance getting started, don't hesitate to ask. We're always happy to collaborate with you!

## First steps

1. Fork [our repo](https://github.com/TurtleOld/hasta-la-vista-money.git), here's the [guide on forking](https://help.github.com/en/github/getting-started-with-github/fork-a-repo)
2. [Clone your new repo](https://help.github.com/en/github/creating-cloning-and-archiving-repositories/cloning-a-repository) (forked repo) to have a local copy of the code
3. Apply the required changes.
4. Send a Pull Request to our original repo. Here's [the helpful guide](https://help.github.com/en/github/collaborating-with-issues-and-pull-requests/creating-a-pull-request) on how to do that

## Installation and launch of the application

Use Poetry to manage dependencies.

To install **Poetry**, run the following command:

**Linux, macOS, Windows (WSL):**

```bash
curl -sSL https://install.python-poetry.org | python3 -
```
A detailed installation guide for Poetry is available at [official documentation](<https://python-poetry.org/docs/>).

------------------------------------------------------------------------

## 1. Installation

### 1.1 Cloning the Repository and Activating the Virtual Environment

#### Cloning the repository

```bash
git clone https://github.com/TurtleOld/hasta-la-vista-money.git
cd hasta-la-vista-money
```

### 1.2 Populating values in the .env file
```bash
make .env
```

SECRET_KEY - Key for the settings.py file. You can generate the key using the command - ```bash
make secretkey
```

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

------------------------------------------------------------------------

### 1.3 Activating the virtual environment:

```bash
make shell
```

If you encounter the error: ```bash
Command 'make' not found...
```  
Run the following command in the console:

```bash
sudo apt install make
```

Then:

```bash
make install
```

------------------------------------------------------------------------

## 2. Running the application in development mode

```bash
make start
```

## 3. Test code

```bash
make test
```

## 4. Linting

```bash
make lint
```

## 5. Formatting code
Before pushing the code to the remote repository, format it according to the guidelines:
```bash
make format
```