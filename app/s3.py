"""Klien S3 seadanya: tanda tangan AWS SigV4 + PUT/GET/DELETE/LIST.

Cukup untuk mengunggah berkas cadangan ke penyimpanan apa pun yang berbicara
S3 — Cloudflare R2, Backblaze B2, MinIO, atau AWS sendiri. Ditulis sendiri
memakai hashlib/hmac bawaan supaya tidak menambah dependensi (boto3 ±50 MB)
ke image yang jalan di mesin 256 MB.
"""
import datetime
import hashlib
import hmac
import urllib.error
import urllib.parse
import urllib.request

ALGO = "AWS4-HMAC-SHA256"
UNSIGNED = "UNSIGNED-PAYLOAD"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def signing_key(secret: str, date: str, region: str, service: str = "s3") -> bytes:
    k = _hmac(("AWS4" + secret).encode(), date)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def canonical(method: str, path: str, query: str, headers: dict, payload_hash: str) -> tuple:
    keys = sorted(h.lower() for h in headers)
    canon_headers = "".join(f"{k}:{str(headers[[h for h in headers if h.lower() == k][0]]).strip()}\n"
                            for k in keys)
    signed = ";".join(keys)
    req = "\n".join([method, path, query, canon_headers, signed, payload_hash])
    return req, signed


def sign(method: str, url: str, access_key: str, secret_key: str, region: str,
         payload: bytes = b"", extra_headers: dict = None, now=None) -> dict:
    """Header Authorization lengkap untuk satu permintaan."""
    u = urllib.parse.urlsplit(url)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    date = stamp[:8]
    payload_hash = _sha256(payload)

    headers = {"host": u.netloc, "x-amz-content-sha256": payload_hash, "x-amz-date": stamp}
    headers.update(extra_headers or {})

    path = urllib.parse.quote(u.path or "/", safe="/~")
    query = "&".join(sorted(f"{urllib.parse.quote(k, safe='~')}={urllib.parse.quote(v, safe='~')}"
                            for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)))
    canon_req, signed_headers = canonical(method, path, query, headers, payload_hash)
    scope = f"{date}/{region}/s3/aws4_request"
    to_sign = "\n".join([ALGO, stamp, scope, _sha256(canon_req.encode())])
    signature = hmac.new(signing_key(secret_key, date, region), to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = (f"{ALGO} Credential={access_key}/{scope}, "
                                f"SignedHeaders={signed_headers}, Signature={signature}")
    return headers


def request(method: str, url: str, cfg: dict, payload: bytes = b"", extra: dict = None,
            timeout: int = 60) -> tuple:
    """Kembalikan (status, body). Kesalahan jaringan jadi (0, pesan)."""
    headers = sign(method, url, cfg["access_key"], cfg["secret_key"], cfg.get("region") or "auto",
                   payload, extra)
    req = urllib.request.Request(url, data=payload or None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (URL dari setelan pemilik)
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode()


def object_url(cfg: dict, key: str) -> str:
    return f"{cfg['endpoint'].rstrip('/')}/{cfg['bucket']}/{urllib.parse.quote(key, safe='/~')}"


def put(cfg: dict, key: str, data: bytes, content_type: str = "application/octet-stream") -> tuple:
    return request("PUT", object_url(cfg, key), cfg, data, {"content-type": content_type})


def delete(cfg: dict, key: str) -> tuple:
    return request("DELETE", object_url(cfg, key), cfg)


def list_keys(cfg: dict, prefix: str = "") -> list:
    """Daftar nama objek (maksimal 1000, cukup untuk retensi harian)."""
    url = (f"{cfg['endpoint'].rstrip('/')}/{cfg['bucket']}?list-type=2"
           f"&prefix={urllib.parse.quote(prefix, safe='')}&max-keys=1000")
    status, body = request("GET", url, cfg)
    if status != 200:
        return []
    import re
    return re.findall(r"<Key>([^<]+)</Key>", body.decode(errors="replace"))
