"""8 Python HTTP clients, the same 10,000 HTTPS GET calls, 50 in flight, median of 5 runs.

Every client verifies TLS against the test server's certificate. A run only counts if all
10,000 answers were status 200 with the body "ok\\n"; otherwise the client is marked FAILED.
"""

import asyncio
import ssl
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

URL = "https://127.0.0.1:8443/"
CA = "/etc/nginx/cert.pem"
N = 10_000
IN_FLIGHT = 50
RUNS = 5
BODY = b"ok\n"


def _ssl_ctx() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=CA)


def _thread_pool(make_one) -> int:
    """Run N calls on IN_FLIGHT threads. make_one() returns a per-thread function giving (status, body)."""
    local = threading.local()

    def one(_: int) -> bool:
        if not hasattr(local, "fn"):
            local.fn = make_one()
        status, body = local.fn()
        return status == 200 and body == BODY

    with ThreadPoolExecutor(IN_FLIGHT) as pool:
        results = list(pool.map(one, range(N)))
    return sum(results)


def run_requests() -> int:
    import requests

    def make_one():
        s = requests.Session()

        def fn():
            r = s.get(URL, verify=CA)
            return r.status_code, r.content
        return fn
    return _thread_pool(make_one)


def run_http_client() -> int:
    import http.client

    def make_one():
        conn = http.client.HTTPSConnection("127.0.0.1", 8443, context=_ssl_ctx())

        def fn():
            conn.request("GET", "/")
            r = conn.getresponse()
            return r.status, r.read()
        return fn
    return _thread_pool(make_one)


def run_urllib3() -> int:
    import urllib3
    pm = urllib3.PoolManager(maxsize=IN_FLIGHT, cert_reqs="CERT_REQUIRED", ca_certs=CA)

    def make_one():
        def fn():
            r = pm.request("GET", URL)
            return r.status, r.data
        return fn
    return _thread_pool(make_one)


async def _gather(one) -> int:
    """Start all N calls, at most IN_FLIGHT at a time, so no call waits on a pool timeout."""
    sem = asyncio.Semaphore(IN_FLIGHT)

    async def limited() -> bool:
        async with sem:
            return await one()
    results = await asyncio.gather(*[limited() for _ in range(N)])
    return sum(results)


def run_httpx() -> int:
    import httpx

    async def main() -> int:
        limits = httpx.Limits(max_connections=IN_FLIGHT, max_keepalive_connections=IN_FLIGHT)
        async with httpx.AsyncClient(verify=_ssl_ctx(), limits=limits) as client:
            async def one() -> bool:
                r = await client.get(URL)
                return r.status_code == 200 and r.content == BODY
            return await _gather(one)
    return asyncio.run(main())


def run_aiohttp() -> int:
    import aiohttp

    async def main() -> int:
        conn = aiohttp.TCPConnector(limit=IN_FLIGHT, ssl=_ssl_ctx())
        async with aiohttp.ClientSession(connector=conn) as session:
            async def one() -> bool:
                async with session.get(URL) as r:
                    body = await r.read()
                    return r.status == 200 and body == BODY
            return await _gather(one)
    return asyncio.run(main())


def run_niquests() -> int:
    import niquests

    async def main() -> int:
        async with niquests.AsyncSession(pool_connections=1, pool_maxsize=IN_FLIGHT) as s:
            async def one() -> bool:
                r = await s.get(URL, verify=CA)
                return r.status_code == 200 and r.content == BODY
            return await _gather(one)
    return asyncio.run(main())


def run_niquests_session_verify() -> int:
    """Harness check only: the certificate set once on the session, as niquests' docs configure it."""
    import niquests

    async def main() -> int:
        async with niquests.AsyncSession(pool_connections=1, pool_maxsize=IN_FLIGHT) as s:
            s.verify = CA
            async def one() -> bool:
                r = await s.get(URL)
                return r.status_code == 200 and r.content == BODY
            return await _gather(one)
    return asyncio.run(main())


def run_curl_cffi() -> int:
    from curl_cffi.requests import AsyncSession

    async def main() -> int:
        async with AsyncSession(max_clients=IN_FLIGHT, verify=CA) as s:
            async def one() -> bool:
                r = await s.get(URL)
                return r.status_code == 200 and r.content == BODY
            return await _gather(one)
    return asyncio.run(main())


def run_pycurl() -> int:
    import pycurl
    multi = pycurl.CurlMulti()
    free = []
    for _ in range(IN_FLIGHT):
        c = pycurl.Curl()
        c.setopt(pycurl.URL, URL)
        c.setopt(pycurl.CAINFO, CA)
        free.append(c)
    started = 0
    good = 0
    done = 0
    bufs = {}
    while done < N:
        while free and started < N:
            c = free.pop()
            buf = BytesIO()
            c.setopt(pycurl.WRITEDATA, buf)
            bufs[id(c)] = buf
            multi.add_handle(c)
            started += 1
        while True:
            ret, _ = multi.perform()
            if ret != pycurl.E_CALL_MULTI_PERFORM:
                break
        while True:
            _, ok_list, err_list = multi.info_read()
            for c in ok_list:
                if c.getinfo(pycurl.RESPONSE_CODE) == 200 and bufs[id(c)].getvalue() == BODY:
                    good += 1
                multi.remove_handle(c)
                free.append(c)
                done += 1
            for c, _, _ in err_list:
                multi.remove_handle(c)
                free.append(c)
                done += 1
            if not ok_list and not err_list:
                break
        multi.select(1.0)
    return good


CONTENDERS = {
    "requests": run_requests,
    "http.client": run_http_client,
    "urllib3": run_urllib3,
    "httpx": run_httpx,
    "aiohttp": run_aiohttp,
    "niquests": run_niquests,
    "curl_cffi": run_curl_cffi,
    "pycurl": run_pycurl,
}


CHECKS = {"niquests_session_verify": run_niquests_session_verify}  # harness checks, not ranked


def main() -> None:
    every = {**CONTENDERS, **CHECKS}
    names = sys.argv[1:] or list(CONTENDERS)
    times = {name: [] for name in names}
    status = {name: "OK" for name in names}
    print("# " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + f" N={N} in_flight={IN_FLIGHT} runs={RUNS}")
    print("# python " + sys.version.split()[0])
    for run in range(RUNS):
        for name in names:
            fn = every[name]
            if status[name] != "OK":
                continue
            t0 = time.perf_counter()
            try:
                good = fn()
            except Exception as exc:  # a client that crashes is a result, recorded as such
                status[name] = "FAILED: " + repr(exc)[:200]
                print(f"# run {run + 1} {name} error {exc!r}", file=sys.stderr)
                continue
            dt = time.perf_counter() - t0
            if good != N:
                status[name] = f"FAILED: {good} of {N} good answers"
                continue
            times[name].append(dt)
            print(f"# run {run + 1} {name} {dt:.3f}", file=sys.stderr, flush=True)
    print("client,median_s,runs,status")
    for name in names:
        med = f"{statistics.median(times[name]):.3f}" if times[name] else ""
        runs = " ".join(f"{t:.2f}" for t in times[name])
        print(f"{name},{med},{runs},{status[name]}")


if __name__ == "__main__":
    main()
