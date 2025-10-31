# Hasta La Vista, Money! 💰

[![hasta-la-vista-money](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml/badge.svg)](https://github.com/TurtleOld/hasta-la-vista-money/actions/workflows/hasta_la_vista_money.yaml)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/5281be8b483c4c7d8576bdf0ad15d94d)](https://app.codacy.com/gh/TurtleOld/hasta-la-vista-money/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![Codacy Coverage](https://app.codacy.com/project/badge/Coverage/5281be8b483c4c7d8576bdf0ad15d94d)](https://app.codacy.com/gh/TurtleOld/hasta-la-vista-money/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_coverage)
[![Lines of Code](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)](https://sloc.xyz/github/hlvm-app/hasta-la-vista-money/?category=code)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-green.svg)](https://www.djangoproject.com/)

**[🇷🇺 Русская версия](README.md)** | **[📚 Documentation](https://hasta-la-vista-money.readthedocs.io/)**

---

## 🎯 About the Project

**Hasta La Vista, Money!** is a modern open-source personal finance management system designed for self-hosting. Take full control of your financial data with powerful analytics and budget planning tools.

### ✨ Why Hasta La Vista, Money?

- 🏠 **Self-hosted** — full control over your data and infrastructure
- 🔓 **Open Source** — transparent code, free Apache 2.0 license
- 🔒 **Privacy** — your financial data stays on your server only
- 🚀 **Easy Deployment** — one-click launch via Docker Compose
- 🌐 **Multi-language** — fully localized interface (Russian/English)

---

## 💡 Key Features

<table>
<tr>
<td width="50%">

### 💳 Financial Accounting
- Manage multiple accounts
- Support for various currencies
- Track income and expenses
- Hierarchical categorization
- Complete transaction history

### 📊 Analytics & Reports
- Detailed statistics by period
- Interactive charts and graphs
- Expense analysis by category
- Data export in JSON format

### 🧾 Receipt Processing
- AI-powered receipt recognition
- QR code data import
- Manual purchase entry
- Analysis by sellers and products

</td>
<td width="50%">

### 📈 Budgeting
- Income and expense planning
- Plan vs actual comparison
- Budget execution tracking
- Smart limit notifications

### 👤 Personal Profile
- Dashboard with statistics
- 6-month detailed analytics
- Top expense categories
- Optimization recommendations

### 🔔 Notification System
- Low balance warnings
- Expense excess alerts
- Savings encouragement
- Personalized recommendations

</td>
</tr>
</table>

---

## 🛠 Technology Stack

| Component | Technologies |
|-----------|-------------|
| **Backend** | Django 5.2, Python 3.12, Django REST Framework |
| **Frontend** | Bootstrap 5, Chart.js, jQuery, HTMX |
| **Database** | PostgreSQL, SQLite (for development) |
| **API** | RESTful API, OpenAPI/Swagger documentation |
| **Containerization** | Docker, Docker Compose |
| **Security** | CSP, CSRF, JWT authentication, django-axes |
| **Monitoring** | Sentry, Django Debug Toolbar |
| **Localization** | i18n, full Russian/English support |

---

## 🚀 Quick Start

### Minimum Requirements
- Docker and Docker Compose
- 1 GB free disk space
- 512 MB RAM

### Installation in 3 Steps

```bash
# 1. Clone the repository
git clone https://github.com/TurtleOld/hasta-la-vista-money.git
cd hasta-la-vista-money

# 2. Create .env file with minimal settings
cat > .env << EOF
SECRET_KEY=$(openssl rand -base64 50)
DEBUG=false
ALLOWED_HOSTS=localhost,127.0.0.1
EOF

# 3. Start the application
docker compose up -d
```

**Done!** Open your browser and go to [http://127.0.0.1:8090](http://127.0.0.1:8090)

> 💡 **Tip:** On first launch, the application will automatically create an SQLite database. For production, PostgreSQL is recommended.

### First Steps
1. Register an administrator account
2. Create your first financial account
3. Add income and expense categories
4. Start tracking your finances!

> 📚 **Complete installation and configuration guide:** [hasta-la-vista-money.readthedocs.io](https://hasta-la-vista-money.readthedocs.io/)

---

## ⚙️ Configuration

The application is configured through environment variables in the `.env` file:

### Main Variables

| Variable | Description | Default Value |
|----------|-------------|---------------|
| `SECRET_KEY` | Django secret key (required) | - |
| `DEBUG` | Debug mode | `false` |
| `ALLOWED_HOSTS` | Allowed hosts | `localhost,127.0.0.1` |
| `DATABASE_URL` | PostgreSQL URL (optional) | SQLite |
| `LANGUAGE_CODE` | Interface language | `en` |
| `TIME_ZONE` | Timezone | `UTC` |

### Additional Features

- **PostgreSQL**: Recommended for production instead of SQLite
- **AI for receipts**: OpenAI API integration for automatic receipt recognition
- **Sentry**: Error monitoring in production
- **Redis**: Caching for improved performance

> 📖 **Full list of variables and configuration examples:** [Configuration Documentation](https://hasta-la-vista-money.readthedocs.io/)

---

## 🔒 Security

The application includes multiple protection mechanisms:

- ✅ CSRF and XSS attack protection
- ✅ Content Security Policy (CSP)
- ✅ JWT authentication for API
- ✅ All input data validation
- ✅ SQL injection protection via Django ORM
- ✅ API rate limiting (django-axes)
- ✅ Secure password storage (bcrypt)

---

## 📚 Documentation

Complete documentation is hosted on **[Read the Docs](https://hasta-la-vista-money.readthedocs.io/)**:

- 📖 [User Guide](https://hasta-la-vista-money.readthedocs.io/) — getting started, features, usage examples
- 🛠 [Developer Guide](https://hasta-la-vista-money.readthedocs.io/contribute/) — architecture, development, testing
- 🔌 [API Documentation](https://hasta-la-vista-money.readthedocs.io/api/) — REST API, endpoints, request examples

---

## 🤝 Contributing

We welcome any contribution to the project! Here's how you can help:

### Ways to Contribute

- 🐛 **Report a bug** — create an [Issue](https://github.com/TurtleOld/hasta-la-vista-money/issues)
- 💡 **Suggest an improvement** — describe your idea in [Discussions](https://github.com/TurtleOld/hasta-la-vista-money/discussions)
- 🔧 **Fix an issue** — create a Pull Request
- 📝 **Improve documentation** — docs always need updates
- 🌍 **Add translation** — help localize the application

### Development Process

```bash
# 1. Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/hasta-la-vista-money.git

# 2. Create a branch for your feature
git checkout -b feature/amazing-feature

# 3. Install development dependencies
uv sync --dev

# 4. Make changes and test
uv run pytest

# 5. Create a Pull Request
```

> 📋 **More details:** [Contributor Guide](https://hasta-la-vista-money.readthedocs.io/contribute/)

---

## 💬 Community & Support

- 💬 [GitHub Discussions](https://github.com/TurtleOld/hasta-la-vista-money/discussions) — discussions, questions, ideas
- 🐛 [Issue Tracker](https://github.com/TurtleOld/hasta-la-vista-money/issues) — bugs and feature requests
- 📧 [Email](mailto:dev@pavlovteam.ru) — direct contact with developer

---

## 📄 License

This project is licensed under the **Apache License 2.0**.  
See the [LICENSE](LICENSE) file for details.

```
Copyright 2022-2025 Alexander Pavlov (TurtleOld)
Licensed under the Apache License, Version 2.0
```

---

## ⭐ Support the Project

If you like **Hasta La Vista, Money!**, give it a ⭐ on GitHub!  
It helps other users discover the project.

---

<div align="center">

**Hasta La Vista, Money!** — your reliable assistant in personal finance management! 💪

Made with ❤️ in Russia

[🌐 Website](https://hasta-la-vista-money.readthedocs.io/) • [📖 Documentation](https://hasta-la-vista-money.readthedocs.io/) • [🐛 Bug Reports](https://github.com/TurtleOld/hasta-la-vista-money/issues)

</div>
