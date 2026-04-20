# 💣 Terraform Nuker

![Build Status](https://github.com/damienjburks/terraform-nuker/actions/workflows/main.yml/badge.svg?logo=github)
![License](https://img.shields.io/badge/license-MIT-blue)
![Vault](https://img.shields.io/badge/vault-enabled-black?logo=hashicorp)
![Kubernetes](https://img.shields.io/badge/k8s-CronJob-326CE5?logo=kubernetes)

## 🚀 Overview

**Terraform Nuker** is a Kubernetes-native CronJob that automatically destroys Terraform Cloud workspaces on a schedule. It iterates through configured organizations, checks workspace state, enables auto-apply, and triggers destroy runs — useful for tearing down ephemeral or dev environments nightly.

## 🛠 Features

- 🕐 Runs as a Kubernetes CronJob (daily at 2 AM America/Chicago by default)
- 🔐 Vault Agent Injector for secure TFC API key retrieval
- 🏗️ Processes multiple Terraform Cloud organizations
- ⏩ Supports workspace exclusion lists
- 🔁 Skips workspaces where the last apply was already a destroy
- 📦 Helm chart for easy deployment

## ⚙️ Configuration

Workspace processing is configured in `app/clients/tfc_client.py`:

```python
self.org_list = ["DSB", "DJB-Personal"]
self.exclude_workspaces = {
    "DJB-Personal": ["openvpn-server"],
    "DSB": ["azure-devsecops-pipelines"],
}
```

The CronJob schedule and other settings are in `helm/values.yaml`.

## 🚢 Deployment

```bash
helm install terraform-nuker ./helm
```
