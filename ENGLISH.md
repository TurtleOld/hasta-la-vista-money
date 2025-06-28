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

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | `base64 /dev/urandom \| head -c50` |
| `DEBUG` | Debug mode | `false` (production) |
| `DATABASE_URL` | Database URL | `postgres://user:pass@localhost:5432/db` |
| `ALLOWED_HOSTS` | Allowed hosts | `localhost,127.0.0.1` |
| `LANGUAGE_CODE` | Interface language | `ru` |
| `TIME_ZONE` | Timezone | `Europe/Moscow` |

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

The project is distributed under the MIT license. See the [LICENSE](LICENSE) file for details.

---

**Hasta La Vista, Money!** — your reliable assistant in personal finance management! 💪 