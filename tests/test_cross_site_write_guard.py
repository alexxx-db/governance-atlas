"""CSRF guard: browsers label cross-site requests via Sec-Fetch-Site; the app
must refuse state-changing /api calls marked cross-site or same-site (another
*.databricksapps.com app), and leave same-origin / non-browser calls alone."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

_ENV = {"DATABRICKS_WAREHOUSE_ID": "wh-test", "GOVAT_CATALOG": "main", "GOVAT_SCHEMA": "atlas"}


class CrossSiteWriteGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._env = patch.dict(os.environ, _ENV)
        cls._env.start()
        import runtime_app

        cls.client = TestClient(runtime_app.app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._env.stop()

    def test_cross_site_and_same_site_writes_refused(self) -> None:
        for site in ("cross-site", "same-site"):
            resp = self.client.post("/api/governance/requests", json={}, headers={"Sec-Fetch-Site": site})
            self.assertEqual(resp.status_code, 403, site)
            self.assertEqual(resp.json()["error"]["code"], "cross_site_request")

    def test_same_origin_and_headerless_writes_pass_the_guard(self) -> None:
        for headers in ({"Sec-Fetch-Site": "same-origin"}, {}):
            resp = self.client.post("/api/governance/requests", json={}, headers=headers)
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            self.assertNotEqual((body.get("error") or {}).get("code"), "cross_site_request")

    def test_reads_are_not_affected(self) -> None:
        resp = self.client.get("/api/runtime/status", headers={"Sec-Fetch-Site": "cross-site"})
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        self.assertNotEqual((body.get("error") or {}).get("code"), "cross_site_request")


if __name__ == "__main__":
    unittest.main()
