# Bill Payment Reminder System

A comprehensive system to help users manage their bills and payments efficiently.

## Features

- User Authentication (Register, Login, Profile Management)
- Bill Management (Add, Update, Delete bills)
- Automated Email Reminders
- Interactive Dashboard
- Calendar Integration
- Sorting and Filtering Capabilities

## Setup Instructions

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run migrations:
```bash
python manage.py makemigrations
python manage.py migrate
```

4. Create a superuser:
```bash
python manage.py createsuperuser
```

5. Run the development server:
```bash
python manage.py runserver
```

6. Access the application at http://127.0.0.1:8000/

## Environment Variables

Create a `.env` file in the root directory with the following variables:
```
DEBUG=True
SECRET_KEY=your-secret-key
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-specific-password
```

## Technologies Used

- Django 5.0.2
- SQLite Database
- HTML5, CSS3, JavaScript
- Bootstrap 5
- Celery for background tasks
- Redis for message broker 