"""
Vault Secrets Loader Module

This module provides a class to load secrets from Vault Agent-injected files.
"""

import os


class VaultSecretsLoader:
    """
    A class to load secrets from Vault Agent-injected files.
    """

    def __init__(self, secret_path="/vault/secrets"):
        """
        Initializes the VaultSecretsLoader.

        Args:
            secret_path (str): The base path where Vault secrets are injected.
        """
        self.secret_path = secret_path

    def load_secret(self, secret_file_name: str):
        """
        Loads the secret from the Vault-injected file.

        Returns:
            str: The Redis password, or None if the file is not found.
        """
        return self._load_secret_file(secret_file_name)

    def _load_secret_file(self, filename):
        """
        Loads the content of a secret file.

        Args:
            filename (str): The name of the secret file to load.

        Returns:
            str: The content of the secret file, or None if the file is not found.
        """
        file_path = os.path.join(self.secret_path, filename)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            print(
                f"Secret file '{filename}' not found at path '{file_path}'. Is Vault Agent Injector configured?"
            )
            return None
