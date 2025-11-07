# 🚀 OreeStats API - Email Sending & Tracking System

Django REST API for the AISDR MVP project. Handles Gmail OAuth, email sending via Gmail API, tracking (opens, clicks, replies), and provides a multi-tenant client dashboard.

---

## 📋 **Features**

### **Email Management**
- ✅ Send emails via Gmail API
- ✅ Queue-based email processing with Celery
- ✅ Sticky mailbox assignment (same lead = same mailbox)
- ✅ Gmail rate limiting & daily send limits
- ✅ OAuth 2.0 authentication for Gmail accounts

### **Email Tracking**
- ✅ Open tracking (invisible pixel)
- ✅ Click tracking (link wrapping)
- ✅ Reply tracking (webhook)
- ✅ Real-time event logging

### **Client Dashboard**
- ✅ JWT authentication
- ✅ Multi-tenant isolation
- ✅ Campaign statistics (all-time, 7-day, 30-day)
- ✅ Sequence performance metrics
- ✅ Email replies feed
- ✅ Daily timeline data
- ✅ Mailbox status monitoring
- ✅ Password management
- ✅ Campaign pause/resume

### **Background Processing**
- ✅ Celery workers for async tasks
- ✅ Celery beat for scheduled tasks
- ✅ Redis message broker
- ✅ Daily send count reset

---

## 🏗️ **Tech Stack**

- **Framework:** Django 5.2 + Django REST Framework
- **Database:** PostgreSQL (Neon for AISDR, Render for Django models)
- **Cache/Queue:** Redis
- **Task Queue:** Celery + Celery Beat
- **Email:** Gmail API (OAuth 2.0)
- **Authentication:** JWT (PyJWT)
- **Deployment:** Render
- **Documentation:** Swagger/OpenAPI (drf-spectacular)

---

## 📁 **Project Structure**

```
OreeStats/
├── OreeStats/              # Django project settings
│   ├── settings.py         # Main configuration
│   ├── urls.py             # Root URL routing
│   ├── celery.py           # Celery configuration
│   └── wsgi.py             # WSGI application
│
├── email_service/          # Main app
│   ├── models.py           # Database models
│   ├── views.py            # API endpoints
│   ├── serializers.py      # DRF serializers
│   ├── urls.py             # App URL routing
│   ├── tasks.py            # Celery tasks
│   ├── utils.py            # Helper functions
│   └── gmail_client.py     # Gmail API wrapper
│
├── render.yaml             # Render deployment config
├── build.sh                # Build script for Render
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (local)
└── README.md               # This file
```

---

## 🚀 **Quick Start (Local Development)**

### **1. Prerequisites**

- Python 3.11+
- PostgreSQL
- Redis

### **2. Clone Repository**

```bash
git clone https://github.com/YOUR_USERNAME/oreestats-api.git
cd oreestats-api
```

### **3. Install Dependencies**

```bash
pip install -r requirements.txt
```

### **4. Configure Environment**

Copy `.env.example` to `.env` and fill in values:

```bash
# Django
DEBUG=True
SECRET_KEY=your-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (AISDR - Neon)
DB_NAME=neondb
DB_USER=neondb_owner
DB_PASSWORD=your-password
DB_HOST=your-host.neon.tech
DB_PORT=5432

# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Google OAuth
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/oauth/callback

# JWT
JWT_SECRET_KEY=your-jwt-secret
JWT_ALGORITHM=HS256

# API Key
OREE_API_KEY=your-api-key
```

### **5. Run Migrations**

```bash
python manage.py migrate
```

### **6. Start Services**

**Terminal 1 - Django Server:**
```bash
python manage.py runserver
```

**Terminal 2 - Celery Worker:**
```bash
celery -A OreeStats worker --loglevel=info
```

**Terminal 3 - Celery Beat:**
```bash
celery -A OreeStats beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

**Terminal 4 - Redis:**
```bash
redis-server
```

---

## 🌐 **API Endpoints**

### **Email Sending**
```
POST   /api/email/send              # Queue email for sending
GET    /api/email/status/:lead_id   # Get email status
```

### **Tracking**
```
GET    /api/track/open/:pixel_id.png    # Track email open
GET    /api/track/click/:click_id       # Track link click
POST   /api/track/reply                 # Track email reply
```

### **OAuth**
```
GET    /api/oauth/initiate/:client_id   # Start OAuth flow
GET    /api/oauth/callback              # OAuth callback
```

### **Client Dashboard**
```
POST   /api/client/login                # Client login
POST   /api/client/logout               # Client logout
GET    /api/client/stats                # Campaign statistics
GET    /api/client/campaigns            # Sequence performance
GET    /api/client/replies              # Recent replies
GET    /api/client/timeline             # Daily timeline data
GET    /api/client/mailboxes            # Mailbox status
POST   /api/client/change-password      # Change password
PUT    /api/client/settings             # Update settings
```

### **Utility**
```
GET    /api/health                      # Health check
```

---

## 📚 **Documentation**

### **Swagger/OpenAPI**
- Local: http://localhost:8000/api/docs/
- Production: https://your-app.onrender.com/api/docs/

### **Guides**
- [Client Dashboard Backend](../CLIENT_DASHBOARD_BACKEND_COMPLETE.md)
- [Quick Start Guide](../QUICK_START_CLIENT_DASHBOARD.md)
- [Render Deployment Guide](../RENDER_DEPLOYMENT_GUIDE.md)
- [Deployment Checklist](../DEPLOYMENT_CHECKLIST.md)
- [Sticky Mailbox Assignment](../STICKY_MAILBOX_ASSIGNMENT.md)
- [Two-Tier Business Model](../TWO_TIER_BUSINESS_MODEL.md)

---

## 🚀 **Deployment to Render**

### **Quick Deploy**

1. **Push to GitHub:**
```bash
git add .
git commit -m "Ready for deployment"
git push origin main
```

2. **Deploy with Blueprint:**
- Go to [Render Dashboard](https://dashboard.render.com)
- Click "New" → "Blueprint"
- Select your repository
- Click "Apply"
- Set manual environment variables (see guide)

3. **Verify Deployment:**
```bash
curl https://your-app.onrender.com/api/health
```

**See:** [`RENDER_DEPLOYMENT_GUIDE.md`](../RENDER_DEPLOYMENT_GUIDE.md) for detailed instructions.

---

## 🧪 **Testing**

### **Test Client Login**

```bash
# Create test client
python create_client_account.py

