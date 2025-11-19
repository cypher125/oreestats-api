"""
Utility functions and decorators for email service
"""
from functools import wraps
from django.conf import settings
from rest_framework.response import Response
from rest_framework import status
import logging
from django.db import connections, connection as default_connection

logger = logging.getLogger(__name__)


def require_api_key(view_func):
    """
    Decorator to require API key authentication for endpoints
    
    Expects Authorization header with format: Bearer <API_KEY>
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Get authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        if not auth_header:
            return Response(
                {'error': 'Missing Authorization header'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # Check format: Bearer <KEY>
        parts = auth_header.split(' ')
        if len(parts) != 2 or parts[0] != 'Bearer':
            return Response(
                {'error': 'Invalid Authorization header format. Expected: Bearer <API_KEY>'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        provided_key = parts[1]
        expected_key = settings.OREE_API_KEY
        
        if provided_key != expected_key:
            logger.warning(f"Invalid API key attempt from {get_client_ip(request)}")
            return Response(
                {'error': 'Invalid API key'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        # API key is valid, proceed
        return view_func(request, *args, **kwargs)
    
    return wrapper


def get_client_ip(request):
    """
    Get the client's IP address from request
    
    Args:
        request: Django request object
    
    Returns:
        IP address as string
    """
    # Check for X-Forwarded-For header (proxy/load balancer)
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    
    return ip


def parse_user_agent(user_agent):
    """
    Parse user agent string into components
    
    Args:
        user_agent: User agent string
    
    Returns:
        Dict with browser, os, device info
    """
    if not user_agent:
        return {
            'browser': 'Unknown',
            'os': 'Unknown',
            'device': 'Unknown'
        }
    
    user_agent_lower = user_agent.lower()
    
    # Detect browser
    if 'chrome' in user_agent_lower:
        browser = 'Chrome'
    elif 'firefox' in user_agent_lower:
        browser = 'Firefox'
    elif 'safari' in user_agent_lower:
        browser = 'Safari'
    elif 'edge' in user_agent_lower:
        browser = 'Edge'
    else:
        browser = 'Other'
    
    # Detect OS
    if 'windows' in user_agent_lower:
        os_name = 'Windows'
    elif 'mac' in user_agent_lower:
        os_name = 'macOS'
    elif 'linux' in user_agent_lower:
        os_name = 'Linux'
    elif 'android' in user_agent_lower:
        os_name = 'Android'
    elif 'ios' in user_agent_lower or 'iphone' in user_agent_lower or 'ipad' in user_agent_lower:
        os_name = 'iOS'
    else:
        os_name = 'Other'
    
    # Detect device type
    if any(device in user_agent_lower for device in ['iphone', 'android', 'mobile']):
        device = 'Mobile'
    elif any(device in user_agent_lower for device in ['ipad', 'tablet']):
        device = 'Tablet'
    else:
        device = 'Desktop'
    
    return {
        'browser': browser,
        'os': os_name,
        'device': device
    }


def get_aisdr_connection():
    try:
        return connections['aisdr']
    except Exception:
        return default_connection


def get_next_mailbox_token(client_id):
    """
    Get the next Gmail token/mailbox to use for sending (round-robin rotation)
    
    Supports multiple Gmail accounts per client for better deliverability.
    Automatically rotates through available mailboxes based on least recent usage.
    
    Args:
        client_id: UUID of the client
    
    Returns:
        GmailToken object for the next mailbox to use
    
    Raises:
        ValueError: If no active tokens found for client
    """
    from .models import GmailToken
    from django.utils import timezone
    
    # Get all active tokens for this client, ordered by least recently used
    tokens = GmailToken.objects.filter(
        client_id=client_id,
        status='active'
    ).order_by('last_used_at')  # Nulls first (never used), then oldest first
    
    if not tokens.exists():
        logger.error(f"No active Gmail tokens found for client {client_id}")
        raise ValueError(f"No active Gmail tokens for client {client_id}. Please complete OAuth setup.")
    
    # Get the least recently used token
    next_token = tokens.first()
    
    # Update last_used_at timestamp
    next_token.last_used_at = timezone.now()
    next_token.save(update_fields=['last_used_at'])
    
    logger.info(f"Selected mailbox {next_token.email_address} for client {client_id}")
    
    return next_token


def get_mailbox_with_capacity(client_id):
    """
    Get a mailbox that hasn't hit its daily send limit
    
    Args:
        client_id: UUID of the client
    
    Returns:
        GmailToken object with available capacity
    
    Raises:
        ValueError: If all mailboxes at limit
    """
    from .models import GmailToken
    from django.db.models import F
    
    # Find tokens with remaining capacity
    tokens = GmailToken.objects.filter(
        client_id=client_id,
        status='active'
    ).annotate(
        remaining=F('daily_send_limit') - F('daily_send_count')
    ).filter(
        remaining__gt=0  # Has capacity remaining
    ).order_by('-remaining', 'last_used_at')  # Most capacity first, then least recently used
    
    if not tokens.exists():
        logger.warning(f"All mailboxes at daily limit for client {client_id}")
        raise ValueError(f"All mailboxes have reached daily send limit for client {client_id}")
    
    next_token = tokens.first()
    logger.info(f"Selected mailbox {next_token.email_address} ({next_token.remaining} remaining) for client {client_id}")
    
    return next_token


def reset_daily_send_counts():
    """
    Reset daily send counts for all mailboxes (run daily at midnight)
    Should be called by Celery beat scheduler
    """
    from .models import GmailToken
    
    updated = GmailToken.objects.filter(status='active').update(daily_send_count=0)
    logger.info(f"Reset daily send counts for {updated} mailboxes")
    
    return updated


def get_or_assign_mailbox_for_lead(lead_id, client_id):
    """
    Get the assigned mailbox for a lead, or assign one if not exists.
    This ensures the same lead always uses the same mailbox (sticky assignment).
    
    This is Ben's requirement: "Keep same mailbox for same lead"
    
    Benefits:
    - Better deliverability (consistent sender-recipient relationship)
    - Professional (same person in conversation)
    - Better email threading
    - Easier for prospect to reply
    
    Args:
        lead_id: UUID of the lead (from AISDR database)
        client_id: UUID of the client (from AISDR database)
    
    Returns:
        GmailToken object for the assigned mailbox
    
    Raises:
        Exception: If no active mailboxes found for client
    """
    from .models import LeadMailboxAssignment, GmailToken
    from django.utils import timezone
    
    # Check if lead already has an assigned mailbox
    try:
        assignment = LeadMailboxAssignment.objects.get(
            lead_id=lead_id,
            client_id=client_id,
            status='active'
        )
        
        # Verify the mailbox is still active
        try:
            token = GmailToken.objects.get(
                email_address=assignment.assigned_email,
                client_id=client_id,
                status='active'
            )
            
            # Update usage stats
            assignment.last_used_at = timezone.now()
            assignment.email_count += 1
            assignment.save(update_fields=['last_used_at', 'email_count'])
            
            logger.info(f"Using existing mailbox {token.email_address} for lead {lead_id} (email #{assignment.email_count})")
            return token
            
        except GmailToken.DoesNotExist:
            # Assigned mailbox is no longer active, need to reassign
            logger.warning(f"Assigned mailbox {assignment.assigned_email} for lead {lead_id} is no longer active, reassigning")
            assignment.status = 'inactive'
            assignment.save(update_fields=['status'])
            # Fall through to assign new mailbox
        
    except LeadMailboxAssignment.DoesNotExist:
        # No assignment exists, create new one
        logger.info(f"No existing assignment for lead {lead_id}, assigning new mailbox")
    
    # Assign a new mailbox using round-robin logic
    token = get_next_mailbox_token(client_id)
    
    if not token:
        raise Exception(f"No active mailboxes found for client {client_id}")
    
    # Create assignment
    LeadMailboxAssignment.objects.create(
        lead_id=lead_id,
        client_id=client_id,
        assigned_email=token.email_address,
        email_count=1,
        status='active'
    )
    
    logger.info(f"Assigned new mailbox {token.email_address} to lead {lead_id}")
    return token


# ============================================
# CLIENT AUTHENTICATION (JWT)
# ============================================

import jwt
from datetime import datetime, timedelta
from django.http import JsonResponse

def generate_client_jwt(client_id, company_name, tier, email):
    """
    Generate JWT token for client dashboard authentication
    
    Args:
        client_id: UUID of the client
        company_name: Company name
        tier: 'self_serve' or 'managed'
        email: Client email
    
    Returns:
        JWT token string
    """
    payload = {
        'client_id': str(client_id),
        'company_name': company_name,
        'tier': tier,
        'email': email,
        'exp': datetime.utcnow() + timedelta(days=7),  # Token valid for 7 days
        'iat': datetime.utcnow()
    }
    
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token


def verify_client_jwt(token):
    """
    Verify and decode JWT token
    
    Args:
        token: JWT token string
    
    Returns:
        Payload dict if valid, None if invalid/expired
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
        return None


def require_client_auth(view_func):
    """
    Decorator to require client JWT authentication
    
    Expects Authorization header with format: Bearer <JWT_TOKEN>
    Adds client_id and client_company to request object
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header:
            return JsonResponse({'error': 'No authorization header provided'}, status=401)
        
        if not auth_header.startswith('Bearer '):
            return JsonResponse({'error': 'Invalid authorization format. Use: Bearer <token>'}, status=401)
        
        token = auth_header.split(' ')[1]
        payload = verify_client_jwt(token)
        
        if not payload:
            return JsonResponse({'error': 'Invalid or expired token'}, status=401)
        
        # Add client info to request
        request.client_id = payload['client_id']
        request.client_company = payload['company_name']
        request.client_tier = payload['tier']
        request.client_email = payload['email']
        
        logger.info(f"Authenticated client: {payload['company_name']} ({payload['client_id']})")
        
        return view_func(request, *args, **kwargs)
    
    return wrapper
