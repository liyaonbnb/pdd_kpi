import unittest
from v2.test_api import app

class AutomationRouteTests(unittest.TestCase):
    def test_daily_automation_routes(self):
        paths = app.openapi()["paths"]
        for path in ("/api/v2/automation/daily/preview", "/api/v2/automation/daily/send", "/api/v2/automation/schedule-status", "/api/wecom/preview", "/api/wecom/send", "/api/wecom/schedule-status", "/api/wecom/config", "/api/wecom/listen"):
            self.assertIn(path, paths)

if __name__ == "__main__":
    unittest.main()

