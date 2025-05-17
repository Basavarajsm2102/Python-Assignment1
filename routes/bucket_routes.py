from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from utils.s3_utils import s3_client, get_folder_size
import logging

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    buckets = []
    stats = []
    try:
        # Fetch bucket list
        response = s3_client.list_buckets()
        buckets = [bucket['Name'] for bucket in response['Buckets']]
        
        # Fetch bucket statistics
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
        logger.error(f"Error fetching buckets or stats: {e}")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "buckets": buckets,
        "stats": stats
    })

@router.get("/bucket/{bucket_name}", response_class=HTMLResponse)
async def list_bucket(request: Request, bucket_name: str, prefix: str = ""):
    objects = []
    folders = []
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix, Delimiter='/'):
            for folder in page.get('CommonPrefixes', []):
                folder_key = folder['Prefix']
                folders.append({
                    'Key': folder_key,
                    'Size': get_folder_size(bucket_name, folder_key)
                })
            for obj in page.get('Contents', []):
                objects.append({
                    'Key': obj['Key'],
                    'LastModified': obj['LastModified'].strftime('%Y-%m-%d %H:%M:%S'),
                    'Size': obj['Size'],
                    'Type': 'File'
                })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error listing bucket contents for {bucket_name}/{prefix}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    return templates.TemplateResponse("bucket.html", {
        "request": request,
        "bucket_name": bucket_name,
        "prefix": prefix,
        "objects": objects,
        "folders": folders
    })

@router.post("/create_bucket", response_class=HTMLResponse)
async def create_bucket(request: Request, bucket_name: str = Form(...)):
    try:
        s3_client.create_bucket(Bucket=bucket_name)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"Bucket {bucket_name} created successfully"
        })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error creating bucket {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/delete_bucket/{bucket_name}", response_class=HTMLResponse)
async def delete_bucket(request: Request, bucket_name: str):
    try:
        s3_client.delete_bucket(Bucket=bucket_name)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"Bucket {bucket_name} deleted successfully"
        })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error deleting bucket {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/create_folder/{bucket_name}", response_class=HTMLResponse)
async def create_folder(request: Request, bucket_name: str, folder_name: str = Form(...), prefix: str = Form("")):
    try:
        folder_key = f"{prefix}{folder_name}/"
        s3_client.put_object(Bucket=bucket_name, Key=folder_key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"Folder {folder_name} created successfully"
        })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error creating folder in {bucket_name}/{prefix}: {e}")
        raise HTTPException(status_code=400, detail=str(e))