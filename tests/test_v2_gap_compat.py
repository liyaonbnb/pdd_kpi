import unittest

from v2.test_api import app


class GapCompatRouteTests(unittest.TestCase):
    def test_missing_v1_compat_routes_are_mounted(self):
        paths = app.openapi()["paths"]
        for path in (
            "/api/users",
            "/api/backups",
            "/api/exports/products",
            "/api/exports/styles",
            "/api/costs/global/export",
            "/api/costs/global/import",
        ):
            self.assertIn(path, paths)


if __name__ == "__main__":
    unittest.main()