"""
Storage service for S3-compatible storage (Cloudflare R2).
"""

import os
import asyncio
from typing import Optional, BinaryIO, Union
from datetime import timedelta

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.config import Config

from app.observability.logging import get_logger

logger = get_logger(__name__)


class StorageService:
    """S3-compatible storage service."""
    
    def __init__(self):
        self.endpoint_url = os.getenv("S3_ENDPOINT")
        self.region = os.getenv("S3_REGION", "auto")
        self.bucket_name = os.getenv("S3_BUCKET")
        self.access_key = os.getenv("S3_ACCESS_KEY")
        self.secret_key = os.getenv("S3_SECRET_KEY")
        
        # Use local storage for development if S3 not configured
        self.use_local = not all([
            self.endpoint_url, self.bucket_name, 
            self.access_key, self.secret_key
        ])
        
        if self.use_local:
            self.local_storage_path = os.getenv("LOCAL_STORAGE_PATH", "/tmp/transcribe/storage")
            os.makedirs(self.local_storage_path, exist_ok=True)
            logger.info("Using local file storage (S3 not configured)")
        else:
            # Configure S3 client
            config = Config(
                region_name=self.region,
                retries={'max_attempts': 3},
                max_pool_connections=20
            )
            
            self.s3_client = boto3.client(
                's3',
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=config
            )
            logger.info(f"Storage service initialized (bucket: {self.bucket_name})")
    
    async def upload_file(
        self, 
        file_content: bytes, 
        key: str, 
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload file content to storage.
        Returns the storage URI.
        """
        try:
            if self.use_local:
                return await self._upload_local(file_content, key)
            else:
                return await self._upload_s3(file_content, key, content_type)
                
        except Exception as e:
            logger.error(f"File upload failed for key {key}: {e}")
            raise
    
    async def _upload_local(self, file_content: bytes, key: str) -> str:
        """Upload to local filesystem."""
        file_path = os.path.join(self.local_storage_path, key)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Use asyncio to avoid blocking
        def write_file():
            with open(file_path, 'wb') as f:
                f.write(file_content)
        
        await asyncio.get_event_loop().run_in_executor(None, write_file)
        
        # Return local file URI
        return f"file://{file_path}"
    
    async def _upload_s3(
        self, 
        file_content: bytes, 
        key: str, 
        content_type: Optional[str] = None
    ) -> str:
        """Upload to S3-compatible storage."""
        def upload():
            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type
            
            # Add metadata
            extra_args['Metadata'] = {
                'uploaded_at': str(int(asyncio.get_event_loop().time())),
                'service': 'transcribe'
            }
            
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=file_content,
                **extra_args
            )
        
        await asyncio.get_event_loop().run_in_executor(None, upload)
        
        # Return S3 URI
        return f"s3://{self.bucket_name}/{key}"
    
    async def download_file(self, uri: str) -> bytes:
        """
        Download file content from storage URI.
        """
        try:
            if uri.startswith("file://"):
                return await self._download_local(uri)
            elif uri.startswith("s3://"):
                return await self._download_s3(uri)
            else:
                raise ValueError(f"Unsupported URI scheme: {uri}")
                
        except Exception as e:
            logger.error(f"File download failed for URI {uri}: {e}")
            raise
    
    async def _download_local(self, uri: str) -> bytes:
        """Download from local filesystem."""
        file_path = uri[7:]  # Remove "file://" prefix
        
        def read_file():
            with open(file_path, 'rb') as f:
                return f.read()
        
        return await asyncio.get_event_loop().run_in_executor(None, read_file)
    
    async def _download_s3(self, uri: str) -> bytes:
        """Download from S3-compatible storage."""
        # Parse S3 URI
        uri_parts = uri[5:].split('/', 1)  # Remove "s3://" prefix
        bucket = uri_parts[0]
        key = uri_parts[1] if len(uri_parts) > 1 else ""
        
        def download():
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            return response['Body'].read()
        
        return await asyncio.get_event_loop().run_in_executor(None, download)
    
    async def get_signed_url(
        self, 
        key: str, 
        expires_in: int = 3600,
        method: str = 'get_object'
    ) -> str:
        """
        Generate signed URL for file access.
        """
        try:
            if self.use_local:
                # For local storage, return a direct file path or HTTP URL
                # In production, you'd serve these through a web server
                file_path = os.path.join(self.local_storage_path, key)
                if os.path.exists(file_path):
                    # Return as a downloadable URL (assuming a file server)
                    return f"/storage/{key}"
                else:
                    raise FileNotFoundError(f"File not found: {key}")
            else:
                return await self._get_signed_url_s3(key, expires_in, method)
                
        except Exception as e:
            logger.error(f"Signed URL generation failed for key {key}: {e}")
            raise
    
    async def _get_signed_url_s3(
        self, 
        key: str, 
        expires_in: int,
        method: str
    ) -> str:
        """Generate S3 signed URL."""
        def generate_url():
            return self.s3_client.generate_presigned_url(
                method,
                Params={'Bucket': self.bucket_name, 'Key': key},
                ExpiresIn=expires_in
            )
        
        return await asyncio.get_event_loop().run_in_executor(None, generate_url)
    
    async def delete_file(self, uri: str) -> bool:
        """
        Delete file from storage.
        """
        try:
            if uri.startswith("file://"):
                return await self._delete_local(uri)
            elif uri.startswith("s3://"):
                return await self._delete_s3(uri)
            else:
                logger.warning(f"Cannot delete unsupported URI: {uri}")
                return False
                
        except Exception as e:
            logger.error(f"File deletion failed for URI {uri}: {e}")
            return False
    
    async def _delete_local(self, uri: str) -> bool:
        """Delete from local filesystem."""
        file_path = uri[7:]  # Remove "file://" prefix
        
        def delete_file():
            if os.path.exists(file_path):
                os.remove(file_path)
                return True
            return False
        
        return await asyncio.get_event_loop().run_in_executor(None, delete_file)
    
    async def _delete_s3(self, uri: str) -> bool:
        """Delete from S3-compatible storage."""
        # Parse S3 URI
        uri_parts = uri[5:].split('/', 1)  # Remove "s3://" prefix
        bucket = uri_parts[0]
        key = uri_parts[1] if len(uri_parts) > 1 else ""
        
        def delete_object():
            self.s3_client.delete_object(Bucket=bucket, Key=key)
            return True
        
        await asyncio.get_event_loop().run_in_executor(None, delete_object)
        return True
    
    async def list_files(self, prefix: str) -> list:
        """
        List files with given prefix.
        """
        try:
            if self.use_local:
                return await self._list_local(prefix)
            else:
                return await self._list_s3(prefix)
                
        except Exception as e:
            logger.error(f"File listing failed for prefix {prefix}: {e}")
            return []
    
    async def _list_local(self, prefix: str) -> list:
        """List local files."""
        def list_files():
            full_prefix = os.path.join(self.local_storage_path, prefix)
            files = []
            
            if os.path.exists(full_prefix):
                for root, dirs, filenames in os.walk(full_prefix):
                    for filename in filenames:
                        file_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(file_path, self.local_storage_path)
                        files.append(rel_path)
            
            return files
        
        return await asyncio.get_event_loop().run_in_executor(None, list_files)
    
    async def _list_s3(self, prefix: str) -> list:
        """List S3 files."""
        def list_objects():
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            return [obj['Key'] for obj in response.get('Contents', [])]
        
        return await asyncio.get_event_loop().run_in_executor(None, list_objects)
    
    async def health_check(self) -> dict:
        """
        Check storage service health.
        """
        try:
            if self.use_local:
                # Check if local storage directory is writable
                test_file = os.path.join(self.local_storage_path, ".health_check")
                with open(test_file, 'w') as f:
                    f.write("ok")
                os.remove(test_file)
                return {"status": "healthy", "type": "local"}
            else:
                # Check S3 connectivity
                def check_s3():
                    self.s3_client.head_bucket(Bucket=self.bucket_name)
                    return {"status": "healthy", "type": "s3", "bucket": self.bucket_name}
                
                return await asyncio.get_event_loop().run_in_executor(None, check_s3)
                
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}