"""
TFC Client Module

This module provides a TfcClient class for interacting with the Terraform Cloud API.
It includes methods to fetch workspaces, check the last apply status, enable auto-apply,
create destroy runs, and process organizations.
"""

import re
import time
import logging
import traceback
import requests
from utils.secrets import VaultSecretsLoader


class TfcClient:
    """
    A client for interacting with the Terraform Cloud API.

    This class provides methods to fetch workspaces, check the last apply status,
    enable auto-apply, create destroy runs, and process organizations.
    """

    def __init__(self, api_url="https://app.terraform.io/api/v2"):
        """
        Initializes the TfcClient instance.

        Args:
            api_url (str): The base URL for the Terraform Cloud API.
        """
        self.api_url = api_url
        token = VaultSecretsLoader().load_secret("tfc-creds")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/vnd.api+json",
        }
        self.org_list = ["devsecblueprint", "damienjburks"]
        self.exclude_workspaces = {
            "damienjburks": ["personal-website"],
            "devsecblueprint": ["dsb-platform", "the-herald"],
        }

    def get_workspaces(self, org_name):
        """
        Fetches all workspaces for a given organization.

        Args:
            org_name (str): The name of the organization.

        Returns:
            list: A list of workspaces.
        """
        url = f"{self.api_url}/organizations/{org_name}/workspaces"
        workspaces = []

        logging.info("Fetching workspaces for organization: %s", org_name)
        while url:
            try:
                res = requests.get(url, headers=self.headers, timeout=10)
                res.raise_for_status()
                data = res.json()
                workspaces.extend(data["data"])
                url = data.get("links", {}).get("next")
            except requests.RequestException as e:
                logging.error("Failed to fetch workspaces for '%s': %s", org_name, e)
                logging.debug(traceback.format_exc())
                break

        logging.info(
            "Retrieved %d workspaces for organization: %s", len(workspaces), org_name
        )
        return workspaces

    def was_last_apply_destroy(self, workspace_id):
        """
        Checks if the most recent apply for a workspace was a destroy operation.

        Args:
            workspace_id (str): The ID of the workspace to check.

        Returns:
            bool: True if the most recent apply was a destroy, False otherwise.
        """
        url = f"{self.api_url}/workspaces/{workspace_id}/runs"
        logging.info(
            "Checking if the most recent apply for workspace ID '%s' was a destroy.",
            workspace_id,
        )

        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            res.raise_for_status()
            runs = res.json()["data"]

            # Find the most recent completed run
            for run in runs:
                if run["attributes"]["status"] == "applied":
                    is_destroy = run["attributes"]["is-destroy"]
                    logging.info(
                        "Most recent apply for workspace ID '%s' was a %s operation.",
                        workspace_id,
                        "destroy" if is_destroy else "normal",
                    )
                    return is_destroy

            logging.warning(
                "No completed apply runs found for workspace ID '%s'.", workspace_id
            )
            return False

        except requests.RequestException as e:
            logging.error(
                "Failed to check the most recent apply for workspace ID '%s': %s",
                workspace_id,
                e,
            )
            logging.debug(traceback.format_exc())
            return False

    def enable_auto_apply(self, workspace_id):
        """
        Enables the Auto Apply setting for a workspace.

        Args:
            workspace_id (str): The ID of the workspace to update.

        Returns:
            bool: True if Auto Apply was successfully enabled, False otherwise.
        """
        url = f"{self.api_url}/workspaces/{workspace_id}"
        payload = {"data": {"attributes": {"auto-apply": True}, "type": "workspaces"}}

        logging.info("Enabling Auto Apply for workspace ID: %s", workspace_id)
        try:
            res = requests.patch(url, headers=self.headers, json=payload, timeout=10)
            if res.status_code == 200:
                logging.info(
                    "Auto Apply successfully enabled for workspace ID: %s", workspace_id
                )
                return True
            logging.error(
                "Failed to enable Auto Apply for workspace ID '%s': %s",
                workspace_id,
                res.text,
            )
            return False
        except requests.RequestException as e:
            logging.error(
                "Error enabling Auto Apply for workspace ID '%s': %s", workspace_id, e
            )
            logging.debug(traceback.format_exc())
            return False

    def create_destroy_run(self, workspace_id, workspace_name, target_addrs=None):
        """
        Creates a destroy run for a workspace.

        Args:
            workspace_id (str): The ID of the workspace.
            workspace_name (str): The name of the workspace.
            target_addrs (list, optional): Resource addresses to scope the destroy
                to (equivalent to ``terraform destroy -target=...``). When provided,
                only these resources are destroyed, leaving everything else intact.

        Returns:
            str: The created run ID, or None if creation failed.
        """
        attributes = {
            "is-destroy": True,
            "message": "Automated destroy with auto-apply",
        }
        if target_addrs:
            attributes["target-addrs"] = target_addrs

        payload = {
            "data": {
                "attributes": attributes,
                "type": "runs",
                "relationships": {
                    "workspace": {"data": {"type": "workspaces", "id": workspace_id}}
                },
            }
        }

        url = f"{self.api_url}/runs"
        if target_addrs:
            logging.info(
                "Creating targeted destroy run for workspace: %s (ID: %s) with %d target(s)",
                workspace_name,
                workspace_id,
                len(target_addrs),
            )
        else:
            logging.info(
                "Creating destroy run for workspace: %s (ID: %s)",
                workspace_name,
                workspace_id,
            )
        try:
            res = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if res.status_code == 201:
                run_id = res.json()["data"]["id"]
                logging.info(
                    "[✓] Destroy run created for workspace '%s' (run_id: %s)",
                    workspace_name,
                    run_id,
                )
                return run_id
            logging.error(
                "[x] Failed to create destroy run for '%s': %s",
                workspace_name,
                res.text,
            )
            return None
        except requests.RequestException as e:
            logging.error(
                "Failed to create destroy run for workspace '%s': %s", workspace_name, e
            )
            logging.debug(traceback.format_exc())
            return None

    def wait_for_run(self, run_id, poll_interval=5, timeout=1800):
        """
        Polls a run until it reaches a terminal state.

        Args:
            run_id (str): The ID of the run to poll.
            poll_interval (int): Seconds to wait between status checks.
            timeout (int): Maximum seconds to wait before giving up.

        Returns:
            str: The terminal run status (e.g. "applied", "errored",
                "planned_and_finished"), or None on error/timeout.
        """
        # Statuses that indicate the run is finished and won't change further.
        terminal_statuses = {
            "applied",
            "planned_and_finished",
            "errored",
            "canceled",
            "force_canceled",
            "discarded",
        }
        url = f"{self.api_url}/runs/{run_id}"
        deadline = time.time() + timeout

        logging.info("Waiting for run '%s' to reach a terminal state...", run_id)
        while time.time() < deadline:
            try:
                res = requests.get(url, headers=self.headers, timeout=10)
                res.raise_for_status()
                status = res.json()["data"]["attributes"]["status"]
                logging.info("Run '%s' status: %s", run_id, status)
                if status in terminal_statuses:
                    return status
            except requests.RequestException as e:
                logging.error("Failed to poll run '%s': %s", run_id, e)
                logging.debug(traceback.format_exc())
                return None
            time.sleep(poll_interval)

        logging.error(
            "Timed out waiting for run '%s' to reach a terminal state.", run_id
        )
        return None

    def get_plan_log(self, run_id):
        """
        Fetches the plan log output for a run.

        Args:
            run_id (str): The ID of the run.

        Returns:
            str: The plan log text, or an empty string if it could not be fetched.
        """
        run_url = f"{self.api_url}/runs/{run_id}?include=plan"
        try:
            res = requests.get(run_url, headers=self.headers, timeout=10)
            res.raise_for_status()
            included = res.json().get("included", [])
            log_read_url = None
            for item in included:
                if item.get("type") == "plans":
                    log_read_url = item["attributes"].get("log-read-url")
                    break

            if not log_read_url:
                logging.warning("No plan log URL found for run '%s'.", run_id)
                return ""

            # The log-read-url is a pre-signed URL and does not need auth headers.
            log_res = requests.get(log_read_url, timeout=30)
            log_res.raise_for_status()
            return log_res.text
        except requests.RequestException as e:
            logging.error("Failed to fetch plan log for run '%s': %s", run_id, e)
            logging.debug(traceback.format_exc())
            return ""

    @staticmethod
    def extract_prevent_destroy_addrs(plan_log):
        """
        Parses a plan log and extracts resource addresses blocked by prevent_destroy.

        Terraform emits an "Instance cannot be destroyed" error for each resource
        that has ``lifecycle.prevent_destroy = true`` when a destroy is planned.
        The blocked resource address appears on the "Resource ... has lifecycle.prevent_destroy set"
        line following the error.

        Args:
            plan_log (str): The raw plan log text.

        Returns:
            list: Sorted list of unique blocked resource addresses.
        """
        if not plan_log:
            return []

        blocked = set()
        # Matches lines like:
        #   Resource aws_s3_bucket.protected has lifecycle.prevent_destroy set, but the
        # and:
        #   on ... line N, in resource "aws_s3_bucket" "protected":
        resource_line = re.compile(
            r"Resource\s+([a-zA-Z0-9_.\[\]\"'\-/]+)\s+has\s+lifecycle\.prevent_destroy\s+set"
        )
        # Fallback: the diagnostic "resource" reference block.
        block_ref = re.compile(
            r'in\s+resource\s+"([^"]+)"\s+"([^"]+)"'
        )

        lines = plan_log.splitlines()
        for i, line in enumerate(lines):
            match = resource_line.search(line)
            if match:
                blocked.add(match.group(1).strip())
                continue

            # If we see a prevent_destroy diagnostic, look for a nearby block ref.
            if "prevent_destroy" in line and "cannot be destroyed" in line.lower():
                # Scan a small window around the error for the resource block ref.
                window = lines[max(0, i - 3) : i + 4]
                for w in window:
                    ref = block_ref.search(w)
                    if ref:
                        blocked.add(f"{ref.group(1)}.{ref.group(2)}")

        return sorted(blocked)

    def get_state_resource_addrs(self, workspace_id):
        """
        Enumerates the resource addresses in a workspace's current state version.

        Args:
            workspace_id (str): The ID of the workspace.

        Returns:
            list: Resource addresses (e.g. "aws_s3_bucket.foo",
                "module.bar.aws_instance.baz"), or an empty list on failure.
        """
        # Fetch the current state version to obtain the JSON state download URL.
        # NOTE: the `include=resources` sideload is not supported here and returns
        # a 400, so we download and parse the JSON state directly instead.
        url = f"{self.api_url}/workspaces/{workspace_id}/current-state-version"
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            res.raise_for_status()
            attributes = res.json()["data"]["attributes"]
        except requests.RequestException as e:
            logging.error(
                "Failed to fetch current state version for workspace '%s': %s",
                workspace_id,
                e,
            )
            logging.debug(traceback.format_exc())
            return []

        download_url = attributes.get("hosted-json-state-download-url")
        if not download_url:
            logging.error(
                "No JSON state download URL available for workspace '%s'. "
                "State may still be processing.",
                workspace_id,
            )
            return []

        try:
            # The download URL is pre-signed but TFC requires the bearer token.
            state_res = requests.get(download_url, headers=self.headers, timeout=30)
            state_res.raise_for_status()
            state = state_res.json()
        except requests.RequestException as e:
            logging.error(
                "Failed to download JSON state for workspace '%s': %s",
                workspace_id,
                e,
            )
            logging.debug(traceback.format_exc())
            return []

        addresses = self._parse_state_addresses(state)
        if not addresses:
            logging.debug(
                "State parse returned no resources for '%s'. Top-level keys: %s",
                workspace_id,
                list(state.keys()) if isinstance(state, dict) else type(state),
            )
        logging.info(
            "Found %d resource instance(s) in state for workspace '%s'.",
            len(addresses),
            workspace_id,
        )
        return addresses

    @classmethod
    def _parse_state_addresses(cls, state):
        """
        Extracts resource instance addresses from a Terraform JSON state document.

        Handles both formats TFC can serve:
          * ``terraform show -json`` output (``hosted-json-state-download-url``),
            which nests resources under ``values.root_module`` and its
            ``child_modules`` and provides a ready-made ``address`` per resource.
          * Raw state (``hosted-state-download-url``), which has a top-level
            ``resources`` array with ``instances``.

        Produces addresses like ``module.foo.aws_instance.bar["a"]`` that are
        valid as ``-target`` values. Data sources are ignored since they are not
        destroyable.

        Args:
            state (dict): The parsed JSON state document.

        Returns:
            list: Sorted list of unique resource instance addresses.
        """
        if not isinstance(state, dict):
            return []

        # Format 1: `terraform show -json` output.
        values = state.get("values")
        if isinstance(values, dict) and "root_module" in values:
            addresses = set()
            cls._collect_show_json_module(values["root_module"], addresses)
            return sorted(addresses)

        # Format 2: raw state file.
        return sorted(cls._parse_raw_state_addresses(state))

    @staticmethod
    def _collect_show_json_module(module, addresses):
        """
        Recursively collects managed-resource addresses from a show-json module.

        Args:
            module (dict): A module object with ``resources`` and ``child_modules``.
            addresses (set): Accumulator set of addresses.
        """
        for resource in module.get("resources", []):
            if resource.get("mode") == "data":
                continue
            address = resource.get("address")
            if address:
                addresses.add(address)

        for child in module.get("child_modules", []):
            TfcClient._collect_show_json_module(child, addresses)

    @staticmethod
    def _parse_raw_state_addresses(state):
        """
        Collects managed-resource instance addresses from a raw state document.

        Args:
            state (dict): The parsed raw state document.

        Returns:
            set: Resource instance addresses.
        """
        addresses = set()
        for resource in state.get("resources", []):
            if resource.get("mode") == "data":
                continue

            module = resource.get("module")  # e.g. "module.network"
            r_type = resource.get("type")
            name = resource.get("name")
            if not r_type or not name:
                continue

            base = f"{r_type}.{name}"
            if module:
                base = f"{module}.{base}"

            instances = resource.get("instances", [])
            if not instances:
                addresses.add(base)
                continue

            for instance in instances:
                index_key = instance.get("index_key")
                if index_key is None:
                    addresses.add(base)
                elif isinstance(index_key, str):
                    addresses.add(f'{base}["{index_key}"]')
                else:
                    addresses.add(f"{base}[{index_key}]")

        return addresses

    def destroy_workspace(self, workspace_id, workspace_name):
        """
        Destroys a workspace's resources using the two-pass A1 strategy.

        Pass 1: attempt a full destroy run. If it succeeds, we're done.
        Pass 2: if the run errored because of prevent_destroy, parse the blocked
        resource addresses out of the plan log, compute the set of destroyable
        resources (everything in state minus the blocked ones), and issue a
        targeted destroy run for only those resources.

        Args:
            workspace_id (str): The ID of the workspace.
            workspace_name (str): The name of the workspace.
        """
        self.enable_auto_apply(workspace_id)

        # --- Pass 1: full destroy ---
        run_id = self.create_destroy_run(workspace_id, workspace_name)
        if not run_id:
            logging.error(
                "Could not create initial destroy run for '%s'. Skipping.",
                workspace_name,
            )
            return

        status = self.wait_for_run(run_id)
        if status == "applied":
            logging.info(
                "[✓] Full destroy applied for workspace '%s'.", workspace_name
            )
            return
        if status in ("planned_and_finished",):
            logging.info(
                "[✓] Nothing to destroy for workspace '%s' (no changes).",
                workspace_name,
            )
            return
        if status != "errored":
            logging.warning(
                "Destroy run for '%s' ended with status '%s'. Not retrying.",
                workspace_name,
                status,
            )
            return

        # --- Pass 2: inspect failure and retry with targeting ---
        logging.info(
            "Destroy run for '%s' errored. Checking for prevent_destroy resources...",
            workspace_name,
        )
        plan_log = self.get_plan_log(run_id)
        blocked = self.extract_prevent_destroy_addrs(plan_log)

        if not blocked:
            logging.error(
                "[x] Destroy run for '%s' errored but no prevent_destroy resources "
                "were detected. Manual investigation required.",
                workspace_name,
            )
            return

        logging.info(
            "  🛡️ Protected (prevent_destroy) resources in '%s': %s",
            workspace_name,
            ", ".join(blocked),
        )

        all_addrs = self.get_state_resource_addrs(workspace_id)
        if not all_addrs:
            logging.error(
                "[x] Could not enumerate state resources for '%s'; cannot build a "
                "targeted destroy. Skipping.",
                workspace_name,
            )
            return

        blocked_set = set(blocked)
        targets = [addr for addr in all_addrs if addr not in blocked_set]

        if not targets:
            logging.info(
                "  ⏩ All resources in '%s' are protected. Nothing to destroy.",
                workspace_name,
            )
            return

        logging.info(
            "  🎯 Issuing targeted destroy for %d of %d resource(s) in '%s' "
            "(skipping %d protected).",
            len(targets),
            len(all_addrs),
            workspace_name,
            len(blocked),
        )
        targeted_run_id = self.create_destroy_run(
            workspace_id, workspace_name, target_addrs=targets
        )
        if not targeted_run_id:
            logging.error(
                "[x] Failed to create targeted destroy run for '%s'.", workspace_name
            )
            return

        targeted_status = self.wait_for_run(targeted_run_id)
        if targeted_status == "applied":
            logging.info(
                "[✓] Targeted destroy applied for '%s'. Protected resources left "
                "intact: %s",
                workspace_name,
                ", ".join(blocked),
            )
        else:
            logging.error(
                "[x] Targeted destroy for '%s' ended with status '%s'.",
                workspace_name,
                targeted_status,
            )

    def process_organization(self, org_name):
        """
        Processes all workspaces in an organization.

        Args:
            org_name (str): The name of the organization.
        """
        logging.info("🔍 Starting processing for organization: %s", org_name)
        workspaces = self.get_workspaces(org_name)

        if not workspaces:
            logging.warning("No workspaces found for organization: %s", org_name)
            return

        for ws in workspaces:
            ws_id = ws["id"]
            ws_name = ws["attributes"]["name"]

            if ws_name in self.exclude_workspaces.get(org_name, []):
                logging.info(
                    "  ⏩ Skipping workspace '%s' (whitelisted in %s)",
                    ws_name,
                    org_name,
                )
                continue

            logging.info("▶️ Processing workspace: %s (ID: %s)", ws_name, ws_id)

            try:
                # Check if the last apply was a destroy
                if self.was_last_apply_destroy(ws_id):
                    logging.info(
                        "[!] Last apply for workspace '%s' was a destroy. Skipping...",
                        ws_name,
                    )
                    continue

                logging.info("Destroying workspace resources...")
                self.destroy_workspace(ws_id, ws_name)
            except Exception as e:
                logging.error("[!] Error processing workspace '%s': %s", ws_name, e)
                logging.debug(traceback.format_exc())

            time.sleep(1)  # Avoid API rate limits

        logging.info("✅ Finished processing for organization: %s", org_name)

    def run(self):
        """
        Runs the TfcClient to process all organizations.
        """
        try:
            for org in self.org_list:
                self.process_organization(org)
        except Exception as e:
            logging.critical("Unhandled exception in main: %s", e)
            logging.debug(traceback.format_exc())
            raise
