#!/usr/bin/env python3
"""
Destroy the Alex Financial Advisor Part 7 infrastructure.
This script:
1. Empties the S3 bucket
2. Destroys infrastructure with Terraform
3. Cleans up local artifacts
"""

import subprocess
import sys
import os
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _cdk_app_dir() -> Path:
    return _repo_root() / "infra" / "cdk"


def use_cdk_for_part7() -> bool:
    return os.environ.get("ALEX_USE_CDK", "").strip().lower() in ("1", "true", "yes")


def run_command(cmd, cwd=None, check=True, capture_output=False):
    """Run a command and optionally capture output."""
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")

    if capture_output:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=isinstance(cmd, str))
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            return None
        return result.stdout.strip()
    else:
        result = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str))
        if check and result.returncode != 0:
            return False
        return True


def confirm_destruction():
    """Ask for confirmation before destroying resources."""
    print("⚠️  WARNING: This will destroy all Part 7 infrastructure!")
    print("This includes:")
    print("  - CloudFront distribution")
    print("  - API Gateway")
    print("  - Lambda function")
    print("  - S3 bucket and all contents")
    print("  - IAM roles and policies")
    print("")

    response = input("Are you sure you want to continue? Type 'yes' to confirm: ")
    return response.lower() == 'yes'


def get_bucket_name():
    """S3 bucket for Part 7 frontend: CDK stack Alex7Frontend output, else Terraform."""
    raw = subprocess.run(
        [
            "aws",
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            "Alex7Frontend",
            "--query",
            "Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue",
            "--output",
            "text",
        ],
        capture_output=True,
        text=True,
    )
    if raw.returncode == 0 and raw.stdout.strip():
        return raw.stdout.strip()

    terraform_dir = _repo_root() / "terraform" / "7_frontend"
    if not terraform_dir.exists():
        print(f"  ❌ Terraform directory not found: {terraform_dir}")
        return None

    bucket_output = run_command(
        ["terraform", "output", "-raw", "s3_bucket_name"],
        cwd=terraform_dir,
        capture_output=True,
    )

    return bucket_output if bucket_output else None


def empty_s3_bucket(bucket_name):
    """Empty the S3 bucket before deletion."""
    if not bucket_name:
        print("  ⚠️  No bucket name provided, skipping...")
        return

    print(f"\n🗑️  Emptying S3 bucket: {bucket_name}")

    # Check if bucket exists
    exists = run_command(
        ["aws", "s3", "ls", f"s3://{bucket_name}"],
        capture_output=True,
        check=False
    )

    if not exists:
        print(f"  Bucket {bucket_name} doesn't exist or is already empty")
        return

    # Delete all objects
    print(f"  Deleting all objects from {bucket_name}...")
    run_command([
        "aws", "s3", "rm",
        f"s3://{bucket_name}/",
        "--recursive"
    ])

    # Delete all versions (if versioning is enabled)
    print(f"  Deleting all object versions...")
    run_command([
        "aws", "s3api", "delete-objects",
        "--bucket", bucket_name,
        "--delete", "$(aws s3api list-object-versions --bucket " + bucket_name + " --output json --query='{Objects: Versions[].{Key:Key,VersionId:VersionId}}')"
    ], check=False)

    print(f"  ✅ Bucket {bucket_name} emptied")


def destroy_terraform():
    """Destroy infrastructure with Terraform."""
    print("\n🏗️  Destroying infrastructure with Terraform...")

    terraform_dir = _repo_root() / "terraform" / "7_frontend"

    if not terraform_dir.exists():
        print(f"  ❌ Terraform directory not found: {terraform_dir}")
        return False

    # Check if Terraform is initialized
    if not (terraform_dir / ".terraform").exists():
        print("  ⚠️  Terraform not initialized, nothing to destroy")
        return True

    # Destroy the infrastructure
    print("  Running terraform destroy...")
    print("  Type 'yes' when prompted to confirm destruction.")

    success = run_command(["terraform", "destroy"], cwd=terraform_dir)

    if success:
        print("  ✅ Infrastructure destroyed successfully")
    else:
        print("  ❌ Failed to destroy infrastructure")
        print("  You may need to manually clean up resources in AWS Console")

    return success


def destroy_cdk_part7():
    """Destroy CDK stack Alex7Frontend."""
    print("\n🏗️  Destroying CDK stack Alex7Frontend...")
    exists = subprocess.run(
        [
            "aws",
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            "Alex7Frontend",
        ],
        capture_output=True,
        text=True,
    )
    if exists.returncode != 0:
        print("  ⚠️  CloudFormation stack Alex7Frontend not found; nothing to destroy via CDK")
        return True

    cdk_dir = _cdk_app_dir()
    if not cdk_dir.exists():
        print(f"  ❌ CDK app not found: {cdk_dir}")
        return False
    if not (cdk_dir / "node_modules").exists():
        print("  Installing CDK dependencies (npm install)...")
        run_command(["npm", "install"], cwd=cdk_dir)
    run_command(["npm", "run", "build"], cwd=cdk_dir)
    success = run_command(
        ["npx", "cdk", "destroy", "Alex7Frontend", "--force"],
        cwd=cdk_dir,
    )
    if success:
        print("  ✅ CDK stack destroyed successfully")
    return bool(success)


def destroy_part7_infrastructure():
    if use_cdk_for_part7():
        return destroy_cdk_part7()
    return destroy_terraform()


def clean_local_artifacts():
    """Clean up local build artifacts."""
    print("\n🧹 Cleaning up local artifacts...")

    artifacts = [
        Path(__file__).parent.parent / "backend" / "api" / "api_lambda.zip",
        Path(__file__).parent.parent / "frontend" / "out",
        Path(__file__).parent.parent / "frontend" / ".next",
    ]

    for artifact in artifacts:
        if artifact.exists():
            if artifact.is_file():
                artifact.unlink()
                print(f"  Deleted: {artifact}")
            else:
                import shutil
                shutil.rmtree(artifact)
                print(f"  Deleted directory: {artifact}")

    print("  ✅ Local artifacts cleaned")


def main():
    """Main destruction function."""
    print("💥 Alex Financial Advisor - Part 7 Infrastructure Destruction")
    print("=" * 60)

    # Confirm destruction
    if not confirm_destruction():
        print("\n❌ Destruction cancelled")
        sys.exit(0)

    # Get bucket name before destroying infrastructure
    bucket_name = get_bucket_name()

    # Empty S3 bucket first (required before Terraform can delete it)
    if bucket_name:
        empty_s3_bucket(bucket_name)

    # Destroy Part 7 (Terraform or CDK)
    destroy_part7_infrastructure()

    # Clean local artifacts
    clean_local_artifacts()

    print("\n" + "=" * 60)
    print("✅ Destruction complete!")
    print("\nTo redeploy, run:")
    print("  uv run scripts/deploy.py")


if __name__ == "__main__":
    main()