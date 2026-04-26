import boto3

client = boto3.client("bedrock", region_name="us-east-1")
models = client.list_foundation_models(byProvider="Anthropic")["modelSummaries"]

print(f"{'STATUS':<12} {'MODEL ID'}")
print("-" * 70)
for m in sorted(models, key=lambda x: x["modelId"]):
    status = m.get("modelLifecycle", {}).get("status", "UNKNOWN")
    print(f"{status:<12} {m['modelId']}")
