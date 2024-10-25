# Deploy as bot server

## For GitHub

1. Create a new GitHub App from [here](https://github.com/settings/apps/new)
2. In the webhook URL, use the domain where panto will be deployed. E.g. `https://<your_panto_domain>/github/webhook`
3. Generate one random secret for the webhook verification.
4. In the permissions section, grant following 4 permissions.
    1. `Metadata` -> Access: `Read-Only`
    2. `Pull requests` -> Access: `Read and write`
    3. `Contents` -> Access: `Read-Only`
    4. `Issues` -> Access: `Read and write`
5. In "Subscribe to events" section, enable followng events
    1. `Installation target`
    2. `Issue comment`
    3. `Pull request`
    4. `Issues`
    5. `Pull request review`
    6. `Pull request review comment`
    7. `Pull request review thread`
6. Create the app now.
7. Now create one `.envrc` file with following values from the [`.envrc.template`](../.envrc.template) file and change the follow keys -
    1. `GH_APP_ID` -> GitHub App Id (typically 6 digit number)
    2. `GH_WEBHOOK_SECRET` -> The webhook secret that have been configured in step 3
    3. `GH_BOT_NAME` -> The app name that have been set
    4. `GH_APP_PRIVATE_KEY_BASE64` -> Generate a new private key from the app details page under "Private keys" section. And encode it in base64 format.
    5. `OPENAI_API_KEY` -> OpenAI key
    6. `ONLY_WHITELISTED_ACCOUNTS` -> Your gitlab org url
8. [Follow this section](#deploy-panto-service) to deploy Panto service in your infra.
9. Now Install the app into your account and start using it.

## For Bitbucket

> A persistence storage is required for storing post installation config for bitbucket. As of now, we only support Firebase and Postgres. Please change the `DEFAULT_CONFIG_STORAGE_SRV` to `DB` or `FIREBASE`.

1. Create one `.envrc` file with following values from the [`.envrc.template`](../.envrc.template) file and change the follow keys -
    1. `BITBUCKET_APP_BASE_URL` -> Base url where the panto service will be deployed
    2. `BITBUCKET_APP_KEY` -> any unique id (e.g. `panto-for-<your-company>`).
    3. `OPENAI_API_KEY` -> OpenAI key
    4. `ONLY_WHITELISTED_ACCOUNTS` -> Your Bitbucket workspace url
    5. Based on the persistence storage, fill up the .envrc
2. [Follow this section](#deploy-panto-service) to deploy Panto service in your infra.
3. Go to bitbucket "Develop apps" section under the workspace settings.
    1. Click on the "Register App" and use `https://<YOUR_BITBUCKET_APP_BASE_URL>/bitbucket/atlassian-connect.json` in the Descriptor URL section.
    2. Register App.
4. Click to the "Installation URL" and install to your workspace.

## For GitLab

1. Create one `.envrc` file with following values from the [`.envrc.template`](../.envrc.template) file and change the follow keys -
    1. `OPENAI_API_KEY` -> OpenAI key
    2. `ONLY_WHITELISTED_ACCOUNTS` -> Your gitlab org url
    3. `MY_GL_WEBHOOK_SECRET` -> Generate one random secret for the webhook verification.
    4. `MY_GL_ACCESS_TOKEN` -> Check the point 3.
2. [Follow this section](#deploy-panto-service) to deploy Panto service in your infra.
3. Follow [this doc](https://docs.google.com/document/d/1S9BI_6pSa1j8IXDA2KLcq7sjScj0tDYz-j-5PpcHx9w/edit?usp=sharing) to create access token and setup webhooks

## Deploy Panto service

1. Generate a `.envrc` from [`.envrc.template`](../.envrc.template) and modifiy as per need.
2. `make image.build` to build docker image. Default name `panto`.
3. `make image.run` to run the image. It'll expose `5001` port
