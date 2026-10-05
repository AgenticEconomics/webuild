---
name: webuild-k3s-private-deploy
description: >-
  Deploy and customize WeBuild as a local private k3s platform (namespace
  vitacardia, NodePort 30080, local sandbox image, DashScope). Use when
  deploying WeBuild on local k3s, privatizing WeBuild, fixing sandbox pods,
  DASHSCOPE_API_KEY, Disconnected sessions, or working on the vitacardia branch.
---

# WeBuild 本地 k3s 私有化部署

在 `vitacardia` 分支上工作。不要推到 `main`。平台和沙箱都在 k3s 命名空间 `vitacardia`。宿主机 80/443 留给已有站点（VitaCardia Caddy），WeBuild 入口是 NodePort **30080**。

已落地的清单在 `deploy/k3s/` 和 `deploy/scripts/k3s-*.sh`。按下面的顺序执行，不要改回阿里云 ACS，也不要跑会占用 80 端口的 `deploy/scripts/k3s-up.sh`。

## 约束

- 命名空间固定 `vitacardia`。平台 Pod 和 `app=webuild-sandbox` 沙箱 Pod 共用它。
- Gateway 默认命名空间仍是 `webuild-sandbox`。本地部署必须设 `SANDBOX_NAMESPACE=vitacardia`（已写在 `deploy/k3s/platform.yaml`）。
- 镜像走本机 containerd，标签 `docker.io/library/<name>:local`。`SANDBOX_IMAGE_PULL_SECRET=none`，`SANDBOX_IMAGE_PULL_POLICY=IfNotPresent`。不要配 ACR pull secret。
- 登录账号来自 `deploy/k3s/invite_whitelist.example.json`：`vitacardia` / `vitacardia`。登录入口在 Web IDE 的 Settings，`POST /api/auth/login`。
- 模型密钥的环境变量名是 `DASHSCOPE_API_KEY`。没有 `DASHBOARD_API_KEY`。
- 不要把密钥、`deploy/.env.k3s`、`sandbox/webuild-linux-x86_64`、`sandbox/agent-skills` 提交进 git。

## 访问方式

| 从哪里打开 | 地址 |
|---|---|
| 这台机器上 | `http://127.0.0.1:30080/` |
| 内网 | `http://<节点 InternalIP>:30080/` |

公网安全组默认不通 30080。SSH 隧道要在开发者自己的电脑上执行，不要在服务器上 `ssh -L` 自己的公网 IP。

浏览器聊天 WebSocket 必须带页面端口：`ws://<host>:30080/ws/relay`。`defaultWsUrl()` 使用 `window.location.host`。只写 hostname 会落到 80 端口的 Caddy，页面就一直 Disconnected，而沙箱 Pod 仍是 Running。Settings 里如果保存过不带端口的地址，删掉或改成带 `:30080` 的地址。

## 部署顺序

```
- [ ] 安装 k3s（关掉 Traefik）
- [ ] 配置镜像加速
- [ ] 构建并导入平台镜像
- [ ] 构建沙箱二进制和镜像，导入 k3s
- [ ] 写入 DASHSCOPE_API_KEY 后部署
- [ ] 按验收清单检查
```

### 1. 安装 k3s

GitHub 直连很慢。用镜像下载，并禁用 Traefik，否则和宿主机 80 冲突。

```sh
curl -sfL https://get.k3s.io | INSTALL_K3S_MIRROR=cn \
  INSTALL_K3S_EXEC='--disable=traefik' sh -
```

若安装脚本仍从 GitHub 拉二进制，设置：

```sh
INSTALL_K3S_ARTIFACT_URL=https://ghfast.top/https://github.com/k3s-io/k3s/releases/download
```

`k3s kubectl get nodes` 为 Ready 后再继续。

### 2. 国内镜像

Docker Hub 直连会超时。`/etc/rancher/k3s/registries.yaml`：

```yaml
mirrors:
  docker.io:
    endpoint:
      - https://docker.m.daocloud.io
      - https://dockerproxy.net
```

