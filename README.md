# Cloud File Navigator Pro

Cloud File Navigator Pro is a web-based file management application for AWS S3, built with Python, FastAPI, and Tailwind CSS. It provides a user-friendly interface to manage S3 buckets and files without relying on JavaScript, ensuring accessibility and simplicity. The application supports advanced features like bulk operations, file tagging, temporary file sharing, and a bucket usage dashboard, making it ideal for both individual and enterprise users.

## Features

- **Bucket Management**: Create, list, and delete S3 buckets.
- **File and Folder Operations**: Upload, download, delete, rename, copy, and move files/folders.
- **Bulk Operations**: Copy, move, or delete multiple files/folders at once.
- **Advanced Search**: Filter files by name, size, date, content type, and custom tags.
- **File Sharing**: Generate temporary, pre-signed URLs for secure file sharing.
- **Bucket Usage Dashboard**: View bucket statistics (size, file/folder count, last modified) with a CSS-based bar chart.
- **File Tagging**: Add and filter files by custom tags for better organization.
- **Preview Files**: Inline preview for images, text, and PDFs.
- **Breadcrumbs Navigation**: Navigate folder hierarchies easily.

## Prerequisites

- Python 3.12+
- AWS account with S3 access
- AWS CLI configured with credentials (`aws configure`)

## Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-username/cloud-file-navigator-pro.git
   cd cloud-file-navigator-pro
   ```

2. **Create a Virtual Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure AWS Credentials**:
   Ensure AWS credentials are set up:
   ```bash
   aws configure
   ```
   Required IAM permissions:
   ```json
   {
       "Effect": "Allow",
       "Action": [
           "s3:GetObject",
           "s3:PutObject",
           "s3:DeleteObject",
           "s3:ListBucket",
           "s3:PutObjectTagging",
           "s3:GetObjectTagging"
       ],
       "Resource": ["arn:aws:s3:::*"]
   }
   ```

5. **Project Structure**:
   ```
   cloud-file-navigator-pro/
   ├── main.py
   ├── templates/
   │   ├── index.html
   │   ├── bucket.html
   │   ├── preview.html
   │   ├── metadata.html
   │   ├── search.html
   │   ├── success.html
   │   ├── confirm_delete.html
   │   ├── uploading.html
   │   ├── share.html
   │   ├── dashboard.html
   ├── static/
   └── README.md
   ```

## Running the Application

1. **Start the Server**:
   ```bash
   uvicorn main:app --reload
   ```
   The application will be available at `http://localhost:8000`.

2. **Access the Application**:
   Open your browser and navigate to `http://localhost:8000`. The homepage will display your S3 buckets.

## Usage

- **Homepage**: Create new buckets or view existing ones. Click “View Dashboard” for bucket statistics.
- **Bucket View**: Manage files/folders, upload files, create folders, or search with filters (name, size, date, tags).
- **File Actions**: Preview, download, share (generate temporary URLs), view metadata, or add tags.
- **Bulk Operations**: Select multiple items for deletion, copying, or moving using the destination path input.
- **Dashboard**: View bucket sizes, file/folder counts, and last modified dates with a visual bar chart.

## Testing

1. **Create a Bucket**:
   - On the homepage, enter a unique bucket name (e.g., `test-bucket-123`) and create it.
2. **Upload a File**:
   - Navigate to the bucket, upload a file (e.g., `image.jpg`), and verify it appears.
3. **Share a File**:
   - Click “Share” next to a file, select an expiration time, and test the generated URL.
4. **Add Tags**:
   - View a file’s metadata, add a tag (e.g., `projectX`), and search using the tag filter.
5. **View Dashboard**:
   - From the homepage, check the dashboard for bucket stats and the size comparison chart.

## Contributing

Contributions are welcome! Please submit a pull request or open an issue to discuss improvements.

## License

[MIT License](LICENSE)

## Contact

For support or feature requests, contact [basavarajsm2102@gmail.com] or open an issue on GitHub.
