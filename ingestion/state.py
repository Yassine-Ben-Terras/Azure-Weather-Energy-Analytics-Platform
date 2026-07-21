"""Blob client shared by Azure (managed identity) and Azurite (connection string)."""
import os
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient


def get_client(connection_string=None):
    connection_string = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string)
    return BlobServiceClient(
        account_url=os.environ["AZURE_STORAGE_ACCOUNT_URL"],
        credential=DefaultAzureCredential(managed_identity_client_id=os.getenv("AZURE_CLIENT_ID")),
    )
