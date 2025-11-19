import json
import uuid
from django.test import TestCase, override_settings
from django.urls import reverse
from email_service.models import EmailSendQueue, EmailTrackingPixel
from email_service.utils import generate_client_jwt, verify_client_jwt
from email_service.tracking import TrackingPixelGenerator, EmailTracker


class EmailServiceTests(TestCase):
    @override_settings(OREE_API_KEY='test-key')
    def test_send_email_enqueue_success(self):
        url = reverse('email_service:send_email')
        payload = {
            'lead_id': str(uuid.uuid4()),
            'client_id': str(uuid.uuid4()),
            'recipient_email': 'user@example.com',
            'email_subject': 'Hello',
            'email_body': '<p>Body</p>',
            'sequence_number': 1,
            'send_delay_days': 0,
        }
        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer test-key',
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn('queue_id', data)
        self.assertTrue(EmailSendQueue.objects.filter(id=data['queue_id']).exists())

    def test_send_email_requires_api_key(self):
        url = reverse('email_service:send_email')
        payload = {
            'lead_id': str(uuid.uuid4()),
            'client_id': str(uuid.uuid4()),
            'recipient_email': 'user@example.com',
            'email_subject': 'Hello',
            'email_body': '<p>Body</p>',
            'sequence_number': 1,
        }
        resp = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_jwt_roundtrip(self):
        token = generate_client_jwt(str(uuid.uuid4()), 'Acme', 'self_serve', 'client@acme.com')
        payload = verify_client_jwt(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload['company_name'], 'Acme')
        self.assertEqual(payload['tier'], 'self_serve')
        self.assertEqual(payload['email'], 'client@acme.com')

    def test_tracking_pixel_headers(self):
        headers = TrackingPixelGenerator.get_pixel_headers()
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertIn('no-cache', headers['Cache-Control'])

    def test_track_open_endpoint_updates_pixel(self):
        pid = str(uuid.uuid4())
        EmailTrackingPixel.objects.create(lead_id=uuid.uuid4(), message_id='msg123', pixel_id=pid)
        url = reverse('email_service:track_open', kwargs={'pixel_id': pid})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/png')
        pixel = EmailTrackingPixel.objects.get(pixel_id=pid)
        self.assertTrue(pixel.opened)
        self.assertGreaterEqual(pixel.open_count, 1)

    def test_track_click_endpoint_redirects(self):
        lead_id = uuid.uuid4()
        message_id = 'msg123'
        dest = 'https://example.com'
        tracking_url = EmailTracker.create_click_tracking(lead_id, message_id, dest, client_id=uuid.uuid4())
        click_id = tracking_url.split('/')[-1]
        url = reverse('email_service:track_click', kwargs={'click_id': click_id})
        resp = self.client.get(url, follow=False)
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn(dest, resp['Location'])
