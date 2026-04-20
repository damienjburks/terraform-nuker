"""
TFC Client Module

This module provides a TfcClient class for interacting with the Terraform Cloud API.
It includes methods to fetch workspaces, check the last apply status, enable auto-apply,
create destroy runs, and process organizations.
"""

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
            "devsecblueprint": ["dsb-platform", "dsb-platform-dev", "the-herald"],
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

    def create_destroy_run(self, workspace_id, workspace_name):
        """
        Creates a destroy run for a workspace.

        Args:
            workspace_id (str): The ID of the workspace.
            workspace_name (str): The name of the workspace.
        """
        payload = {
            "data": {
                "attributes": {
                    "is-destroy": True,
                    "message": "Automated destroy with auto-apply",
                },
                "type": "runs",
                "relationships": {
                    "workspace": {"data": {"type": "workspaces", "id": workspace_id}}
                },
            }
        }

        url = f"{self.api_url}/runs"
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
            else:
                logging.error(
                    "[x] Failed to create destroy run for '%s': %s",
                    workspace_name,
                    res.text,
                )
        except requests.RequestException as e:
            logging.error(
                "Failed to create destroy run for workspace '%s': %s", workspace_name, e
            )
            logging.debug(traceback.format_exc())

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

                logging.info("Creating destroy run...")
                self.enable_auto_apply(ws_id)
                self.create_destroy_run(ws_id, ws_name)
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