写完后重启 k3s。Docker 拉基础镜像用 `docker.m.daocloud.io/library/...`，再 `docker tag` 成 `docker.io/library/...`。`deploy/scripts/k3s-build-images.sh` 已按这个方式拉 `python:3.11-slim`、`node:20-alpine`、`nginx:alpine`、`postgres:16-alpine`。

在国内编译 Rust 时：

- rustup：`RUSTUP_DIST_SERVER=https://mirrors.ustc.edu.cn/rust-static`
- crates.io：`~/.cargo/config.toml` 使用 USTC sparse index
- GitHub git 依赖：进程内 `insteadOf` 到 `https://ghfast.top/https://github.com/`，并设 `CARGO_NET_GIT_FETCH_WITH_CLI=true`。不要改全局 git config。
- 构建需要 `/usr/local/bin/protoc`（protobuf 29）和 `/usr/local/bin/rg`。设置 `WEBUILD_TOOLS_BUNDLE_RG_PATH`、`WEBUILD_SHELL_BUNDLE_RG_PATH`。

### 3. 平台镜像

```sh
deploy/scripts/k3s-build-images.sh
```

导入目标是 k3s 的 containerd，不是 Docker。`docker images` 里有图，Kubernetes 仍可能 `ImagePullBackOff`。

### 4. 沙箱镜像

沙箱基础镜像必须和编译 `webuild` 的宿主机 glibc 一致。这台机器是 Ubuntu 26.04，所以 `sandbox/Dockerfile` 是 `FROM ubuntu:26.04`。二进制在更老的 Ubuntu 里会报 `GLIBC_2.43 not found`，Pod 立刻 Error。`restartPolicy: Never`，失败的 Pod 不会自己恢复，删掉后重新开会话。

```sh
cargo build -p xai-webuild-pager-bin --release
cp target/release/xai-webuild-pager sandbox/webuild-linux-x86_64
deploy/scripts/k3s-import-sandbox.sh --build
docker run --rm --entrypoint /usr/local/bin/webuild webuild-sandbox:local --version
```

Gateway 使用的名字是 `docker.io/library/webuild-sandbox:local`。导入后确认 `k3s ctr images ls` 里有这个 tag。覆盖 tag 之后，新建的 Pod 才会用到新 digest；已经 Error 的旧 Pod 不会换镜像。

### 5. 密钥和部署

`deploy/scripts/k3s-deploy.sh` 只在 Secret `webuild-env` **不存在**时创建它。已存在时不会更新 `DASHSCOPE_API_KEY`。

第一次部署前导出密钥：

```sh
export DASHSCOPE_API_KEY='sk-...'
deploy/scripts/k3s-deploy.sh
```

之后改密钥：

```sh
k3s kubectl -n vitacardia patch secret webuild-env --type merge \
  -p '{"stringData":{"DASHSCOPE_API_KEY":"sk-..."}}'
k3s kubectl -n vitacardia rollout restart deploy/gateway
```

不要在行尾写 `\ `（反斜杠加空格），那会被当成另一个参数。改 Secret 后必须重启 Gateway，并且新开沙箱。已经在跑的沙箱不会读到新密钥。

Secret 里还有脚本生成的 `DB_PASSWORD`、`JWT_SECRET`、`RELAY_INTERNAL_TOKEN`。不要把它们打进日志或文档。

### 6. 集群内关键配置

这些值已经在 `deploy/k3s/platform.yaml`，换环境时保持同一关系：

