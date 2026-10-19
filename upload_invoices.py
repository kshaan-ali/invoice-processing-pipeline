#!/usr/bin/env python3
"""
Upload invoice files to the source S3 bucket to trigger the processing Lambda.

Uploading an invoice to the source bucket fires the S3 event that invokes
lambda_function.py, which runs Textract -> Bedrock -> DynamoDB and saves the
extracted text back to S3.

Usage:
    # Upload every supported file in the ./invoices folder
    python upload_invoices.py --bucket my-source-bucket

    # Upload a specific file or files
    python upload_invoices.py --bucket my-source-bucket invoices/InvoiceOne.jpg

    # Upload from a different folder and put objects under a key prefix
    python upload_invoices.py --bucket my-source-bucket --path ./scans --prefix incoming/
"""

import argparse
import os
import sys

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# Formats Textract AnalyzeExpense supports (mirrors lambda_function.py).
SUPPORTED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif")

DEFAULT_INVOICE_DIR = "invoices"


def is_supported(filename):
    """Return True if the file has a Textract-supported extension."""
    return filename.lower().endswith(SUPPORTED_EXTENSIONS)


def collect_files(paths, folder):
    """
    Build the list of files to upload.

    If explicit paths are given, use those (validated). Otherwise scan the
    given folder for supported files.
    """
    files = []

    if paths:
        for p in paths:
            if not os.path.isfile(p):
                print(f"Skipping '{p}': not a file", file=sys.stderr)
                continue
            if not is_supported(p):
                print(f"Skipping '{p}': unsupported format "
                      f"(expected {', '.join(SUPPORTED_EXTENSIONS)})",
                      file=sys.stderr)
                continue
            files.append(p)
        return files

    if not os.path.isdir(folder):
        print(f"Folder not found: {folder}", file=sys.stderr)
        return files

    for entry in sorted(os.listdir(folder)):
        full = os.path.join(folder, entry)
        if os.path.isfile(full) and is_supported(entry):
            files.append(full)

    return files


def upload(s3, bucket, file_path, prefix):
    """Upload a single file to S3, returning True on success."""
    key = f"{prefix}{os.path.basename(file_path)}" if prefix else os.path.basename(file_path)
    try:
        s3.upload_file(file_path, bucket, key)
        print(f"Uploaded {file_path} -> s3://{bucket}/{key}")
        return True
    except ClientError as e:
        print(f"Failed to upload {file_path}: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Upload invoice files to the source S3 bucket to trigger "
        "the processing Lambda."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Specific files to upload. If omitted, all supported files in "
        "--path are uploaded.",
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="Source S3 bucket that triggers the Lambda.",
    )
    parser.add_argument(
        "--path",
        default=DEFAULT_INVOICE_DIR,
        help=f"Folder to scan when no files are listed (default: {DEFAULT_INVOICE_DIR}).",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="Optional key prefix to prepend to each uploaded object "
        "(e.g. 'incoming/').",
    )
    parser.add_argument(
        "--region",
        help="AWS region (defaults to your configured region).",
    )
    args = parser.parse_args()

    files = collect_files(args.files, args.path)
    if not files:
        print("No supported files to upload.", file=sys.stderr)
        return 1

    s3 = boto3.client("s3", region_name=args.region) if args.region else boto3.client("s3")

    print(f"Uploading {len(files)} file(s) to bucket '{args.bucket}'...\n")

    succeeded = 0
    try:
        for f in files:
            if upload(s3, args.bucket, f, args.prefix):
                succeeded += 1
    except NoCredentialsError:
        print("\nError: no AWS credentials found. Configure them with "
              "`aws configure` or environment variables.", file=sys.stderr)
        return 1

    failed = len(files) - succeeded
    print(f"\nDone. {succeeded} uploaded, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
