"""End-to-end check of a running stack, through the published ports (standard library only).

    uv run --no-project python scripts/smoke.py [--gpu]

It signs platform tokens with PLATFORM_JWT_SECRET from .env, as Community does, then checks that
every service is up and that they reach each other: a Mie job runs through Cloud's queue and
worker into S3, Materials accepts Community's tokens, Community uses the real Materials and Cloud
instead of its built-in mocks, and Studio is configured with the public URLs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = {}
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip()

COMMUNITY = ENV.get("COMMUNITY_URL", "http://localhost:3000")
STUDIO = ENV.get("STUDIO_URL", "http://localhost:8080")
CLOUD = ENV.get("CLOUD_URL", "http://localhost:8200")
MATERIALS = ENV.get("MATERIALS_URL", "http://localhost:8100")
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def token(aud: str, sub: str = "smoke-test") -> str:
    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    now = int(time.time())
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({"sub": sub, "role": "user", "aud": aud, "iss": "lightsmith-community",
                           "iat": now, "exp": now + 300}).encode())
    sig = hmac.new(ENV["PLATFORM_JWT_SECRET"].encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


def http(method: str, url: str, body=None, headers=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json", **({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")
    except OSError as e:
        return 0, {}, str(e)


def main() -> None:
    # --- liveness --------------------------------------------------------------------------
    st, _, body = http("GET", f"{CLOUD}/v1/health")
    check("cloud health", st == 200, body[:120])
    st, _, body = http("GET", f"{MATERIALS}/healthz")
    check("materials health", st == 200, body[:120])
    st, _, _ = http("GET", f"{STUDIO}/healthz")
    check("studio health", st == 200)
    st, _, _ = http("GET", COMMUNITY, timeout=60)
    check("community home page", st == 200, f"HTTP {st}")

    # --- Studio is configured with the public URLs ------------------------------------------
    st, _, body = http("GET", f"{STUDIO}/config.js")
    check("studio config.js points at Cloud, Materials and Community",
          st == 200 and all(f'"{u}"' in body for u in (CLOUD, MATERIALS, COMMUNITY)))

    # --- CORS: Studio (another origin) may call Cloud and Materials --------------------------
    for name, base, path in (("cloud", CLOUD, "/v1/jobs"), ("materials", MATERIALS, "/v1/materials")):
        st, h, _ = http("OPTIONS", base + path, headers={
            "Origin": STUDIO, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        check(f"{name} allows CORS from Studio", h.get("access-control-allow-origin") in (STUDIO, "*"), f"HTTP {st}")

    # --- Cloud: a platform token runs a job through the queue, the worker and S3 --------------
    spec = {"kind": "scattering", "medium_index": 1.33, "wavelengths": [500.0, 550.0, 600.0],
            "particles": [{"shape": {"kind": "sphere", "radius_nm": 40},
                           "material": {"kind": "constant_index", "n_real": 1.5, "n_imag": 0.01}}]}
    auth = {"Authorization": f"Bearer {token('compute')}"}
    st, _, body = http("POST", f"{CLOUD}/v1/jobs", {"simulation": spec, "method": "mie", "device": "cpu",
                                                    "label": "deploy smoke test"}, auth)
    check("cloud accepts a job with a Community token", st == 202, body[:200])
    if st == 202:
        job_id = json.loads(body)["job_id"]
        deadline, job = time.time() + 180, {}
        while time.time() < deadline:
            st, _, body = http("GET", f"{CLOUD}/v1/jobs/{job_id}", headers=auth)
            job = json.loads(body) if st == 200 else {}
            if job.get("status") in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(1)
        c_ext = (job.get("result") or {}).get("c_ext_nm2") or []
        check("cloud worker solves the job", job.get("status") == "succeeded" and len(c_ext) == 3 and min(c_ext) > 0,
              f"status {job.get('status')}, error {job.get('error')}")
        st, _, body = http("GET", f"{CLOUD}/v1/jobs/{job_id}/result", headers=auth)
        check("cloud serves the stored result", st == 200 and "c_ext_nm2" in body, f"HTTP {st}")
    if "--gpu" in sys.argv:  # with `--profile gpu`: a DDA job must land on the CUDA worker
        st, _, body = http("POST", f"{CLOUD}/v1/jobs", {"simulation": {**spec, "options": {"dda": {"dipoles_per_diameter": 16}}},
                                                        "method": "dda", "device": "gpu"}, auth)
        job = {}
        if st == 202:
            job_id, deadline = json.loads(body)["job_id"], time.time() + 300
            while time.time() < deadline and job.get("status") not in ("succeeded", "failed", "cancelled"):
                time.sleep(1)
                job = json.loads(http("GET", f"{CLOUD}/v1/jobs/{job_id}", headers=auth)[2])
        used = job.get("device_used") or {}
        check("cloud GPU worker runs a DDA job on CUDA",
              job.get("status") == "succeeded" and str(used.get("device", "")).startswith("cuda"),
              f"HTTP {st}, status {job.get('status')}, device {used}, error {job.get('error')}")
    st, _, _ = http("GET", f"{CLOUD}/v1/jobs?mine=1", headers={"Authorization": "Bearer not.a.token"})
    check("cloud rejects a bad token", st == 401, f"HTTP {st}")

    # --- Materials: public reads, and Community tokens for authenticated calls ----------------
    st, _, body = http("GET", f"{MATERIALS}/v1/stats")
    stats = json.loads(body) if st == 200 else {}
    check("materials stats", st == 200, body[:160])
    st, _, body = http("GET", f"{MATERIALS}/v1/submissions?mine=true",
                       headers={"Authorization": f"Bearer {token('materials-db')}"})
    check("materials accepts a Community token", st == 200, f"HTTP {st} {body[:120]}")
    st, _, _ = http("GET", f"{MATERIALS}/v1/submissions?mine=true",
                    headers={"Authorization": f"Bearer {token('compute')}"})
    check("materials rejects a token for another audience", st == 401, f"HTTP {st}")
    st, _, body = http("GET", f"{MATERIALS}/v1/datasets?q=Au&limit=1")
    items = json.loads(body).get("items", []) if st == 200 else []
    if items:  # only after `--profile import run --rm materials-import`
        ds = items[0]["id"]
        st, _, body = http("GET", f"{MATERIALS}/v1/datasets/{ds}/fit/drude-lorentz", timeout=120)
        check("materials fits a Drude-Lorentz model with the library", st == 200, f"{ds}: HTTP {st} {body[:120]}")
    else:
        print(f"skip materials model fit (no datasets imported; stats: {json.dumps(stats)[:80]})")

    # --- Community talks to the real services, not its built-in mocks -------------------------
    st, _, body = http("GET", f"{COMMUNITY}/materials", timeout=60)
    check("community materials page uses Lightsmith Materials",
          st == 200 and "Showing built-in sample data" not in body, f"HTTP {st}")

    print()
    if failures:
        sys.exit(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    print("all checks passed")


if __name__ == "__main__":
    main()
