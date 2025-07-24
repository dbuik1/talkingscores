"""
Essential tests for Talking Scores - focused on critical issues.
"""

from django.test import TestCase, Client
from django.urls import reverse
from talkingscoresapp.models import TSScore
import os


class SecurityTests(TestCase):
    """Security-focused test cases."""
    
    def test_file_path_traversal_prevention(self):
        """Test that file path traversal attacks are prevented."""
        malicious_names = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32\\config\\sam", 
            "test/../../../secret.txt",
            "/etc/passwd",
            "\\windows\\system32\\config\\sam"
        ]
        
        for malicious_name in malicious_names:
            score = TSScore(id="test123", filename=malicious_name)
            path = score.get_data_file_path()
            
            # Ensure the path is within the expected directory structure
            self.assertIn("test123", path)
            # Most importantly: ensure no path traversal characters remain
            self.assertNotIn("..", path)
            self.assertNotIn("/etc/", path)
            self.assertNotIn("\\windows\\", path.lower())


class BasicFunctionalityTests(TestCase):
    """Tests for basic page loads."""
    
    def setUp(self):
        self.client = Client()
        
    def test_homepage_loads(self):
        """Ensure the main page works."""
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Talking Scores')
        
    def test_change_log_loads(self):
        """Test the change log page loads correctly."""
        response = self.client.get(reverse('change-log'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Change Log')
        
    def test_contact_us_loads(self):
        """Test the contact us page loads correctly."""
        response = self.client.get(reverse('contact-us'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Contact Us')