"""
Main module for the Terraform Nuker CronJob.
This module serves as the entry point for the Kubernetes CronJob
that processes Terraform Cloud organizations.
"""

import logging
import sys

from clients.tfc_client import TfcClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def main():
    """
    Entry point for the CronJob. Runs the TfcClient processing job.
    """
    logging.info("Starting Terraform Nuker TFC processing job...")
    try:
        TfcClient().run()
        logging.info("TFC processing job completed successfully.")
    except Exception as e:
        logging.critical("TFC processing job failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
