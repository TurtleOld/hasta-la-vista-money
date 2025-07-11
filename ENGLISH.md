# Hasta La Vista, Money! 💰

[![hasta-la-vista-money](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml/badge.svg)](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml)
[![](https://app.codacy.com/project/badge/Grade/5281be8b483c4c7d8576bdf0ad15d94d)](https://app.codacy.com/gh/TurtleOld/hasta-la-vista-money/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![](https://app.codacy.com/project/badge/Coverage/5281be8b483c4c7d8576bdf0ad15d94d)](https://app.codacy.com/gh/TurtleOld/hasta-la-vista-money/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_coverage)
[![](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)
[![](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=blanks)](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=blanks)
[![](https://wakatime.com/badge/github/TurtleOld/hasta-la-vista-money.svg)](https://wakatime.com/badge/github/TurtleOld/hasta-la-vista-money)

**[🇷🇺 Русская версия](README.md)**

## 🎯 About the Project

**Hasta La Vista, Money!** is a modern personal finance management system designed as a self-hosted open source solution for efficient income and expense tracking and budget planning. The application provides a complete set of tools for financial state control with an intuitive interface and powerful analytics.

**Key Features:**
- 🏠 **Self-hosted** — full control over data and infrastructure
- 🔓 **Open Source** — transparent code and customization capabilities
- 👤 **Personal Use** — all users have full administrator rights
- 🔒 **Privacy** — your financial data stays on your server

### ✨ Key Capabilities

#### 💳 **Account Management**
- Create and manage multiple accounts
- Support for various currencies
- Automatic total balance calculation
- Transaction history for each account

#### 📊 **Income and Expense Tracking**
- Categorization of income and expenses
- Hierarchical category structure
- Quick operation addition
- Filtering and search by dates, categories, amounts

#### 🧾 **Receipt Processing**
- Automatic receipt recognition
- QR code data import
- Manual purchase entry
- Purchase analysis by sellers and products

#### 📈 **Budgeting and Planning**
- Monthly income and expense planning
- Comparison of plans with actual data
- Budget execution tracking
- Limit exceed notifications

#### 📋 **Reports and Analytics**
- Detailed statistics by periods
- Income and expense dynamics charts
- Category analysis
- Data export in JSON format

#### 👤 **Personal Profile**
- **Extended Information**: email, first name, last name
- **Statistics Dashboard**: total balance, monthly income/expenses, savings
- **Tab System**: personal information, statistics, recent operations, settings
- **Detailed Analytics**: 6-month charts, top categories, savings percentage
- **Smart Notifications**: low balance warnings, expense exceed alerts, recommendations
- **Data Export**: complete user data export

#### 🔔 **Notification System**
- Automatic notifications about important events
- Low account balance warnings
- Notifications about expenses exceeding income
- Encouragement for good savings
- Recommendations for improving financial state

### 🛠 Technology Stack

- **Backend**: Django 5.2, Python 3.12
- **Frontend**: Bootstrap 5, Chart.js, jQuery
- **Database**: PostgreSQL
- **Containerization**: Docker & Docker Compose
- **Security**: CSP, CSRF protection, authentication
- **Internationalization**: Russian language support

### 🚀 Quick Start

#### Requirements
- Docker and Docker Compose
- PostgreSQL (optional, can use SQLite for development)

#### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/TurtleOld/hasta-la-vista-money.git
cd hasta-la-vista-money
```

2. **Create a `.env` file in the project root:**
```bash
# Required settings
SECRET_KEY=your-secret-key-here
DEBUG=false
DATABASE_URL=postgres://username:password@localhost:5432/hasta_la_vista_money
ALLOWED_HOSTS=localhost,127.0.0.1

# Additional settings (optional)
LANGUAGE_CODE=ru
TIME_ZONE=Europe/Moscow
```

3. **Start the application:**
```bash
docker compose up -d
```

4. **Open your browser and go to:**
```
http://127.0.0.1:8090
```

5. **Create an account:**
- Go to the registration page
- Fill out the registration form
- Done! Now you have full access to all system functions

### 📱 Main Features

#### 🎯 **Complete Financial Management Functionality:**
- ✅ Registration and authentication
- ✅ Personal profile management with extended analytics
- ✅ Add and edit accounts
- ✅ Income and expense tracking
- ✅ Operation categorization
- ✅ Budget planning
- ✅ Financial state analysis
- ✅ Data export
- ✅ Notifications and recommendations
- ✅ Receipt and QR code processing
- ✅ Detailed statistics and reports
- ✅ System management (monitoring, settings, backup)

### 🔧 Configuration

#### Environment Variables

## Required Variables

| Variable           | Description                                   | Example/Default Value                        | Required?   |
|--------------------|-----------------------------------------------|----------------------------------------------|-------------|
| `SECRET_KEY`       | Django secret key                             | `base64 /dev/urandom \| head -c50`           | Yes         |
| `DEBUG`            | Debug mode                                    | `false` (production) / `true` (dev)          | Yes         |
| `ALLOWED_HOSTS`    | Allowed hosts (comma-separated)               | `localhost,127.0.0.1`                        | Yes         |

### For PostgreSQL (if used, otherwise not needed):

| Variable           | Description                                   | Example/Default Value                        | Required?   |
|--------------------|-----------------------------------------------|----------------------------------------------|-------------|
| `DATABASE_URL`     | Database URL (PostgreSQL)                     | `postgres://user:pass@localhost:5432/db`     | Yes (if not SQLite) |
| `POSTGRES_DB`      | DB name (alternative to DATABASE_URL)          | `postgres`                                   | No          |
| `POSTGRES_USER`    | DB user                                       | `postgres`                                   | No          |
| `POSTGRES_PASSWORD`| DB password                                   | `postgres`                                   | No          |
| `POSTGRES_HOST`    | DB host                                       | `localhost`                                  | No          |
| `POSTGRES_PORT`    | DB port                                       | `5432`                                       | No          |

## Optional Variables

| Variable                  | Description                                   | Example/Default Value                        | Required?   |
|--------------------------|-----------------------------------------------|----------------------------------------------|-------------|
| `BASE_URL`               | Base site URL                                 | `http://127.0.0.1:8000/`                     | No          |
| `CSRF_TRUSTED_ORIGINS`   | Trusted origins for CSRF                      | `https://example.com`                        | No          |
| `LOCAL_IPS`              | Local IPs for INTERNAL_IPS                    | `127.0.0.1`                                  | No          |
| `LANGUAGE_CODE`          | Interface language                            | `en`                                         | No          |
| `TIME_ZONE`              | Timezone                                      | `Europe/Moscow`                              | No          |
| `SENTRY_DSN`             | Sentry DSN                                    | `<dsn>`                                      | No          |
| `SENTRY_ENVIRONMENT`     | Sentry environment                            | `production`                                 | No          |
| `SENTRY_ENDPOINT`        | report_uri for CSP                            | `<url>`                                      | No          |
| `URL_CSP_SCRIPT_SRC`     | Additional CSP sources                        | `https://mycdn.com`                          | No          |
| `SESSION_COOKIE_AGE`     | Session cookie lifetime (seconds)              | `31536000`                                   | No          |
| `SESSION_COOKIE_HTTPONLY`| HttpOnly for session cookie                   | `True`                                       | No          |
| `SESSION_COOKIE_NAME`    | Session cookie name                           | `sessionid`                                  | No          |
| `SESSION_COOKIE_SAMESITE`| SameSite for session cookie                   | `Lax`                                        | No          |
| `SESSION_COOKIE_SECURE`  | Secure for session cookie                     | `False`                                      | No          |
| `SECURE_SSL_REDIRECT`    | Force HTTPS                                   | `True`                                       | No          |
| `SECURE_CONTENT_TYPE_NOSNIFF` | MIME sniffing protection                  | `True`                                       | No          |
| `ACCESS_TOKEN_LIFETIME`  | Access token lifetime (minutes)               | `60`                                         | No          |
| `REFRESH_TOKEN_LIFETIME` | Refresh token lifetime (days)                 | `7`                                          | No          |
| `DEBUG_TOOLBAR_ENABLED`  | Enable Debug Toolbar                          | `True`                                       | No          |

### For AI Integration (receipt reading):

| Variable           | Description                                   | Example/Default Value                        | Required?   |
|--------------------|-----------------------------------------------|----------------------------------------------|-------------|
| `API_BASE_URL`     | Base URL for AI service                       | `https://models.github.ai/inference`         | No          |
| `API_KEY`          | API key for AI service                        | `<token>`                                    | No (but needed for AI) |
| `API_MODEL`        | AI model                                      | `openai/gpt-4o`                              | No          |

## Example .env

```env
# Required
SECRET_KEY=your-secret-key-here
DEBUG=false
ALLOWED_HOSTS=localhost,127.0.0.1

# For PostgreSQL (if not SQLite)
DATABASE_URL=postgres://username:password@localhost:5432/hasta_la_vista_money

# Optional
BASE_URL=http://127.0.0.1:8000/
LANGUAGE_CODE=en
TIME_ZONE=Europe/Moscow
SENTRY_DSN=
SENTRY_ENVIRONMENT=
SENTRY_ENDPOINT=
URL_CSP_SCRIPT_SRC=
SESSION_COOKIE_AGE=31536000
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_NAME=sessionid
SESSION_COOKIE_SAMESITE=Lax
SESSION_COOKIE_SECURE=False
SECURE_SSL_REDIRECT=True
SECURE_CONTENT_TYPE_NOSNIFF=True
ACCESS_TOKEN_LIFETIME=60
REFRESH_TOKEN_LIFETIME=7
DEBUG_TOOLBAR_ENABLED=True

# For AI
API_BASE_URL=https://models.github.ai/inference
API_KEY=
API_MODEL=openai/gpt-4o
```

### 📊 Monitoring and Analytics

The application provides built-in monitoring tools:
- Logging of all operations
- Performance tracking
- Error monitoring
- Usage statistics

### 🔒 Security

- CSRF attack protection
- Content Security Policy (CSP)
- Secure authentication
- Validation of all input data
- SQL injection protection
- Secure password storage

### 📚 Documentation

Detailed documentation is available on [Read the Docs](https://hasta-la-vista-money.readthedocs.io/):
- [User Guide](https://hasta-la-vista-money.readthedocs.io/)
- [Developer Guide](https://hasta-la-vista-money.readthedocs.io/contribute/)
- [API Documentation](https://hasta-la-vista-money.readthedocs.io/api/)

### 🤝 Contributing

We welcome contributions to the project! If you want to help:

1. Fork the repository
2. Create a branch for a new feature
3. Make changes
4. Create a Pull Request

Read more about the development process in the [contributor guide](https://hasta-la-vista-money.readthedocs.io/contribute/).

### 📄 License

The project is distributed under the Apache license. See the [LICENSE](LICENSE) file for details.

---

**Hasta La Vista, Money!** — your reliable assistant in personal finance management! 💪
