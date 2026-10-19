#!/usr/bin/env python3
"""
Setup script for the Textract output S3 bucket.

Creates the S3 bucket used by the invoice-processing Lambda to store the
extracted OCR text. The bucket name follows the same `textract-ml-ai-{suffix}`
pattern that lambda_function.py builds in save_text_to_s3() (Strategy 2), so the
value printed here can be dropped straight into the TEXTRACT_OUTPUT_BUCKET
environment variable (Strategy 1).

Usage:
    python setup_s3_bucket.py [--region ap-south-1] [--suffix 12345678]
                              [--bucket textract-ml-ai-12345678]

If --bucket is given, it is used as-is. Otherwise a name is generated as
`textract-ml-ai-{suffix}`, where --suffix defaults to a random 8-digit number.
"""

import argparse
import random
import sys

import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def build_bucket_name(suffix=None):
    """Return a bucket name using the textract-ml-ai-{suffix} pattern."""
    if suffix is None:
        suffix = str(random.randint(10_000_000, 99_999_999))
    return f"textract-ml-ai-{suffix}"


def resolve_region(explicit_region):
    """Determine the region to use, falling back to the default boto3 session."""
    if explicit_region:
        return explicit_region
    region = boto3.session.Session().region_name
    if not region:
        region = "ap-south-1"
        print(f"No region configured; defaulting to {region}")
    return region


def bucket_exists(s3, bucket_name):
    """Return True if the bucket already exists and is accessible."""
    try:
        s3.head_bucket(Bucket=bucket_name)
        return True
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            return False
        # 403 means it exists but is owned by someone else / no access.
        if error_code == "403":
            raise RuntimeError(
                f"Bucket '{bucket_name}' already exists but is not accessible "
                f"to your account. Choose a different --suffix or --bucket."
            ) from e
        raise


def create_bucket(s3, bucket_name, region):
    """Create the bucket, handling the us-east-1 API exception."""
    # Only us-east-1 omits LocationConstraint; all other regions, including
    # ap-south-1, require it when using a region-specific S3 endpoint.
    if region == "us-east-1":
        s3.create_bucket(Bucket=bucket_name)
    else:
        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": region},
        )


def print_next_steps(bucket_name):
    """Print the configuration instructions for wiring the bucket to Lambda."""
    print("\n" + "=" * 60)
    print("Bucket is ready. Next steps:")
    print("=" * 60)
    print("\n1. Set the Lambda environment variable:\n")
    print(f"   TEXTRACT_OUTPUT_BUCKET={bucket_name}\n")
    print("   Via AWS CLI:\n")
    print("   aws lambda update-function-configuration \\")
    print("       --function-name YOUR_LAMBDA_FUNCTION_NAME \\")
    print(f"       --environment Variables={{TEXTRACT_OUTPUT_BUCKET={bucket_name}}}\n")
    print("2. Ensure the Lambda IAM role can write to this bucket")
    print("   (s3:PutObject, s3:GetObject, s3:HeadBucket on")
    print("   arn:aws:s3:::textract-ml-ai-*).\n")


def main():
    parser = argparse.ArgumentParser(
        description="Create the Textract output S3 bucket for the invoice Lambda."
    )
    parser.add_argument(
        "--region",
        help="AWS region for the bucket (defaults to your configured region, "
        "then ap-south-1).",
    )
    parser.add_argument(
        "--suffix",
        help="Suffix for the textract-ml-ai-{suffix} bucket name "
        "(defaults to a random 8-digit number).",
    )
    parser.add_argument(
        "--bucket",
        help="Use this exact bucket name instead of generating one.",
    )
    args = parser.parse_args()

    region = resolve_region(args.region)
    bucket_name = args.bucket or build_bucket_name(args.suffix)

    print(f"Region:      {region}")
    print(f"Bucket name: {bucket_name}")

    s3 = boto3.client("s3", region_name=region)

    try:
        if bucket_exists(s3, bucket_name):
            print(f"\nBucket '{bucket_name}' already exists and is accessible. "
                  f"Nothing to create.")
            print_next_steps(bucket_name)
            return 0

        create_bucket(s3, bucket_name, region)
        print(f"\nCreated bucket: {bucket_name}")
        print_next_steps(bucket_name)
        return 0

    except NoCredentialsError:
        print("\nError: no AWS credentials found. Configure them with "
              "`aws configure` or environment variables.", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    except ClientError as e:
        print(f"\nError creating bucket: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
