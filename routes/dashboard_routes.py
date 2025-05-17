from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from utils.s3_utils import s3_client
import logging

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = []
    try:
        response = s3_client.list_buckets()
        for bucket in response['Buckets']:
            bucket_name = bucket['Name']
            total_size = 0
            file_count = 0
            folder_count = 0
            last_modified = None
            paginator = s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name):
                for obj in page.get('Contents', []):
                    total_size += obj['Size']
                    file_count += 1
                    if not last_modified or obj['LastModified'] > last_modified:
                        last_modified = obj['LastModified']
            folder_paginator = s3_client.get_paginator('list_objects_v2')
            for page in folder_paginator.paginate(Bucket=bucket_name, Delimiter='/'):
                folder_count += len(page.get('CommonPrefixes', []))
            stats.append({
                'name': bucket_name,
                'total_size': total_size,
                'file_count': file_count,
                'folder_count': folder_count,
                'last_modified': last_modified.strftime('%Y-%m-%d %H:%M:%S') if last_modified else 'N/A'
            })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error getting bucket stats: {e}")
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats
    })