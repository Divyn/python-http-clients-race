# 8 Python HTTP clients, the same 10,000 calls

requests, httpx, aiohttp, niquests, urllib3, http.client, pycurl and curl_cffi each made the same 10,000 HTTPS GET calls, 50 in flight, to an nginx test server on the same box. Every client was set up the way its own docs say for many calls and checked the server's certificate. A run only counts if all 10,000 answers are status 200 with the body "ok".

Score: seconds for 10,000 calls, median of 5 runs. Lower is faster.

| Client | Seconds |
|---|---|
| httpx 0.28.1 | 36.13 |
| requests 2.34.2 | 14.07 |
| niquests 3.21.3 | 12.05 |
| urllib3 2.8.0 | 8.23 |
| curl_cffi 0.17.0 | 4.63 |
| http.client (Python 3.13.5) | 3.51 |
| aiohttp 3.14.5 | 3.47 |
| pycurl 7.49.0 | 1.06 |

Run 2026-11-19 on a Vultr `vc2-1c-1gb` server (1 vCPU, 961 MB RAM), Seattle, Debian 13, Python 3.13.5. Client and server share one CPU core and there is no network, so this measures how much CPU each client spends per call, not network speed.

Niquests check: setting the certificate once on the session, as niquests' docs do, gave 12.08 s against 11.85 s per request (`results/niquests-check.csv`), so the harness was not the cause.

- `setup.sh`: installs nginx with a self-signed certificate and the 8 clients.
- `http_race.py`: the race. `python http_race.py` runs all 8; `python http_race.py niquests niquests_session_verify` runs the check.
- `results/`: raw output, logs and the exact package versions.

## Run it yourself

1. Make a fresh Debian 13 server (these runs used Vultr `vc2-1c-1gb`: 1 vCPU, 1 GB, $5 a month).
2. Copy this folder to `/root/exp` on it, then run `cd /root/exp && sh run.sh`.
3. `run.sh` writes its state to `STATUS` (SETTING_UP, RUNNING, DONE, or SETUP_FAILED / RUN_FAILED). When it says DONE, the results are in `results.csv` and `run.log`.
