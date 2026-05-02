#!/usr/bin/env python3
"""
Deploy researcher service to AWS App Runner
Cross-platform deployment script for Mac/Windows/Linux
"""

import subprocess
import sys
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

# Allow OPENROUTER_API_KEY to populate OPENAI_* for App Runner update payload
_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))
from env_bootstrap import apply_openrouter_openai_aliases

apply_openrouter_openai_aliases()


def run_command(cmd, capture_output=False, shell=False):
    """Run a command and handle errors."""
    try:
        result = subprocess.run(
            cmd, shell=shell, capture_output=capture_output, text=True, check=True
        )
        if capture_output:
            return result.stdout.strip()
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        if e.stderr:
            print(f"Error details: {e.stderr}")
        sys.exit(1)


def main():
    print("Alex Researcher Service - Docker Deployment")
    print("===========================================")

    # Get AWS account ID
    print("\nGetting AWS account details...")
    account_id = run_command(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        capture_output=True,
    )

    region = os.environ.get("DEFAULT_AWS_REGION")
    if not region:
        print("Error: DEFAULT_AWS_REGION not found in your .env file.")
        sys.exit(1)

    ecr_repository = "alex-researcher"

    print(f"AWS Account: {account_id}")
    print(f"Region: {region}")

    # Resolve ECR repository URL (Terraform/CDK or live ECR)
    print("\nGetting ECR repository URL...")
    terraform_dir = Path(__file__).parent.parent.parent / "terraform" / "4_researcher"
    ecr_url = None
    if (terraform_dir / ".terraform").exists():
        original_dir = os.getcwd()
        try:
            os.chdir(terraform_dir)
            tf_result = subprocess.run(
                ["terraform", "output", "-raw", "ecr_repository_url"],
                capture_output=True,
                text=True,
            )
            if tf_result.returncode == 0:
                ecr_url = tf_result.stdout.strip() or None
        finally:
            os.chdir(original_dir)
    if not ecr_url:
        aws_ecr = subprocess.run(
            [
                "aws",
                "ecr",
                "describe-repositories",
                "--repository-names",
                ecr_repository,
                "--region",
                region,
                "--query",
                "repositories[0].repositoryUri",
                "--output",
                "text",
            ],
            capture_output=True,
            text=True,
        )
        if aws_ecr.returncode == 0:
            ecr_url = aws_ecr.stdout.strip() or None
    if not ecr_url:
        print(
            "Error: ECR repository not found. Deploy Part 4 (terraform/4_researcher or CDK) or create "
            f"repository '{ecr_repository}' in {region}."
        )
        sys.exit(1)

    print(f"ECR Repository: {ecr_url}")

    # Login to ECR
    print("\nLogging in to ECR...")
    password = run_command(
        ["aws", "ecr", "get-login-password", "--region", region], capture_output=True
    )

    login_cmd = ["docker", "login", "--username", "AWS", "--password-stdin", ecr_url]
    login_process = subprocess.Popen(
        login_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    stdout, stderr = login_process.communicate(input=password)

    if login_process.returncode != 0:
        print(f"Error logging into ECR: {stderr}")
        sys.exit(1)

    print("Login successful!")

    # Generate a unique tag using timestamp
    import time

    timestamp = int(time.time())
    image_tag = f"deploy-{timestamp}"

    # Build Docker image (context = backend/ so env_bootstrap.py is included)
    backend_dir = Path(__file__).resolve().parent.parent
    researcher_dockerfile = Path(__file__).resolve().parent / "Dockerfile"
    print(f"\nBuilding Docker image for linux/amd64 with tag: {image_tag}")
    print("(This ensures compatibility with AWS App Runner)")
    run_command(
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "-f",
            str(researcher_dockerfile),
            "-t",
            f"{ecr_repository}:{image_tag}",
            ".",
        ],
        cwd=str(backend_dir),
    )

    # Tag for ECR with both unique tag and latest
    print("\nTagging image for ECR...")
    run_command(["docker", "tag", f"{ecr_repository}:{image_tag}", f"{ecr_url}:{image_tag}"])
    run_command(["docker", "tag", f"{ecr_repository}:{image_tag}", f"{ecr_url}:latest"])

    # Push to ECR
    print("\nPushing image to ECR...")
    run_command(["docker", "push", f"{ecr_url}:{image_tag}"])
    run_command(["docker", "push", f"{ecr_url}:latest"])

    print("\n✅ Docker image pushed successfully!")
    print(
        "\nNext step: Deploy Part 4 (e.g. terraform apply in terraform/4_researcher or your CDK stack) to create the App Runner service."
    )

    # Get App Runner service ARN
    print("\nGetting App Runner service details...")
    try:
        services = run_command(
            [
                "aws",
                "apprunner",
                "list-services",
                "--region",
                region,
                "--query",
                "ServiceSummaryList[?ServiceName=='alex-researcher'].ServiceArn",
                "--output",
                "json",
            ],
            capture_output=True,
        )

        if services:
            service_arns = json.loads(services)
            if service_arns:
                service_arn = service_arns[0]
                print(f"Found service: {service_arn}")

                # Get the current service configuration to preserve the access role
                print("\nGetting current service configuration...")
                service_details = run_command(
                    [
                        "aws",
                        "apprunner",
                        "describe-service",
                        "--service-arn",
                        service_arn,
                        "--region",
                        region,
                        "--query",
                        "Service.SourceConfiguration.AuthenticationConfiguration.AccessRoleArn",
                        "--output",
                        "text",
                    ],
                    capture_output=True,
                )

                # Update the service to use the new image with unique tag
                print(f"\nUpdating service to use new image: {ecr_url}:{image_tag}")
                run_command(
                    [
                        "aws",
                        "apprunner",
                        "update-service",
                        "--service-arn",
                        service_arn,
                        "--region",
                        region,
                        "--source-configuration",
                        json.dumps(
                            {
                                "ImageRepository": {
                                    "ImageIdentifier": f"{ecr_url}:{image_tag}",
                                    "ImageConfiguration": {
                                        "Port": "8000",
                                        "RuntimeEnvironmentVariables": {
                                            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
                                            "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL", ""),
                                            "OPENROUTER_API_KEY": os.environ.get(
                                                "OPENROUTER_API_KEY", ""
                                            ),
                                            "ALEX_API_KEY": os.environ.get("ALEX_API_KEY", ""),
                                            "ALEX_API_ENDPOINT": os.environ.get(
                                                "ALEX_API_ENDPOINT", ""
                                            ),
                                        },
                                    },
                                    "ImageRepositoryType": "ECR",
                                },
                                "AuthenticationConfiguration": {"AccessRoleArn": service_details},
                                "AutoDeploymentsEnabled": False,
                            }
                        ),
                    ],
                    capture_output=True,
                )
                print("✅ Service updated with new image!")

                # Wait for deployment to complete
                print("\nWaiting for deployment to complete (this may take 5-10 minutes)...")
                import time

                max_attempts = 120  # 10 minutes with 5-second intervals
                attempts = 0

                while attempts < max_attempts:
                    status = run_command(
                        [
                            "aws",
                            "apprunner",
                            "describe-service",
                            "--service-arn",
                            service_arn,
                            "--region",
                            region,
                            "--query",
                            "Service.Status",
                            "--output",
                            "text",
                        ],
                        capture_output=True,
                    )

                    # Strip any whitespace that might be causing comparison issues
                    status = status.strip()

                    if status == "RUNNING":
                        print("\n✅ Deployment complete! Service is running.")

                        # Get and display the service URL
                        service_url = run_command(
                            [
                                "aws",
                                "apprunner",
                                "describe-service",
                                "--service-arn",
                                service_arn,
                                "--region",
                                region,
                                "--query",
                                "Service.ServiceUrl",
                                "--output",
                                "text",
                            ],
                            capture_output=True,
                        )

                        print(f"\n🚀 Your service is available at:")
                        print(f"   https://{service_url}")
                        print(f"\nTest it with:")
                        print(f"   curl https://{service_url}/health")
                        break
                    elif status == "OPERATION_IN_PROGRESS":
                        # Check operation status for more details
                        operation_status = run_command(
                            [
                                "aws",
                                "apprunner",
                                "list-operations",
                                "--service-arn",
                                service_arn,
                                "--region",
                                region,
                                "--query",
                                "OperationSummaryList[0].Status",
                                "--output",
                                "text",
                            ],
                            capture_output=True,
                        ).strip()

                        if operation_status == "SUCCEEDED":
                            # Operation completed but service status might not be updated yet
                            print("\n⏳ Operation succeeded, checking service status...")
                            time.sleep(2)
                            continue
                        elif operation_status == "FAILED":
                            print(f"\n❌ Deployment failed!")
                            print("Check the AWS Console for error details.")
                            break
                        else:
                            print(".", end="", flush=True)
                            # Show progress every 30 seconds
                            if attempts > 0 and attempts % 6 == 0:
                                elapsed_minutes = (attempts * 5) / 60
                                print(
                                    f" ({elapsed_minutes:.1f} minutes elapsed)", end="", flush=True
                                )
                            time.sleep(5)
                            attempts += 1
                    else:
                        print(f"\n⚠️ Unexpected status: {status}")
                        print("Check the AWS Console for more details.")
                        break
                else:
                    print("\n⚠️ Deployment is taking longer than expected.")
                    print("Check the status in the AWS Console.")
            else:
                print(
                    "\nApp Runner service not found. Deploy Part 4 (terraform/4_researcher or CDK) first."
                )
                print("\nTo manually deploy:")
                print("  1. Go to AWS Console > App Runner")
                print("  2. Select 'alex-researcher' service")
                print("  3. Click 'Deploy' to pull the latest image")
    except Exception as e:
        print(f"\nCouldn't automatically start deployment: {e}")
        print("\nTo manually deploy:")
        print("  1. Go to AWS Console > App Runner")
        print("  2. Select 'alex-researcher' service")
        print("  3. Click 'Deploy' to pull the latest image")


if __name__ == "__main__":
    main()
