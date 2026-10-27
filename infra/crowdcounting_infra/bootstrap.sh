# CrowdCounting first-boot bootstrap. cloud-init runs this once per instance, as root.
# The stack fills in the {{PLACEHOLDERS}}; CDK prepends a trap that reports the exit code to
# CloudFormation (cfn-signal), so any failing command fails the deploy instead of hanging it.
# Output goes to /var/log/cloud-init-output.log. No `set -x`: the secret must not be logged.
set -euo pipefail
export HOME=/root

APP_DIR=/opt/crowdcounting
REGION="{{REGION}}"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.aws.yml)
PLUGIN_DIR=/usr/local/lib/docker/cli-plugins

log() { echo "[crowdcounting] $*"; }

# --- 1. Host tools ------------------------------------------------------------------------
# cfn-signal (used by the exit trap) and unzip ship with most AL2023 images; install if not.
if [ ! -x /opt/aws/bin/cfn-signal ] || ! command -v unzip >/dev/null; then
  dnf install -y -q aws-cfn-bootstrap unzip
fi

systemctl enable --now docker

# Version of the newest GitHub release of $1 (owner/repo), from the /releases/latest redirect.
latest_tag() {
  curl -fsSLI --retry 5 -o /dev/null -w '%{url_effective}' "https://github.com/$1/releases/latest" \
    | sed 's#.*/tag/##'
}

install_plugin() {  # <plugin file name> <download url>
  mkdir -p "$PLUGIN_DIR"
  curl -fsSL --retry 5 -o "$PLUGIN_DIR/$1" "$2"
  chmod 0755 "$PLUGIN_DIR/$1"
}

# Docker Compose v2 builds through buildx (>= 0.17), and the Dockerfiles use BuildKit features
# (RUN --mount=type=cache), so make sure both plugins are present and recent enough.
buildx_version=$(docker buildx version 2>/dev/null | awk '{print $2}' | tr -d v || true)
if [ -z "$buildx_version" ] \
  || [ "$(printf '%s\n' 0.17.0 "$buildx_version" | sort -V | head -n1)" != 0.17.0 ]; then
  tag=$(latest_tag docker/buildx)
  log "installing docker buildx $tag (found: ${buildx_version:-none})"
  install_plugin docker-buildx \
    "https://github.com/docker/buildx/releases/download/${tag}/buildx-${tag}.linux-amd64"
fi
if ! docker compose version >/dev/null 2>&1; then
  log "installing docker compose (latest release)"
  install_plugin docker-compose \
    "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64"
fi
docker buildx version
docker compose version

# --- 2. GPU -------------------------------------------------------------------------------
# The DLAMI ships the NVIDIA driver and nvidia-container-toolkit; make sure Docker knows the
# runtime (idempotent).
if command -v nvidia-ctk >/dev/null; then
  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker
fi

# The backend's PyTorch wheels are built against CUDA 13, which needs NVIDIA driver >= 580.
# If the GPU or a new enough driver is missing, fall back to CPU so the demo still comes up.
device=cuda:0
driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1 || true)
if [ -z "$driver" ]; then
  log "WARNING: nvidia-smi found no GPU; running inference on the CPU"
  device=cpu
elif [ "${driver%%.*}" -lt 580 ]; then
  log "WARNING: NVIDIA driver $driver is older than 580 (CUDA 13); running inference on the CPU"
  device=cpu
else
  log "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -n1), driver $driver"
fi

# --- 3. App code --------------------------------------------------------------------------
mkdir -p "$APP_DIR"
aws s3 cp "s3://{{ASSET_BUCKET}}/{{ASSET_KEY}}" /tmp/crowdcounting.zip --region "$REGION" --quiet
unzip -o -q /tmp/crowdcounting.zip -d "$APP_DIR"
rm -f /tmp/crowdcounting.zip
mkdir -p "$APP_DIR/videos"

# --- 4. Configuration ---------------------------------------------------------------------
secret_key=$(aws secretsmanager get-secret-value --region "$REGION" \
  --secret-id "{{SECRET_ARN}}" --query SecretString --output text)
(
  umask 077
  cat > "$APP_DIR/.env" <<EOF
# Written by the instance bootstrap. Read by docker compose for \${VAR} substitution, and passed
# to the backend container whole by docker-compose.gpu.yml (env_file).
CC_SECRET_KEY=${secret_key}
CC_DEMO_MODE=true
CC_STREAM_FPS=8
# Keep the downloaded scenario videos on the /data volume (writable by the container user).
CC_DEMO_VIDEO_DIR=/data/demo-videos
CC_DEVICE=${device}
CC_DETECTOR=ultralytics
# The scenarios' zones and limits were tuned at this inference size and confidence; the
# plaza's distant crowd is mostly missed at the default 640.
CC_DETECTOR_IMGSZ=1280
CC_CONFIDENCE=0.3
# Viewers reach the app over HTTPS (CloudFront), so session cookies can be Secure.
CC_COOKIE_SECURE=true
# Cost controls for a public URL: video is the only part whose cost grows with every viewer.
CC_MAX_VIDEO_VIEWERS={{MAX_VIDEO_VIEWERS}}
CC_VIDEO_SESSION_MAX_S={{VIDEO_SESSION_MAX_S}}
CC_VIDEO_IDLE_TIMEOUT_S={{VIDEO_IDLE_TIMEOUT_S}}
# Per-camera and fleet metrics as CloudWatch Embedded Metric Format lines on stdout, which
# the awslogs driver (docker-compose.aws.yml) delivers to CloudWatch.
CC_METRICS=emf
CC_METRICS_INTERVAL_S=60
# For docker-compose.aws.yml's logging options.
AWS_REGION=${REGION}
CC_LOG_GROUP={{LOG_GROUP}}
EOF
)
unset secret_key

# --- 5. Build and start -------------------------------------------------------------------
cd "$APP_DIR"
"${COMPOSE[@]}" up -d --build

# Report success to CloudFormation only once nginx answers and proxies to a healthy backend.
for _ in $(seq 1 90); do
  if curl -fsS --max-time 5 http://localhost/api/health >/dev/null 2>&1; then
    log "app is healthy"
    exit 0
  fi
  sleep 10
done
log "ERROR: app did not become healthy within 15 minutes"
"${COMPOSE[@]}" ps || true
"${COMPOSE[@]}" logs --tail 200 || true  # Docker keeps a local copy alongside awslogs
exit 1
