import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Supraja.settings')
django.setup()

from django.contrib.auth.models import User

# Create admin1
if not User.objects.filter(username='admin1').exists():
    User.objects.create_superuser('admin1', 'admin1@example.com', 'admin1')
    print("Created admin1")
else:
    print("admin1 already exists")

# Create admin2
if not User.objects.filter(username='admin2').exists():
    User.objects.create_superuser('admin2', 'admin2@example.com', 'admin2')
    print("Created admin2")
else:
    print("admin2 already exists")
