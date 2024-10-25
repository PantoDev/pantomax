#!/bin/bash

set -e

# Configuration
RESOURCE_GROUP="panto-git-resources-india"
WEB_APP_NAME="panto"
ZIP_FILE_PATH="deployment.zip"
DOCKER_IMAGE_NAME="panto-image-zip"
DOCKER_CONTAINER_NAME="panto-builder-container"
LOCAL_APP_PATH="tmp/build"
APP_VERSION="$(git rev-parse HEAD).$(date +%s)"

# Check if the current branch is 'main'
branch=$(git rev-parse --abbrev-ref HEAD)

if [ "$branch" != "main" ]; then
  echo "You are not on the 'main' branch. Aborting..."
  exit 1
fi

if [[ $(git status --porcelain) ]]; then
  echo "Uncommitted changes detected."
  echo "Please commit or stash your changes before proceeding. Aborting..."
  exit 1
fi

echo "running test"
make test

echo "Releasing APP_VERSION = $APP_VERSION"

rm -rf $LOCAL_APP_PATH
mkdir -p $LOCAL_APP_PATH

# Check if required commands are available
for cmd in docker az curl zip; do
    if ! command -v $cmd &> /dev/null; then
        echo "$cmd not found. Please install it first."
        exit 1
    fi
done

# Build Docker Image
echo "Building Docker image..."
docker build -t $DOCKER_IMAGE_NAME --platform=linux/amd64 -f Dockerfile.zip.build --build-arg ZIP_FILE_PATH=$ZIP_FILE_PATH --build-arg APP_VERSION=$APP_VERSION .

# Run Docker Container and Copy zip file
echo "Running Docker container and copying files..."
docker run -d --name $DOCKER_CONTAINER_NAME $DOCKER_IMAGE_NAME tail -f /dev/null
docker cp $DOCKER_CONTAINER_NAME:/app/$ZIP_FILE_PATH $LOCAL_APP_PATH/$ZIP_FILE_PATH
docker kill $DOCKER_CONTAINER_NAME
docker rm $DOCKER_CONTAINER_NAME


# Log in to Azure CLI
echo "Checking Azure CLI login status..."
if az account show --output none &> /dev/null; then
    echo "Already logged in to Azure CLI."
else
    echo "Not logged in. Logging in now..."
    az login --output none
    if [ $? -ne 0 ]; then
        echo "Failed to log in to Azure CLI."
        exit 1
    fi
fi

# Deploy ZIP file to Azure Web App
# echo "Deploying ZIP file to Azure Web App..."
# curl -X POST -u "$WEB_APP_NAME:$AZURE_APP_PASSWORD" \
#     --data-binary @"$ZIP_FILE_PATH" \
#     "https://$WEB_APP_NAME.scm.azurewebsites.net/api/zipdeploy"

echo "Deploying ZIP file to Azure Web App..."
az webapp deploy --resource-group $RESOURCE_GROUP \
                  --name $WEB_APP_NAME \
                  --src-path $LOCAL_APP_PATH/$ZIP_FILE_PATH \
                  --type zip

if [ $? -ne 0 ]; then
    echo "Deployment failed."
    exit 1
fi

echo "Deployment successful."
