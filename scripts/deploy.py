#!/usr/bin/env python3
"""
Deploy the Alex Financial Advisor Part 7 infrastructure.
This script:
1. Packages the Lambda function
2. Deploys infrastructure with Terraform to get API URL
3. Builds the NextJS frontend with production API URL
4. Uploads frontend files to S3
5. Invalidates CloudFront cache

NOTE: This script uses .env.production for deployment and does NOT modify .env.local
"""

import subprocess
import sys
import os
import json
import time
import shutil
from pathlib import Path


def _npm_exe() -> str:
    """Windows CreateProcess cannot run `npm` without extension; use npm.cmd."""
    return "npm.cmd" if os.name == "nt" else "npm"


def _ensure_nodejs_on_path() -> None:
    """Windows + uv: child processes may not inherit a PATH that includes Node/npm."""
    if shutil.which(_npm_exe()):
        return
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "nodejs"),
    ]
    for p in candidates:
        if p and os.path.isfile(os.path.join(p, "npm.cmd")):
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
            return


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _cdk_app_dir() -> Path:
    return _repo_root() / "infra" / "cdk"


def run_command(cmd, cwd=None, check=True, capture_output=False, env=None):
    """Run a command and optionally capture output."""
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")

    if capture_output:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=isinstance(cmd, str), env=env)
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        return result.stdout.strip()
    else:
        result = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), env=env)
        if check and result.returncode != 0:
            sys.exit(1)
        return None


def use_cdk_for_part7() -> bool:
    return os.environ.get("ALEX_USE_CDK", "").strip().lower() in ("1", "true", "yes")


def check_prerequisites():
    """Check that all required tools are installed."""
    print("🔍 Checking prerequisites...")
    _ensure_nodejs_on_path()

    tools = {
        "docker": "Docker is required for Lambda packaging",
        _npm_exe(): "npm is required for building the frontend",
        "aws": "AWS CLI is required for S3 sync and CloudFront invalidation",
    }

    for tool, message in tools.items():
        try:
            run_command([tool, "--version"], capture_output=True)
            print(f"  ✅ {tool} is installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"  ❌ {message}")
            sys.exit(1)

    if use_cdk_for_part7():
        try:
            run_command(["npx", "cdk", "--version"], capture_output=True, cwd=_cdk_app_dir())
            print("  ✅ AWS CDK CLI available (npx cdk)")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("  ❌ ALEX_USE_CDK is set but `npx cdk` failed. Install Node/npm and run: cd infra/cdk && npm install")
            sys.exit(1)
    else:
        prefer_cdk = os.environ.get("ALEX_PREFER_CDK_OUTPUTS", "").strip().lower() in ("1", "true", "yes")
        if prefer_cdk and _describe_stack_outputs("Alex7Frontend"):
            print("  ✅ ALEX_PREFER_CDK_OUTPUTS: using existing Alex7Frontend stack; Terraform not required")
        else:
            try:
                run_command(["terraform", "--version"], capture_output=True)
                print("  ✅ terraform is installed")
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("  ❌ Terraform is required unless you set ALEX_USE_CDK=1 or ALEX_PREFER_CDK_OUTPUTS=1 with Alex7Frontend already deployed")
                sys.exit(1)

    # Check if Docker is running (optional if an API zip already exists)
    api_zip = _repo_root() / "backend" / "api" / "api_lambda.zip"
    docker_ok = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    ).returncode == 0
    if docker_ok:
        print("  ✅ Docker is running")
    elif api_zip.exists():
        print("  ⚠️  Docker is not running; will reuse existing api_lambda.zip if packaging is skipped")
    else:
        print("  ❌ Docker is not running. Please start Docker Desktop (required to build api_lambda.zip).")
        sys.exit(1)

    # Check AWS credentials
    try:
        run_command(["aws", "sts", "get-caller-identity"], capture_output=True)
        print("  ✅ AWS credentials configured")
    except subprocess.CalledProcessError:
        print("  ❌ AWS credentials not configured. Run 'aws configure'")
        sys.exit(1)


