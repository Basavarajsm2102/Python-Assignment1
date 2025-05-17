from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from utils.s3_utils import s3_client, get_file_metadata
from datetime import datetime
import logging

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)

@router.post("/search/{bucket_name}", response_class=HTMLResponse)
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
    objects = []
    paginator = s3_client.get_paginator('list_objects_v2')
    try:
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
            for obj in page.get('Contents', []):
                if search_query.lower() in obj['Key'].lower():
                    metadata = get_file_metadata(bucket_name, obj['Key'])
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
                            tag_response = s3_client.get_object_tagging(Bucket=bucket_name, Key=obj['Key'])
                            tags = {t['Key']: t['Value'] for t in tag_response.get('TagSet', [])}
                            if tag not in tags.values():
                                include = False
                        except s3_client.exceptions.ClientError as e:
                            logger.error(f"Error getting tags for {bucket_name}/{obj['Key']}: {e}")
                            include = False
                    if include:
                        objects.append({
                            'Key': obj['Key'],
                            'LastModified': obj['LastModified'].strftime('%Y-%m-%d %H:%M:%S'),
                            'Size': obj['Size'],
                            'Type': 'File'
                        })
    except s3_client.exceptions.ClientError as e:
        logger.error(f"Error searching objects in {bucket_name}/{prefix}: {e}")
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