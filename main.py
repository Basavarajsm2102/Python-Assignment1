import os
import boto3
import zipfile
import io
from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from botocore.exceptions import ClientError
from urllib.parse import quote
import mimetypes
import logging
from typing import List, Dict
from datetime import datetime
import uuid
import re

# Initialize FastAPI app
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# AWS S3 client configuration
s3_client = boto3.client('s3')

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Helper functions
def sanitize_filename(filename: str) -> str:
    """Sanitize filename to ensure valid S3 key."""
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '_', filename.strip())
    return sanitized if sanitized else f"file_{uuid.uuid4().hex}"

def get_file_metadata(bucket: str, key: str) -> Dict:
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
    total_size = 0
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                total_size += obj['Size']
    except ClientError as e:
        logger.error(f"Error calculating folder size for {bucket}/{prefix}: {e}")
    return total_size

def get_bucket_stats() -> List[Dict]:
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
    except ClientError as e:
        logger.error(f"Error getting bucket stats: {e}")
    return stats

def search_s3_objects(bucket: str, prefix: str, search_query: str, min_size: int = None, max_size: int = None, start_date: str = None, end_date: str = None, content_type: str = None, tag: str = None) -> List[Dict]:
    objects = []
    paginator = s3_client.get_paginator('list_objects_v2')
    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                if search_query.lower() in obj['Key'].lower():
                    metadata = get_file_metadata(bucket, obj['Key'])
                    include = True
                    if min_size is not None and obj['Size'] < min_size:
                        include = False
                    if max_size is not None and obj['Size'] > max_size:
                        include = False
                    if start_date:
                        start = datetime.strptime(start_date, '%Y-%m-%d')
                        if obj['LastModified'].date() < start.date():
                            include = False
                    if end_date:
                        end = datetime.strptime(end_date, '%Y-%m-%d')
                        if obj['LastModified'].date() > end.date():
                            include = False
                    if content_type and metadata.get('content_type', 'N/A') != content_type:
                        include = False
                    if tag:
                        try:
                            tag_response = s3_client.get_object_tagging(Bucket=bucket, Key=obj['Key'])
                            tags = {t['Key']: t['Value'] for t in tag_response.get('TagSet', [])}
                            if tag not in tags.values():
                                include = False
                        except ClientError as e:
                            logger.error(f"Error getting tags for {bucket}/{obj['Key']}: {e}")
                            include = False
                    if include:
                        objects.append({
                            'Key': obj['Key'],
                            'LastModified': obj['LastModified'].strftime('%Y-%m-%d %H:%M:%S'),
                            'Size': obj['Size'],
                            'Type': 'File'
                        })
    except ClientError as e:
        logger.error(f"Error searching objects in {bucket}/{prefix}: {e}")
    return objects

def list_folder_contents(bucket: str, prefix: str) -> List[Dict]:
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
    except ClientError as e:
        logger.error(f"Error listing folder contents for {bucket}/{prefix}: {e}")
    return objects

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    buckets = []
    try:
        response = s3_client.list_buckets()
        buckets = [bucket['Name'] for bucket in response['Buckets']]
    except ClientError as e:
        logger.error(f"Error listing buckets: {e}")
    return templates.TemplateResponse("index.html", {"request": request, "buckets": buckets})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = get_bucket_stats()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats
    })

@app.get("/bucket/{bucket_name}", response_class=HTMLResponse)
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
    except ClientError as e:
        logger.error(f"Error listing bucket contents for {bucket_name}/{prefix}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    return templates.TemplateResponse("bucket.html", {
        "request": request,
        "bucket_name": bucket_name,
        "prefix": prefix,
        "objects": objects,
        "folders": folders
    })

@app.post("/create_bucket", response_class=HTMLResponse)
async def create_bucket(request: Request, bucket_name: str = Form(...)):
    try:
        s3_client.create_bucket(Bucket=bucket_name)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"Bucket {bucket_name} created successfully"
        })
    except ClientError as e:
        logger.error(f"Error creating bucket {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/delete_bucket/{bucket_name}", response_class=HTMLResponse)
async def delete_bucket(request: Request, bucket_name: str):
    try:
        s3_client.delete_bucket(Bucket=bucket_name)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"Bucket {bucket_name} deleted successfully"
        })
    except ClientError as e:
        logger.error(f"Error deleting bucket {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/create_folder/{bucket_name}", response_class=HTMLResponse)
async def create_folder(request: Request, bucket_name: str, folder_name: str = Form(...), prefix: str = Form("")):
    try:
        folder_key = f"{prefix}{folder_name}/"
        s3_client.put_object(Bucket=bucket_name, Key=folder_key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"Folder {folder_name} created successfully"
        })
    except ClientError as e:
        logger.error(f"Error creating folder in {bucket_name}/{prefix}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/upload_file/{bucket_name}", response_class=HTMLResponse)
