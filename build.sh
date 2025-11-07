#!/usr/bin/env bash
# exit on error
set -o errexit

echo "==================================================
OREESTATS API - BUILD SCRIPT
==================================================
"

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Collect static files
echo "📁 Collecting static files..."
python manage.py collectstatic --no-input

# Run database migrations
echo "🗄️  Running database migrations..."
python manage.py migrate --no-input

# Create Django superuser (optional, only if needed)
# Uncomment if you want to create a superuser automatically
# echo "👤 Creating superuser..."
# python manage.py shell -c "
# from django.contrib.auth import get_user_model;
# User = get_user_model();
# User.objects.filter(username='admin').exists() or \
# User.objects.create_superuser('admin', 'admin@oreestats.com', '$DJANGO_SUPERUSER_PASSWORD')
# "

echo "
==================================================
✅ BUILD COMPLETE
==================================================
"
