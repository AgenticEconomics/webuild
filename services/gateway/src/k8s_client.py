"""Kubernetes client wrapper for sandbox pod lifecycle management."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import structlog
from kubernetes import client, config, watch
from kubernetes.client.exceptions import ApiException

logger = structlog.get_logger()

SANDBOX_NAMESPACE = os.environ.get("SANDBOX_NAMESPACE", "webuild-sandbox").strip() or "webuild-sandbox"
SANDBOX_LABEL_PREFIX = "webuild.io/sandbox"
# Empty / none / off skips imagePullSecrets (local k3s images already in containerd).
# Unset keeps the ACS private-registry secret.
_PULL_SECRET_DISABLED = {"", "none", "off", "-"}


def image_pull_secret_name() -> str | None:
    """Secret name for private registries, or None when the image is local."""
    raw = os.environ.get("SANDBOX_IMAGE_PULL_SECRET", "acr-webuild").strip()
    if raw.lower() in _PULL_SECRET_DISABLED:
        return None
    return raw


def image_pull_policy() -> str | None:
    """Explicit pull policy, or None to let Kubernetes apply its default."""
    raw = os.environ.get("SANDBOX_IMAGE_PULL_POLICY", "").strip()
    return raw or None


class K8sClient:
    """Wraps the official Kubernetes Python client for sandbox pod operations."""

    def __init__(self) -> None:
        self._core_v1: client.CoreV1Api | None = None
        self._loaded = False

    def load_config(self, kubeconfig_path: str | None = None) -> None:
        """Load kubeconfig from file path or in-cluster config."""
        if kubeconfig_path:
            config.load_kube_config(config_file=kubeconfig_path)
            logger.info("k8s_config_loaded", source="kubeconfig", path=kubeconfig_path)
        else:
            try:
                config.load_incluster_config()
                logger.info("k8s_config_loaded", source="incluster")
            except config.ConfigException:
                config.load_kube_config()
                logger.info("k8s_config_loaded", source="default_kubeconfig")

        self._core_v1 = client.CoreV1Api()
        self._loaded = True

    @property
    def core_v1(self) -> client.CoreV1Api:
        if not self._loaded or self._core_v1 is None:
            raise RuntimeError("K8sClient not initialised — call load_config() first")
        return self._core_v1

    # ------------------------------------------------------------------
    # Pod creation
    # ------------------------------------------------------------------

    # Sandbox agent code to inject as ConfigMap (when using standard image)
    _AGENT_CODE: str | None = None

    @classmethod
    def load_agent_code(cls) -> str:
        """Load the sandbox agent Python code for ConfigMap injection."""
        if cls._AGENT_CODE is None:
            import pathlib
            agent_path = pathlib.Path(__file__).parent.parent / "sandbox" / "agent" / "sandbox_agent.py"
            if agent_path.exists():
                cls._AGENT_CODE = agent_path.read_text()
                logger.info("agent_code_loaded", path=str(agent_path), size=len(cls._AGENT_CODE))
            else:
                cls._AGENT_CODE = ""
                logger.warning("agent_code_not_found", path=str(agent_path))
        return cls._AGENT_CODE

    def _ensure_agent_configmap(self, sandbox_id: str) -> str:
        """Create a ConfigMap with the agent code. Returns configmap name."""
        cm_name = f"sandbox-agent-{sandbox_id}"
        agent_code = self.load_agent_code()

        cm = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=cm_name,
                namespace=SANDBOX_NAMESPACE,
                labels={"app": "webuild-sandbox", SANDBOX_LABEL_PREFIX: sandbox_id},
            ),
            data={"sandbox_agent.py": agent_code},
        )

        try:
            self.core_v1.create_namespaced_config_map(namespace=SANDBOX_NAMESPACE, body=cm)
            logger.info("agent_configmap_created", name=cm_name)
        except ApiException as e:
            if e.status == 409:
                logger.debug("agent_configmap_exists", name=cm_name)
            else:
                raise
        return cm_name

    def create_sandbox_pod(
        self,
        sandbox_id: str,
        image: str,
        env_vars: dict[str, str] | None = None,
        resources: dict | None = None,
        ttl_seconds: int = 3600,
        agent_mode: str = "webuild",
    ) -> tuple[str, str]:
        """Create a sandbox Pod + ClusterIP Service. Returns (pod_name, service_name).

        agent_mode:
          - "webuild": use image ENTRYPOINT (sandbox-init → webuild headless)
          - "python" / "legacy-python": ConfigMap-inject sandbox_agent.py (Phase II–IV)
        """

        pod_name = f"sandbox-{sandbox_id}"
        svc_name = f"sandbox-{sandbox_id}"

        res = resources or {}
        cpu_request = res.get("cpu_request", "1")
        memory_request = res.get("memory_request", "2Gi")
        cpu_limit = res.get("cpu_limit", "4")
        memory_limit = res.get("memory_limit", "8Gi")
        ephemeral_storage = res.get("ephemeral_storage", "20Gi")

        env_list = [client.V1EnvVar(name=k, value=v) for k, v in (env_vars or {}).items()]

        volumes: list | None = None
        volume_mounts: list | None = None
        command: list[str] | None = None
        args: list[str] | None = None
        run_as_user = 1000  # ubuntu in sandbox image

        use_legacy_python = agent_mode in ("python", "legacy-python")
        if use_legacy_python:
            # Phase II–IV path: inject Python agent into slim image
            cm_name = self._ensure_agent_configmap(sandbox_id)
            volumes = [
                client.V1Volume(
                    name="agent-code",
                    config_map=client.V1ConfigMapVolumeSource(name=cm_name),
                ),
            ]
            volume_mounts = [
                client.V1VolumeMount(
                    name="agent-code",
                    mount_path="/opt/agent",
                    read_only=True,
                ),
            ]
            command = ["bash", "-c"]
            args = [
                "pip install --break-system-packages -q httpx websockets structlog "
                "--index-url https://mirrors.aliyun.com/pypi/simple/ "
                "--trusted-host mirrors.aliyun.com && "
                "exec python3 /opt/agent/sandbox_agent.py"
            ]
            run_as_user = 0  # pip install needs root on slim image
        # else: rely on image ENTRYPOINT (/opt/sandbox/sandbox-init.sh → webuild)

        # Container
        container_kwargs: dict = {
            "name": "sandbox",
            "image": image,
            "env": env_list or None,
            "ports": [client.V1ContainerPort(container_port=8080, protocol="TCP")],
            "command": command,
            "args": args,
            "volume_mounts": volume_mounts,
            "resources": client.V1ResourceRequirements(
                requests={
                    "cpu": cpu_request,
                    "memory": memory_request,
                    "ephemeral-storage": ephemeral_storage,
                },
                limits={
                    "cpu": cpu_limit,
                    "memory": memory_limit,
                    "ephemeral-storage": ephemeral_storage,
                },
            ),
            "security_context": client.V1SecurityContext(
                run_as_user=run_as_user,
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
        }
        pull_policy = image_pull_policy()
        if pull_policy:
            container_kwargs["image_pull_policy"] = pull_policy
        container = client.V1Container(**container_kwargs)

        labels = {
            "app": "webuild-sandbox",
            SANDBOX_LABEL_PREFIX: sandbox_id,
            "webuild.io/ttl-seconds": str(ttl_seconds),
            "webuild.io/created-at": str(int(datetime.now(timezone.utc).timestamp())),
            "webuild.io/agent-mode": "python" if use_legacy_python else "webuild",
        }

        pod_spec_kwargs: dict = {
            "containers": [container],
            "volumes": volumes,
            "restart_policy": "Never",
            "termination_grace_period_seconds": 30,
        }
        pull_secret = image_pull_secret_name()
        if pull_secret:
            # Private registry (ACS ACR secret acr-webuild, or a local override).
            pod_spec_kwargs["image_pull_secrets"] = [
                client.V1LocalObjectReference(name=pull_secret),
            ]

        pod_spec = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=SANDBOX_NAMESPACE,
                labels=labels,
            ),
            spec=client.V1PodSpec(**pod_spec_kwargs),
        )

        self.core_v1.create_namespaced_pod(namespace=SANDBOX_NAMESPACE, body=pod_spec)
        logger.info(
            "sandbox_pod_created",
            pod_name=pod_name,
            sandbox_id=sandbox_id,
            agent_mode="python" if use_legacy_python else "webuild",
            image=image,
        )

        # Service for internal cluster access
        svc = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=svc_name,
                namespace=SANDBOX_NAMESPACE,
                labels={SANDBOX_LABEL_PREFIX: sandbox_id},
            ),
            spec=client.V1ServiceSpec(
                selector={SANDBOX_LABEL_PREFIX: sandbox_id},
                ports=[client.V1ServicePort(port=8080, target_port=8080, protocol="TCP")],
                type="ClusterIP",
            ),
        )

        self.core_v1.create_namespaced_service(namespace=SANDBOX_NAMESPACE, body=svc)
        logger.info("sandbox_svc_created", svc_name=svc_name, sandbox_id=sandbox_id)

        return pod_name, svc_name

    # ------------------------------------------------------------------
    # Pod deletion
    # ------------------------------------------------------------------

    def delete_sandbox_pod(self, sandbox_id: str) -> None:
        """Delete the sandbox Pod and its Service."""
        pod_name = f"sandbox-{sandbox_id}"
        svc_name = f"sandbox-{sandbox_id}"

        # Delete service first (idempotent)
        try:
            self.core_v1.delete_namespaced_service(
                name=svc_name,
                namespace=SANDBOX_NAMESPACE,
                body=client.V1DeleteOptions(propagation_policy="Background"),
            )
            logger.info("sandbox_svc_deleted", svc_name=svc_name, sandbox_id=sandbox_id)
        except ApiException as e:
            if e.status != 404:
                raise
            logger.debug("sandbox_svc_already_gone", svc_name=svc_name, sandbox_id=sandbox_id)

        # Delete pod
        try:
            self.core_v1.delete_namespaced_pod(
                name=pod_name,
                namespace=SANDBOX_NAMESPACE,
                body=client.V1DeleteOptions(grace_period_seconds=10),
            )
            logger.info("sandbox_pod_deleted", pod_name=pod_name, sandbox_id=sandbox_id)
        except ApiException as e:
            if e.status != 404:
                raise
            logger.debug("sandbox_pod_already_gone", pod_name=pod_name, sandbox_id=sandbox_id)

    # ------------------------------------------------------------------
    # Pod status
    # ------------------------------------------------------------------

    def get_pod_status(self, sandbox_id: str) -> str | None:
        """Return the Pod phase: Pending, Running, Succeeded, Failed, or None if not found."""
        pod_name = f"sandbox-{sandbox_id}"
        try:
            pod = self.core_v1.read_namespaced_pod_status(
                name=pod_name, namespace=SANDBOX_NAMESPACE
            )
            return pod.status.phase
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    # ------------------------------------------------------------------
    # Pod logs
    # ------------------------------------------------------------------

    def get_pod_logs(self, sandbox_id: str, tail_lines: int = 200) -> str:
        """Return recent log output from the sandbox pod."""
        pod_name = f"sandbox-{sandbox_id}"
        try:
            return self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=SANDBOX_NAMESPACE,
                tail_lines=tail_lines,
                timestamps=True,
            )
        except ApiException as e:
            if e.status == 404:
                return ""
            raise

    # ------------------------------------------------------------------
    # Pod exec / file transfer (Phase VII)
    # ------------------------------------------------------------------

    def exec_in_pod(
        self,
        sandbox_id: str,
        command: list[str],
        *,
        stdin_data: bytes | None = None,
        timeout_seconds: int = 120,
    ) -> tuple[int, bytes, bytes]:
        """Run a command in the sandbox pod. Returns (exit_code, stdout, stderr)."""
        from kubernetes.stream import stream

        pod_name = f"sandbox-{sandbox_id}"
        resp = stream(
            self.core_v1.connect_get_namespaced_pod_exec,
            pod_name,
            SANDBOX_NAMESPACE,
            command=command,
            stderr=True,
            stdin=stdin_data is not None,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        try:
            import time

            deadline = time.time() + timeout_seconds
            if stdin_data is not None:
                # Chunk large payloads
                offset = 0
                chunk_size = 64 * 1024
                while offset < len(stdin_data):
                    resp.write_stdin(stdin_data[offset : offset + chunk_size])
                    offset += chunk_size
                try:
                    resp.write_stdin("")  # signal end on some client versions
                except Exception:
                    pass

            while resp.is_open():
                if time.time() > deadline:
                    raise TimeoutError(f"exec timed out after {timeout_seconds}s")
                resp.update(timeout=1)
                if resp.peek_stdout():
                    chunk = resp.read_stdout()
                    if chunk:
                        stdout_chunks.append(
                            chunk if isinstance(chunk, bytes) else chunk.encode("utf-8", "replace")
                        )
                if resp.peek_stderr():
                    chunk = resp.read_stderr()
                    if chunk:
                        stderr_chunks.append(
                            chunk if isinstance(chunk, bytes) else chunk.encode("utf-8", "replace")
                        )
        finally:
            try:
                resp.close()
            except Exception:
                pass

        code = 0
        try:
            code = int(getattr(resp, "returncode", 0) or 0)
        except Exception:
            code = 0
        out = b"".join(stdout_chunks)
        err = b"".join(stderr_chunks)
        return code, out, err

    def ensure_workspace_layout(self, sandbox_id: str) -> None:
        """Idempotently create Phase VII workspace directories (+ WORKSPACE.md if missing)."""
        from src.pathutil import WORKSPACE_SUBDIRS

        dirs = " ".join(f"/workspace/{d}" for d in WORKSPACE_SUBDIRS)
        cmd = [
            "/bin/bash",
            "-lc",
            f"mkdir -p {dirs} && "
            f"if [ -f /opt/sandbox/WORKSPACE.md ] && [ ! -f /workspace/WORKSPACE.md ]; then "
            f"cp /opt/sandbox/WORKSPACE.md /workspace/WORKSPACE.md; fi",
        ]
        code, _out, err = self.exec_in_pod(sandbox_id, cmd)
        if code not in (0, None) and err:
            logger.warning(
                "ensure_workspace_layout_warn",
                sandbox_id=sandbox_id,
                code=code,
                stderr=err.decode("utf-8", "replace")[:500],
            )

    def upload_file_to_pod(
        self,
        sandbox_id: str,
        dest_dir: str,
        filename: str,
        data: bytes,
    ) -> str:
        """Upload a single file into /workspace/<dest_dir>/<filename> via tar stdin.

        Returns the workspace-relative path (posix).
        """
        import io
        import tarfile

        from src.pathutil import resolve_under_workspace, sanitize_filename, validate_upload_dest

        dest = validate_upload_dest(dest_dir)
        safe_name = sanitize_filename(filename)
        resolve_under_workspace(dest, safe_name)

        self.ensure_workspace_layout(sandbox_id)

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=safe_name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
        payload = buf.getvalue()

        # Fixed argv — dest is allowlisted
        command = ["tar", "-C", f"/workspace/{dest}", "-xf", "-"]
        code, _out, err = self.exec_in_pod(sandbox_id, command, stdin_data=payload)
        if code not in (0, None):
            detail = err.decode("utf-8", "replace")[:500]
            raise RuntimeError(f"upload failed (exit={code}): {detail}")
        return f"{dest}/{safe_name}"

    def list_files_in_pod(self, sandbox_id: str, prefix: str) -> list[dict]:
        """List files under /workspace/<prefix>. Returns [{path,size,mtime}]."""
        from src.pathutil import validate_list_prefix

        rel = validate_list_prefix(prefix)
        self.ensure_workspace_layout(sandbox_id)
        # %P = path relative to search root; size; mtime epoch
        script = (
            f'root="/workspace/{rel}"; '
            f'if [ ! -d "$root" ]; then exit 0; fi; '
            f'find "$root" -type f -printf "%P\\t%s\\t%T@\\n" 2>/dev/null | head -n 2000'
        )
        code, out, err = self.exec_in_pod(sandbox_id, ["/bin/bash", "-lc", script])
        if code not in (0, None):
            detail = err.decode("utf-8", "replace")[:500]
            raise RuntimeError(f"list failed (exit={code}): {detail}")
        results: list[dict] = []
        for line in out.decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            name, size_s, mtime_s = parts[0], parts[1], parts[2]
            try:
                size = int(size_s)
                mtime = float(mtime_s)
            except ValueError:
                continue
            rel_path = f"{rel}/{name}".replace("//", "/") if name else rel
            results.append({"path": rel_path, "size": size, "mtime": mtime})
        results.sort(key=lambda x: x["path"])
        return results

    def download_file_from_pod(self, sandbox_id: str, rel_path: str) -> tuple[str, bytes]:
        """Download one file from /workspace. Returns (basename, content)."""
        import io
        import tarfile

        from src.pathutil import validate_download_path

        rel = validate_download_path(rel_path)
        # tar path must be relative to /workspace
        command = ["tar", "-C", "/workspace", "-cf", "-", rel]
        code, out, err = self.exec_in_pod(sandbox_id, command)
        if code not in (0, None) or not out:
            detail = err.decode("utf-8", "replace")[:500]
            raise FileNotFoundError(f"download failed for {rel}: {detail or 'empty'}")
        with tarfile.open(fileobj=io.BytesIO(out), mode="r:") as tar:
            members = [m for m in tar.getmembers() if m.isfile()]
            if not members:
                raise FileNotFoundError(f"No file in archive for {rel}")
            member = members[0]
            extracted = tar.extractfile(member)
            if extracted is None:
                raise FileNotFoundError(f"Cannot extract {rel}")
            data = extracted.read()
            name = os.path.basename(member.name) or os.path.basename(rel)
            return name, data

    # ------------------------------------------------------------------
    # Event watch (for streaming)
    # ------------------------------------------------------------------

    def watch_pod_events(
        self, sandbox_id: str, timeout_seconds: int = 60
    ) -> list[dict]:
        """Watch pod events for a bounded period. Returns a list of event dicts."""
        pod_name = f"sandbox-{sandbox_id}"
        w = watch.Watch()
        events: list[dict] = []

        try:
            for event in w.stream(
                self.core_v1.list_namespaced_event,
                namespace=SANDBOX_NAMESPACE,
                field_selector=f"involvedObject.name={pod_name}",
                timeout_seconds=timeout_seconds,
            ):
                obj = event["object"]
                events.append(
                    {
                        "type": event["type"],
                        "reason": obj.reason,
                        "message": obj.message,
                        "count": obj.count,
                        "last_timestamp": obj.last_timestamp.isoformat() if obj.last_timestamp else None,
                    }
                )
        except Exception:
            logger.exception("watch_events_error", sandbox_id=sandbox_id)
        finally:
            w.stop()

        return events

    # ------------------------------------------------------------------
    # Resolve pod IP for WebSocket proxying
    # ------------------------------------------------------------------

    def get_pod_ip(self, sandbox_id: str) -> str | None:
        """Return the Pod's cluster IP, or None if not available."""
        pod_name = f"sandbox-{sandbox_id}"
        try:
            pod = self.core_v1.read_namespaced_pod(
                name=pod_name, namespace=SANDBOX_NAMESPACE
            )
            return pod.status.pod_ip
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    # ------------------------------------------------------------------
    # Cleanup helpers
    # ------------------------------------------------------------------

    def list_sandbox_pods(self) -> list[dict]:
        """List all sandbox pods with their labels and creation timestamps."""
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=SANDBOX_NAMESPACE,
                label_selector="app=webuild-sandbox",
            )
            results = []
            for pod in pods.items:
                results.append(
                    {
                        "pod_name": pod.metadata.name,
                        "sandbox_id": pod.metadata.labels.get(SANDBOX_LABEL_PREFIX, ""),
                        "phase": pod.status.phase,
                        "created_at": pod.metadata.creation_timestamp.isoformat()
                        if pod.metadata.creation_timestamp
                        else None,
                    }
                )
            return results
        except ApiException:
            logger.exception("list_sandbox_pods_error")
            return []
