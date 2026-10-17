#!/usr/bin/env python3
"""Generate cell-ops JuiceFS manifests; run with: mise exec -- python3 scripts/setup-juicefs.py.

Required environment:
  JFS_PG_PASSWORD, B2_ENDPOINT, B2_BUCKET, B2_ACCESS_KEY_ID, B2_SECRET_ACCESS_KEY
Optional:
  JFS_PG_HOST=100.104.107.28 JFS_PG_PORT=5432 JFS_PG_DATABASE=juicefs
  JFS_PG_USER=juicefs JFS_PG_SSLMODE=require JFS_NAME=cell
  JFS_CACHE_GIB=350 JFS_CACHE_LIMIT_GIB=320 JFS_NODE=vie10

No cluster mutations, Git commits, plaintext Secret files, or database creation.
The CSI initializes the filesystem on first provisioning using the encrypted Secret.
Refuses to overwrite an existing generated application directory.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import quote, urlencode, urlsplit


def fail(message):
    raise SystemExit(message)


def run(args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True)
    if result.returncode:
        # Never include subprocess input or output: it may contain credentials.
        fail(f"Command failed ({result.returncode}): {args[0]}. No credentials printed.")
    return result.stdout


def env(name, default=None):
    value = os.environ.get(name, default)
    if not value:
        fail(f"Missing environment variable: {name}")
    return value


def manifest(api, kind, name, spec=None, **extra):
    obj = {"apiVersion": api, "kind": kind, "metadata": {"name": name}}
    if spec is not None:
        obj["spec"] = spec
    obj.update(extra)
    return obj


def yaml_text(obj):
    return run(["yq", "-P", "-p=json", "."], json.dumps(obj))


def main():
    for tool in ("git", "sops", "yq", "kustomize"):
        if not shutil.which(tool):
            fail(f"Missing tool: {tool}; run through mise exec.")
    root = Path(run(["git", "rev-parse", "--show-toplevel"]).strip())
    os.chdir(root)
    if not Path(".sops.yaml").is_file():
        fail("Repository .sops.yaml not found.")
    base = Path("kubernetes/apps/juicefs-system")
    if base.exists():
        fail(f"{base} already exists; refusing to overwrite. Edit existing manifests instead.")
    entry = Path("kubernetes/apps/kustomization.yaml")
    if not entry.is_file():
        fail(f"Missing repository entry point: {entry}")

    password = env("JFS_PG_PASSWORD")
    access_key = env("B2_ACCESS_KEY_ID")
    secret_key = env("B2_SECRET_ACCESS_KEY")
    endpoint = env("B2_ENDPOINT").rstrip("/")
    if not endpoint.startswith("https://"):
        endpoint = "https://" + endpoint
    parsed = urlsplit(endpoint)
    if (not re.fullmatch(r"s3\.[a-z0-9-]+\.backblazeb2\.com", parsed.netloc)
            or parsed.path or parsed.query or parsed.fragment):
        fail("B2_ENDPOINT must be the B2 S3 endpoint, e.g. https://s3.eu-central-003.backblazeb2.com")
    bucket = env("B2_BUCKET")
    if not re.fullmatch(r"[A-Za-z0-9-]{6,63}", bucket):
        fail("B2_BUCKET must be a bucket name, without endpoint or path.")
    fsname = env("JFS_NAME", "cell")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", fsname):
        fail("JFS_NAME must be a lowercase filesystem name.")
    node = env("JFS_NODE", "vie10")
    mode = env("JFS_PG_SSLMODE", "require")
    if mode not in ("require", "disable"):
        fail("JFS_PG_SSLMODE must be require or disable.")
    host = env("JFS_PG_HOST", "100.104.107.28")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        fail("JFS_PG_HOST must be an IPv4 address or DNS name.")
    try:
        port = int(env("JFS_PG_PORT", "5432"))
        cache = int(env("JFS_CACHE_GIB", "350"))
        limit = int(env("JFS_CACHE_LIMIT_GIB", "320"))
    except ValueError:
        fail("Port and cache sizes must be integers.")
    if not 1 <= port <= 65535 or not 0 < limit <= cache * 0.95:
        fail("Invalid port or cache size; cache limit must leave at least 5% free.")
    url = (f"postgres://{quote(env('JFS_PG_USER', 'juicefs'), safe='')}:"
           f"{quote(password, safe='')}@{host}:{port}/"
           f"{quote(env('JFS_PG_DATABASE', 'juicefs'), safe='')}?"
           + urlencode({"sslmode": mode}))
    ns = "juicefs-system"
    secret_name = "juicefs-secret"
    pvc_name = "juicefs-cache-vie10" if node == "vie10" else f"juicefs-cache-{node}"
    app = base / "juicefs/app"
    secret_path = app / "secret.sops.yaml"
    secret = manifest("v1", "Secret", secret_name, type="Opaque", stringData={
        "name": fsname, "metaurl": url, "storage": "s3",
        "bucket": endpoint + "/" + bucket,
        "access-key": access_key, "secret-key": secret_key,
    })
    encrypted = run([
        "sops", "--encrypt", "--input-type", "json", "--output-type", "yaml",
        "--filename-override", str(secret_path), "/dev/stdin",
    ], json.dumps(secret))
    # Detect missing/wrong encryption rules before writing anything.
    encrypted_obj = json.loads(run(["yq", "-o=json", "."], encrypted))
    if not all(str(v).startswith("ENC[") for v in encrypted_obj.get("stringData", {}).values()):
        fail("SOPS did not encrypt stringData; check .sops.yaml.")
    if not encrypted_obj.get("sops") or not encrypted_obj.get("stringData"):
        fail("Invalid SOPS output.")

    namespace = manifest("v1", "Namespace", ns)
    namespace["metadata"].update({
        "annotations": {"kustomize.toolkit.fluxcd.io/prune": "disabled"},
        "labels": {"pod-security.kubernetes.io/enforce": "privileged"},
    })
    ks = manifest("kustomize.toolkit.fluxcd.io/v1", "Kustomization", "juicefs", {
        "interval": "1h", "path": "./" + str(app), "prune": True,
        "sourceRef": {"kind": "GitRepository", "name": "flux-system", "namespace": "flux-system"},
        "targetNamespace": ns, "wait": False,
        "dependsOn": [{"name": "topolvm", "namespace": "flux-system"}],
        "decryption": {"provider": "sops", "secretRef": {"name": "sops-age"}},
    })
    ks["metadata"]["namespace"] = "flux-system"
    values = {
        "immutable": True,
        "mountMode": "mountpod",
        "csidriver": {"disableHooks": True},
        "controller": {"replicas": 1, "nodeSelector": {"kubernetes.io/hostname": node}},
        "node": {"nodeSelector": {"kubernetes.io/hostname": node}},
        "dashboard": {"enabled": False},
        "snapshot": {"enabled": False},
        "defaultMountImage": {"ce": "juicedata/mount:ce-v1.4.1"},
        "globalConfig": {
            "enabled": True, "manageByHelm": True, "enableNodeSelector": True,
            "mountPodPatch": [{
                "cacheDirs": [{"type": "PVC", "name": pvc_name}],
                "mountOptions": [f"cache-size={limit * 1024}", "free-space-ratio=0.05", "buffer-size=64"],
                "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                              "limits": {"memory": "1Gi"}},
            }],
        },
    }
    release = manifest("helm.toolkit.fluxcd.io/v2", "HelmRelease", "juicefs", {
        "interval": "1h",
        "chart": {"spec": {"chart": "juicefs-csi-driver", "version": "0.33.1",
                           "sourceRef": {"kind": "HelmRepository", "name": "juicefs"}, "interval": "1h"}},
        "values": values,
    })
    pvc = manifest("v1", "PersistentVolumeClaim", pvc_name, {
        "accessModes": ["ReadWriteOnce"], "storageClassName": "topolvm-cache",
        "resources": {"requests": {"storage": f"{cache}Gi"}},
    })
    sc = manifest("storage.k8s.io/v1", "StorageClass", "juicefs", provisioner="csi.juicefs.com",
        reclaimPolicy="Retain", volumeBindingMode="WaitForFirstConsumer",
        allowVolumeExpansion=True, parameters={
            "csi.storage.k8s.io/provisioner-secret-name": secret_name,
            "csi.storage.k8s.io/provisioner-secret-namespace": ns,
            "csi.storage.k8s.io/node-publish-secret-name": secret_name,
            "csi.storage.k8s.io/node-publish-secret-namespace": ns,
            "csi.storage.k8s.io/controller-expand-secret-name": secret_name,
            "csi.storage.k8s.io/controller-expand-secret-namespace": ns,
        })
    docs = {
        base / "namespace.yaml": namespace,
        base / "kustomization.yaml": {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
                                       "resources": ["./namespace.yaml", "./juicefs/ks.yaml"]},
        base / "juicefs/ks.yaml": ks,
        app / "kustomization.yaml": {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization",
            "resources": ["./helmrepository.yaml", "./helmrelease.yaml", "./secret.sops.yaml",
                          "./cache-pvc.yaml", "./storageclass.yaml"]},
        app / "helmrepository.yaml": manifest("source.toolkit.fluxcd.io/v1", "HelmRepository", "juicefs", {
            "interval": "1h", "url": "https://juicedata.github.io/charts/"}),
        app / "helmrelease.yaml": release,
        app / "cache-pvc.yaml": pvc,
        app / "storageclass.yaml": sc,
    }
    rendered = {path: yaml_text(doc) for path, doc in docs.items()}
    rendered[secret_path] = encrypted
    original = entry.read_text()
    updated = run(["yq", '.resources += ["./juicefs-system"] | .resources |= unique', str(entry)])
    try:
        for path, content in rendered.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        entry.write_text(updated)
        # Capture stdout: it may contain encrypted Secret manifests.
        run(["kustomize", "build", "kubernetes/apps"])
        run(["kustomize", "build", str(app)])
    except BaseException:
        entry.write_text(original)
        shutil.rmtree(base)
        raise
    print("Generated kubernetes/apps/juicefs-system; SOPS encryption and Kustomize builds passed.")
    print("No commit, push, cluster operation, or filesystem initialization was performed.")
    print("The cache PVC remains Pending until first consumption; CSI initializes JuiceFS on first use.")


if __name__ == "__main__":
    main()

