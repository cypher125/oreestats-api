"""
Email Tracking System
Handles open tracking (pixels) and click tracking (redirects)
"""
import secrets
from django.utils import timezone
from django.conf import settings
from bs4 import BeautifulSoup
from .models import EmailTrackingPixel, EmailClickTracking, EmailEvent
from .utils import get_aisdr_connection
import logging

logger = logging.getLogger(__name__)


class EmailTracker:
    """
    Handles email tracking (opens, clicks)
    """
    
    @staticmethod
    def generate_pixel_id():
        """Generate unique tracking pixel ID"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def generate_click_id():
        """Generate unique click tracking ID"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def create_tracking_pixel(lead_id, message_id, client_id):
        """
        Create tracking pixel record and return pixel URL
        
        Args:
            lead_id: UUID of the lead
            message_id: Gmail message ID
            client_id: UUID of the client
        
        Returns:
            Tracking pixel URL (str)
        """
        try:
            pixel = EmailTrackingPixel.objects.create(
                lead_id=lead_id,
                message_id=message_id,
                pixel_id=EmailTracker.generate_pixel_id()
            )
            
            # Build pixel URL
            tracking_domain = settings.TRACKING_DOMAIN
            tracking_protocol = settings.TRACKING_PROTOCOL
            pixel_url = f"{tracking_protocol}://{tracking_domain}/api/track/open/{pixel.pixel_id}.png"
            
            logger.info(f"Created tracking pixel {pixel.pixel_id} for lead {lead_id}")
            
            return pixel_url
            
        except Exception as e:
            logger.error(f"Error creating tracking pixel: {e}")
            return None
    
    @staticmethod
    def create_click_tracking(lead_id, message_id, destination_url, client_id):
        """
        Create click tracking record and return tracking URL
        
        Args:
            lead_id: UUID of the lead
            message_id: Gmail message ID
            destination_url: Original destination URL
            client_id: UUID of the client
        
        Returns:
            Tracking URL (str)
        """
        try:
            click = EmailClickTracking.objects.create(
                lead_id=lead_id,
                message_id=message_id,
                click_id=EmailTracker.generate_click_id(),
                destination_url=destination_url
            )
            
            # Build tracking URL
            tracking_domain = settings.TRACKING_DOMAIN
            tracking_protocol = settings.TRACKING_PROTOCOL
            tracking_url = f"{tracking_protocol}://{tracking_domain}/api/track/click/{click.click_id}"
            
            logger.debug(f"Created click tracking {click.click_id} for {destination_url[:50]}")
            
            return tracking_url
            
        except Exception as e:
            logger.error(f"Error creating click tracking: {e}")
            return destination_url  # Return original URL as fallback
    
    @staticmethod
    def record_open(pixel_id, user_agent=None, ip_address=None, client_id=None):
        """
        Record email open event
        
        Args:
            pixel_id: Tracking pixel ID
            user_agent: Browser user agent string
            ip_address: User's IP address
            client_id: UUID of the client (optional)
        
        Returns:
            Boolean indicating success
        """
        try:
            pixel = EmailTrackingPixel.objects.get(pixel_id=pixel_id)
            
            now = timezone.now()
            
            # Update pixel record
            if not pixel.opened:
                pixel.opened = True
                pixel.first_opened_at = now
            
            pixel.open_count += 1
            pixel.last_opened_at = now
            pixel.save()
            
            # Determine device type from user agent
            device_type = EmailTracker._parse_device_type(user_agent)
            
            # Create event record
            EmailEvent.objects.create(
                lead_id=pixel.lead_id,
                client_id=client_id or pixel.lead_id,  # Fallback if client_id not provided
                event_type='OPEN',
                message_id=pixel.message_id,
                user_agent=user_agent,
                ip_address=ip_address,
                device_type=device_type
            )
            
            # Update lead metrics (direct SQL for performance)
            EmailTracker._update_lead_open_metrics(pixel.lead_id, now)
            
            logger.info(f"Recorded open for pixel {pixel_id}, lead {pixel.lead_id}")
            
            return True
            
        except EmailTrackingPixel.DoesNotExist:
            logger.warning(f"Tracking pixel not found: {pixel_id}")
            return False
        except Exception as e:
            logger.error(f"Error recording open: {e}")
            return False
    
    @staticmethod
    def record_click(click_id, user_agent=None, ip_address=None, client_id=None):
        """
        Record email click event
        
        Args:
            click_id: Click tracking ID
            user_agent: Browser user agent string
            ip_address: User's IP address
            client_id: UUID of the client (optional)
        
        Returns:
            Dict with 'success' (bool) and 'destination_url' (str)
        """
        try:
            click = EmailClickTracking.objects.get(click_id=click_id)
            
            now = timezone.now()
            
            # Update click record
            if click.click_count == 0:
                click.first_clicked_at = now
            
            click.click_count += 1
            click.last_clicked_at = now
            click.save()
            
            # Determine device type
            device_type = EmailTracker._parse_device_type(user_agent)
            
            # Create event record
            EmailEvent.objects.create(
                lead_id=click.lead_id,
                client_id=client_id or click.lead_id,  # Fallback
                event_type='CLICK',
                message_id=click.message_id,
                url=click.destination_url,
                user_agent=user_agent,
                ip_address=ip_address,
                device_type=device_type
            )
            
            # Update lead metrics
            EmailTracker._update_lead_click_metrics(click.lead_id, now)
            
            logger.info(f"Recorded click for {click_id}, lead {click.lead_id}")
            
            return {
                'success': True,
                'destination_url': click.destination_url
            }
            
        except EmailClickTracking.DoesNotExist:
            logger.warning(f"Click tracking not found: {click_id}")
            return {
                'success': False,
                'destination_url': '/'  # Fallback to homepage
            }
        except Exception as e:
            logger.error(f"Error recording click: {e}")
            return {
                'success': False,
                'destination_url': '/'
            }
    
    @staticmethod
    def replace_links_with_tracking(html_body, lead_id, message_id, client_id):
        """
        Replace all links in HTML body with tracking URLs
        
        Args:
            html_body: HTML email body
            lead_id: UUID of the lead
            message_id: Gmail message ID
            client_id: UUID of the client
        
        Returns:
            Dict with 'html' (modified HTML) and 'tracked_links' (dict)
        """
        try:
            soup = BeautifulSoup(html_body, 'html.parser')
            tracked_links = {}
            
            # Find all <a> tags with href
            for link in soup.find_all('a', href=True):
                original_url = link['href']
                
                # Skip mailto: and tel: links
                if original_url.startswith(('mailto:', 'tel:', '#')):
                    continue
                
                # Skip already tracked links
                if 'track/click' in original_url:
                    continue
                
                # Create tracking URL
                tracking_url = EmailTracker.create_click_tracking(
                    lead_id=lead_id,
                    message_id=message_id,
                    destination_url=original_url,
                    client_id=client_id
                )
                
                # Replace in HTML
                link['href'] = tracking_url
                tracked_links[original_url] = tracking_url
            
            modified_html = str(soup)
            
            logger.info(f"Replaced {len(tracked_links)} links with tracking for lead {lead_id}")
            
            return {
                'html': modified_html,
                'tracked_links': tracked_links
            }
            
        except Exception as e:
            logger.error(f"Error replacing links with tracking: {e}")
            # Return original HTML on error
            return {
                'html': html_body,
                'tracked_links': {}
            }
    
    @staticmethod
    def add_tracking_to_email(html_body, lead_id, message_id, client_id):
        """
        Add both pixel tracking and link tracking to email HTML
        
        Args:
            html_body: HTML email body
            lead_id: UUID of the lead
            message_id: Gmail message ID
            client_id: UUID of the client
        
        Returns:
            Modified HTML with tracking
        """
        # Replace links with tracking
        result = EmailTracker.replace_links_with_tracking(
            html_body, lead_id, message_id, client_id
        )
        html_with_tracked_links = result['html']
        
        # Create tracking pixel
        pixel_url = EmailTracker.create_tracking_pixel(
            lead_id, message_id, client_id
        )
        
        # Add pixel to HTML
        if pixel_url:
            pixel_html = f'<img src="{pixel_url}" width="1" height="1" style="display:none;" alt="" />'
            html_with_tracking = html_with_tracked_links + pixel_html
        else:
            html_with_tracking = html_with_tracked_links
        
        return html_with_tracking
    
    # Private helper methods
    
    @staticmethod
    def _parse_device_type(user_agent):
        """
        Parse device type from user agent string
        
        Args:
            user_agent: User agent string
        
        Returns:
            Device type ('mobile', 'tablet', 'desktop', or 'unknown')
        """
        if not user_agent:
            return 'unknown'
        
        user_agent_lower = user_agent.lower()
        
        if any(device in user_agent_lower for device in ['iphone', 'android', 'mobile']):
            return 'mobile'
        elif any(device in user_agent_lower for device in ['ipad', 'tablet']):
            return 'tablet'
        elif any(device in user_agent_lower for device in ['windows', 'mac', 'linux']):
            return 'desktop'
        else:
            return 'unknown'
    
    @staticmethod
    def _update_lead_open_metrics(lead_id, timestamp):
        """
        Update lead open metrics using direct SQL
        
        Args:
            lead_id: UUID of the lead
            timestamp: Timestamp of the open event
        """
        try:
            with get_aisdr_connection().cursor() as cursor:
                cursor.execute("""
                    UPDATE leads 
                    SET emails_opened = emails_opened + 1,
                        first_opened_at = COALESCE(first_opened_at, %s),
                        last_engagement_type = 'OPEN',
                        last_engagement_at = %s
                    WHERE id = %s
                """, [timestamp, timestamp, str(lead_id)])
        except Exception as e:
            logger.error(f"Error updating lead open metrics: {e}")
    
    @staticmethod
    def _update_lead_click_metrics(lead_id, timestamp):
        """
        Update lead click metrics using direct SQL
        
        Args:
            lead_id: UUID of the lead
            timestamp: Timestamp of the click event
        """
        try:
            with get_aisdr_connection().cursor() as cursor:
                cursor.execute("""
                    UPDATE leads 
                    SET emails_clicked = emails_clicked + 1,
                        first_clicked_at = COALESCE(first_clicked_at, %s),
                        last_engagement_type = 'CLICK',
                        last_engagement_at = %s
                    WHERE id = %s
                """, [timestamp, timestamp, str(lead_id)])
        except Exception as e:
            logger.error(f"Error updating lead click metrics: {e}")


class TrackingPixelGenerator:
    """
    Generates the actual 1x1 transparent PNG for tracking pixels
    """
    
    # 1x1 transparent PNG in base64
    TRANSPARENT_PIXEL = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\x00\x01'
        b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    
    @staticmethod
    def get_pixel():
        """
        Get 1x1 transparent PNG as bytes
        
        Returns:
            Bytes of PNG image
        """
        return TrackingPixelGenerator.TRANSPARENT_PIXEL
    
    @staticmethod
    def get_pixel_headers():
        """
        Get HTTP headers for serving tracking pixel
        
        Returns:
            Dict of headers
        """
        return {
            'Content-Type': 'image/png',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
