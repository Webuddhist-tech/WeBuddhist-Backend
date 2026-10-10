#!/bin/bash

# Fix permissions for database directories so uvicorn can watch them
# This needs to be run with sudo

echo "Fixing permissions for local database directories..."

# Make directories readable and executable for the current user
sudo chmod -R 755 local_setup/data/database-local 2>/dev/null || true

# Change ownership to current user
sudo chown -R $USER:$USER local_setup/data/database-local 2>/dev/null || true

echo "Permissions fixed! You can now run ./start_dev.sh with auto-reload working."
