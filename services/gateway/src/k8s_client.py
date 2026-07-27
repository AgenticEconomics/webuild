"""Kubernetes client wrapper for sandbox pod lifecycle management."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import structlog
from kubernetes import client, config, watch
from kubernetes.client.exceptions import ApiException

logger = structlog.get_logger()

SANDBOX_NAMESPACE = "webuild-sandbox"
SANDBOX_LABEL_PREFIX = "webuild.io/sandbox"


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
    ) -> tuple[str, str]:
        """Create a sandbox Pod + ClusterIP Service. Returns (pod_name, service_name)."""

        pod_name = f"sandbox-{sandbox_id}"
        svc_name = f"sandbox-{sandbox_id}"

        res = resources or {}
        cpu_request = res.get("cpu_request", "500m")
        memory_request = res.get("memory_request", "1Gi")
        cpu_limit = res.get("cpu_limit", "2")
        memory_limit = res.get("memory_limit", "4Gi")
        ephemeral_storage = res.get("ephemeral_storage", "10Gi")

        env_list = [client.V1EnvVar(name=k, value=v) for k, v in (env_vars or {}).items()]

        # Always inject agent code via ConfigMap (custom images not yet available)
        volumes = None
        volume_mounts = None
        command = None
        args = None

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

        # Container
        container = client.V1Container(
            name="sandbox",
            image=image,
            env=env_list or None,
            ports=[client.V1ContainerPort(container_port=8080, protocol="TCP")],
            command=command,
            args=args,
            volume_mounts=volume_mounts,
            resources=client.V1ResourceRequirements(
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
            security_context=client.V1SecurityContext(
                run_as_user=0,  # Run as root to install pip packages, then agent drops privileges
                capabilities=client.V1Capabilities(drop=["ALL"]),
            ),
        )

        labels = {
            "app": "webuild-sandbox",
            SANDBOX_LABEL_PREFIX: sandbox_id,
            "webuild.io/ttl-seconds": str(ttl_seconds),
            "webuild.io/created-at": str(int(datetime.now(timezone.utc).timestamp())),
        }

        pod_spec = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=SANDBOX_NAMESPACE,
                labels=labels,
            ),
            spec=client.V1PodSpec(
                containers=[container],
                volumes=volumes,
                restart_policy="Never",
                termination_grace_period_seconds=30,
            ),
        )

        self.core_v1.create_namespaced_pod(namespace=SANDBOX_NAMESPACE, body=pod_spec)
        logger.info("sandbox_pod_created", pod_name=pod_name, sandbox_id=sandbox_id)

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
