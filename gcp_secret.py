from google.cloud import secretmanager
import json


def gcp_get_secret(
    project_id="932734078447", secret_id="runkeeper_cookie", version_id="latest"
):
    """Access the payload for the given secret version and return it as a dictionary."""

    # Create the Secret Manager client.
    client = secretmanager.SecretManagerServiceClient()

    # Build the resource name of the secret version.
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"

    # Access the secret version.
    response = client.access_secret_version(request={"name": name})

    # Get the secret payload as a string.
    payload_str = response.payload.data.decode("UTF-8")

    try:
        # Attempt to parse the payload as JSON.
        payload_dict = json.loads(payload_str)
        if "checker" in payload_dict:  # check if checker is in the dictionary.
            return [payload_dict["checker"]]  # Return the checker dictionary as a list.
        else:
            return []  # return an empty list if checker is not found.
    except json.JSONDecodeError:
        # If parsing fails, it's not valid JSON.
        print(f"Warning: Secret payload is not valid JSON. Returning None.")
        return None  # Return None so the format_cookies function can handle it.
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None


def gcp_update_secret(
    new_value, project_id="932734078447", secret_id="runkeeper_cookie"
):
    """
    Updates the secret with a new value by creating a new version.

    Args:
        new_value (dict or str): The new value to store in the secret.
                                If a dict is provided, it will be converted to JSON.
        project_id (str): The Google Cloud project ID.
        secret_id (str): The ID of the secret to update.

    Returns:
        The response from the add_secret_version call, or None if an error occurred.
    """
    try:
        # Create the Secret Manager client
        client = secretmanager.SecretManagerServiceClient()

        # Build the resource name of the parent secret
        parent = f"projects/{project_id}/secrets/{secret_id}"

        # Convert dictionary to JSON string if needed
        if isinstance(new_value, dict):
            payload = json.dumps(new_value).encode("UTF-8")
        else:
            # If it's already a string, just encode it
            payload = str(new_value).encode("UTF-8")

        # Add the new secret version
        response = client.add_secret_version(
            request={"parent": parent, "payload": {"data": payload}}
        )

        print(f"Added new version: {response.name}")
        return response

    except Exception as e:
        print(f"Error updating secret: {e}")
        return None


if __name__ == "__main__":
    project_id = "932734078447"  # Replace with your project ID
    secret_id = "runkeeper_cookie"  # Replace with your secret name

    secret_value = gcp_get_secret(project_id, secret_id)
    # print(f"Secret value: {secret_value}")