- `RELAY_URL=ws://relay-server.vitacardia.svc.cluster.local:8002/ws`
- `HUB_WS_URL=ws://hub-broker.vitacardia.svc.cluster.local:8003/ws`
- 沙箱走集群内 Service，路径是 `/ws`。`/ws/relay` 只给浏览器经 Nginx 使用，Nginx 再把它转到 relay 的 `/ws`。
- `MODEL=qwen-max` 不在内置模型表里，agent 会回退到 `qwen3.7-max`。拉取 `https://webuild.datoms.cn/api/auth/v1/models` 返回 404 可以忽略。
- 沙箱资源：request `500m` / `1Gi`，limit `2` CPU / `4Gi` / 临时盘 `8Gi`。`/environments` 仍显示模板值；真正生效的是创建 Pod 时的 `effective_resources()`。
- Role `sandbox-manager` 必须包含 `pods/status`。缺了它，`GET/DELETE /api/gateway/sandboxes/{id}` 返回 500，页面报 `Failed to terminate sandbox: 500`。
- NetworkPolicy 只选择 `app=webuild-sandbox`。不要让它选中平台 Pod。
- Auth、Relay、Gateway 有 `wait-postgres` initContainer。没有它时，Auth 会在表创建前启动，登录 500（`relation "users" does not exist`），但 `/health` 仍是 200。

## 验收

在节点上执行。全部通过才算能用。

```sh
curl -fsS -o /dev/null -w 'ide %{http_code}\n' http://127.0.0.1:30080/
curl -fsS http://127.0.0.1:30080/api/auth/health
curl -fsS http://127.0.0.1:30080/api/relay/health
curl -fsS http://127.0.0.1:30080/api/gateway/health
```

登录后新建一个会话（不要复用 Error Pod）：

1. 新 Pod `sandbox-<session-id>` 变为 Running。
2. 日志里有 `webuild` 版本号，且没有 `GLIBC_`。
3. 日志里有 `cloud sandbox agent connected to WeBuild Relay`。
4. 打开会话页，输入框从 `Connecting...` 变成可发送。Relay 会话 `browser_connected` 和 `agent_connected` 都为 true。
5. 沙箱列表里可以删除；删除返回 200，状态变为 `terminated`。

侧边栏在沙箱列表页显示 Disconnected 是正常的，那是还没有进入会话 WebSocket。进入会话页后应变为已连接。

## 故障对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 系统 Pod `ImagePullBackOff`，`registry-1.docker.io` 超时 | 没配 registry mirror | 写 `registries.yaml` 并重启 k3s |
| 新建会话 Pod `ImagePullBackOff` | 沙箱镜像只在 Docker 里 | `k3s-import-sandbox.sh` |
| Pod Error，`GLIBC_2.43 not found` | 二进制和镜像 Ubuntu 版本不一致 | `FROM ubuntu:26.04`，重建并导入，新开会话 |
| Pod 环境里 `DASHSCOPE_API_KEY` 为空 | 沙箱创建于 Gateway 重启之前 | 重启 Gateway 后新开会话 |
| 停沙箱 500，`cannot get resource "pods/status"` | Role 缺 `pods/status` | 改 `deploy/k3s/sandbox-namespace.yaml` 后 `kubectl apply` |
| 沙箱 Running，页面一直 Disconnected / Connecting | 浏览器连到了 `:80/ws/relay` | Web IDE 使用 `location.host`；清掉错误的 `webuild_ws_url` |
| 登录 500，health 却是 200 | Postgres 未就绪时 Auth 已启动 | 等 initContainer，再看 auth 日志是否建表成功 |
| `kubectl patch` 报 `secrets " " not found` 或 `invalid character` | 续行符或引号被拆开 | 一条命令写完，确认 `stringData` |
| 在服务器上 SSH 隧道 `Permission denied (publickey)` | 隧道跑错了机器 | 在笔记本上做 `-L 30080:127.0.0.1:30080` |

## 不要做的事

- 不要用 `deploy/docker-compose.yml` 的 ACS/ACR 默认值，也不要让 Compose Nginx 绑定宿主机 80。
- 不要把沙箱 Relay 地址写成 `wss://webuild.datoms.cn/ws/relay`。那是 `sandbox-init.sh` 在未注入 `RELAY_URL` 时的默认值。
- 不要用 `kubectl delete pod` 代替 Gateway 的删除接口处理仍在数据库里的沙箱，否则列表会继续显示 running。Pod 已经没了时，再调一次 `DELETE /api/gateway/sandboxes/{id}` 把记录标成 terminated。
- 改完本地镜像后执行 `k3s ctr images import`，再 `kubectl rollout restart`。`IfNotPresent` 不会去仓库拉同一个 tag。
