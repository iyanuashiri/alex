#!/usr/bin/env python3
"""
Run schema DDL against Aurora via RDS Data API (same path as the API Lambda).
"""

import os
import subprocess
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from dotenv import load_dotenv

load_dotenv(override=True)

region = os.environ.get("DEFAULT_AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))


def _inject_credentials_from_aws_cli_login() -> None:
    """Boto3 may not see `aws login` sessions; mirror the CLI session into the process env."""
    try:
        boto3.client("sts", region_name=region).get_caller_identity()
        return
    except NoCredentialsError:
        pass
    except BotoCoreError:
        return
    proc = subprocess.run(
        ["aws", "configure", "export-credentials", "--format", "env-no-export"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        if msg:
            print(f"aws configure export-credentials failed: {msg[:300]}")
        return
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key.startswith("AWS_") and val:
            os.environ[key] = val


_inject_credentials_from_aws_cli_login()
database = (os.environ.get("AURORA_DATABASE") or "alex").strip()
cluster_arn = (os.environ.get("AURORA_CLUSTER_ARN") or "").strip()
secret_arn = (os.environ.get("AURORA_SECRET_ARN") or "").strip()

if not cluster_arn or not secret_arn:
    try:
        ssm = boto3.client("ssm", region_name=region)
        if not cluster_arn:
            cluster_arn = ssm.get_parameter(Name="/alex/database/cluster-arn")["Parameter"]["Value"]
        if not secret_arn:
            secret_arn = ssm.get_parameter(Name="/alex/database/secret-arn")["Parameter"]["Value"]
        if not os.environ.get("AURORA_DATABASE"):
            try:
                database = ssm.get_parameter(Name="/alex/database/database-name")["Parameter"]["Value"]
            except ClientError:
                pass
    except (ClientError, BotoCoreError) as e:
        print(
            "Missing AURORA_CLUSTER_ARN / AURORA_SECRET_ARN and could not read SSM "
            "(/alex/database/*). Deploy Alex5Database or set these in .env.\n"
            f"Details: {e}"
        )
        sys.exit(1)

if not cluster_arn or not secret_arn:
    print("Missing AURORA_CLUSTER_ARN or AURORA_SECRET_ARN.")
    sys.exit(1)

try:
    boto3.client("sts", region_name=region).get_caller_identity()
except BotoCoreError as e:
    print(f"No valid AWS credentials ({e}). Run aws login / aws sso login, then retry.")
    sys.exit(1)

client = boto3.client("rds-data", region_name=region)

# gen_random_uuid() is built-in on PostgreSQL 13+ (no uuid-ossp extension).
statements = [
    """CREATE TABLE IF NOT EXISTS users (
        clerk_user_id VARCHAR(255) PRIMARY KEY,
        display_name VARCHAR(255),
        years_until_retirement INTEGER,
        target_retirement_income DECIMAL(12,2),
        asset_class_targets JSONB DEFAULT '{"equity": 70, "fixed_income": 30}',
        region_targets JSONB DEFAULT '{"north_america": 50, "international": 50}',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS instruments (
        symbol VARCHAR(20) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        instrument_type VARCHAR(50),
        current_price DECIMAL(12,4),
        allocation_regions JSONB DEFAULT '{}',
        allocation_sectors JSONB DEFAULT '{}',
        allocation_asset_class JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS accounts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        clerk_user_id VARCHAR(255) REFERENCES users(clerk_user_id) ON DELETE CASCADE,
        account_name VARCHAR(255) NOT NULL,
        account_purpose TEXT,
        cash_balance DECIMAL(12,2) DEFAULT 0,
        cash_interest DECIMAL(5,4) DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS positions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        account_id UUID REFERENCES accounts(id) ON DELETE CASCADE,
        symbol VARCHAR(20) REFERENCES instruments(symbol),
        quantity DECIMAL(20,8) NOT NULL,
        as_of_date DATE DEFAULT CURRENT_DATE,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(account_id, symbol)
    )""",
    """CREATE TABLE IF NOT EXISTS jobs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        clerk_user_id VARCHAR(255) REFERENCES users(clerk_user_id) ON DELETE CASCADE,
        job_type VARCHAR(50) NOT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        request_payload JSONB,
        report_payload JSONB,
        charts_payload JSONB,
        retirement_payload JSONB,
        summary_payload JSONB,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        updated_at TIMESTAMP DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(clerk_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(clerk_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
    """CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column()""",
    """CREATE TRIGGER update_instruments_updated_at BEFORE UPDATE ON instruments
        FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column()""",
    """CREATE TRIGGER update_accounts_updated_at BEFORE UPDATE ON accounts
        FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column()""",
    """CREATE TRIGGER update_positions_updated_at BEFORE UPDATE ON positions
        FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column()""",
    """CREATE TRIGGER update_jobs_updated_at BEFORE UPDATE ON jobs
        FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column()""",
]

print("🚀 Running database migrations...")
print("=" * 50)

success_count = 0
error_count = 0

for i, stmt in enumerate(statements, 1):
    stmt_type = "statement"
    if "CREATE TABLE" in stmt.upper():
        stmt_type = "table"
    elif "CREATE INDEX" in stmt.upper():
        stmt_type = "index"
    elif "CREATE TRIGGER" in stmt.upper():
        stmt_type = "trigger"
    elif "CREATE FUNCTION" in stmt.upper() or "CREATE OR REPLACE FUNCTION" in stmt.upper():
        stmt_type = "function"

    first_line = next(l for l in stmt.split("\n") if l.strip())[:60]
    print(f"\n[{i}/{len(statements)}] Creating {stmt_type}...")
    print(f"    {first_line}...")

    try:
        client.execute_statement(
            resourceArn=cluster_arn, secretArn=secret_arn, database=database, sql=stmt
        )
        print("    ✅ Success")
        success_count += 1

    except ClientError as e:
        error_msg = e.response["Error"]["Message"]
        if "already exists" in error_msg.lower():
            print("    ⚠️  Already exists (skipping)")
            success_count += 1
        else:
            print(f"    ❌ Error: {error_msg[:200]}")
            error_count += 1
    except BotoCoreError as e:
        print(f"    ❌ AWS error: {e}")
        error_count += 1

print("\n" + "=" * 50)
print(f"Migration complete: {success_count} successful, {error_count} errors")

if error_count == 0:
    print("\n✅ All migrations completed successfully!")
else:
    print("\n⚠️  Some statements failed. Check errors above.")
    sys.exit(1)
