from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from utils.s3_utils import s3_client, get_file_metadata
import logging

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)

@router.get("/metadata/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def get_metadata(request: Request, bucket_name: str, file_key: str, prefix: str = ""):
    metadata = get_file_metadata(bucket_name, file_key)
    try:
        tag_response = s3_client.get_object_tagging(Bucket=bucket_name, Key=file_key)
        tags = [t['Value'] for t in tag_response.get('TagSet', [])]
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error getting tags for {bucket_name}/{file_key}: {e}")
        tags = []
    return templates.TemplateResponse("metadata.html", {
        "request": request,
        "bucket_name": bucket_name,
        "file_key": file_key,
        "metadata": metadata,
        "prefix": prefix,
        "tags": tags
    })

@router.post("/tag/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def add_tag(request: Request, bucket_name: str, file_key: str, tag: str = Form(...), prefix: str = Form("")):
    try:
        tag_response = s3_client.get_object_tagging(Bucket=bucket_name, Key=file_key)
        tags = tag_response.get('TagSet', [])
        tag_values = [t['Value'] for t in tags]
        if tag and tag not in tag_values:
            tags.append({'Key': f'tag_{len(tags) + 1}', 'Value': tag})
            s3_client.put_object_tagging(
                Bucket=bucket_name,
                Key=file_key,
                Tagging={'TagSet': tags}
            )
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"Tag '{tag}' added to {file_key}"
        })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error adding tag to {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))