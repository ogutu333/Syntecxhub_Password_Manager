#!/usr/bin/env python3

"""
Python Password Manager
-----------------------
A local password manager using:
- AES-256-GCM encryption
- Scrypt key derivation
- Master password authentication
- Encrypted JSON storage

Features:
1. Add passwords
2. Retrieve passwords
3. Search passwords
4. Delete passwords
5. Lock vault
"""

import os
import json
import base64
import getpass

from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.exceptions import InvalidTag


# ==========================================
# CONFIGURATION
# ==========================================

VAULT_FILE = Path("vault.json")

SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32

AAD = b"password-manager-v1"

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1


# ==========================================
# KEY DERIVATION
# ==========================================

def derive_key(master_password, salt):
    """
    Derive a 256-bit encryption key using Scrypt.
    """

    kdf = Scrypt(
        salt=salt,
        length=KEY_SIZE,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P
    )

    return kdf.derive(master_password.encode("utf-8"))


# ==========================================
# ENCRYPTION
# ==========================================

def encrypt_data(data, master_password, salt):
    """
    Encrypt password records using AES-256-GCM.
    """

    key = derive_key(master_password, salt)

    aes = AESGCM(key)

    # Generate a unique nonce for each encryption.
    nonce = os.urandom(NONCE_SIZE)

    # Convert records into JSON bytes.
    plaintext = json.dumps(data).encode("utf-8")

    # Encrypt and authenticate the data.
    ciphertext = aes.encrypt(
        nonce,
        plaintext,
        AAD
    )

    return {
        "version": 1,
        "kdf": "scrypt",
        "n": SCRYPT_N,
        "r": SCRYPT_R,
        "p": SCRYPT_P,
        "salt": base64.b64encode(salt).decode("utf-8"),
        "nonce": base64.b64encode(nonce).decode("utf-8"),
        "ciphertext": base64.b64encode(ciphertext).decode("utf-8")
    }


# ==========================================
# DECRYPTION
# ==========================================

def decrypt_data(vault, master_password):
    """
    Decrypt the encrypted password records.
    """

    salt = base64.b64decode(
        vault["salt"],
        validate=True
    )

    nonce = base64.b64decode(
        vault["nonce"],
        validate=True
    )

    ciphertext = base64.b64decode(
        vault["ciphertext"],
        validate=True
    )

    if len(salt) != SALT_SIZE:
        raise ValueError("Invalid salt.")

    if len(nonce) != NONCE_SIZE:
        raise ValueError("Invalid nonce.")

    if len(ciphertext) < 16:
        raise ValueError("Invalid ciphertext.")

    key = derive_key(master_password, salt)

    aes = AESGCM(key)

    plaintext = aes.decrypt(
        nonce,
        ciphertext,
        AAD
    )

    records = json.loads(plaintext.decode("utf-8"))

    if not isinstance(records, list):
        raise ValueError("Invalid vault contents.")

    for entry in records:
        if not isinstance(entry, dict):
            raise ValueError("Invalid password entry.")

        if not all(
            isinstance(entry.get(field), str)
            for field in ("website", "username", "password")
        ):
            raise ValueError("Invalid password entry.")

    return records


# ==========================================
# SAVE VAULT
# ==========================================

def save_vault(vault):
    """
    Save encrypted vault data to disk.
    Restrict file permissions on Unix-like systems.
    """

    temporary_file = VAULT_FILE.with_suffix(".tmp")

    file_descriptor = os.open(
        temporary_file,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600
    )

    try:
        with os.fdopen(file_descriptor, "w") as file:
            json.dump(vault, file, indent=4)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary_file, VAULT_FILE)

    except Exception:
        if temporary_file.exists():
            temporary_file.unlink()

        raise


# ==========================================
# LOAD VAULT
# ==========================================

def load_vault():
    """
    Load the encrypted vault from disk.
    Validate its encryption parameters.
    """

    with open(VAULT_FILE, "r") as file:
        vault = json.load(file)

    if not isinstance(vault, dict):
        raise ValueError("Invalid vault format.")

    if (
        vault.get("version") != 1
        or vault.get("kdf") != "scrypt"
        or vault.get("n") != SCRYPT_N
        or vault.get("r") != SCRYPT_R
        or vault.get("p") != SCRYPT_P
    ):
        raise ValueError("Unsupported vault format.")

    required_fields = {
        "salt",
        "nonce",
        "ciphertext"
    }

    if not required_fields.issubset(vault):
        raise ValueError("Missing vault data.")

    return vault


# ==========================================
# CREATE VAULT
# ==========================================

def create_vault():
    """
    Create a new encrypted password vault.
    """

    print("\n=== CREATE PASSWORD VAULT ===")

    master_password = getpass.getpass(
        "Create master password: "
    )

    confirm_password = getpass.getpass(
        "Confirm master password: "
    )

    if len(master_password) < 12:
        print("Master password must be at least 12 characters.")
        return False

    if master_password != confirm_password:
        print("Passwords do not match.")
        return False

    salt = os.urandom(SALT_SIZE)

    encrypted_vault = encrypt_data(
        [],
        master_password,
        salt
    )

    save_vault(encrypted_vault)

    print("\nPassword vault created successfully!")

    return True