# Test login
curl -X POST http://localhost:8000/api/client/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@testcompany.com","password":"TestPassword123"}'
```

### **Test Email Sending**

```bash
curl -X POST http://localhost:8000/api/email/send \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "lead_id": "uuid-here",
    "client_id": "uuid-here",
    "recipient_email": "test@example.com",
    "email_subject": "Test Email",
    "email_body": "<p>Test body</p>",
    "sequence_number": 1
  }'
```

---

## 🛠️ **Development**

### **Database Migrations**

```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Rollback
python manage.py migrate email_service 0001
```

### **Create Superuser**

```bash
python manage.py createsuperuser
```

### **Django Shell**

```bash
python manage.py shell
```

### **Celery Monitoring**

```bash
# Inspect active tasks
celery -A OreeStats inspect active

# Get worker stats
celery -A OreeStats inspect stats

# Purge all tasks
celery -A OreeStats purge
```

---

## 🔐 **Security**

### **Authentication Methods**

1. **API Key** - For n8n/external services
   - Header: `Authorization: Bearer YOUR_API_KEY`
   
2. **JWT Tokens** - For client dashboard
   - Header: `Authorization: Bearer JWT_TOKEN`
   - Login at `/api/client/login` to get token

### **Multi-Tenant Isolation**

All client data queries filter by `client_id`:
```python
# ✅ Correct - Isolated
EmailEvent.objects.filter(client_id=request.client_id)

# ❌ Wrong - Exposes all clients
EmailEvent.objects.all()
```

### **Password Security**

- PBKDF2-SHA256 hashing
- Minimum 8 characters
- Never stored in plain text

---

## 📊 **Database Schema**

### **Django Models (Render PostgreSQL)**

- `GmailToken` - OAuth tokens for Gmail accounts
- `EmailSendQueue` - Queued emails for sending
- `EmailEvent` - Tracking events (open, click, reply)
- `LeadMailboxAssignment` - Sticky mailbox assignments
- `EmailTrackingPixel` - Tracking pixel records
- `EmailClickTracking` - Click tracking records

### **AISDR Database (Neon)**

External database with:
- `clients` - Client accounts
- `leads` - Email recipients
- `client_profiles` - Client ICP data

---

## 🐛 **Troubleshooting**

### **Celery worker not processing tasks**

```bash
# Check Redis connection
redis-cli ping
# Expected: PONG

# Check Celery logs
celery -A OreeStats worker --loglevel=debug
```

### **Gmail API rate limit errors**

- Each mailbox limited to 2000 emails/day
- Rate limited to 2.5 emails/second per mailbox
- System uses round-robin across multiple mailboxes

### **Database connection errors**

```bash
# Test PostgreSQL connection
python manage.py dbshell
```

---

## 📈 **Performance**

### **Current Limits**

- **Emails per day:** 2000 per mailbox
- **Send rate:** 2.5 emails/second per mailbox
- **Concurrent workers:** 2 (configurable)
- **Queue processing:** ~100 emails/minute

### **Scaling**

To handle more volume:
1. Add more Gmail mailboxes
2. Increase worker concurrency
3. Scale up Render plan
4. Add more worker services

---

## 🤝 **Contributing**

### **Code Style**

- Use Black for formatting
- Follow Django best practices
- Write docstrings for functions
- Keep views thin, logic in utils

### **Commit Messages**

```bash
# Feature
git commit -m "feat: Add email retry logic"

# Bug fix
git commit -m "fix: Correct timezone in tracking pixel"

# Documentation
git commit -m "docs: Update API endpoint descriptions"
```

---

## 📞 **Support**

### **Issues**

- Check logs in Render Dashboard
- Review relevant guide in docs/
- Verify environment variables

### **Resources**

- [Render Docs](https://render.com/docs)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Celery Docs](https://docs.celeryq.dev/)
- [Gmail API Docs](https://developers.google.com/gmail/api)

---

## 📄 **License**

Proprietary - Momentum Outbound

---

## 🎉 **Status**

**Backend:** ✅ Complete

**Services:**
- Email Sending ✅
- Email Tracking ✅
- Client Dashboard ✅
- Celery Workers ✅
- Deployment Config ✅

**Next Steps:**
1. Deploy to Render
2. Build frontend dashboard
3. Test with real clients
4. Monitor and optimize

---

**Built for AISDR MVP - Email sending and tracking system with multi-tenant client dashboard**
