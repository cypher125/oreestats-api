"""
API Views for Email Service
Handles email sending, tracking, and OAuth
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from google_auth_oauthlib.flow import Flow
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
import logging

from .models import (
    EmailEvent,
    EmailTrackingPixel,
    EmailClickTracking,
    GmailToken,
    EmailSendQueue
)
from .serializers import (
    EmailSendRequestSerializer,
    EmailStatusResponseSerializer,
    EmailSendQueueSerializer,
    EmailEventSerializer
)
from .gmail_client import GmailClientFactory
from .tracking import EmailTracker, TrackingPixelGenerator
from .utils import require_api_key, get_client_ip, get_aisdr_connection

logger = logging.getLogger(__name__)


# ============================================
# EMAIL SENDING ENDPOINTS
# ============================================

@extend_schema(
    tags=['Email'],
    summary='Send Email',
    description='Queue an email for sending. The email will be processed by a background worker within 1 minute and sent via Gmail API.',
    request=EmailSendRequestSerializer,
    responses={
        201: {
            'description': 'Email queued successfully',
            'content': {
                'application/json': {
                    'example': {
                        'success': True,
                        'queue_id': '770e8400-e29b-41d4-a716-446655440002',
                        'scheduled_for': '2025-11-03T10:00:00Z',
                        'message': 'Email queued successfully'
                    }
                }
            }
        },
        400: {'description': 'Invalid request data'},
        401: {'description': 'Invalid API key'},
    },
    examples=[
        OpenApiExample(
            'Minimal Request',
            value={
                'lead_id': '550e8400-e29b-41d4-a716-446655440000',
                'client_id': '660e8400-e29b-41d4-a716-446655440001',
                'recipient_email': 'john@prospect.com',
                'email_subject': 'Quick question',
                'email_body': '<html><body>Email content</body></html>',
                'sequence_number': 1
            }
        ),
        OpenApiExample(
            'Full Request with Scheduling',
            value={
                'lead_id': '550e8400-e29b-41d4-a716-446655440000',
                'client_id': '660e8400-e29b-41d4-a716-446655440001',
                'recipient_email': 'jane@company.com',
                'email_subject': 'Follow up email',
                'email_body': '<html><body><h1>Hi {{first_name}}</h1><p>Content...</p></body></html>',
                'email_cta': 'Book a Demo',
                'sequence_number': 2,
                'send_delay_days': 3,
                'scheduled_for': '2025-11-06T10:00:00Z'
            }
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
@require_api_key
def send_email(request):
    """Queue an email for sending via Gmail API"""
    serializer = EmailSendRequestSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(
            {'error': 'Invalid request data', 'details': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    data = serializer.validated_data
    
    # Determine scheduled_for time
    scheduled_for = data.get('scheduled_for')
    if not scheduled_for:
        send_delay_days = data.get('send_delay_days', 0)
        scheduled_for = timezone.now() + timezone.timedelta(days=send_delay_days)
    
    # Create email in send queue
    try:
        email_queue = EmailSendQueue.objects.create(
            lead_id=data['lead_id'],
            client_id=data['client_id'],
            recipient_email=data['recipient_email'],
            email_subject=data['email_subject'],
            email_body=data['email_body'],
            email_cta=data.get('email_cta', ''),
            sequence_number=data['sequence_number'],
            send_delay_days=data.get('send_delay_days', 0),
            scheduled_for=scheduled_for,
            status='PENDING'
        )
        
        logger.info(f"Email queued for lead {data['lead_id']}, queue ID: {email_queue.id}")
        
        return Response({
            'success': True,
            'queue_id': str(email_queue.id),
            'scheduled_for': scheduled_for.isoformat(),
            'message': 'Email queued successfully'
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Error queuing email: {e}")
        return Response(
            {'error': 'Failed to queue email', 'details': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    tags=['Email'],
    summary='Get Email Status',
    description='Retrieve email engagement metrics and recent events for a specific lead.',
    parameters=[
        OpenApiParameter(
            name='lead_id',
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description='UUID of the lead'
        )
    ],
    responses={
        200: {
            'description': 'Email status retrieved successfully',
            'content': {
                'application/json': {
                    'example': {
                        'lead_id': '550e8400-e29b-41d4-a716-446655440000',
                        'emails_sent': 3,
                        'emails_opened': 2,
                        'emails_clicked': 1,
                        'emails_replied': 0,
                        'emails_bounced': 0,
                        'last_engagement_type': 'CLICK',
                        'last_engagement_at': '2025-11-03T14:30:00Z',
                        'current_sequence_step': 3,
                        'sequence_status': 'ACTIVE',
                        'recent_events': []
                    }
                }
            }
        },
        404: {'description': 'Lead not found'},
        401: {'description': 'Invalid API key'},
    }
)
@api_view(['GET'])
@permission_classes([AllowAny])
@require_api_key
def email_status(request, lead_id):
    """Get email engagement metrics for a lead"""
    try:
        conn = get_aisdr_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    id,
                    emails_sent,
                    emails_opened,
                    emails_clicked,
                    emails_replied,
                    emails_bounced,
                    last_engagement_type,
                    last_engagement_at,
                    current_sequence_step,
                    sequence_status
                FROM leads
                WHERE id = %s
            """, [lead_id])
            
            row = cursor.fetchone()
            
            if not row:
                return Response(
                    {'error': 'Lead not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get recent events
            recent_events = EmailEvent.objects.filter(
                lead_id=lead_id
            ).order_by('-created_at')[:10]
            
            response_data = {
                'lead_id': row[0],
                'emails_sent': row[1] or 0,
                'emails_opened': row[2] or 0,
                'emails_clicked': row[3] or 0,
                'emails_replied': row[4] or 0,
                'emails_bounced': row[5] or 0,
                'last_engagement_type': row[6],
                'last_engagement_at': row[7],
                'current_sequence_step': row[8] or 1,
                'sequence_status': row[9] or 'ACTIVE',
                'recent_events': EmailEventSerializer(recent_events, many=True).data
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
    except Exception as e:
        logger.error(f"Error fetching email status for lead {lead_id}: {e}")
        return Response(
            {'error': 'Failed to fetch email status', 'details': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================
# TRACKING ENDPOINTS
# ============================================

@extend_schema(
    tags=['Tracking'],
    summary='Track Email Open',
    description='Track when an email is opened. This endpoint is automatically embedded in emails as a 1x1 transparent pixel. Returns a PNG image.',
    parameters=[
        OpenApiParameter(
            name='pixel_id',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.PATH,
            description='Unique tracking pixel identifier'
        )
    ],
    responses={
        200: {
            'description': 'Returns 1x1 transparent PNG',
            'content': {'image/png': {}}
        }
    },
    exclude=False
)
@api_view(['GET'])
@permission_classes([AllowAny])
@csrf_exempt
def track_open(request, pixel_id):
    """Track email open via 1x1 pixel"""
    # Get user agent and IP
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    ip_address = get_client_ip(request)
    
    # Record the open
    success = EmailTracker.record_open(
        pixel_id=pixel_id,
        user_agent=user_agent,
        ip_address=ip_address
    )
    
    # Return 1x1 transparent PNG regardless of success
    pixel_data = TrackingPixelGenerator.get_pixel()
    headers = TrackingPixelGenerator.get_pixel_headers()
    
    response = HttpResponse(pixel_data, content_type=headers['Content-Type'])
    response['Cache-Control'] = headers['Cache-Control']
    response['Pragma'] = headers['Pragma']
    response['Expires'] = headers['Expires']
    
    return response


@extend_schema(
    tags=['Tracking'],
    summary='Track Email Click',
    description='Track when a link in an email is clicked. Logs the click event and redirects user to the destination URL.',
    parameters=[
        OpenApiParameter(
            name='click_id',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.PATH,
            description='Unique click tracking identifier'
        )
    ],
    responses={
        302: {'description': 'Redirects to destination URL'}
    }
)
@api_view(['GET'])
@permission_classes([AllowAny])
@csrf_exempt
def track_click(request, click_id):
    """Track email click and redirect to destination"""
    # Get user agent and IP
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    ip_address = get_client_ip(request)
    
    # Record the click
    result = EmailTracker.record_click(
        click_id=click_id,
        user_agent=user_agent,
        ip_address=ip_address
    )
    
    # Redirect to destination URL
    destination_url = result.get('destination_url', '/')
    return HttpResponseRedirect(destination_url)


@extend_schema(
    tags=['Tracking'],
    summary='Track Email Reply',
    description='Log a reply event. This is typically called by the automatic reply detection system (Celery task) or can be called manually when a reply is detected.',
    request={
        'application/json': {
            'type': 'object',
            'properties': {
                'lead_id': {'type': 'string', 'format': 'uuid'},
                'client_id': {'type': 'string', 'format': 'uuid'},
                'message_id': {'type': 'string'},
                'thread_id': {'type': 'string'},
                'reply_content': {'type': 'string'},
                'reply_snippet': {'type': 'string'}
            },
            'required': ['lead_id', 'message_id']
        }
    },
    responses={
        201: {
            'description': 'Reply logged successfully',
            'content': {
                'application/json': {
                    'example': {
                        'success': True,
                        'event_id': 'bb0e8400-e29b-41d4-a716-446655440006'
                    }
                }
            }
        },
        401: {'description': 'Invalid API key'},
    },
    examples=[
        OpenApiExample(
            'Reply Event',
            value={
                'lead_id': '550e8400-e29b-41d4-a716-446655440000',
                'message_id': '18bc1234567890cd',
                'thread_id': '18bc1234567890ab',
                'reply_content': 'Thanks for reaching out...',
                'reply_snippet': 'Thanks for reaching out...'
            }
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
@require_api_key
def track_reply(request):
    """Log a reply event"""
    try:
        data = request.data
        
        # Create reply event
        event = EmailEvent.objects.create(
            lead_id=data['lead_id'],
            client_id=data.get('client_id', data['lead_id']),
            event_type='REPLY',
            message_id=data['message_id'],
            thread_id=data.get('thread_id'),
            reply_content=data.get('reply_content', ''),
            reply_snippet=data.get('reply_snippet', '')
        )
        
        conn = get_aisdr_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE leads 
                SET emails_replied = emails_replied + 1,
                    first_replied_at = COALESCE(first_replied_at, %s),
                    last_engagement_type = 'REPLY',
                    last_engagement_at = %s,
                    sequence_status = 'REPLIED'
                WHERE id = %s
            """, [timezone.now(), timezone.now(), data['lead_id']])
        
        logger.info(f"Logged reply for lead {data['lead_id']}")
        
        return Response({
            'success': True,
            'event_id': str(event.id)
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Error logging reply: {e}")
        return Response(
            {'error': 'Failed to log reply', 'details': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ============================================
# OAUTH ENDPOINTS
# ============================================

@extend_schema(
    tags=['OAuth'],
    summary='Initiate OAuth Flow',
    description='Start the OAuth2 authorization flow for a client to connect their Gmail account. Redirects to Google OAuth consent screen.',
    parameters=[
        OpenApiParameter(
            name='client_id',
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description='UUID of the client'
        )
    ],
    responses={
        302: {'description': 'Redirects to Google OAuth consent screen'}
    }
)
@api_view(['GET'])
@permission_classes([AllowAny])
def oauth_initiate(request, client_id):
    """Initiate OAuth flow for a client"""
    try:
        # Create OAuth flow
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            },
            scopes=settings.GMAIL_SCOPES
        )
        
        flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
        
        # Generate authorization URL
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',  # Force consent to get refresh token
            state=client_id  # Pass client_id in state
        )
        
        logger.info(f"OAuth initiated for client {client_id}")
        
        return HttpResponseRedirect(authorization_url)
        
    except Exception as e:
        logger.error(f"Error initiating OAuth: {e}")
        return Response(
            {'error': 'Failed to initiate OAuth', 'details': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    tags=['OAuth'],
    summary='OAuth Callback',
    description='Handle OAuth2 callback from Google after user authorization. This endpoint is called by Google, not by you directly. Exchanges authorization code for access and refresh tokens.',
    parameters=[
        OpenApiParameter(
            name='code',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            description='Authorization code from Google'
        ),
        OpenApiParameter(
            name='state',
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            description='Client ID (passed from initiate step)'
        )
    ],
    responses={
        200: {
            'description': 'Returns HTML success page',
            'content': {'text/html': {}}
        },
        500: {
            'description': 'Returns HTML error page',
            'content': {'text/html': {}}
        }
    }
)
@api_view(['GET'])
@permission_classes([AllowAny])
def oauth_callback(request):
    """Handle OAuth callback from Google"""
    try:
        code = request.GET.get('code')
        client_id = request.GET.get('state')
        
        if not code or not client_id:
            return Response(
                {'error': 'Missing code or client_id'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Exchange code for tokens
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            },
            scopes=settings.GMAIL_SCOPES,
            state=client_id
        )
        
        flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
        flow.fetch_token(code=code)
        
        credentials = flow.credentials
        
        # Get user's email address
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=credentials)
        profile = service.users().getProfile(userId='me').execute()
        email_address = profile.get('emailAddress')
        history_id = profile.get('historyId')
        
        # Store tokens in database
        gmail_token, created = GmailToken.objects.update_or_create(
            client_id=client_id,
            defaults={
                'email_address': email_address,
                'gmail_user_id': profile.get('emailAddress'),
                'access_token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_expiry': credentials.expiry,
                'scopes': credentials.scopes,
                'status': 'active',
                'last_history_id': history_id
            }
        )
        
        action = "connected" if created else "updated"
        logger.info(f"Gmail {action} for client {client_id}: {email_address}")
        
        # Return success page (you can customize this)
        return HttpResponse(f"""
            <html>
            <head><title>Gmail Connected</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1>✅ Gmail Connected Successfully!</h1>
                <p>Email: <strong>{email_address}</strong></p>
                <p>You can close this window and return to the application.</p>
            </body>
            </html>
        """)
        
    except Exception as e:
        logger.error(f"Error in OAuth callback: {e}")
        return HttpResponse(f"""
            <html>
            <head><title>Error</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1>❌ Error Connecting Gmail</h1>
                <p>{str(e)}</p>
                <p>Please try again or contact support.</p>
            </body>
            </html>
        """, status=500)


# ============================================
# UTILITY ENDPOINTS
# ============================================

@extend_schema(
    tags=['Utility'],
    summary='Health Check',
    description='Check if the API is running and database is accessible. Used for monitoring and load balancer health checks.',
    responses={
        200: {
            'description': 'Service is healthy',
            'content': {
                'application/json': {
                    'example': {
                        'status': 'healthy',
                        'timestamp': '2025-11-03T15:00:00Z',
                        'service': 'Oree Stats API'
                    }
                }
            }
        },
        503: {
            'description': 'Service is unhealthy',
            'content': {
                'application/json': {
                    'example': {
                        'status': 'unhealthy',
                        'error': 'Database connection failed'
                    }
                }
            }
        }
    }
)
@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """Health check endpoint"""
    try:
        # Check database connection
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        return Response({
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'service': 'Oree Stats API'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        return Response({
            'status': 'unhealthy',
            'error': str(e)
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ============================================
# CLIENT DASHBOARD ENDPOINTS
# ============================================

from django.contrib.auth.hashers import check_password, make_password
from .utils import generate_client_jwt, require_client_auth
from .serializers import (
    ClientLoginSerializer,
    ClientStatsSerializer,
    ClientCampaignSerializer,
    ClientReplySerializer,
    ClientTimelineSerializer,
    ClientMailboxSerializer,
    ChangePasswordSerializer,
    UpdateClientSettingsSerializer
)
from .utils import get_aisdr_connection
from datetime import timedelta
from django.db.models import Count, Max


@extend_schema(
    tags=['Client Dashboard'],
    request=ClientLoginSerializer,
    responses={
        200: OpenApiResponse(description='Login successful'),
        401: OpenApiResponse(description='Invalid credentials'),
        403: OpenApiResponse(description='Account not active'),
    },
    description='Client login endpoint for dashboard access',
    examples=[
        OpenApiExample(
            'Login Request',
            value={
                'email': 'client@company.com',
                'password': 'SecurePassword123'
            }
        )
    ]
)
@api_view(['POST'])
@permission_classes([AllowAny])
def client_login(request):
    """
    Client login endpoint
    
    POST /api/client/login
    {
        "email": "client@company.com",
        "password": "password"
    }
    """
    serializer = ClientLoginSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    email = serializer.validated_data['email']
    password = serializer.validated_data['password']
    
    try:
        conn = get_aisdr_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, company_name, email, password_hash, tier, status, dashboard_enabled
            FROM clients
            WHERE email = %s
        """, (email,))
        
        result = cursor.fetchone()
        
        if not result:
            cursor.close()
            return Response({
                'error': 'Invalid email or password'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        client_id, company_name, client_email, password_hash, tier, client_status, dashboard_enabled = result
        
        # Verify password
        if not password_hash or not check_password(password, password_hash):
            cursor.close()
            return Response({
                'error': 'Invalid email or password'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Check account status
        if client_status != 'active':
            cursor.close()
            return Response({
                'error': 'Account is not active. Please contact support.'
            }, status=status.HTTP_403_FORBIDDEN)
        
        if not dashboard_enabled:
            cursor.close()
            return Response({
                'error': 'Dashboard access is not enabled for this account.'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Update last login
        cursor.execute("""
            UPDATE clients SET last_login = NOW() WHERE id = %s
        """, (client_id,))
        cursor.close()
        
        # Generate JWT token
        token = generate_client_jwt(
            client_id=client_id,
            company_name=company_name,
            tier=tier or 'self_serve',
            email=client_email
        )
        
        logger.info(f"Client logged in: {company_name} ({client_email})")
        
        return Response({
            'success': True,
            'token': token,
            'client': {
                'id': str(client_id),
                'company_name': company_name,
                'email': client_email,
                'tier': tier or 'self_serve'
            }
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return Response({
            'error': 'Internal server error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Client Dashboard'],
    responses={200: ClientStatsSerializer},
    description='Get campaign statistics for authenticated client',
    parameters=[
        OpenApiParameter(
            name='Authorization',
            type=str,
            location=OpenApiParameter.HEADER,
            description='Bearer token',
            required=True
        )
    ]
)
@api_view(['GET'])
@require_client_auth
def get_client_stats(request):
    """
    Get stats for authenticated client
    
    GET /api/client/stats
    Headers: Authorization: Bearer <token>
    """
    client_id = request.client_id
    
    # Calculate date ranges
    now = timezone.now()
    last_7_days = now - timedelta(days=7)
    last_30_days = now - timedelta(days=30)
    
    def calculate_stats(start_date=None):
        """Helper to calculate stats for a time period"""
        email_filter = {'client_id': client_id, 'status': 'SENT'}
        event_filter = {'client_id': client_id}
        
        if start_date:
            email_filter['sent_at__gte'] = start_date
            event_filter['created_at__gte'] = start_date
        
        emails_sent = EmailSendQueue.objects.filter(**email_filter).count()
        opens = EmailEvent.objects.filter(**event_filter, event_type='OPEN').count()
        clicks = EmailEvent.objects.filter(**event_filter, event_type='CLICK').count()
        replies = EmailEvent.objects.filter(**event_filter, event_type='REPLY').count()
        
        return {
            'emails_sent': emails_sent,
            'opens': opens,
            'open_rate': round((opens / emails_sent * 100), 1) if emails_sent > 0 else 0,
            'clicks': clicks,
            'click_rate': round((clicks / emails_sent * 100), 1) if emails_sent > 0 else 0,
            'replies': replies,
            'reply_rate': round((replies / emails_sent * 100), 1) if emails_sent > 0 else 0,
        }
    
    stats_data = {
        'client_id': client_id,
        'all_time': calculate_stats(),
        'last_7_days': calculate_stats(last_7_days),
        'last_30_days': calculate_stats(last_30_days),
    }
    
    serializer = ClientStatsSerializer(stats_data)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=['Client Dashboard'],
    responses={200: ClientCampaignSerializer(many=True)},
    description='Get campaign performance by sequence for authenticated client'
)
@api_view(['GET'])
@require_client_auth
def get_client_campaigns(request):
    """
    Get campaign performance by sequence
    
    GET /api/client/campaigns
    Headers: Authorization: Bearer <token>
    """
    client_id = request.client_id
    
    # Get performance by sequence number
    sequences = EmailSendQueue.objects.filter(
        client_id=client_id,
        status='SENT'
    ).values('sequence_number').annotate(
        emails_sent=Count('id'),
        last_sent=Max('sent_at')
    ).order_by('sequence_number')
    
    campaigns = []
    for seq in sequences:
        seq_num = seq['sequence_number']
        
        # Get events for this sequence
        opens = EmailEvent.objects.filter(
            client_id=client_id,
            event_type='OPEN',
            sequence_number=seq_num
        ).count()
        
        clicks = EmailEvent.objects.filter(
            client_id=client_id,
            event_type='CLICK',
            sequence_number=seq_num
        ).count()
        
        replies = EmailEvent.objects.filter(
            client_id=client_id,
            event_type='REPLY',
            sequence_number=seq_num
        ).count()
        
        emails_sent = seq['emails_sent']
        
        campaigns.append({
            'sequence_number': seq_num,
            'emails_sent': emails_sent,
            'opens': opens,
            'open_rate': round((opens / emails_sent * 100), 1) if emails_sent > 0 else 0,
            'clicks': clicks,
            'click_rate': round((clicks / emails_sent * 100), 1) if emails_sent > 0 else 0,
            'replies': replies,
            'reply_rate': round((replies / emails_sent * 100), 1) if emails_sent > 0 else 0,
            'last_sent': seq['last_sent']
        })
    
    serializer = ClientCampaignSerializer(campaigns, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=['Client Dashboard'],
    responses={200: ClientReplySerializer(many=True)},
    description='Get recent email replies for authenticated client',
    parameters=[
        OpenApiParameter(name='limit', type=int, description='Number of replies to return (default: 50)'),
    ]
)
@api_view(['GET'])
@require_client_auth
def get_client_replies(request):
    """
    Get recent email replies
    
    GET /api/client/replies?limit=50
    Headers: Authorization: Bearer <token>
    """
    client_id = request.client_id
    limit = int(request.query_params.get('limit', 50))
    
    replies = EmailEvent.objects.filter(
        client_id=client_id,
        event_type='REPLY'
    ).order_by('-created_at')[:limit]
    
    serializer = ClientReplySerializer(replies, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=['Client Dashboard'],
    responses={200: ClientTimelineSerializer(many=True)},
    description='Get daily email timeline data for charts',
    parameters=[
        OpenApiParameter(name='days', type=int, description='Number of days to include (default: 30)'),
    ]
)
@api_view(['GET'])
@require_client_auth
def get_client_timeline(request):
    """
    Get daily email timeline data for charts
    
    GET /api/client/timeline?days=30
    Headers: Authorization: Bearer <token>
    """
    client_id = request.client_id
    days = int(request.query_params.get('days', 30))
    
    start_date = timezone.now() - timedelta(days=days)
    
    # Get daily email counts
    from django.db.models.functions import TruncDate
    
    daily_emails = EmailSendQueue.objects.filter(
        client_id=client_id,
        status='SENT',
        sent_at__gte=start_date
    ).annotate(
        date=TruncDate('sent_at')
    ).values('date').annotate(
        emails_sent=Count('id')
    ).order_by('date')
    
    # Get daily events
    daily_opens = EmailEvent.objects.filter(
        client_id=client_id,
        event_type='OPEN',
        created_at__gte=start_date
    ).annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        opens=Count('id')
    )
    
    daily_clicks = EmailEvent.objects.filter(
        client_id=client_id,
        event_type='CLICK',
        created_at__gte=start_date
    ).annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        clicks=Count('id')
    )
    
    daily_replies = EmailEvent.objects.filter(
        client_id=client_id,
        event_type='REPLY',
        created_at__gte=start_date
    ).annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        replies=Count('id')
    )
    
    # Combine data
    timeline_dict = {}
    
    for item in daily_emails:
        date = item['date']
        timeline_dict[date] = {
            'date': date,
            'emails_sent': item['emails_sent'],
            'opens': 0,
            'clicks': 0,
            'replies': 0
        }
    
    for item in daily_opens:
        date = item['date']
        if date in timeline_dict:
            timeline_dict[date]['opens'] = item['opens']
    
    for item in daily_clicks:
        date = item['date']
        if date in timeline_dict:
            timeline_dict[date]['clicks'] = item['clicks']
    
    for item in daily_replies:
        date = item['date']
        if date in timeline_dict:
            timeline_dict[date]['replies'] = item['replies']
    
    timeline = list(timeline_dict.values())
    
    serializer = ClientTimelineSerializer(timeline, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=['Client Dashboard'],
    responses={200: ClientMailboxSerializer(many=True)},
    description='Get connected mailboxes status for authenticated client'
)
@api_view(['GET'])
@require_client_auth
def get_client_mailboxes(request):
    """
    Get connected mailboxes status
    
    GET /api/client/mailboxes
    Headers: Authorization: Bearer <token>
    """
    client_id = request.client_id
    
    mailboxes = GmailToken.objects.filter(client_id=client_id).values(
        'email_address',
        'status',
        'daily_send_count',
        'daily_send_limit',
        'last_used_at'
    )
    
    mailbox_list = []
    for mailbox in mailboxes:
        mailbox_list.append({
            'email_address': mailbox['email_address'],
            'status': mailbox['status'],
            'daily_send_count': mailbox['daily_send_count'],
            'daily_send_limit': mailbox['daily_send_limit'],
            'remaining': mailbox['daily_send_limit'] - mailbox['daily_send_count'],
            'last_used_at': mailbox['last_used_at']
        })
    
    serializer = ClientMailboxSerializer(mailbox_list, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=['Client Dashboard'],
    request=ChangePasswordSerializer,
    responses={
        200: OpenApiResponse(description='Password changed successfully'),
        400: OpenApiResponse(description='Invalid current password'),
    },
    description='Change password for authenticated client'
)
@api_view(['POST'])
@require_client_auth
def change_client_password(request):
    """
    Change password for authenticated client
    
    POST /api/client/change-password
    {
        "current_password": "OldPassword123",
        "new_password": "NewPassword456"
    }
    """
    serializer = ChangePasswordSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    client_id = request.client_id
    current_password = serializer.validated_data['current_password']
    new_password = serializer.validated_data['new_password']
    
    try:
        conn = get_aisdr_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT password_hash FROM clients WHERE id = %s
        """, (client_id,))
        
        result = cursor.fetchone()
        
        if not result or not result[0]:
            cursor.close()
            return Response({
                'error': 'Password not set for this account'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        password_hash = result[0]
        
        # Verify current password
        if not check_password(current_password, password_hash):
            cursor.close()
            return Response({
                'error': 'Current password is incorrect'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Hash new password
        new_password_hash = make_password(new_password)
        
        # Update password
        cursor.execute("""
            UPDATE clients SET password_hash = %s WHERE id = %s
        """, (new_password_hash, client_id))
        cursor.close()
        
        logger.info(f"Password changed for client: {request.client_company}")
        
        return Response({
            'success': True,
            'message': 'Password changed successfully'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Password change error: {e}")
        return Response({
            'error': 'Internal server error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Client Dashboard'],
    request=UpdateClientSettingsSerializer,
    responses={200: OpenApiResponse(description='Settings updated successfully')},
    description='Update settings for authenticated client (e.g., pause/resume campaign)'
)
@api_view(['PUT'])
@require_client_auth
def update_client_settings(request):
    """
    Update settings for authenticated client
    
    PUT /api/client/settings
    {
        "campaign_status": "paused"  // or "active"
    }
    """
    serializer = UpdateClientSettingsSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    client_id = request.client_id
    campaign_status = serializer.validated_data.get('campaign_status')
    
    try:
        if campaign_status:
            conn = get_aisdr_connection()
            cursor = conn.cursor()
            
            # Store campaign status in clients table
            cursor.execute("""
                UPDATE clients 
                SET status = %s 
                WHERE id = %s
            """, (campaign_status, client_id))
            
            cursor.close()
            
            
            logger.info(f"Campaign status updated to {campaign_status} for client: {request.client_company}")
        
        return Response({
            'success': True,
            'message': 'Settings updated successfully'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Settings update error: {e}")
        return Response({
            'error': 'Internal server error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=['Client Dashboard'],
    responses={200: OpenApiResponse(description='Logout successful')},
    description='Logout (client-side should delete token)'
)
@api_view(['POST'])
@require_client_auth
def client_logout(request):
    """
    Client logout endpoint
    
    POST /api/client/logout
    Headers: Authorization: Bearer <token>
    
    Note: JWT tokens are stateless, so logout is handled client-side
    by deleting the token. This endpoint is for logging purposes.
    """
    logger.info(f"Client logged out: {request.client_company}")
    
    return Response({
        'success': True,
        'message': 'Logged out successfully'
    }, status=status.HTTP_200_OK)
