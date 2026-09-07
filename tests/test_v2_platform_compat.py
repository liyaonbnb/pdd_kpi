import unittest
from v2.test_api import app

class PlatformCompatRouteTests(unittest.TestCase):
    def test_unified_platform_routes_are_registered(self):
        paths = app.openapi()["paths"]
        expected = {"/api/{platform}/dashboard", "/api/{platform}/orders", "/api/{platform}/trend", "/api/{platform}/analysis", "/api/{platform}/costs", "/api/{platform}/records"}
        self.assertTrue(expected.issubset(paths))

if __name__ == "__main__":
    unittest.main()
