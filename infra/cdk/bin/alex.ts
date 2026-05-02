#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { AgentsStack } from "../lib/stacks/agents-stack";
import { DatabaseStack } from "../lib/stacks/database-stack";
import { EnterpriseStack } from "../lib/stacks/enterprise-stack";
import { FrontendStack } from "../lib/stacks/frontend-stack";
import { PlaceholderStack } from "../lib/stacks/placeholder-stack";
import { SageMakerStack } from "../lib/stacks/sagemaker-stack";

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? "us-east-1",
};

new SageMakerStack(app, "Alex2Sagemaker", { env, stackName: "Alex2Sagemaker" });

new PlaceholderStack(app, "Alex3Ingestion", { env, stackName: "Alex3Ingestion" });
new PlaceholderStack(app, "Alex4Researcher", { env, stackName: "Alex4Researcher" });

const database = new DatabaseStack(app, "Alex5Database", { env, stackName: "Alex5Database" });

const vectorBucket =
  (app.node.tryGetContext("vectorBucket") as string) ?? "REPLACE_VECTOR_BUCKET_FROM_PART3";

const agents = new AgentsStack(app, "Alex6Agents", {
  env,
  stackName: "Alex6Agents",
  auroraClusterArn: database.clusterArn,
  auroraSecretArn: database.secretArn,
  vectorBucket,
  bedrockModelId: (app.node.tryGetContext("bedrockModelId") as string) ?? "us.amazon.nova-pro-v1:0",
  bedrockRegion: (app.node.tryGetContext("bedrockRegion") as string) ?? "us-west-2",
  sagemakerEndpoint: (app.node.tryGetContext("sagemakerEndpoint") as string) ?? "alex-embedding-endpoint",
  polygonApiKey: (app.node.tryGetContext("polygonApiKey") as string) ?? "",
  polygonPlan: (app.node.tryGetContext("polygonPlan") as string) ?? "free",
  langfusePublicKey: (app.node.tryGetContext("langfusePublicKey") as string) ?? "",
  langfuseSecretKey: (app.node.tryGetContext("langfuseSecretKey") as string) ?? "",
  langfuseHost: (app.node.tryGetContext("langfuseHost") as string) ?? "https://us.cloud.langfuse.com",
  openaiApiKey: (app.node.tryGetContext("openaiApiKey") as string) ?? "",
  openrouterApiKey: (app.node.tryGetContext("openrouterApiKey") as string) ?? "",
  openaiBaseUrl: (app.node.tryGetContext("openaiBaseUrl") as string) ?? "",
});
agents.addDependency(database);

const clerkJwks =
  (app.node.tryGetContext("clerkJwksUrl") as string) ??
  "https://example.clerk.accounts.dev/.well-known/jwks.json";
const clerkIssuer =
  (app.node.tryGetContext("clerkIssuer") as string) ?? "https://example.clerk.accounts.dev";

const frontend = new FrontendStack(app, "Alex7Frontend", {
  env,
  stackName: "Alex7Frontend",
  auroraClusterArn: database.clusterArn,
  auroraSecretArn: database.secretArn,
  databaseName: database.databaseName,
  sqsQueueUrl: agents.queueUrl,
  sqsQueueArn: agents.queueArn,
  clerkJwksUrl: clerkJwks,
  clerkIssuer: clerkIssuer,
});
frontend.addDependency(agents);
frontend.addDependency(database);

new EnterpriseStack(app, "Alex8Enterprise", {
  env,
  stackName: "Alex8Enterprise",
  bedrockModelId: (app.node.tryGetContext("bedrockModelId") as string) ?? "us.amazon.nova-pro-v1:0",
});
