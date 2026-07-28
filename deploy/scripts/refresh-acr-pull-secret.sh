#!/usr/bin/env bash
# Refresh Aliyun ACR temporary pull credentials into ACS namespace.
# Temp tokens typically expire in ~1h — run via cron every 45m if using cr_temp_user.
set -euo pipefail
INSTANCE_ID="${ACR_INSTANCE_ID:-cri-6l1wh8e1ogtb0oil}"
REGISTRY="${ACR_REGISTRY:-xingu-aliyun-acr-registry.cn-hangzhou.cr.aliyuncs.com}"
NAMESPACE="${SANDBOX_NAMESPACE:-webuild-sandbox}"
SECRET_NAME="${ACR_PULL_SECRET:-acr-webuild}"
KUBECONFIG="${KUBECONFIG:-/root/sandbox-kubeconfig.yaml}"
ENV_FILE="${ENV_FILE:-/root/webuild/deploy/.env}"

json=$(aliyun cr GetAuthorizationToken --InstanceId "$INSTANCE_ID" --region cn-hangzhou)
user=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["TempUsername"])' <<<"$json")
pass=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["AuthorizationToken"])' <<<"$json")
exp=$(python3 -c 'import json,sys,datetime; t=json.load(sys.stdin)["ExpireTime"]; print(datetime.datetime.utcfromtimestamp(t/1000).isoformat()+"Z")' <<<"$json")

echo "$pass" | docker login "$REGISTRY" -u "$user" --password-stdin >/dev/null
if [[ -f "$ENV_FILE" ]]; then
  python3 - "$ENV_FILE" "$pass" <<'PY'
import pathlib, re, sys
p = pathlib.Path(sys.argv[1]); pw = sys.argv[2]
text = p.read_text()
text2 = re.sub(r"^ACR_PASSWORD=.*$", f"ACR_PASSWORD={pw}", text, flags=re.M)
if text2 == text and "ACR_PASSWORD=" not in text:
    text2 = text.rstrip() + f"\nACR_PASSWORD={pw}\n"
p.write_text(text2)
PY
fi

kubectl --kubeconfig="$KUBECONFIG" -n "$NAMESPACE" delete secret "$SECRET_NAME" --ignore-not-found >/dev/null
kubectl --kubeconfig="$KUBECONFIG" -n "$NAMESPACE" create secret docker-registry "$SECRET_NAME" \
  --docker-server="$REGISTRY" \
  --docker-username="$user" \
  --docker-password="$pass" >/dev/null
echo "acr-webuild refreshed; expires $exp"