async def upload_file(request: Request, bucket_name: str, prefix: str = Form(""), file: UploadFile = File(...)):
    try:
        sanitized_filename = sanitize_filename(file.filename)
        file_key = f"{prefix}{sanitized_filename}"
        logger.debug(f"Uploading file to {bucket_name}/{file_key}")
        
        content_type, _ = mimetypes.guess_type(sanitized_filename)
        content_type = content_type or 'application/octet-stream'
        
        s3_client.upload_fileobj(
            file.file,
            bucket_name,
            file_key,
            ExtraArgs={'ContentType': content_type}
        )
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"File {sanitized_filename} uploaded successfully"
        })
    except ClientError as e:
        error_msg = f"Error uploading file to {bucket_name}/{file_key}: {e.response['Error']['Message']}"
        logger.error(error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        error_msg = f"Unexpected error during upload: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.get("/confirm_delete_folder/{bucket_name}/{folder_key:path}", response_class=HTMLResponse)
async def confirm_delete_folder(request: Request, bucket_name: str, folder_key: str, prefix: str = ""):
    contents = list_folder_contents(bucket_name, folder_key)
    return templates.TemplateResponse("confirm_delete.html", {
        "request": request,
        "bucket_name": bucket_name,
        "folder_key": folder_key,
        "prefix": prefix,
        "contents": contents
    })

@app.post("/delete_file/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def delete_file(request: Request, bucket_name: str, file_key: str):
    try:
        s3_client.delete_object(Bucket=bucket_name, Key=file_key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"File {file_key} deleted successfully"
        })
    except ClientError as e:
        logger.error(f"Error deleting file {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/delete_folder/{bucket_name}/{folder_key:path}", response_class=HTMLResponse)
async def delete_folder(request: Request, bucket_name: str, folder_key: str):
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket_name, Prefix=folder_key):
            for obj in page.get('Contents', []):
                s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
        s3_client.delete_object(Bucket=bucket_name, Key=folder_key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"Folder {folder_key} deleted successfully"
        })
    except ClientError as e:
        logger.error(f"Error deleting folder {bucket_name}/{folder_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/bulk_delete/{bucket_name}", response_class=HTMLResponse)
async def bulk_delete(request: Request, bucket_name: str, keys: List[str] = Form(...)):
    try:
        for key in keys:
            if key.endswith('/'):
                paginator = s3_client.get_paginator('list_objects_v2')
                for page in paginator.paginate(Bucket=bucket_name, Prefix=key):
                    for obj in page.get('Contents', []):
                        s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
                s3_client.delete_object(Bucket=bucket_name, Key=key)
            else:
                s3_client.delete_object(Bucket=bucket_name, Key=key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"{len(keys)} item(s) deleted successfully"
        })
    except ClientError as e:
        logger.error(f"Error in bulk delete for {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/bulk_copy/{bucket_name}", response_class=HTMLResponse)
async def bulk_copy(request: Request, bucket_name: str, keys: List[str] = Form(...), destination: str = Form(...)):
    try:
        for key in keys:
            dest_key = f"{destination.rstrip('/')}/{os.path.basename(key.rstrip('/'))}"
            s3_client.copy_object(Bucket=bucket_name, CopySource={'Bucket': bucket_name, 'Key': key}, Key=dest_key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"{len(keys)} item(s) copied to {destination}"
        })
    except ClientError as e:
        logger.error(f"Error in bulk copy for {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/bulk_move/{bucket_name}", response_class=HTMLResponse)
async def bulk_move(request: Request, bucket_name: str, keys: List[str] = Form(...), destination: str = Form(...)):
    try:
        for key in keys:
            dest_key = f"{destination.rstrip('/')}/{os.path.basename(key.rstrip('/'))}"
            s3_client.copy_object(Bucket=bucket_name, CopySource={'Bucket': bucket_name, 'Key': key}, Key=dest_key)
            if key.endswith('/'):
                paginator = s3_client.get_paginator('list_objects_v2')
                for page in paginator.paginate(Bucket=bucket_name, Prefix=key):
                    for obj in page.get('Contents', []):
                        s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
                s3_client.delete_object(Bucket=bucket_name, Key=key)
            else:
                s3_client.delete_object(Bucket=bucket_name, Key=key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"{len(keys)} item(s) moved to {destination}"
        })
    except ClientError as e:
        logger.error(f"Error in bulk move for {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/rename/{bucket_name}/{key:path}", response_class=HTMLResponse)