def package_lambda():
    """Package the Lambda function using Docker."""
    print("\n📦 Packaging Lambda function...")

    api_dir = _repo_root() / "backend" / "api"
    lambda_zip = api_dir / "api_lambda.zip"

    if not api_dir.exists():
        print(f"  ❌ API directory not found: {api_dir}")
        sys.exit(1)

    docker_ok = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    ).returncode == 0
    if not docker_ok:
        if lambda_zip.exists():
            print(f"  ⏭️  Skipping Docker packaging; using existing {lambda_zip}")
            size_mb = lambda_zip.stat().st_size / (1024 * 1024)
            print(f"  ✅ Lambda package present ({size_mb:.2f} MB)")
            return
        print("  ❌ Docker is not running and no api_lambda.zip found.")
        sys.exit(1)

    # Run the packaging script
    run_command(["uv", "run", "package_docker.py"], cwd=api_dir)

    # Verify the package was created
    if not lambda_zip.exists():
        print(f"  ❌ Lambda package not created: {lambda_zip}")
        sys.exit(1)

    size_mb = lambda_zip.stat().st_size / (1024 * 1024)
    print(f"  ✅ Lambda package created: {lambda_zip} ({size_mb:.2f} MB)")


def _load_repo_dotenv() -> dict[str, str]:
    """Parse repo root .env (KEY=value) for merging into frontend production env."""
    path = _repo_root() / ".env"
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        key = k.strip()
        val = v.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def build_frontend(api_url=None):
    """Build the NextJS frontend."""
    print("\n🎨 Building frontend...")

    frontend_dir = _repo_root() / "frontend"

    if not frontend_dir.exists():
        print(f"  ❌ Frontend directory not found: {frontend_dir}")
        sys.exit(1)

    # Install dependencies if needed
    node_modules = frontend_dir / "node_modules"
    if not node_modules.exists():
        print("  Installing dependencies...")
        run_command([_npm_exe(), "install"], cwd=frontend_dir)

    # If API URL is provided, create .env.production.local to override .env.local
    if api_url:
        print(f"  Creating .env.production.local with API URL: {api_url}")
        env_prod_local = frontend_dir / ".env.production.local"

        # Copy from .env.production as base
        env_prod = frontend_dir / ".env.production"
        if env_prod.exists():
            with open(env_prod, "r") as f:
                lines = f.readlines()
        else:
            # Fallback to .env.local if .env.production doesn't exist
            env_local = frontend_dir / ".env.local"
            if env_local.exists():
                with open(env_local, "r") as f:
                    lines = f.readlines()
            else:
                lines = []

        # Update the API URL
        api_line_found = False
        for i, line in enumerate(lines):
            if line.startswith("NEXT_PUBLIC_API_URL="):
                lines[i] = f"NEXT_PUBLIC_API_URL={api_url}\n"
                api_line_found = True
                break

        if not api_line_found:
            lines.append(f"\nNEXT_PUBLIC_API_URL={api_url}\n")

        # Merge NEXT_PUBLIC_* from repo .env — Next prerender needs Clerk publishable key, etc.
        repo_env = _load_repo_dotenv()
        present = {ln.split("=", 1)[0].strip() for ln in lines if "=" in ln and not ln.strip().startswith("#")}
        for key, val in repo_env.items():
            if not key.startswith("NEXT_PUBLIC_"):
                continue
            if key in present:
                continue
            lines.append(f"{key}={val}\n")
            present.add(key)

        # Write to .env.production.local (highest priority for production builds)
        with open(env_prod_local, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print("  ✅ Created .env.production.local with API URL")

    # Build the frontend - NextJS will automatically use .env.production for production builds
    print("  Building NextJS app for production...")
    # Set NODE_ENV to production to ensure .env.production is used
    build_env = os.environ.copy()
    build_env["NODE_ENV"] = "production"
    run_command([_npm_exe(), "run", "build"], cwd=frontend_dir, env=build_env)

    # Verify the build
    out_dir = frontend_dir / "out"
    if not out_dir.exists():
        print(f"  ❌ Build output not found: {out_dir}")
        print("  Make sure next.config.ts has output: 'export'")
        sys.exit(1)

    print(f"  ✅ Frontend built successfully")


def _describe_stack_outputs(stack_name: str) -> dict | None:
    raw = subprocess.run(
        [
            "aws",
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            stack_name,
            "--query",
            "Stacks[0].Outputs",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if raw.returncode != 0 or not raw.stdout.strip():
        return None
    try:
        rows = json.loads(raw.stdout)
    except json.JSONDecodeError:
        return None
    out: dict[str, dict] = {}
    for row in rows:
        k = row.get("OutputKey")
        v = row.get("OutputValue")
        if k and v is not None:
            out[k] = {"value": v}
    return out


def deploy_terraform():
    """Deploy infrastructure with Terraform."""
    print("\n🏗️  Deploying infrastructure with Terraform...")

    terraform_dir = _repo_root() / "terraform" / "7_frontend"

    if not terraform_dir.exists():
        print(f"  ❌ Terraform directory not found: {terraform_dir}")
        sys.exit(1)

    # Initialize Terraform if needed
    if not (terraform_dir / ".terraform").exists():
        print("  Initializing Terraform...")
        run_command(["terraform", "init"], cwd=terraform_dir)

    # Plan the deployment
    print("  Planning deployment...")
    run_command(["terraform", "plan"], cwd=terraform_dir)

    # Apply the deployment
    print("\n  Applying deployment...")
    print("  Creating AWS resources...")
    run_command(["terraform", "apply", "-auto-approve"], cwd=terraform_dir)

    # Get outputs
    print("\n  Getting outputs...")
    outputs = run_command(
        ["terraform", "output", "-json"],
        cwd=terraform_dir,
        capture_output=True
    )

    return json.loads(outputs)


def deploy_cdk_part7():
    """Deploy Part 7 via AWS CDK (infra/cdk), stack Alex7Frontend."""
    print("\n🏗️  Deploying Part 7 with AWS CDK (Alex7Frontend)...")
    cdk_dir = _cdk_app_dir()
    if not cdk_dir.exists():
        print(f"  ❌ CDK app not found: {cdk_dir}")
        sys.exit(1)

    if not (cdk_dir / "node_modules").exists():
        print("  Installing CDK dependencies (npm install)...")
        run_command([_npm_exe(), "install"], cwd=cdk_dir)

    print("  Compiling TypeScript (npm run build)...")
    run_command([_npm_exe(), "run", "build"], cwd=cdk_dir)

    print("  Running cdk deploy Alex7Frontend...")
    run_command(
        [
            "npx",
            "cdk",
            "deploy",
            "Alex7Frontend",
            "--require-approval",
            "never",
        ],
        cwd=cdk_dir,
    )

    print("\n  Reading CloudFormation stack outputs...")
    parsed = _describe_stack_outputs("Alex7Frontend")
    if not parsed:
        print("  ❌ Could not read outputs for stack Alex7Frontend")
        sys.exit(1)

    return {
        "api_gateway_url": parsed.get("ApiGatewayUrl", {"value": ""}),
        "cloudfront_url": parsed.get("CloudFrontUrl", {"value": ""}),
        "s3_bucket_name": parsed.get("S3BucketName", {"value": ""}),
        "lambda_function_name": parsed.get("LambdaFunctionName", {"value": ""}),
    }


def deploy_part7_infrastructure():
    """Terraform (default) or CDK when ALEX_USE_CDK=1."""
    if use_cdk_for_part7():
        return deploy_cdk_part7()
    existing = _describe_stack_outputs("Alex7Frontend")
    if existing and os.environ.get("ALEX_PREFER_CDK_OUTPUTS", "").strip().lower() in ("1", "true", "yes"):
        print("\n🏗️  Using existing CDK stack Alex7Frontend outputs (ALEX_PREFER_CDK_OUTPUTS=1)...")
        return {
            "api_gateway_url": existing.get("ApiGatewayUrl", {"value": ""}),
            "cloudfront_url": existing.get("CloudFrontUrl", {"value": ""}),
            "s3_bucket_name": existing.get("S3BucketName", {"value": ""}),
            "lambda_function_name": existing.get("LambdaFunctionName", {"value": ""}),
        }
    return deploy_terraform()


def upload_frontend(bucket_name, cloudfront_id):
    """Upload frontend files to S3."""
    print(f"\n📤 Uploading frontend to S3 bucket: {bucket_name}")

    frontend_dir = _repo_root() / "frontend" / "out"

    if not frontend_dir.exists():
        print(f"  ❌ Frontend build not found: {frontend_dir}")
        sys.exit(1)

    # First, clear the bucket
    print("  Clearing S3 bucket...")
    run_command([
        "aws", "s3", "rm",
        f"s3://{bucket_name}/",
        "--recursive"
    ])

    # Upload HTML files with correct content type and no-cache
    print("  Uploading HTML files...")
    run_command([
        "aws", "s3", "cp",
        str(frontend_dir) + "/",
        f"s3://{bucket_name}/",
        "--recursive",
        "--exclude", "*",
        "--include", "*.html",
        "--content-type", "text/html",
        "--cache-control", "max-age=0,no-cache,no-store,must-revalidate"
    ])

    # Upload CSS files
    print("  Uploading CSS files...")
    run_command([
        "aws", "s3", "cp",
        str(frontend_dir) + "/",
        f"s3://{bucket_name}/",
        "--recursive",
        "--exclude", "*",
        "--include", "*.css",
        "--content-type", "text/css",
        "--cache-control", "max-age=31536000,public"
    ])

    # Upload JS files
    print("  Uploading JavaScript files...")
    run_command([
        "aws", "s3", "cp",
        str(frontend_dir) + "/",
        f"s3://{bucket_name}/",
        "--recursive",
        "--exclude", "*",
        "--include", "*.js",
        "--content-type", "application/javascript",
        "--cache-control", "max-age=31536000,public"
    ])

    # Upload JSON files
    print("  Uploading JSON files...")
    run_command([
        "aws", "s3", "cp",
        str(frontend_dir) + "/",
        f"s3://{bucket_name}/",
        "--recursive",
        "--exclude", "*",
        "--include", "*.json",
        "--content-type", "application/json",
        "--cache-control", "max-age=31536000,public"
    ])

    # Upload images
    for ext, content_type in [
        ("*.png", "image/png"),
        ("*.jpg", "image/jpeg"),
        ("*.jpeg", "image/jpeg"),
        ("*.gif", "image/gif"),
        ("*.svg", "image/svg+xml"),
        ("*.ico", "image/x-icon")
    ]:
        run_command([
            "aws", "s3", "cp",
            str(frontend_dir) + "/",
            f"s3://{bucket_name}/",
            "--recursive",
            "--exclude", "*",
            "--include", ext,
            "--content-type", content_type,
            "--cache-control", "max-age=31536000,public"
        ])

    # Upload any remaining files with generic content type
    print("  Uploading remaining files...")
    run_command([
        "aws", "s3", "sync",
        str(frontend_dir) + "/",
        f"s3://{bucket_name}/",
        "--cache-control", "max-age=31536000,public"
    ])

    print(f"  ✅ Frontend uploaded successfully")

    # Invalidate CloudFront cache
    print(f"\n🔄 Invalidating CloudFront cache...")
    result = run_command([
        "aws", "cloudfront", "create-invalidation",
        "--distribution-id", cloudfront_id,
        "--paths", "/*"
    ], capture_output=True)

    print(f"  ✅ CloudFront invalidation created")


def run_aurora_schema_migrations():
    """Create users/accounts/jobs tables on Aurora if missing (RDS Data API)."""
    print("\n🗄️  Applying Aurora schema (backend/database/run_migrations.py)...")
    db_dir = _repo_root() / "backend" / "database"
    parsed = _describe_stack_outputs("Alex5Database")
    child_env = os.environ.copy()
    if parsed:
        arn = (parsed.get("AuroraClusterArn") or {}).get("value") or ""
        sec = (parsed.get("AuroraSecretArn") or {}).get("value") or ""
        if arn:
            child_env["AURORA_CLUSTER_ARN"] = arn
        if sec:
            child_env["AURORA_SECRET_ARN"] = sec
    result = subprocess.run(
        ["uv", "run", "python", "run_migrations.py"],
        cwd=str(db_dir),
        env=child_env,
    )
    if result.returncode != 0:
        print("  ❌ Aurora migrations failed. Fix errors above, then re-run deploy.")
        sys.exit(1)
    print("  ✅ Aurora schema is up to date")


def display_deployment_info(outputs):
    """Display deployment information without modifying local env files."""
    print("\n📝 Deployment Information")

    # Extract values from outputs
    api_url = outputs["api_gateway_url"]["value"]
    cloudfront_url = outputs["cloudfront_url"]["value"]

    print(f"\n  ✅ Deployment successful!")
    print(f"\n  CloudFront URL: {cloudfront_url}")
    print(f"  API Gateway URL: {api_url}")
    print(f"\n  Note: Your local .env.local file remains unchanged.")
    print(f"  The production build uses .env.production with the AWS API URL.")


def main():
    """Main deployment function."""
    print("🚀 Alex Financial Advisor - Part 7 Deployment")
    print("=" * 50)

    # Check prerequisites
    check_prerequisites()

    # Package Lambda
    package_lambda()

    # Deploy infrastructure first to get the API URL
    outputs = deploy_part7_infrastructure()

    run_aurora_schema_migrations()

    # Prefer CloudFront as the browser API base so /api/* matches the static site origin.
    cf = (outputs.get("cloudfront_url") or {}).get("value") or ""
    gw = (outputs.get("api_gateway_url") or {}).get("value") or ""
    api_url = cf.strip() if cf.strip() else gw

    # Build frontend with the production API URL
    build_frontend(api_url)

    # Extract CloudFront distribution ID
    cloudfront_url = outputs["cloudfront_url"]["value"]
    # Extract distribution ID from CloudFront URL
    dist_id_output = run_command([
        "aws", "cloudfront", "list-distributions",
        "--query", f"DistributionList.Items[?DomainName=='{cloudfront_url.replace('https://', '')}'].Id",
        "--output", "text"
    ], capture_output=True)

    if not dist_id_output:
        print("  ⚠️  Could not find CloudFront distribution ID")
        print("  You'll need to manually invalidate the cache")
        cloudfront_id = None
    else:
        cloudfront_id = dist_id_output

    # Upload frontend
    bucket_name = outputs["s3_bucket_name"]["value"]
    if cloudfront_id:
        upload_frontend(bucket_name, cloudfront_id)
    else:
        print("\n📤 Uploading frontend to S3...")
        run_command([
            "aws", "s3", "sync",
            str(_repo_root() / "frontend" / "out") + "/",
            f"s3://{bucket_name}/",
            "--delete"
        ])

    # Display deployment info (no longer modifies .env.local)
    display_deployment_info(outputs)

    print("\n" + "=" * 50)
    print("✅ Deployment complete!")
    print(f"\n🌐 Your application is available at:")
    print(f"   {outputs['cloudfront_url']['value']}")
    print(f"\n📊 Monitor your Lambda function at:")
    print(f"   AWS Console > Lambda > {outputs['lambda_function_name']['value']}")
    print("\n⏳ Note: CloudFront distribution may take 5-10 minutes to fully propagate")


if __name__ == "__main__":
    main()