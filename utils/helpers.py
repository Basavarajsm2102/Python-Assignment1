import re
import uuid
import logging
from typing import List, Dict

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to ensure valid S3 key."""
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '_', filename.strip())
    return sanitized if sanitized else f"file_{uuid.uuid4().hex}"

def list_folder_contents(bucket: str, prefix: str, s3_client) -> List[Dict]:
    """List contents of a folder in S3."""
    objects = []
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                objects.append({
                    'Key': obj['Key'],
                    'LastModified': obj['LastModified'].strftime('%Y-%m-%d %H:%M:%S'),
                    'Size': obj['Size']
                })
    except s3_client.exceptions.ClientError as e:
        logging.getLogger(__name__).error(f"Error listing folder contents for {bucket}/{prefix}: {e}")
    return objects