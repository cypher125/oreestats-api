#!/bin/bash
################################################################################
# OreeStats VPS Deployment Script
# 
# This script automates the deployment of:
# - Django API with Gunicorn
# - Celery Worker & Beat
# - Redis
# - PostgreSQL (optional)
# - Nginx
# - Supervisor
#
# Usage: 
#   chmod +x vps_setup.sh
#   ./vps_setup.sh
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "=================================="
echo "  OreeStats VPS Deployment"
echo "=================================="
echo -e "${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
   echo -e "${RED}Please run as root (use sudo)${NC}"
   exit 1
fi

# Get non-root user
read -p "Enter the username for deployment (default: oreestats): " USERNAME
USERNAME=${USERNAME:-oreestats}

# Get domain
read -p "Enter your domain name (or press Enter to use IP only): " DOMAIN

# Ask about PostgreSQL
read -p "Install PostgreSQL locally? (y/n, default: n - use Neon): " INSTALL_PG
INSTALL_PG=${INSTALL_PG:-n}

echo -e "${YELLOW}Starting deployment...${NC}"

################################################################################
# Step 1: System Update
################################################################################
echo -e "${GREEN}[1/12] Updating system...${NC}"
apt update && apt upgrade -y

################################################################################
# Step 2: Install Basic Tools
################################################################################
echo -e "${GREEN}[2/12] Installing basic tools...${NC}"
apt install -y git curl wget vim build-essential software-properties-common

################################################################################
# Step 3: Create User (if doesn't exist)
################################################################################
if id "$USERNAME" &>/dev/null; then
    echo -e "${YELLOW}User $USERNAME already exists${NC}"
else
    echo -e "${GREEN}[3/12] Creating user $USERNAME...${NC}"
    adduser --disabled-password --gecos "" $USERNAME
    usermod -aG sudo $USERNAME
fi

################################################################################
# Step 4: Install Python 3.11
################################################################################
echo -e "${GREEN}[4/12] Installing Python 3.11...${NC}"
add-apt-repository ppa:deadsnakes/ppa -y
apt update
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

################################################################################
# Step 5: Install PostgreSQL (Optional)
################################################################################
if [[ "$INSTALL_PG" == "y" ]]; then
    echo -e "${GREEN}[5/12] Installing PostgreSQL...${NC}"
    apt install -y postgresql postgresql-contrib
    systemctl start postgresql
    systemctl enable postgresql
    
    # Create database and user
    read -sp "Enter PostgreSQL password for oreestats_user: " PG_PASSWORD
    echo
    
    sudo -u postgres psql << EOF
CREATE DATABASE oreestats;
CREATE USER oreestats_user WITH PASSWORD '$PG_PASSWORD';
ALTER ROLE oreestats_user SET client_encoding TO 'utf8';
ALTER ROLE oreestats_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE oreestats_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE oreestats TO oreestats_user;
EOF
    
    DATABASE_URL="postgresql://oreestats_user:$PG_PASSWORD@localhost:5432/oreestats"
else
    echo -e "${YELLOW}[5/12] Skipping PostgreSQL installation (using external DB)${NC}"
    read -p "Enter your DATABASE_URL: " DATABASE_URL
fi

################################################################################
# Step 6: Install Redis
################################################################################
echo -e "${GREEN}[6/12] Installing Redis...${NC}"
apt install -y redis-server

# Configure Redis
sed -i 's/^supervised no/supervised systemd/' /etc/redis/redis.conf

systemctl restart redis
systemctl enable redis

################################################################################
# Step 7: Install Nginx
################################################################################
echo -e "${GREEN}[7/12] Installing Nginx...${NC}"
apt install -y nginx
systemctl start nginx
systemctl enable nginx

# Configure firewall
ufw allow 'Nginx Full'
ufw allow OpenSSH
ufw --force enable

################################################################################
# Step 8: Clone Repository
################################################################################
echo -e "${GREEN}[8/12] Setting up project directory...${NC}"

# Create apps directory
su - $USERNAME -c "mkdir -p ~/apps"

echo -e "${YELLOW}Upload your project to /home/$USERNAME/apps/oreestats${NC}"
echo -e "${YELLOW}Or clone from Git repository${NC}"
read -p "Press Enter when project is uploaded..."

PROJECT_DIR="/home/$USERNAME/apps/oreestats/OreeStats"

if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}Project directory not found at $PROJECT_DIR${NC}"
    exit 1
fi

################################################################################
# Step 9: Setup Python Environment
################################################################################
echo -e "${GREEN}[9/12] Setting up Python environment...${NC}"

su - $USERNAME << EOF
cd ~/apps/oreestats/OreeStats
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn supervisor
EOF

################################################################################
# Step 10: Create Environment File
################################################################################
echo -e "${GREEN}[10/12] Creating environment file...${NC}"

read -sp "Enter Django SECRET_KEY (or press Enter to generate): " SECRET_KEY
echo
if [ -z "$SECRET_KEY" ]; then
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
fi

read -p "Enter GOOGLE_CLIENT_ID: " GOOGLE_CLIENT_ID
read -sp "Enter GOOGLE_CLIENT_SECRET: " GOOGLE_CLIENT_SECRET
echo
read -p "Enter OREE_API_KEY (or press Enter to generate): " OREE_API_KEY
if [ -z "$OREE_API_KEY" ]; then
    OREE_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
fi

# Create .env file
cat > $PROJECT_DIR/.env << ENVEOF
DEBUG=False
SECRET_KEY=$SECRET_KEY
ALLOWED_HOSTS=${DOMAIN:-localhost},$(curl -s ifconfig.me)

DATABASE_URL=$DATABASE_URL

REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

JWT_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
JWT_ALGORITHM=HS256

OREE_API_KEY=$OREE_API_KEY

GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
GOOGLE_REDIRECT_URI=https://${DOMAIN}/api/oauth/callback
GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.modify

TRACKING_DOMAIN=${DOMAIN}
TRACKING_PROTOCOL=https

CORS_ALLOWED_ORIGINS=https://${DOMAIN}

WEB_CONCURRENCY=4
ENVEOF

chown $USERNAME:$USERNAME $PROJECT_DIR/.env

################################################################################
# Step 11: Run Migrations
################################################################################
echo -e "${GREEN}[11/12] Running database migrations...${NC}"

su - $USERNAME << EOF
cd ~/apps/oreestats/OreeStats
source venv/bin/activate
export \$(cat .env | xargs)
python manage.py migrate
python manage.py collectstatic --noinput
mkdir -p ~/apps/oreestats/logs
EOF

################################################################################
# Step 12: Setup Supervisor
################################################################################
echo -e "${GREEN}[12/12] Configuring Supervisor...${NC}"

apt install -y supervisor

# Gunicorn config
cat > $PROJECT_DIR/gunicorn_config.py << GUNICORNEOF
import multiprocessing

bind = "127.0.0.1:8000"
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
timeout = 120
accesslog = "/home/$USERNAME/apps/oreestats/logs/gunicorn-access.log"
errorlog = "/home/$USERNAME/apps/oreestats/logs/gunicorn-error.log"
loglevel = "info"
proc_name = "oreestats-api"
GUNICORNEOF

# Supervisor - Django API
cat > /etc/supervisor/conf.d/oreestats-api.conf << APIEOF
[program:oreestats-api]
command=/home/$USERNAME/apps/oreestats/OreeStats/venv/bin/gunicorn OreeStats.wsgi:application -c /home/$USERNAME/apps/oreestats/OreeStats/gunicorn_config.py
directory=/home/$USERNAME/apps/oreestats/OreeStats
user=$USERNAME
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/home/$USERNAME/apps/oreestats/logs/gunicorn.log
environment=PATH="/home/$USERNAME/apps/oreestats/OreeStats/venv/bin"
APIEOF

# Supervisor - Celery Worker
cat > /etc/supervisor/conf.d/oreestats-celery-worker.conf << WORKEREOF
[program:oreestats-celery-worker]
command=/home/$USERNAME/apps/oreestats/OreeStats/venv/bin/celery -A OreeStats worker --loglevel=info --concurrency=2
directory=/home/$USERNAME/apps/oreestats/OreeStats
user=$USERNAME
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/home/$USERNAME/apps/oreestats/logs/celery-worker.log
environment=PATH="/home/$USERNAME/apps/oreestats/OreeStats/venv/bin"
stopwaitsecs=600
WORKEREOF

# Supervisor - Celery Beat
cat > /etc/supervisor/conf.d/oreestats-celery-beat.conf << BEATEOF
[program:oreestats-celery-beat]
command=/home/$USERNAME/apps/oreestats/OreeStats/venv/bin/celery -A OreeStats beat --loglevel=info
directory=/home/$USERNAME/apps/oreestats/OreeStats
user=$USERNAME
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/home/$USERNAME/apps/oreestats/logs/celery-beat.log
environment=PATH="/home/$USERNAME/apps/oreestats/OreeStats/venv/bin"
BEATEOF

# Reload Supervisor
supervisorctl reread
supervisorctl update
supervisorctl start all

################################################################################
# Configure Nginx
################################################################################
echo -e "${GREEN}Configuring Nginx...${NC}"

if [ -z "$DOMAIN" ]; then
    SERVER_NAME="_"
else
    SERVER_NAME="$DOMAIN www.$DOMAIN"
fi

cat > /etc/nginx/sites-available/oreestats << NGINXEOF
upstream oreestats_api {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name $SERVER_NAME;
    
    client_max_body_size 100M;
    
    access_log /var/log/nginx/oreestats-access.log;
    error_log /var/log/nginx/oreestats-error.log;

    location /static/ {
        alias /home/$USERNAME/apps/oreestats/OreeStats/staticfiles/;
        expires 30d;
    }

    location /media/ {
        alias /home/$USERNAME/apps/oreestats/OreeStats/media/;
        expires 30d;
    }

    location / {
        proxy_pass http://oreestats_api;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
        proxy_connect_timeout 120s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/oreestats /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl restart nginx

################################################################################
# Final Steps
################################################################################
echo -e "${GREEN}"
echo "=================================="
echo "  Deployment Complete!"
echo "=================================="
echo -e "${NC}"

VPS_IP=$(curl -s ifconfig.me)

echo -e "${GREEN}✅ All services installed and started!${NC}"
echo ""
echo -e "${YELLOW}Service Status:${NC}"
supervisorctl status
echo ""
echo -e "${YELLOW}Access your API at:${NC}"
if [ -z "$DOMAIN" ]; then
    echo "  http://$VPS_IP/api/health"
else
    echo "  http://$DOMAIN/api/health"
fi
echo ""
echo -e "${YELLOW}Important Information:${NC}"
echo "  - API Key: $OREE_API_KEY"
echo "  - Logs: /home/$USERNAME/apps/oreestats/logs/"
echo "  - Project: /home/$USERNAME/apps/oreestats/OreeStats"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "  1. Test health endpoint: curl http://$VPS_IP/api/health"
if [ ! -z "$DOMAIN" ]; then
    echo "  2. Setup SSL: sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN"
fi
echo "  3. Create superuser: su - $USERNAME -c 'cd ~/apps/oreestats/OreeStats && source venv/bin/activate && python manage.py createsuperuser'"
echo "  4. Check logs: tail -f /home/$USERNAME/apps/oreestats/logs/*.log"
echo ""
echo -e "${GREEN}Deployment script completed successfully!${NC}"
