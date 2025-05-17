import os
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Setup logging
logger = logging.getLogger(__name__)

# AWS S3 client configuration
aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
aws_region = os.getenv("AWS_REGION", "us-east-1")

if not aws_access_key_id or not aws_secret_access_key:
    raise ValueError("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set in .env file")

try:
    s3_client = boto3.client(
        's3',
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=aws_region
    )
except Exception as e:
    logger.error(f"Failed to initialize S3 client: {str(e)}")
    raise ValueError(f"Failed to initialize S3 client: {str(e)}")

def get_file_metadata(bucket: str, key: str) -> dict:
    """Retrieve metadata for an S3 object."""
    try:
        response = s3_client.head_object(Bucket=bucket, Key=key)
        return {
            'size': response['ContentLength'],
            'last_modified': response['LastModified'].strftime('%Y-%m-%d %H:%M:%S'),
            'content_type': response.get('ContentType', 'N/A'),
            'etag': response['ETag'].strip('"')
        }
    except ClientError as e:
        logger.error(f"Error getting metadata for {bucket}/{key}: {e}")
        return {}

def get_folder_size(bucket: str, prefix: str) -> int:
    """Calculate total size of objects in a folder."""
    total_size = 0
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                total_size += obj['Size']
    except ClientError as e:
        logger.error(f"Error calculating folder size for {bucket}/{prefix}: {e}")
    return total_size

def generate_presigned_url(bucket: str, key: str, expires_in: int) -> str:
    """Generate a pre-signed URL for an S3 object."""
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=expires_in
        )
        return url
    except ClientError as e:
        logger.error(f"Error generating pre-signed URL for {bucket}/{key}: {e}")
        raise