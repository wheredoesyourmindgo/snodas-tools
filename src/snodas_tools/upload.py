"""
Optional upload of results to S3 or any S3-compatible object store (DigitalOcean Spaces, Cloudflare R2, MinIO, ...).

Requires the `s3` extra: `pip install "snodas-tools[s3]"`. Credentials come from the usual AWS sources
(`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables, `~/.aws/credentials`, an instance role, ...).
"""

import logging
import mimetypes
from pathlib import Path

log = logging.getLogger(__name__)


def make_client(endpoint_url: str | None = None, region: str | None = None):
    """Create a boto3 S3 client."""
    try:
        import boto3  # pylint: disable=import-outside-toplevel
    except ImportError:
        raise RuntimeError('Uploading needs boto3: pip install "snodas-tools[s3]"') from None
    return boto3.session.Session().client("s3", endpoint_url=endpoint_url, region_name=region)


def upload_files(
    files: list[Path],
    root: Path,
    bucket: str,
    prefix: str = "",
    public: bool = False,
    client=None,
    endpoint_url: str | None = None,
    region: str | None = None,
) -> list[str]:
    """
    Upload files, keeping their path relative to `root` under `prefix`. Returns the object keys written.
    """
    client = client or make_client(endpoint_url, region)
    keys = []
    for path in files:
        path = Path(path)
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = Path(path.name)
        key = "/".join(part for part in (prefix.strip("/"), relative.as_posix()) if part)
        extra = {"ContentType": mimetypes.guess_type(path.name)[0] or "application/octet-stream"}
        if public:
            extra["ACL"] = "public-read"
        client.upload_file(str(path), bucket, key, ExtraArgs=extra)
        log.info("uploaded %s to s3://%s/%s", path, bucket, key)
        keys.append(key)
    return keys
