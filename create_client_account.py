"""
Helper script to create client accounts with dashboard access
Run: python create_client_account.py
"""

import os
import sys
import django
import uuid
from pathlib import Path

# Setup Django
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'OreeStats.settings')
django.setup()

from django.contrib.auth.hashers import make_password
import psycopg2
from django.conf import settings


def create_client_account():
    """
    Interactive script to create a new client account
    """
    print("\n" + "="*60)
    print("CREATE CLIENT ACCOUNT - Momentum AISDR Dashboard")
    print("="*60 + "\n")
    
    # Get client details
    company_name = input("Company Name: ").strip()
    if not company_name:
        print("❌ Company name is required!")
        return
    
    email = input("Email Address: ").strip().lower()
    if not email or '@' not in email:
        print("❌ Valid email address is required!")
        return
    
    password = input("Password (min 8 characters): ").strip()
    if len(password) < 8:
        print("❌ Password must be at least 8 characters!")
        return
    
    tier = input("Tier (self_serve/managed) [self_serve]: ").strip().lower()
    if not tier:
        tier = 'self_serve'
    if tier not in ['self_serve', 'managed']:
        print("❌ Tier must be 'self_serve' or 'managed'!")
        return
    
    print("\n" + "-"*60)
    print("Creating account...")
    print("-"*60 + "\n")
    
    try:
        # Connect to AISDR database
        conn = psycopg2.connect(
            dbname=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT
        )
        cursor = conn.cursor()
        
        # Check if email already exists
        cursor.execute("SELECT id FROM clients WHERE email = %s", (email,))
        if cursor.fetchone():
            print(f"❌ Email {email} already exists!")
            cursor.close()
            conn.close()
            return
        
        # Generate client ID
        client_id = str(uuid.uuid4())
        
        # Hash password
        password_hash = make_password(password)
        
        # Insert client
        cursor.execute("""
            INSERT INTO clients (
                id,
                company_name,
                email,
                password_hash,
                tier,
                status,
                dashboard_enabled,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
        """, (
            client_id,
            company_name,
            email,
            password_hash,
            tier,
            'active',
            True
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Client account created successfully!\n")
        print("="*60)
        print("CLIENT CREDENTIALS")
        print("="*60)
        print(f"Client ID:     {client_id}")
        print(f"Company:       {company_name}")
        print(f"Email:         {email}")
        print(f"Password:      {password}")
        print(f"Tier:          {tier}")
        print(f"Status:        active")
        print(f"Dashboard:     enabled")
        print("="*60)
        print("\n📧 EMAIL TO SEND TO CLIENT:\n")
        print(f"""
Subject: Welcome to Momentum AISDR - Dashboard Access

Hi {company_name} Team,

Your Momentum AISDR dashboard is ready!

🔐 LOGIN DETAILS:
Email:    {email}
Password: {password}
URL:      https://dashboard.momentumoutbound.com/login

📊 WHAT YOU CAN DO:
✓ View campaign statistics in real-time
✓ See email performance (opens, clicks, replies)
✓ Monitor connected mailboxes
✓ Pause/resume campaigns anytime
✓ Change your password

🚀 NEXT STEPS:
1. Log in to your dashboard
2. Change your password (recommended)
3. Review your campaign settings
4. Monitor your emails!

Need help? Reply to this email or contact support@momentumoutbound.com

Best regards,
Momentum Outbound Team
        """)
        print("\n" + "="*60)
        
    except Exception as e:
        print(f"❌ Error creating client: {e}")
        import traceback
        traceback.print_exc()


def list_clients():
    """List all existing clients"""
    try:
        conn = psycopg2.connect(
            dbname=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT
        )
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, company_name, email, tier, status, dashboard_enabled
            FROM clients
            ORDER BY created_at DESC
        """)
        
        clients = cursor.fetchall()
        cursor.close()
        conn.close()
        
        print("\n" + "="*80)
        print("EXISTING CLIENTS")
        print("="*80)
        
        if not clients:
            print("\nNo clients found.")
        else:
            print(f"\nTotal: {len(clients)} clients\n")
            print(f"{'ID':<40} {'Company':<25} {'Email':<30} {'Tier':<12} {'Status':<10} {'Dashboard':<10}")
            print("-"*80)
            for client in clients:
                client_id, company, email, tier, status, dashboard = client
                dashboard_status = "✅ Yes" if dashboard else "❌ No"
                print(f"{client_id[:36]:<40} {company[:24]:<25} {email[:29]:<30} {tier or 'N/A':<12} {status:<10} {dashboard_status:<10}")
        
        print("\n" + "="*80 + "\n")
        
    except Exception as e:
        print(f"❌ Error listing clients: {e}")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'list':
        list_clients()
    else:
        create_client_account()