# ==========================================
# UNLOCK VAULT
# ==========================================

def unlock_vault():
    """
    Authenticate the user and decrypt the vault.
    """

    print("\n=== UNLOCK PASSWORD VAULT ===")

    master_password = getpass.getpass(
        "Enter master password: "
    )

    try:

        vault = load_vault()

        records = decrypt_data(
            vault,
            master_password
        )

        salt = base64.b64decode(
            vault["salt"],
            validate=True
        )

        print("\nVault unlocked successfully!")

        return records, master_password, salt

    except InvalidTag:

        print("\nIncorrect password or corrupted vault.")

        return None

    except (
        ValueError,
        KeyError,
        OSError,
        json.JSONDecodeError
    ):

        print("\nUnable to open the vault.")

        return None


# ==========================================
# ADD PASSWORD
# ==========================================

def add_password(records, master_password, salt):
    """
    Add a new credential to the vault.
    """

    print("\n=== ADD NEW PASSWORD ===")

    website = input("Website: ").strip()

    username = input("Username/Email: ").strip()

    password = getpass.getpass(
        "Password: "
    )

    if not website or not username or not password:
        print("All fields are required.")
        return

    entry = {
        "website": website,
        "username": username,
        "password": password
    }

    records.append(entry)

    encrypted_vault = encrypt_data(
        records,
        master_password,
        salt
    )

    save_vault(encrypted_vault)

    print("\nPassword saved successfully!")


# ==========================================
# RETRIEVE PASSWORD
# ==========================================

def retrieve_password(records):
    """
    Retrieve saved credentials by website.
    """

    print("\n=== RETRIEVE PASSWORD ===")

    website = input("Enter website: ").strip()

    matches = [
        entry for entry in records
        if entry["website"].casefold() == website.casefold()
    ]

    if not matches:

        print("\nNo matching credentials found.")

        return

    for entry in matches:

        print("\nWebsite:", entry["website"])

        print("Username:", entry["username"])

        print("Password:", entry["password"])


# ==========================================
# SEARCH PASSWORDS
# ==========================================

def search_password(records):
    """
    Search credentials by website or username.
    """

    print("\n=== SEARCH PASSWORDS ===")

    query = input(
        "Search website or username: "
    ).strip()

    if not query:

        print("Please enter a search term.")

        return

    results = [
        entry for entry in records
        if query.casefold() in entry["website"].casefold()
        or query.casefold() in entry["username"].casefold()
    ]

    if not results:

        print("\nNo matching entries found.")

        return

    for entry in results:

        print("\nWebsite:", entry["website"])

        print("Username:", entry["username"])

        print("Password: ********")


# ==========================================
# DELETE PASSWORD
# ==========================================

def delete_password(records, master_password, salt):
    """
    Delete a selected credential from the vault.
    """

    print("\n=== DELETE PASSWORD ===")

    website = input("Enter website: ").strip()

    matches = [
        entry for entry in records
        if entry["website"].casefold() == website.casefold()
    ]

    if not matches:

        print("\nNo matching credentials found.")

        return

    for index, entry in enumerate(matches, start=1):

        print(
            f"{index}. {entry['website']} - {entry['username']}"
        )

    try:

        choice = int(input("\nSelect entry to delete: "))

        if choice < 1 or choice > len(matches):

            print("Invalid selection.")

            return

    except ValueError:

        print("Please enter a valid number.")

        return

    selected = matches[choice - 1]

    confirm = input(
        f"Delete {selected['website']} account? (y/n): "
    ).strip().lower()

    if confirm != "y":

        print("Deletion cancelled.")

        return

    records.remove(selected)

    encrypted_vault = encrypt_data(
        records,
        master_password,
        salt
    )

    save_vault(encrypted_vault)

    print("\nPassword deleted successfully!")


# ==========================================
# MAIN MENU
# ==========================================

def main():
    """
    Main application entry point.
    """

    print("\n================================")
    print("       PYTHON PASSWORD MANAGER")
    print("================================")

    if not VAULT_FILE.exists():

        created = create_vault()

        if not created:
            return

    result = unlock_vault()

    if result is None:
        return

    records, master_password, salt = result

    while True:

        print("\n================================")
        print("       PASSWORD MANAGER")
        print("================================")

        print("1. Add Password")
        print("2. Retrieve Password")
        print("3. Delete Password")
        print("4. Search Passwords")
        print("5. Exit")

        choice = input("\nSelect an option: ").strip()

        try:

            if choice == "1":

                add_password(
                    records,
                    master_password,
                    salt
                )

            elif choice == "2":

                retrieve_password(records)

            elif choice == "3":

                delete_password(
                    records,
                    master_password,
                    salt
                )

            elif choice == "4":

                search_password(records)

            elif choice == "5":

                print("\nPassword manager locked. Goodbye!")

                break

            else:

                print("\nInvalid option. Try again.")

        except OSError:

            print("\nStorage error. Changes may not have been saved.")

        except (ValueError, KeyError):

            print("\nUnable to process the vault operation.")


# ==========================================
# RUN APPLICATION
# ==========================================

if __name__ == "__main__":

    main()
