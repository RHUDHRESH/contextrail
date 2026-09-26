"""A scripted Freshservice tenant for tests: httpx.MockTransport only, never the network.

`FakeTenant` records every request and answers from a route table keyed by (method, path). A route value is a
Response, a callable(request) -> Response, or an exception instance to raise (timeouts, connection errors).
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

DOMAIN = "northbeam.freshservice.com"
API_KEY = "fake-fs-key-for-tests"
BASE = f"https://{DOMAIN}/api/v2"

Route = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


class FakeTenant:
    def __init__(self, routes: dict[tuple[str, str], Route | list[Route]] | None = None) -> None:
        self.routes: dict[tuple[str, str], Route | list[Route]] = dict(routes or {})
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key not in self.routes:
            return httpx.Response(404, json={"description": f"no route {key}"})
        route = self.routes[key]
        if isinstance(route, list):  # a sequence of answers, one per call; the last one repeats
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        if callable(route) and not isinstance(route, httpx.Response):
            return route(request)
        return route

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content)


def ok(payload: object, status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)