async def rename_object(request: Request, bucket_name: str, key: str, new_name: str = Form(...), prefix: str = Form("")):
    try:
        new_key = f"{prefix}{new_name}" if not key.endswith('/') else f"{prefix}{new_name}/"
        s3_client.copy_object(Bucket=bucket_name, CopySource={'Bucket': bucket_name, 'Key': key}, Key=new_key)
        if key.endswith('/'):
            paginator = s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name, Prefix=key):
                for obj in page.get('Contents', []):
                    new_obj_key = obj['Key'].replace(key, new_key, 1)
                    s3_client.copy_object(Bucket=bucket_name, CopySource={'Bucket': bucket_name, 'Key': obj['Key']}, Key=new_obj_key)
                    s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
        s3_client.delete_object(Bucket=bucket_name, Key=key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"{'Folder' if key.endswith('/') else 'File'} {key} renamed to {new_key}"
        })
    except ClientError as e:
        logger.error(f"Error renaming object {bucket_name}/{key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/copy_file/{bucket_name}", response_class=HTMLResponse)
async def copy_file(request: Request, bucket_name: str, file_key: str = Form(...), destination: str = Form(...)):
    try:
        s3_client.copy_object(Bucket=bucket_name, CopySource={'Bucket': bucket_name, 'Key': file_key}, Key=destination)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"File copied to {destination}"
        })
    except ClientError as e:
        logger.error(f"Error copying file {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/move_file/{bucket_name}", response_class=HTMLResponse)
async def move_file(request: Request, bucket_name: str, file_key: str = Form(...), destination: str = Form(...)):
    try:
        s3_client.copy_object(Bucket=bucket_name, CopySource={'Bucket': bucket_name, 'Key': file_key}, Key=destination)
        s3_client.delete_object(Bucket=bucket_name, Key=file_key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"File moved to {destination}"
        })
    except ClientError as e:
        logger.error(f"Error moving file {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/preview/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def preview_file(request: Request, bucket_name: str, file_key: str, prefix: str = ""):
    try:
        # Check file size
        metadata = s3_client.head_object(Bucket=bucket_name, Key=file_key)
        file_size = metadata['ContentLength']
        content_type = metadata.get('ContentType', 'application/octet-stream')
        logger.debug(f"Previewing {bucket_name}/{file_key}: size={file_size}, content_type={content_type}")
        
        if file_size > 10 * 1024 * 1024:  # 10MB limit
            return templates.TemplateResponse("preview.html", {
                "request": request,
                "bucket_name": bucket_name,
                "file_key": file_key,
                "prefix": prefix,
                "error": "File too large for preview (max 10MB)"
            })
        
        # Handle text files
        if content_type.startswith('text/') or file_key.endswith(('.txt', '.csv', '.json', '.log')):
            obj = s3_client.get_object(Bucket=bucket_name, Key=file_key)
            text = obj['Body'].read().decode('utf-8', errors='replace')
            return templates.TemplateResponse("preview.html", {
                "request": request,
                "bucket_name": bucket_name,
                "file_key": file_key,
                "prefix": prefix,
                "text_content": text,
                "content_type": "text"
            })
        
        # Handle images and PDFs
        if content_type.startswith(('image/', 'application/pdf')) or file_key.endswith(('.png', '.jpg', '.jpeg', '.gif', '.pdf')):
            url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': file_key},
                ExpiresIn=300
            )
            return templates.TemplateResponse("preview.html", {
                "request": request,
                "bucket_name": bucket_name,
                "file_key": file_key,
                "prefix": prefix,
                "url": url,
                "content_type": "image" if content_type.startswith('image/') else "pdf"
            })
        
        # Unsupported file type
        return templates.TemplateResponse("preview.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "error": f"Preview not supported for content type: {content_type}"
        })
    except ClientError as e:
        error_msg = f"Error previewing file {bucket_name}/{file_key}: {e.response['Error']['Message']}"
        logger.error(error_msg)
        return templates.TemplateResponse("preview.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "error": error_msg
        })
    except Exception as e:
        error_msg = f"Unexpected error previewing file: {str(e)}"
        logger.error(error_msg)
        return templates.TemplateResponse("preview.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "error": error_msg
        })

@app.get("/download/{bucket_name}/{file_key:path}")
async def download_file(bucket_name: str, file_key: str):
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
        return StreamingResponse(
            io.BytesIO(response['Body'].read()),
            media_type=response['ContentType'],
            headers={"Content-Disposition": f"attachment; filename={os.path.basename(file_key)}"}
        )
    except ClientError as e:
        logger.error(f"Error downloading file {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/zip_files/{bucket_name}", response_class=FileResponse)
