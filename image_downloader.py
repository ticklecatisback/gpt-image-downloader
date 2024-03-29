from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
# Assuming you might still want to use requests for other purposes, keeping it imported
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from io import BytesIO
import os
import tempfile
import base64
import zipfile
import shutil

app = FastAPI()

SERVICE_ACCOUNT_FILE = 'YOUR_JOSN_FILE'
SCOPES = ['https://www.googleapis.com/auth/drive']
BING_API_KEY = 'BING_API_KEY'  # If you plan to use Bing Image Search API directly


def build_drive_service():
    credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=credentials)

def get_image_urls_for_query(query, limit=5):
    search_url = "https://api.bing.microsoft.com/v7.0/images/search"
    headers = {"Ocp-Apim-Subscription-Key": BING_API_KEY}
    params = {"q": query, "count": limit}
    response = requests.get(search_url, headers=headers, params=params)
    response.raise_for_status()
    search_results = response.json()
    return [img["contentUrl"] for img in search_results["value"]]

def download_image_in_memory(image_url):
    headers = {'User-Agent': 'Mozilla/5.0'}  # Including a user-agent header
    try:
        response = requests.get(image_url, headers=headers)
        response.raise_for_status()  # This will raise an exception for 4XX or 5XX responses
        return BytesIO(response.content)
    except requests.RequestException as e:
        print(f"Error downloading {image_url}: {e}")
        return None  # Return None to indicate the download failed



def upload_file_to_drive(service, file_name, file_content, mime_type='image/jpeg'):
    file_metadata = {'name': file_name}
    media = MediaIoBaseUpload(file_content, mimetype=mime_type, resumable=True)
    try:
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        # Set the file to be publicly readable
        permission = {
            'type': 'anyone',
            'role': 'reader',
        }
        service.permissions().create(fileId=file.get('id'), body=permission).execute()
        return f"https://drive.google.com/uc?id={file.get('id')}"
    except HttpError as error:
        print(f'An error occurred: {error}')
        raise HTTPException(status_code=500, detail=f"Failed to upload {file_name}: {str(error)}")


@app.post("/test-upload/")
async def test_upload():
    service = build_drive_service()
    test_image_url = "https://cat-world.com/wp-content/uploads/2017/06/spotted-tabby-1.jpg"  # Replace this with a real URL to a test image

    # Simulate downloading an image to memory
    image_content = requests.get(test_image_url).content
    temp_dir = tempfile.mkdtemp()
    zip_filename = os.path.join(temp_dir, "test-image.zip")
    
    # Create a zip file with the test image
    with zipfile.ZipFile(zip_filename, 'w') as zipf:
        image_name = "test-image.jpg"
        image_path = os.path.join(temp_dir, image_name)
        with open(image_path, 'wb') as image_file:
            image_file.write(image_content)
        zipf.write(image_path, arcname=image_name)
    
    # Upload the zip file to Google Drive
    file_metadata = {'name': 'test-image.zip'}
    media = MediaFileUpload(zip_filename, mimetype='application/zip')
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = file.get('id')

    # Set the file to be publicly readable
    permission = {
        'type': 'anyone',
        'role': 'reader',
    }
    service.permissions().create(fileId=file_id, body=permission).execute()
    drive_url = f"https://drive.google.com/uc?id={file_id}"
    
    # Clean up the temporary directory
    shutil.rmtree(temp_dir)

    return {"message": "Test image zip uploaded successfully.", "url": drive_url}


@app.get("/")
async def root():
    return HTMLResponse(content="<h1>Image Uploader to Google Drive</h1>")

@app.post("/download-images/")
async def download_images(query: str = Query(..., description="The search query for downloading images"), 
                          limit: int = Query(1, description="The number of images to download")):
    image_urls = get_image_urls_for_query(query, limit=limit)
    service = build_drive_service()
    uploaded_urls = []

    with tempfile.TemporaryDirectory() as temp_dir:
        zip_filename = os.path.join(temp_dir, "images.zip")
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            for i, image_url in enumerate(image_urls):
                file_content = download_image_in_memory(image_url)
                if not file_content:
                    continue  # Skip this image and proceed to the next
                
                image_name = f"image_{i}.jpg"
                image_path = os.path.join(temp_dir, image_name)
                with open(image_path, 'wb') as image_file:
                    image_file.write(file_content.getbuffer())  # Write the image content to a file
                
                zipf.write(image_path, arcname=image_name)  # Add the image to the zip file

        # Upload the zip file to Google Drive
        file_metadata = {'name': 'images.zip'}
        media = MediaFileUpload(zip_filename, mimetype='application/zip')
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        permission = {'type': 'anyone', 'role': 'reader'}
        service.permissions().create(fileId=file.get('id'), body=permission).execute()
        drive_url = f"https://drive.google.com/uc?id={file.get('id')}"
        
        return {"message": "Zip file uploaded successfully.", "url": drive_url}
