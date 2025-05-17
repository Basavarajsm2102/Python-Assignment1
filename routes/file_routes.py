from fastapi import APIRouter, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates
from utils.s3_utils import s3_client, generate_presigned_url, get_file_metadata
from utils.helpers import sanitize_filename, list_folder_contents
import mimetypes
import io
import zipfile
import os
import logging

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)

@router.post("/upload_file/{bucket_name}", response_class=HTMLResponse)
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
    except s3_client.exceptions.ClientError as e:
        error_msg = f"Error uploading file to {bucket_name}/{file_key}: {e.response['Error']['Message']}"
        logger.error(error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        error_msg = f"Unexpected error during upload: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@router.get("/preview/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def preview_file(request: Request, bucket_name: str, file_key: str, prefix: str = ""):
    try:
        metadata = s3_client.head_object(Bucket=bucket_name, Key=file_key)
        file_size = metadata['ContentLength']
        content_type = metadata.get('ContentType', 'application/octet-stream')
        logger.debug(f"Previewing {bucket_name}/{file_key}: size={file_size}, content_type={content_type}")
        
        if file_size > 10 * 1024 * 1024:
            return templates.TemplateResponse("preview.html", {
                "request": request,
                "bucket_name": bucket_name,
                "file_key": file_key,
                "prefix": prefix,
                "error": "File too large for preview (max 10MB)"
            })
        
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
        
        if content_type.startswith(('image/', 'application/pdf')) or file_key.endswith(('.png', '.jpg', '.jpeg', '.gif', '.pdf')):
            url = generate_presigned_url(bucket_name, file_key, 300)
            return templates.TemplateResponse("preview.html", {
                "request": request,
                "bucket_name": bucket_name,
                "file_key": file_key,
                "prefix": prefix,
                "url": url,
                "content_type": "image" if content_type.startswith('image/') else "pdf"
            })
        
        return templates.TemplateResponse("preview.html", {
            "request": request,
            "bucket_name": bucket_name,
            "file_key": file_key,
            "prefix": prefix,
            "error": f"Preview not supported for content type: {content_type}"
        })
    except s3_client.exceptions.ClientError as e:
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

@router.get("/download/{bucket_name}/{file_key:path}")
async def download_file(bucket_name: str, file_key: str):
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
        return StreamingResponse(
            io.BytesIO(response['Body'].read()),
            media_type=response['ContentType'],
            headers={"Content-Disposition": f"attachment; filename={os.path.basename(file_key)}"}
        )
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error downloading file {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/share/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def share_file_get(request: Request, bucket_name: str, file_key: str, prefix: str = ""):
    try:
        logger.debug(f"Generating default pre-signed URL for {bucket_name}/{file_key}")
        default_expires_in = 3600
        url = generate_presigned_url(bucket_name, file_key, default_expires_in)
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
    except s3_client.exceptions.ClientError as e:
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

@router.post("/share/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
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
        
        url = generate_presigned_url(bucket_name, file_key, expires_in_int)
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
    except s3_client.exceptions.ClientError as e:
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

@router.post("/delete_file/{bucket_name}/{file_key:path}", response_class=HTMLResponse)
async def delete_file(request: Request, bucket_name: str, file_key: str):
    try:
        s3_client.delete_object(Bucket=bucket_name, Key=file_key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"File {file_key} deleted successfully"
        })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error deleting file {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/confirm_delete_folder/{bucket_name}/{folder_key:path}", response_class=HTMLResponse)
async def confirm_delete_folder(request: Request, bucket_name: str, folder_key: str, prefix: str = ""):
    contents = list_folder_contents(bucket_name, folder_key, s3_client)
    return templates.TemplateResponse("confirm_delete.html", {
        "request": request,
        "bucket_name": bucket_name,
        "folder_key": folder_key,
        "prefix": prefix,
        "contents": contents
    })

@router.post("/delete_folder/{bucket_name}/{folder_key:path}", response_class=HTMLResponse)
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
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error deleting folder {bucket_name}/{folder_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/bulk_delete/{bucket_name}", response_class=HTMLResponse)
async def bulk_delete(request: Request, bucket_name: str, keys: list[str] = Form(...)):
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
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error in bulk delete for {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/bulk_copy/{bucket_name}", response_class=HTMLResponse)
async def bulk_copy(request: Request, bucket_name: str, keys: list[str] = Form(...), destination: str = Form(...)):
    try:
        for key in keys:
            dest_key = f"{destination.rstrip('/')}/{os.path.basename(key.rstrip('/'))}"
            s3_client.copy_object(Bucket=bucket_name, CopySource={'Bucket': bucket_name, 'Key': key}, Key=dest_key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"{len(keys)} item(s) copied to {destination}"
        })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error in bulk copy for {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/bulk_move/{bucket_name}", response_class=HTMLResponse)
async def bulk_move(request: Request, bucket_name: str, keys: list[str] = Form(...), destination: str = Form(...)):
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
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error in bulk move for {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/rename/{bucket_name}/{key:path}", response_class=HTMLResponse)
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
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error renaming object {bucket_name}/{key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/copy_file/{bucket_name}", response_class=HTMLResponse)
async def copy_file(request: Request, bucket_name: str, file_key: str = Form(...), destination: str = Form(...)):
    try:
        s3_client.copy_object(Bucket=bucket_name, CopySource={'Bucket': bucket_name, 'Key': file_key}, Key=destination)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"File copied to {destination}"
        })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error copying file {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/move_file/{bucket_name}", response_class=HTMLResponse)
async def move_file(request: Request, bucket_name: str, file_key: str = Form(...), destination: str = Form(...)):
    try:
        s3_client.copy_object(Bucket=bucket_name, CopySource={'Bucket': bucket_name, 'Key': file_key}, Key=destination)
        s3_client.delete_object(Bucket=bucket_name, Key=file_key)
        return templates.TemplateResponse("success.html", {
            "request": request,
            "message": f"File moved to {destination}"
        })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error moving file {bucket_name}/{file_key}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/zip_files/{bucket_name}", response_class=FileResponse)
async def zip_files(request: Request, bucket_name: str, files: list[str] = Form(...)):
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
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error zipping files in {bucket_name}: {e}")
        raise HTTPException(status_code=400, detail=str(e))