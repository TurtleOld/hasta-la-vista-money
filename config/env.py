import environ

env = environ.Env()

BASE_DIR = environ.Path(__file__) - 2
APPS_DIR = BASE_DIR.path("hasta_la_vista_money")