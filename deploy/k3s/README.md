# VitaCardia 本地 k3s

平台和沙箱都在 k3s 命名空间 `vitacardia`。宿主机 80/443 留给 VitaCardia 网站，WeBuild 入口是 NodePort **30080**。

```sh
deploy/scripts/k3s-build-images.sh
deploy/scripts/k3s-deploy.sh
```

浏览器打开 `http://<节点 IP>:30080/`。本地账号是 `vitacardia` / `vitacardia`。沙箱里的 agent 连接集群内的 `ws://relay-server.vitacardia.svc.cluster.local:8002/ws`。

沙箱镜像另外导入：

```sh
deploy/scripts/k3s-import-sandbox.sh --build
```

k3s 安装时关掉 Traefik，避免占用 80 端口：

```sh
curl -sfL https://get.k3s.io | sh -s - --disable=traefik
```

账号来自 `deploy/k3s/invite_whitelist.example.json`。沙箱镜像名是 `docker.io/library/webuild-sandbox:local`。未导入时，新建会话对应的 Pod 会停在 `ImagePullBackOff`。Gateway 使用集群内 ServiceAccount，命名空间由 `SANDBOX_NAMESPACE=vitacardia` 指定。