async def zip_files(request: Request, bucket_name: str, files: List[str] = Form(...)):
    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_key in files:
                response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
                zip_file.writestr(os.path.basename(file_key), response['Body'].read())
        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type='application/zip',
            headers={"Content-Disposition": "attachment; filename=files.zip"}
        )
    except ClientError as e:
        logger.error(f"Error zipping files in {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/metadata/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def get_metadata(request: Request, bucket_name: str, file_key: str, prefix: str = ""):
    metadata = get_file_metadata(bucket_name, file_key)
    try:
        tag_response = s3_client.get_object_tagging(Bucket=bucket_name, Key=file_key)
        tags = [t['Value'] for t in tag_response.get('TagSet', [])]
    except ClientError as e:
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

@app.post("/search/{bucket_name}", response_class=HTMLResponse)
async def search_files(
    request: Request,
    bucket_name: str,
    search_query: str = Form(...),
    prefix: str = Form(""),
    min_size: int = Form(None),
    max_size: int = Form(None),
    start_date: str = Form(None),
    end_date: str = Form(None),
    content_type: str = Form(None),
    tag: str = Form(None)
):
    objects = search_s3_objects(bucket_name, prefix, search_query, min_size, max_size, start_date, end_date, content_type, tag)
    return templates.TemplateResponse("search.html", {
        "request": request,
        "bucket_name": bucket_name,
        "prefix": prefix,
        "objects": objects,
        "search_query": search_query,
        "min_size": min_size,
        "max_size": max_size,
        "start_date": start_date,
        "end_date": end_date,
        "content_type": content_type,
        "tag": tag
    })

@app.get("/share/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def share_file_get(request: Request, bucket_name: str, file_key: str, prefix: str = ""):
    try:
        logger.debug(f"Generating default pre-signed URL for {bucket_name}/{file_key}")
        default_expires_in = 3600  # 1 hour
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': file_key},
            ExpiresIn=default_expires_in
        )
        logger.info(f"Default pre-signed URL generated: {url}")
        return templates.TemplateResponse("share.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "url": url,
            "expires_in": default_expires_in,
            "error": None
        })
    except ClientError as e:
        error_msg = f"Error generating share URL: {e.response['Error']['Message']}"
        logger.error(error_msg)
        return templates.TemplateResponse("share.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "url": None,
            "expires_in": None,
            "error": error_msg
        })
    except Exception as e:
        error_msg = f"Unexpected error generating share URL: {str(e)}"
        logger.error(error_msg)
        return templates.TemplateResponse("share.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "url": None,
            "expires_in": None,
            "error": error_msg
        })

@app.post("/share/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def share_file_post(request: Request, bucket_name: str, file_key: str, prefix: str = Form(""), expires_in: str = Form(None)):
    try:
        if not expires_in:
            logger.warning(f"No expiration time selected for {bucket_name}/{file_key}")
            return templates.TemplateResponse("share.html", {
                "request": request,
                "bucket_name": bucket_name,
                "file_key": file_key,
                "prefix": prefix,
                "url": None,
                "expires_in": None,
                "error": "Please select an expiration time"
            })
        
        expires_in_int = int(expires_in)
        logger.debug(f"Generating pre-signed URL for {bucket_name}/{file_key} with expiry {expires_in_int}s")
        if expires_in_int <= 0 or expires_in_int > 604800:
            logger.warning(f"Invalid expiration time {expires_in_int} for {bucket_name}/{file_key}")
            return templates.TemplateResponse("share.html", {
                "request": request,
                "bucket_name": bucket_name,
                "file_key": file_key,
                "prefix": prefix,
                "url": None,
                "expires_in": None,
                "error": "Expiration time must be between 1 and 604800 seconds"
            })
        
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': file_key},
            ExpiresIn=expires_in_int
        )
        logger.info(f"Generated pre-signed URL for {bucket_name}/{file_key}: {url}")
        return templates.TemplateResponse("share.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "url": url,
            "expires_in": expires_in_int,
            "error": None
        })
    except ClientError as e:
        error_msg = f"Error generating share URL: {e.response['Error']['Message']}"
        logger.error(error_msg)
        return templates.TemplateResponse("share.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "url": None,
            "expires_in": None,
            "error": error_msg
        })
    except ValueError:
        error_msg = "Invalid expiration time format"
        logger.error(error_msg)
        return templates.TemplateResponse("share.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "url": None,
            "expires_in": None,
            "error": error_msg
        })
    except Exception as e:
        error_msg = f"Unexpected error generating share URL: {str(e)}"
        logger.error(error_msg)
        return templates.TemplateResponse("share.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "url": None,
            "expires_in": None,
            "error": error_msg
        })

@app.post("/tag/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
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
    except ClientError as e:
        logger.error(f"Error adding tag to {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)